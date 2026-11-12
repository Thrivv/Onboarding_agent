#!/usr/bin/env python3
"""
Does "not correct" still mean no?

    python backend/tests/confirmation_check.py

Exit 0 = every case behaves. Exit 1 = a case regressed, named.

## Why this file exists

`is_confirmation` decides whether a typed chat message runs
`handle_verification_response`, which calls `update_user_onboarding_status` at
four sites and `update_ki_verification_by_name` at one. **A wrong answer here
moves a real application forward.**

The implementation it replaced was a substring scan, so `not correct` matched
`correct` and advanced the stage — a user rejecting a document approved it.
`looks broken` matched `ok` inside `lo-ok-s`; `my business name` matched `si`
inside `bu-si-ness`.

None of the other suites can see this. `contract_check` proves the route and
the signature are unchanged; the golden corpus covers stage resolution given a
state, not how a sentence is classified. This is the only thing standing
between that bug and a rebuild.

Cases are grouped by what they protect, so a failure says what broke rather
than just which string.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.onboarding.confirmation import is_confirmation  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

# (message, expected, why it matters)
CASES: list[tuple[str, bool, str]] = [
    # ---- plain approvals must keep working -------------------------------
    ("yes", True, "the most common approval"),
    ("ok", True, "the second most common"),
    ("okay", True, ""),
    ("Okay", True, "case-insensitive"),
    ("  yes  ", True, "surrounding whitespace"),
    ("confirm", True, ""),
    ("correct", True, ""),
    ("verified", True, ""),
    ("sure", True, ""),
    ("yep", True, ""),
    ("yeah", True, ""),
    ("perfect", True, ""),
    ("fine", True, ""),
    ("right", True, ""),
    ("good", True, ""),
    ("approve", True, ""),
    ("approved", True, ""),
    ("looks good", True, "phrase must beat its component words"),
    # ---- Spanish ---------------------------------------------------------
    ("si", True, "Spanish yes, unaccented"),
    ("sí", True, "Spanish yes, accented — must behave identically"),
    ("vale", True, ""),
    ("claro", True, ""),
    ("correcto", True, ""),
    ("bien", True, ""),
    ("perfecto", True, ""),
    ("se ve bien", True, "phrase"),
    ("de acuerdo", True, "phrase"),
    # ---- THE BUG: negation must never approve ----------------------------
    ("not correct", False, "THE BUG — used to advance the stage"),
    ("that is not correct", False, "THE BUG"),
    ("no", False, ""),
    ("nope", False, ""),
    ("this is wrong", False, ""),
    ("incorrect", False, ""),
    ("the DOB is wrong", False, "correction, not approval"),
    ("the name is different", False, ""),
    ("dont confirm", False, "negated verb"),
    ("don't confirm", False, "apostrophe must not defeat the negation"),
    ("no es correcto", False, "Spanish negation"),
    ("incorrecto", False, "Spanish"),
    # ---- THE BUG: substring matches ---------------------------------------
    ("looks broken", False, "THE BUG — 'ok' inside 'looks'"),
    ("my business name", False, "THE BUG — 'si' inside 'business'"),
    ("the address is missing", False, "THE BUG — 'si' inside 'missing'"),
    # ---- neither approval nor rejection -----------------------------------
    ("I have a question", False, ""),
    ("who is the owner?", False, ""),
    ("please fix it", False, ""),
    ("cancel", False, ""),
    ("", False, "empty"),
    ("   ", False, "whitespace only"),
]

# conversation.py gates on max_words=3 as well.
GATED_CASES: list[tuple[str, int, bool, str]] = [
    ("ok", 3, True, "short approval passes the gate"),
    ("looks good", 3, True, "two-word phrase passes"),
    ("yes please that is fine", 3, False, "prose is not an approval"),
    ("not correct", 3, False, "negation still wins inside the gate"),
]


def main() -> int:
    print("=" * 72)
    print("  CONFIRMATION CHECK — does 'not correct' still mean no?")
    print("=" * 72)
    failures: list[str] = []

    print(f"\n{DIM}[1/2] is_confirmation(message){RESET}")
    for message, expected, why in CASES:
        actual = is_confirmation(message)
        if actual == expected:
            continue
        note = f"  ({why})" if why else ""
        failures.append(
            f"{message!r}: expected {expected}, got {actual}{note}"
        )

    print(f"\n{DIM}[2/2] is_confirmation(message, max_words=N){RESET}")
    for message, limit, expected, why in GATED_CASES:
        actual = is_confirmation(message, max_words=limit)
        if actual == expected:
            continue
        failures.append(
            f"{message!r} (max_words={limit}): expected {expected}, got {actual}  ({why})"
        )

    total = len(CASES) + len(GATED_CASES)
    print("\n" + "=" * 72)
    if failures:
        print(f"  {RED}{len(failures)} of {total} FAILED{RESET}")
        for f in failures:
            print(f"    - {f}")
        return 1
    print(f"  {GREEN}ALL {total} CASES PASS{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
