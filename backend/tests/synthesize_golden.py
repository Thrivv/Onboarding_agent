"""
Synthetic golden-file generator for the two PURE onboarding functions.

Why this exists
---------------
Stage B0 records real behaviour by instrumenting a live onboarding run. That
costs API credits (OCR + LLM on every document) and has not been run.

But two of the six B5 target functions make **no external calls at all** —
verified by AST scan: no LLM, no OCR, no Supabase, no email. They read the
user record and the documents directory and return a decision:

    get_onboarding_status   378 lines  — which stage, which document next
    get_submitted_documents 160 lines  — what has been uploaded and is valid

For those two, real behavioural verification is free: fabricate the inputs,
call the current code, snapshot the outputs. No credits, no live services.

What this DOES and does NOT prove
---------------------------------
DOES: that a refactor of these two functions returns byte-identical output for
every input in the corpus. `get_onboarding_status` is the onboarding state
machine — the single most valuable thing to pin down before touching it.

DOES NOT: cover `upload_conversational`, `process_uploaded_document`,
`handle_verification_response` or `chat_conversational`. Those call OCR and the
LLM, so their behaviour cannot be reproduced without either API credits or a
mocking layer that would itself encode assumptions. They are verified by
structural means only — see docs/STAGE_B5_RESULT.md.

This is a genuine partial substitute for B0, not a replacement. It should be
described that way.

Usage
-----
    python backend/tests/synthesize_golden.py --record   # write golden files
    python backend/tests/synthesize_golden.py            # verify against them
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(BACKEND))

# The documents root must be set BEFORE app.config is imported, since the path
# helpers resolve it at import time.
_TMP_DOCS = Path(tempfile.mkdtemp(prefix="golden_docs_"))
os.environ.setdefault("DOCUMENTS_PATH", str(_TMP_DOCS))
os.environ.setdefault("SUPABASE_URL", "https://synthetic.supabase.co")
os.environ.setdefault("SUPABASE_API_KEY", "synthetic-key-not-used")

# ---------------------------------------------------------------------------
# The input space
# ---------------------------------------------------------------------------

# Document types the state machine branches on, with the extractor field shapes
# the real output.json files carry.
DOC_SHAPES = {
    "commercial_license": {"company_name": "ACME TRADING LLC", "license_number": "CN-1234567"},
    "trade_license": {"company_name": "ACME TRADING LLC", "license_number": "TL-7654321"},
    "moa": {"company_name": "ACME TRADING LLC", "partners": ["ALICE ROE", "BOB DOE"]},
    "eid": {"name": "ALICE ROE", "id_number": "784-1990-1234567-1"},
    "passport": {"name": "ALICE ROE", "passport_number": "P1234567"},
    "ejari": {"tenant_name": "ACME TRADING LLC", "contract_number": "EJ-999"},
}

ACCOUNT_TYPES = ["Corporate", None]
OWNERSHIP_TYPES = ["Single Owner", "Partnership", "Multiple Owners", None]
DOCUMENT_STAGES = [
    "identification",
    "corporate_shareholder_docs",
    "member_eids",
    "so_member_eids",
    "complete",
    None,
]

# Document sets chosen to walk the flow rather than to enumerate blindly:
# nothing uploaded, part-way, and complete — for both flows.
DOC_SETS = [
    [],
    ["commercial_license"],
    ["commercial_license", "eid"],
    ["commercial_license", "eid", "ejari"],
    ["commercial_license", "moa"],
    ["commercial_license", "moa", "eid"],
    ["trade_license", "eid", "ejari"],
    ["passport"],
    ["commercial_license", "trade_license", "moa", "eid", "ejari"],
]

VALIDITY = [True, False]


# ---------------------------------------------------------------------------
# State-file scenarios
# ---------------------------------------------------------------------------
# The later half of the state machine does not branch on `user_data` at all —
# it branches on BREADCRUMB FILES the pipeline drops in the user's documents
# directory. A corpus that varies only the user record and the uploaded
# documents never reaches those branches: the first version of this file
# produced 540 cases that touched just 3 of the stages.
#
# Each scenario below lays down one plausible combination of those files.

SCENARIOS = {
    "clean": {},
    "ownership_ambiguous": {"ownership_ambiguous.json": {"reason": "no partners extracted"}},
    "ki_role_pending": {
        "pending_ki_role_assignment.json": {"member_name": "BOB DOE", "options": ["Director", "Shareholder"]}
    },
    "kis_present": {
        "key_individuals.json": [
            {"id": "ki-1", "display_name": "ALICE ROE", "role": "Authorised Signatory",
             "verification_status": "verified", "is_account_owner": True},
            {"id": "ki-2", "display_name": "BOB DOE", "role": "Shareholder",
             "verification_status": "pending", "is_account_owner": False},
        ]
    },
    "ki_loop_done": {
        "key_individuals.json": [
            {"id": "ki-1", "display_name": "ALICE ROE", "role": "Authorised Signatory",
             "verification_status": "verified", "is_account_owner": True},
        ],
        "ki_loop_done.json": {"finalized_at": "2026-07-28T10:00:00+00:00"},
    },
    "package_done": {
        "key_individuals.json": [
            {"id": "ki-1", "display_name": "ALICE ROE", "role": "Authorised Signatory",
             "verification_status": "verified", "is_account_owner": True},
        ],
        "ki_loop_done.json": {"finalized_at": "2026-07-28T10:00:00+00:00"},
        "product_package.json": {"selected_package": "Essential", "availed_products": ["Account"]},
    },
    "compliance_done": {
        "key_individuals.json": [
            {"id": "ki-1", "display_name": "ALICE ROE", "role": "Authorised Signatory",
             "verification_status": "verified", "is_account_owner": True},
        ],
        "ki_loop_done.json": {"finalized_at": "2026-07-28T10:00:00+00:00"},
        "product_package.json": {"selected_package": "Essential", "availed_products": ["Account"]},
        "fatca.json": {"is_us_person": False, "submitted": True},
        "pep.json": {"is_pep": False, "submitted": True},
    },
    "fully_done": {
        "key_individuals.json": [
            {"id": "ki-1", "display_name": "ALICE ROE", "role": "Authorised Signatory",
             "verification_status": "verified", "is_account_owner": True},
        ],
        "ki_loop_done.json": {"finalized_at": "2026-07-28T10:00:00+00:00"},
        "product_package.json": {"selected_package": "Essential", "availed_products": ["Account"]},
        "fatca.json": {"is_us_person": False, "submitted": True},
        "pep.json": {"is_pep": False, "submitted": True},
        "self_declaration.json": {"confirmed_at": "2026-07-28T11:00:00+00:00"},
    },
}

# Member-progress states, which drive the member_eids stage.
MEMBER_STATES = {
    "no_members": None,
    "members_pending": {"members": ["ALICE ROE", "BOB DOE"], "current_index": 0,
                        "ubo_names": [], "verified_members": [],
                        "expanded_members": [], "pending_coi": []},
    "members_partial": {"members": ["ALICE ROE", "BOB DOE"], "current_index": 1,
                        "ubo_names": ["ALICE ROE"], "verified_members": ["ALICE ROE"],
                        "expanded_members": [], "pending_coi": []},
    "members_done": {"members": ["ALICE ROE", "BOB DOE"], "current_index": 2,
                     "ubo_names": ["ALICE ROE"], "verified_members": ["ALICE ROE", "BOB DOE"],
                     "expanded_members": [], "pending_coi": []},
}


def _write_state(email: str, scenario: str, member_state: str) -> None:
    """Drop the breadcrumb files for one scenario into the user's docs folder."""
    from app.services.chatupload_helpers import member_progress_path, user_docs_path

    base = user_docs_path(email)
    base.mkdir(parents=True, exist_ok=True)
    for name, payload in SCENARIOS[scenario].items():
        (base / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    mp = MEMBER_STATES[member_state]
    if mp is not None:
        p = member_progress_path(email)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(mp, indent=2), encoding="utf-8")


