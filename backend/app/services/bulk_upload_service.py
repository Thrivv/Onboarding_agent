"""
Parallel-processing helpers for bulk document upload.

Kept separate from `process_uploaded_document` / `upload_conversational`
in `upload.py` — this module doesn't change either of those. It only adds
a way to run several existing, unmodified per-file calls concurrently and
line their results back up in submission order. See `upload.py`'s
`/upload-conversational-bulk` route for how these pieces fit together,
and why the state-writing step (member_progress.json, ownership
classification) deliberately happens after this, sequentially, never
inside a worker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional, Sequence

from app.services.cross_validator import CrossValidator

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENCY = 5


async def run_parallel(
    items: Sequence,
    worker: Callable,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> list:
    """
    Run `worker(item)` once per item, concurrently, capped at
    `max_concurrency` in flight at once — so a big batch doesn't fire a
    dozen simultaneous calls at the OCR/tampering APIs.

    `worker` is a plain synchronous function. The tamper check and OCR
    calls it wraps are themselves blocking, so each call runs in its own
    thread via `asyncio.to_thread` rather than needing to be rewritten as
    async — `process_uploaded_document` is used as-is.

    Results come back in the SAME ORDER as `items`, regardless of which
    finished first (`asyncio.gather` preserves input order) — callers
    rely on this to line up a result with the file the user actually
    picked.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded(item):
        async with semaphore:
            return await asyncio.to_thread(worker, item)

    return await asyncio.gather(*[_bounded(item) for item in items])


def extract_person_name(extracted_data: Optional[dict]) -> Optional[str]:
    """Best-effort pull of a person's name out of an EID/passport OCR result."""
    if not extracted_data:
        return None

    name = (
        extracted_data.get("Name")
        or extracted_data.get("name")
        or extracted_data.get("full_name")
        or extracted_data.get("Full Name")
        or ""
    ).strip()

    if not name:
        given = (extracted_data.get("given_names") or "").strip()
        surname = (extracted_data.get("surname") or "").strip()
        name = f"{given} {surname}".strip()

    return name or None


def name_matches_expected(expected_member: str, extracted_name: Optional[str]) -> bool:
    """
    Informational only — does the name OCR actually read off this file
    look like the member it was assigned to (by submission order)?

    A False here does not block verification. The existing single-file
    upload path doesn't cross-check this either (should_validate_name in
    upload_conversational is hardcoded off for member documents), so this
    keeps the same trust model. It's surfaced to the frontend so a user
    who picked files in a different order than the member list gets a
    warning instead of a silent misfile — physically reassigning the
    saved document to a different member is a follow-up, not done here.
    """
    if not extracted_name:
        return True
    return CrossValidator()._fuzzy_name_match(expected_member, extracted_name)


def fuzzy_assign_members(pending_members: List[str], extracted_names: List[Optional[str]]) -> dict:
    """
    Greedy best-match assignment of each extracted name (one per uploaded
    file, same order/index as `extracted_names`) to a pending member name.

    Returns {index_into_extracted_names: matched_member_name_or_None}. A
    None means no pending member matched confidently enough for that
    file — the caller should leave it on its order-based slot rather than
    guess.

    Greedy, not a real assignment solver (no Hungarian algorithm): for
    the batch sizes this handles — a handful of members at once — a
    single greedy pass over every (file, candidate) pair, taking the
    strongest match first, is enough and far simpler to reason about.
    """
    matcher = CrossValidator()

    scored = []
    for i, name in enumerate(extracted_names):
        if not name:
            continue
        for candidate in pending_members:
            if matcher._fuzzy_name_match(name, candidate):
                scored.append((i, candidate))

    assignment: dict = {}
    used_files = set()
    used_members = set()
    for i, candidate in scored:
        if i in used_files or candidate in used_members:
            continue
        assignment[i] = candidate
        used_files.add(i)
        used_members.add(candidate)

    for i in range(len(extracted_names)):
        assignment.setdefault(i, None)

    return assignment


