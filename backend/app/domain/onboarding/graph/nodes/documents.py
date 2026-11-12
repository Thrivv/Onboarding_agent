"""
Stage 4/5/6 — classify_account and the document-collection nodes.

`classify_account` (Stage 4) loads the user record and seeds the rest of
`OnboardingState` via `graph.adapters.state_from_user` — the same read-only
helpers `get_onboarding_status()` already calls. It also carries the
ownership-ambiguous interrupt (Stage 6): `graph.pending.ownership_ambiguous`
is the same check `_resolve_pending_actions` performs, ported in Stage 2.

`collect_commercial_only` / `collect_moa_ejari_identity` / `collect_moa_ejari`
/ `collect_member_eids` (Stage 5) all share one body, `_process_document`,
which wraps `process_uploaded_document` exactly as `upload.py` and
`handle_reply.py` call it today — same arguments, same file writes, same
return shape. Nothing about OCR, tampering detection, cross-validation, or
message generation is reimplemented here; this module only decides which
existing call to make and folds its result back into `OnboardingState`.

None of `process_uploaded_document`'s internals can be exercised in an
environment without a real AWS_BEARER_TOKEN_BEDROCK and live document images — the
wiring below is verified by inspection and by the smoke test in
`tests/graph_smoke_test.py` (which stubs `process_uploaded_document` itself),
not by actually invoking OCR from this sandbox.
"""

from __future__ import annotations
from app.i18n import localized

import logging
from typing import Any, Optional

from langgraph.types import interrupt

from app.domain.onboarding.graph.pending import ownership_ambiguous
from app.domain.onboarding.graph.state import OnboardingState

logger = logging.getLogger(__name__)