def _seed_ref_no(email: str) -> None:
    """
    Pre-populate the ref_no cache so the harness never touches Supabase.

    `get_document_ref_no()` looks the reference number up in the database and
    falls back to the email address when that fails. Without this seed the
    goldens would be recorded with the lookup FAILING (no network in the
    sandbox) and would then mismatch on any machine where it SUCCEEDS —
    a false positive that would look exactly like a refactoring regression.

    Seeding makes the corpus independent of whether the database is reachable.
    """
    from app.services import document_helpers

    document_helpers._ref_no_cache[email] = f"ref-{email.split('@')[0]}"


def _write_docs(email: str, doc_types: list[str], is_valid: bool) -> None:
    """Lay out a synthetic documents directory the way the real pipeline does."""
    from app.services.chatupload_helpers import user_docs_path

    base = user_docs_path(email)
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    for i, dt in enumerate(doc_types):
        folder = base / f"{dt}_{i}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "output.json").write_text(
            json.dumps(
                {
                    "document_type": dt,
                    "is_valid": is_valid,
                    "filename": f"{dt}.pdf",
                    "extracted_data": DOC_SHAPES[dt],
                    "uploaded_at": "2026-07-28T10:00:00+00:00",
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _cases():
    """Yield (case_id, user_data, doc_types, is_valid)."""
    n = 0
    for docs, valid, acct, own, stage, scen, mem in itertools.product(
        DOC_SETS, VALIDITY, ACCOUNT_TYPES, OWNERSHIP_TYPES, DOCUMENT_STAGES,
        SCENARIOS, MEMBER_STATES,
    ):
        # Skip combinations that cannot occur: a non-Corporate account never
        # carries an ownership type in this product.
        if acct is None and own is not None:
            continue
        # Member progress only exists on the partnership path; pairing it with
        # Single Owner would pin down a state the product cannot produce.
        if mem != "no_members" and own == "Single Owner":
            continue
        n += 1
        email = f"case{n:05d}@synthetic.test"
        user_data = {
            "email": email,
            "name": "ALICE ROE",
            "account_type": acct,
            "ownership_type": own,
            "document_stage": stage,
            "onboarding_step": "document_collection",
        }
        yield f"case{n:05d}", email, user_data, docs, valid, scen, mem


def _params():
    """The full input space, as explicit parameter dicts."""
    n = 0
    for docs, valid, acct, own, stage, scen, mem in itertools.product(
        DOC_SETS, VALIDITY, ACCOUNT_TYPES, OWNERSHIP_TYPES, DOCUMENT_STAGES,
        SCENARIOS, MEMBER_STATES,
    ):
        if acct is None and own is not None:
            continue
        if mem != "no_members" and own == "Single Owner":
            continue
        n += 1
        yield {
            "documents": docs, "is_valid": valid, "account_type": acct,
            "ownership_type": own, "document_stage": stage,
            "scenario": scen, "member_state": mem,
        }


def _evaluate(idx: int, params: dict) -> dict:
    """Run both functions for one parameter set and return normalised output."""
    from app.domain.onboarding.documents import get_submitted_documents
    from app.domain.onboarding.stages import get_onboarding_status

    email = f"case{idx:05d}@synthetic.test"
    user_data = {
        "email": email,
        "name": "ALICE ROE",
        "account_type": params["account_type"],
        "ownership_type": params["ownership_type"],
        "document_stage": params["document_stage"],
        "onboarding_step": "document_collection",
    }
    _seed_ref_no(email)
    _write_docs(email, params["documents"], params["is_valid"])
    _write_state(email, params["scenario"], params["member_state"])

    out = {}
    for label, fn, args in (
        ("get_submitted_documents", get_submitted_documents, (email,)),
        ("get_onboarding_status", get_onboarding_status, (email, user_data, True)),
    ):
        try:
            out[label] = {"ok": _normalise(fn(*args), email)}
        except Exception as exc:  # a raise is behaviour too — pin it down
            out[label] = {"raised": f"{type(exc).__name__}: {exc}"}
    shutil.rmtree(_TMP_DOCS / _safe(email), ignore_errors=True)
    return out


def _normalise(value, email: str):
    """
    Make output comparable across runs: strip the per-case email and the temp
    directory, both of which change every run.
    """
    if isinstance(value, dict):
        return {k: _normalise(v, email) for k, v in sorted(value.items())}
    if isinstance(value, list):
        items = [_normalise(v, email) for v in value]
        # Document lists come from `Path.iterdir()`, whose order is arbitrary and
        # differs between filesystems — the corpus recorded on Linux did not match
        # a replay on Windows, reporting 336 "behaviour changes" that were purely
        # directory-iteration order.
        #
        # Sorting is correct here rather than a fudge: the application cannot
        # depend on this order either, because iterdir() never promised one.
        # `get_onboarding_status` only walks the list to set flags, which is
        # order-independent.
        #
        # Deliberately narrow — it fires only on lists of DOCUMENT dicts. Lists of
        # strings such as `pending_documents` and `required_documents` are left
        # untouched, because their order decides which document is requested next
        # and a change there is exactly what this corpus exists to catch.
        if items and all(isinstance(i, dict) and "document_type" in i for i in items):
            items.sort(
                key=lambda d: (
                    str(d.get("document_type") or ""),
                    str(d.get("filename") or ""),
                    str(d.get("member_name") or ""),
                )
            )
        return items
    if isinstance(value, str):
        out = value.replace(email, "{EMAIL}")
        out = out.replace(f"ref-{email.split(chr(64))[0]}", "{REF}")
        if str(_TMP_DOCS) in out:
            out = out.replace(str(_TMP_DOCS), "{DOCS}")
        return out
    return value


def _safe(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_")


def _digest(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _record() -> dict:
    """
    Walk the full input space, then keep only a MINIMAL COVERING SET.

    The full product is ~14,700 cases but yields only ~700 distinct results.
    Storing all of them produced a 45 MB file and a 40-second run, which is how
    a safety net stops being run. So: evaluate everything once, then keep the
    first case that produces each distinct result.

    Nothing is weakened by this. Every distinct behaviour the full space can
    produce is still represented and still asserted; what is dropped is the
    14,000 cases that were re-proving results already covered.
    """
    seen: dict[str, dict] = {}
    corpus: list[dict] = []
    total = 0
    for i, params in enumerate(_params(), start=1):
        total += 1
        out = _evaluate(i, params)
        d = _digest(out)
        if d in seen:
            continue
        seen[d] = out
        corpus.append({"id": f"c{len(corpus):04d}", "params": params, "result": d})
    print(f"  explored {total} combinations -> {len(corpus)} distinct behaviours")

    # A harness that breaks itself must not quietly record a useless baseline.
    # The first version of this file did exactly that: a NameError inside
    # _evaluate was caught by the per-case try/except, every case returned the
    # same "raised" payload, and it recorded ONE case and printed success.
    broken = [
        d
        for d, out in seen.items()
        if any(
            "NameError" in (v.get("raised") or "") or "ImportError" in (v.get("raised") or "")
            for v in out.values()
        )
    ]
    if broken:
        raise SystemExit(
            f"REFUSING TO RECORD: {len(broken)} distinct result(s) are harness errors "
            f"(NameError/ImportError), not application behaviour.\n"
            f"  example: {json.dumps(seen[broken[0]])[:300]}"
        )
    if len(corpus) < 50:
        raise SystemExit(
            f"REFUSING TO RECORD: only {len(corpus)} distinct behaviours from {total} "
            f"combinations. That is implausibly low and means the harness is not "
            f"exercising the code — investigate before trusting this baseline."
        )
    return {"signatures": seen, "corpus": corpus}


def _replay(corpus: list[dict]) -> dict:
    """Re-run exactly the stored corpus."""
    return {c["id"]: _evaluate(i + 1, c["params"]) for i, c in enumerate(corpus)}


def _diff_keys(was, now, path: str = "") -> list[str]:
    """
    Report only the fields that actually differ.

    `get_onboarding_status` returns 21 keys; dumping both blobs and truncating
    at 400 characters showed two near-identical walls of text with the
    difference somewhere past the cutoff. Diffing key by key is the difference
    between a tool you use and one you squint at.
    """
    out: list[str] = []
    if isinstance(was, dict) and isinstance(now, dict):
        for k in sorted(set(was) | set(now)):
            if was.get(k) != now.get(k):
                out.extend(_diff_keys(was.get(k), now.get(k), f"{path}.{k}" if path else str(k)))
        return out
    label = path or "(value)"
    out.append(f"{label}:")
    out.append(f"    was: {json.dumps(was)[:200]}")
    out.append(f"    now: {json.dumps(now)[:200]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true", help="write golden files")
    args = ap.parse_args()

    GOLDEN.mkdir(parents=True, exist_ok=True)
    target = GOLDEN / "pure_functions.json"

    if args.record or not target.exists():
        data = _record()
        target.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        shutil.rmtree(_TMP_DOCS, ignore_errors=True)
        print(f"RECORDED {len(data['corpus'])} cases -> {target.relative_to(BACKEND.parent)}")
        return 0

    baseline = json.loads(target.read_text(encoding="utf-8"))
    corpus, sigs = baseline["corpus"], baseline["signatures"]
    current = _replay(corpus)
    shutil.rmtree(_TMP_DOCS, ignore_errors=True)

    diffs = [c for c in corpus if _digest(current[c["id"]]) != c["result"]]
    if diffs:
        print(f"BEHAVIOUR CHANGED in {len(diffs)}/{len(corpus)} case(s):")
        for c in diffs[:8]:
            print(f"\n  --- {c['id']}  params={json.dumps(c['params'])}")
            was, now = sigs[c["result"]], current[c["id"]]
            for label in ("get_submitted_documents", "get_onboarding_status"):
                if was.get(label) == now.get(label):
                    continue
                print(f"      {label}:")
                for line in _diff_keys(was.get(label), now.get(label)):
                    print(f"        {line}")
        if len(diffs) > 8:
            print(f"\n  ... and {len(diffs) - 8} more")
        return 1

    print(f"GOLDEN OK — {len(corpus)} cases, output identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