def reassign_member_document(save_dir, doc_type: str, ref_no: str, correct_member_index: int):
    """
    Move a document `process_uploaded_document` already saved under a
    guessed member slot (needed up front to give it a collision-free
    folder name — see `upload.py`'s bulk member handler) to the member it
    was actually matched to once OCR revealed the name on the document.

    Mirrors the rename block already inside `process_uploaded_document`
    (same approach: rename folder, rename file, patch output.json) —
    applied a second time here because the first rename used a
    placeholder member, not the confirmed one.

    Returns the new save_dir, or None if the rename didn't happen (logged
    and left under its original name; the file itself is untouched and
    stays verified, only its folder label would be off).
    """
    import json
    import shutil
    from pathlib import Path
    from app.services.document_helpers import build_document_id

    try:
        save_dir = Path(save_dir)
        if not save_dir.exists():
            logger.warning(f"[BULK-REASSIGN] Source missing, skipping: {save_dir}")
            return None

        new_document_id = build_document_id(doc_type, ref_no, True, correct_member_index)
        if save_dir.name == new_document_id:
            return save_dir  # already correctly named

        old_files = [p for p in save_dir.iterdir() if p.is_file() and p.name != "output.json"]
        if not old_files:
            logger.warning(f"[BULK-REASSIGN] No document file found in {save_dir}")
            return None
        old_file = old_files[0]

        new_save_dir = save_dir.parent / new_document_id
        if new_save_dir.exists():
            shutil.rmtree(new_save_dir)

        save_dir.rename(new_save_dir)

        new_filename = f"{new_document_id}{old_file.suffix}"
        old_file_in_new_dir = new_save_dir / old_file.name
        new_file = new_save_dir / new_filename
        if old_file_in_new_dir.exists() and old_file_in_new_dir != new_file:
            old_file_in_new_dir.rename(new_file)

        output_json = new_save_dir / "output.json"
        if output_json.exists():
            with open(output_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["filename"] = new_filename
            data["document_id"] = new_document_id
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        # process_uploaded_document mirrors to EXTERNAL_FILE_PATH (when
        # configured) right after its own first rename, under the
        # placeholder member's name. That mirror is now stale — refresh it
        # under the corrected name. Best-effort and never raises (see its
        # own docstring), matching how the first mirror call is treated.
        try:
            from app.services.document_helpers import mirror_to_external_path
            mirror_to_external_path(new_save_dir)
        except Exception as e:
            logger.warning(f"[BULK-REASSIGN] external mirror refresh failed (non-fatal): {e}")

        logger.info(f"[BULK-REASSIGN] {save_dir.name} -> {new_document_id}")
        return new_save_dir
    except Exception as e:
        logger.warning(f"[BULK-REASSIGN] failed for {save_dir}: {e}")
        return None


def build_bulk_success_message(
    doc_type: Optional[str],
    extracted_data: Optional[dict],
    member_name: Optional[str] = None,
    remaining_docs: Optional[List[str]] = None,
    suppress_next_step: bool = False,
    language: Optional[str] = None,
) -> str:
    """
    Deterministic per-file acknowledgment for a bulk-upload result, worded to
    match `document_messaging.generate_dynamic_valid_document_response()` —
    the LLM-generated text the single-file path (`upload_conversational`)
    shows for a valid document. Same professional-banking phrasing and
    sentence shape ("Your X has been received and validated successfully...
    Next, please upload your Y."), just assembled from fixed strings instead
    of a per-file LLM round trip.

    This used to call generate_dynamic_valid_document_response() directly
    for the nicer wording, with this function only as a template fallback if
    that LLM call failed. That call ran in a plain sequential loop AFTER the
    parallel OCR/tamper-check phase — for a 3-file batch that meant 3 blocking
    OpenRouter round trips (same models, same single API key, doing the
    extraction work moments earlier), each with its own retry + fallback-model
    logic, one after another. That's the actual latency this endpoint's own
    docstrings promise not to add ("a batch whose whole point is to finish
    fast" — see this module's original version and upload.py's `/upload-
    conversational-bulk` comment block). Now this is the ONLY thing bulk
    endpoints call for the success message — no LLM call, no rate-limit
    exposure, same wording every time.

    remaining_docs is expected to already be the display-name list returned
    by chatupload_helpers.get_remaining_required_documents() (e.g.
    ["Commercial License", ...]) — the same source the single-file path
    reads from, so "Next, please upload your X" always names the real next
    required document, not an internal doc_type key.

    suppress_next_step: when a batch verifies more than one document at
    once (e.g. Ejari + EID uploaded together), every valid file used to get
    its own "Next, please upload your X" sentence, all naming the SAME next
    document — read back to back that's the assistant repeating itself. The
    caller passes this as True for every result except the last one in the
    batch, so the instruction is only said once. Deliberately a separate
    flag rather than just passing remaining_docs=None for the earlier
    entries: remaining_docs=[] also means "nothing left, move to the next
    STAGE" for MOA specifically (see below) — conflating "don't repeat
    yourself" with "there is genuinely nothing left" would misfire that
    special case for a mid-batch MOA result.
    """
    from app.services.chatupload_helpers import get_display_document_name
    from app.i18n import render_message, doc_label
    from app.utils.language import normalize_language

    # i18n: rendered from the EN/AR/ES catalog (app/i18n/messages.py) in the
    # request's language (X-User-Language); the returned LocalizedStr also
    # carries the other two renderings so a language toggle can swap it
    # without an LLM call. Still a plain str to every existing caller.
    lang = normalize_language(language)
    doc_type_l = (doc_type or "").lower()
    display_name = get_display_document_name(doc_type_l) if doc_type_l else "Document"
    remaining = [] if suppress_next_step else (remaining_docs or [])

    # ── MOA validated with nothing else outstanding ─────────────────────────
    # Mirrors generate_dynamic_valid_document_response's SPECIAL CASE 1: once
    # remaining_docs is empty right after MOA, the next step isn't "done" —
    # it's the member-verification stage (EID/passport collection), which
    # get_remaining_required_documents() doesn't list yet at this point.
    # Guarded on `not suppress_next_step` so a mid-batch MOA result (not the
    # last file) never claims the batch is done just because its own
    # "next step" sentence is being held back for the final message instead.
    is_moa = doc_type_l in ("moa", "memorandum")
    if is_moa and not remaining and not suppress_next_step:
        return render_message("bulk.moa_done", lang)

    # ── Standard path ────────────────────────────────────────────────────────
    member_ctx = render_message("bulk.member_ctx", lang, name=member_name) if member_name else ""
    next_step = render_message("bulk.next", lang, doc=doc_label(remaining[0], lang)) if remaining else ""
    return render_message("bulk.received", lang, doc=doc_label(display_name, lang),
                          member=member_ctx, next=next_step)


def _duplicate_message(doc_type: str):
    from app.i18n import render_message, doc_label
    from app.services.chatupload_helpers import get_display_document_name
    return render_message("bulk.duplicate", None, doc=doc_label(get_display_document_name(doc_type)))


def dedupe_by_document_type(raw_results: List[dict]) -> List[dict]:
    """
    Given a list of per-file results (each with `_filename` and
    `document_type`/`is_valid` keys, as returned by
    `process_uploaded_document`), keep the first valid result per
    document type and flag any later ones in the same batch as
    duplicates rather than silently overwriting the first.

    Used for the corporate-documents batch, where a user might
    accidentally pick two files that both turn out to be the commercial
    licence — `process_uploaded_document` would otherwise rename the
    second on top of the first's already-saved folder.
    """
    seen_types = set()
    out = []
    for r in raw_results:
        doc_type = (r.get("document_type") or "unknown").lower()
        is_valid = bool(r.get("is_valid"))
        if is_valid and doc_type in seen_types:
            out.append({
                **r,
                "is_valid": False,
                "success": False,
                "duplicate_in_batch": True,
                "message": _duplicate_message(doc_type),
            })
            continue
        if is_valid:
            seen_types.add(doc_type)
        out.append(r)
    return out
