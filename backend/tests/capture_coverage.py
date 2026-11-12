#!/usr/bin/env python3
"""
Is the B0 capture good enough to refactor against?

Run this after a capture, BEFORE starting B5:

    python backend/tests/capture_coverage.py

Exit 0 means the recording exercises every branch B5 is going to disturb.
Exit 1 means refactoring against it would be refactoring blind in the places
that matter.

## Why this exists

The first capture produced five files, ~150 records and 768 KB of JSON. It
looked like a successful run. It was not: **all 70 `get_onboarding_status`
records were stage `identification`**, `handle_verification_response` had
exactly one record for a 1,246-line function, and every HTTP response was 200 —
no wrong-document, re-upload or unsupported-file path anywhere.

That is not a safety net. It is a safety net over the first third of one flow,
and the entangled functions B5 decomposes live past that point. A replay suite
built on it would pass and mean nothing — the same trap as the deliberately
broken stage table that 85 of 709 golden cases caught, except here nothing
would catch it.

File count is not coverage. This checks the thing that is actually load-bearing:
which rows of the stage table the recording walked.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "logs" / "backend" / "capture"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# Minimum records before a function's recording is worth replaying at all.
#
# These were recalibrated on 28 July 2026 against a real two-flow capture,
# because the first set was guessed and two of the numbers were wrong in a way
# that made a usable capture look insufficient. Each is now tied to how the
# function is actually reached:
#
# - get_submitted_documents / get_onboarding_status are polled constantly by the
#   UI, so a completed flow produces hundreds. 20/40 is a floor, not a target.
# - process_uploaded_document fires once per uploaded file. Two full flows plus
#   a rejected document is ~20.
# - handle_verification_response is reached ONLY from conversation.py:341, i.e.
#   when the user types a reply to a verification question. Its docstring
#   records **29 return statements**. One recording covers one of them, so this
#   is the one function where the count genuinely gates B5.
MIN_RECORDS = {
    "get_submitted_documents": 20,
    "get_onboarding_status": 40,
    "process_uploaded_document": 20,
    "handle_verification_response": 8,
}

# Every stage the table can report. A capture that never reaches one cannot
# protect the code path that produces it.
REQUIRED_STAGES = {
    "identification",
    "so_member_eids",
    "member_eids",
}

# Document types both runs should produce between them.
#
# NOTE: the value is `eid`, not `emirates_id`. `emirates_id` is the key used in
# the validation field map in documents.py; the extractor and
# process_uploaded_document both emit `eid`. The first version of this file
# required `emirates_id` and therefore reported "never uploaded" against a
# capture containing four of them.
REQUIRED_DOC_TYPES = {"commercial", "ejari", "moa", "eid"}

# The required_documents lists that correspond to distinct stage-table rows.
REQUIRED_DOC_SETS = {
    ("commercial",),                           # unclassified
    ("commercial", "ejari", "identity"),       # single owner, identification
    ("commercial", "ejari", "moa"),            # partnership, identification
}

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)
    print(f"  {RED}GAP{RESET}   {msg}")


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}    {msg}")


def warn(msg: str) -> None:
    notes.append(msg)
    print(f"  {YELLOW}NOTE{RESET}  {msg}")


def load(name: str) -> list[dict]:
    path = CAPTURE / f"{name}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    print("=" * 72)
    print("  B0 CAPTURE COVERAGE — is this good enough to refactor against?")
    print("=" * 72)

    if not CAPTURE.exists():
        print(f"\n{RED}No capture directory at {CAPTURE}{RESET}")
        print("Run docs/B0-capture-runbook.md first.")
        return 1

    # ---------------------------------------------------------------- volume
    print(f"\n{DIM}[1/4] Record volume{RESET}")
    for name, minimum in MIN_RECORDS.items():
        recs = load(name)
        if not recs:
            fail(f"{name}: no records at all — the function was never reached")
        elif len(recs) < minimum:
            fail(f"{name}: {len(recs)} records, want >= {minimum}")
        else:
            ok(f"{name}: {len(recs)} records")

    # ---------------------------------------------------------------- stages
    print(f"\n{DIM}[2/4] Stage-table rows walked{RESET}")
    status = load("get_onboarding_status")
    stages = Counter()
    doc_sets = Counter()
    for r in status:
        ret = r.get("return")
        if not isinstance(ret, dict):
            continue
        if isinstance(ret.get("stage"), str):
            stages[ret["stage"]] += 1
        req = ret.get("required_documents")
        if isinstance(req, list) and all(isinstance(x, str) for x in req):
            doc_sets[tuple(req)] += 1

    if not stages:
        fail("no stage values recorded — cannot tell what was walked")
    else:
        for stage in sorted(REQUIRED_STAGES):
            if stages.get(stage):
                ok(f"stage '{stage}': {stages[stage]} records")
            else:
                fail(f"stage '{stage}': NEVER REACHED")
        extra = set(stages) - REQUIRED_STAGES
        if extra:
            warn(f"also saw: {', '.join(sorted(extra))}")

    print(f"\n{DIM}      required_documents combinations seen{RESET}")
    for combo in sorted(REQUIRED_DOC_SETS):
        if doc_sets.get(combo):
            ok(f"{list(combo)}: {doc_sets[combo]}")
        else:
            fail(f"{list(combo)}: never produced")

    # ------------------------------------------------------------ doc types
    print(f"\n{DIM}[3/4] Document types processed{RESET}")
    seen_types = Counter()
    for r in load("process_uploaded_document"):
        ret = r.get("return")
        if isinstance(ret, dict) and isinstance(ret.get("document_type"), str):
            seen_types[ret["document_type"]] += 1
    for dt in sorted(REQUIRED_DOC_TYPES):
        if seen_types.get(dt):
            ok(f"{dt}: {seen_types[dt]}")
        else:
            fail(f"{dt}: never uploaded")

    # --------------------------------------------------------- error paths
    #
    # Rejected documents are reported IN THE PAYLOAD, not in the status code:
    # `upload-conversational` answers 200 with `document_type: "unknown"` and
    # `is_valid: false`, and the UI renders the reasoning message. So a capture
    # of 31 responses that are all 200 says nothing about whether the failure
    # branches were walked.
    #
    # The first version of this check required a non-200 response and therefore
    # reported "failure cases not exercised" against a capture that contained
    # two rejected uploads. Status code was the wrong signal entirely.
    print(f"\n{DIM}[4/4] Failure paths{RESET}")
    rejected = 0
    for r in load("process_uploaded_document"):
        ret = r.get("return")
        if not isinstance(ret, dict):
            continue
        if ret.get("document_type") == "unknown" or ret.get("is_valid") is False:
            rejected += 1
    if rejected:
        ok(f"{rejected} rejected document(s) recorded (unknown type / is_valid false)")
    else:
        fail(
            "no rejected documents — upload a wrong type, a duplicate or an "
            "unsupported file so the rejection branch is recorded"
        )

    http = load("_http")
    if not http:
        fail("_http.jsonl empty — neither HTTP handler was recorded")
    else:
        ok(f"{len(http)} HTTP records: {dict(Counter(r.get('status') for r in http))}")

    paths = Counter(r.get("path", "").rsplit("/", 1)[-1] for r in http)
    for handler in ("upload-conversational", "chat-conversational"):
        n = paths.get(handler, 0)
        if n >= 10:
            ok(f"{handler}: {n} calls")
        else:
            fail(f"{handler}: {n} calls, want >= 10")

    # ---------------------------------------------------------------- verdict
    print("\n" + "=" * 72)
    if problems:
        print(f"  {RED}CAPTURE INSUFFICIENT{RESET} — {len(problems)} gap(s)")
        print("  Do not start B5 against this recording.\n")
        for p in problems:
            print(f"    - {p}")
        print(
            f"\n  {DIM}Re-run docs/B0-capture-runbook.md and carry BOTH flows all the"
            f"\n  way to completion — not just the identification stage.{RESET}"
        )
        return 1

    print(f"  {GREEN}CAPTURE SUFFICIENT{RESET} — every branch B5 touches is represented")
    if notes:
        print(f"  {YELLOW}{len(notes)} note(s){RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