async def classify_account(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 4 entry node. Loads/refreshes the full state from Supabase + disk,
    then (Stage 6) pauses for the ownership choice if the Commercial License
    auto-classification couldn't confidently read it.

    Async because the resume path below calls the existing
    `save_ownership_type` FastAPI route handler directly (it is an `async
    def`) rather than duplicating its Supabase-write + breadcrumb-clear
    logic here — the same "call the real handler, don't re-derive its body"
    pattern every interrupt node in `graph/nodes/key_individuals.py` follows.
    """
    from app.repositories.user_repository import UserRepository
    from app.domain.onboarding.graph.adapters import state_from_user

    email = state["email"]
    try:
        result = UserRepository.get_by_email_limit_one(email)
        user = result.data[0] if result.data else {}
    except Exception as exc:
        logger.error(f"[graph.classify_account] could not load user {email}: {exc}")
        user = {}

    fresh = state_from_user(email, user, channel=state.get("channel", "chat"))

    # ── Stage 6 — ownership-ambiguous interrupt ─────────────────────────────
    # Ported from stages.py: this used to be an inline `ai_message` override
    # in get_onboarding_status(), fired whenever ownership_ambiguous.json
    # exists. Here it pauses the graph instead of just changing what text the
    # next response contains.
    pending = ownership_ambiguous(email, fresh)
    if pending is not None:
        answer = interrupt(pending)
        # `answer` is expected to be {"ownership_type": ..., "partnership_details": ...}
        # — exactly OwnershipTypeSaveRequest's fields (schemas/ownership.py).
        from app.api.routes.onboarding.ownership import save_ownership_type
        from app.schemas.ownership import OwnershipTypeSaveRequest

        try:
            await save_ownership_type(
                OwnershipTypeSaveRequest(
                    email=email,
                    ownership_type=answer.get("ownership_type", ""),
                    partnership_details=answer.get("partnership_details"),
                )
            )
        except Exception as exc:
            logger.error(f"[graph.classify_account] save_ownership_type failed for {email}: {exc}")
        fresh["ownership_type"] = answer.get("ownership_type", fresh.get("ownership_type"))

    return dict(fresh)


async def _process_document_raw(
    state: OnboardingState,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """
    Does the actual work for `_process_document`, but also hands back the
    raw `process_uploaded_document` result (not just the folded-in state
    updates) — `graph/nodes/members.py`'s `collect_moa_ejari` override needs
    `result["document_type"]` / `result["is_valid"]` to reproduce the same
    member-expansion trigger condition `upload.py` checks today (see that
    module for why: expansion has to fire after EVERY corporate-stage
    document that could plausibly be the last one uploaded, which is a
    decision that needs OCR's classification of what was just uploaded, not
    just whether *something* was uploaded).

    Returns `(state_updates, raw_result)` — `raw_result` is `None` exactly
    when `state_updates` is `{}` (no upload present on this invocation).
    """
    upload = state.get("upload")
    email = state["email"]

    if not upload:
        # No file attached to this invocation — this call is a plain status
        # check (e.g. the frontend polling for the next required document).
        # Nothing to process; route_by_ownership will be re-evaluated with
        # the state exactly as it stands.
        return {}, None

    from app.domain.onboarding.verification.document_processing import (
        process_uploaded_document,
    )
    from app.services.chatupload_helpers import check_documents_status
    from app.domain.onboarding.documents import get_submitted_documents

    try:
        result = process_uploaded_document(
            email=email,
            uploaded_file=upload["file"],
            member_name=upload.get("member_name"),
            language=upload.get("language", "english"),
            precomputed_tampering_result=upload.get("precomputed_tampering_result"),
        )
    except Exception as exc:
        logger.error(f"[graph.process_document] {email}: {exc}")
        result = {"message": localized(None,
            en="I couldn't process that document — please try uploading it again.",
            es="No pude procesar ese documento. Intente cargarlo de nuevo.",
            ar="لم أتمكن من معالجة هذا المستند — يُرجى محاولة تحميله مرة أخرى.")}

    message = result.get("message") if isinstance(result, dict) else None

    updates = {
        "doc_status": check_documents_status(email),
        "submitted_documents": get_submitted_documents(email),
        "upload": None,
        "messages": [{"role": "assistant", "content": message}] if message else [],
    }
    return updates, result


async def _process_document(state: OnboardingState) -> dict[str, Any]:
    """
    Shared body for every `collect_*` node (Stage 5). Consumes
    `state["upload"]` if present — see the field's docstring in `state.py`
    for why this is transient and always cleared before the node returns.

    Async for consistency with `classify_account` and the Stage 7 KI/member
    interrupt nodes below it in the graph — every node in this package is
    invoked via `ainvoke`/`ainvoke`'d subgraphs (see `graph/build.py`), so a
    mixed sync/async node set would work with LangGraph but would be a trap
    for the next person adding a node here. `process_uploaded_document`
    itself is still a plain sync call underneath (unchanged, not reimplemented
    — see the module docstring); only this wrapper's signature changes.
    """
    updates, _raw = await _process_document_raw(state)
    return updates


# Every collect_* node currently shares the same body — kept as four
# separate names (matching graph/routing.py's NODE_* constants) rather than
# one node with an internal switch, because Stage 7's Type-2 corporate-
# shareholder handling needs to hook `collect_member_eids` specifically
# without touching the other three.
#
# NOTE — `collect_moa_ejari` here is the plain document-processing body.
# `graph/build.py` wires `routing.NODE_COLLECT_MOA_EJARI` to
# `graph.nodes.members.collect_moa_ejari` instead (Stage 7's member-
# expansion override), not to this name — this module's version is kept
# only because `members.collect_moa_ejari` imports and wraps it via
# `_process_document_raw`, and as a documented reminder of what the
# unwrapped body looks like.
collect_commercial_only = _process_document
collect_moa_ejari_identity = _process_document
collect_moa_ejari = _process_document

# STAGE_MEMBER_EIDS / STAGE_SO_MEMBER_EIDS — collecting each member's own
# Emirates ID / Passport. No member-expansion trigger applies here (that
# only fires on the corporate-stage documents `members.collect_moa_ejari`
# handles); this is a plain document upload like the other three.
collect_member_eids = _process_document


async def unsupported_account(state: OnboardingState) -> dict[str, Any]:
    """Reached for any non-Corporate account — this product has no flow for it."""
    return {
        "messages": [
            {
                "role": "assistant",
                "content": "This account type isn't supported by the onboarding flow yet.",
            }
        ]
    }


__all__ = [
    "classify_account",
    "collect_commercial_only",
    "collect_moa_ejari_identity",
    "collect_moa_ejari",
    "collect_member_eids",
    "unsupported_account",
]
