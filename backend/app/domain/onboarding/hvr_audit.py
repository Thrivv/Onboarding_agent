r"""
Is `handle_verification_response` still doing anything?

Temporary instrumentation. Delete it once the question below is answered — the
removal checklist is at the bottom.

## The question

`handle_verification_response` is 1,168 lines with 29 returns, and it is the
single hardest item in B5. Everything found so far says it is vestigial:

- The **email channel never calls it.** `handle_reply.py` and `reply_loop.py`
  have no reference and no confirmation logic of their own.
- There is **one** live caller, `conversation.py:334`, reached only when a user
  types a short confirmation into chat.
- `upload.py:1251` records the deliberate migration away from it: that block
  used to say "type okay to confirm" and relied on this function for
  `human_verified` marking and member-progress advancement. It was changed to
  auto-verify at upload time because the old way scanned two EIDs in the wrong
  order.
- The stage transitions it performs are also performed by `upload.py` (9
  `update_user_onboarding_status` sites) and `key_individuals.py` (2). The
  `so_member_eids` self-heal exists in **both** — `[FIX-C]` here and `[FIX-D]`
  in `upload.py:1517`.

What stops deletion is `stages.py:398`, which refuses to mark Single Owner
complete in `so_member_eids` **because it expects this function to do the
transition**. That may be stale, but "looks stale" is the reasoning that
produced three separate bugs already caught in this refactor.

## What this records, and why it is the right signal

Not "did it run" — **"did it change anything that was not already changed."**

A mutation that writes the value the record already held proves the automated
path got there first, and that this function is a redundant second writer. A
mutation that writes a genuinely new value is the opposite: proof it is load
bearing, and exactly the edge case two clean test flows did not hit.

So every line is tagged REDUNDANT or EFFECTIVE. Deletion is safe only if, over
real usage, nothing is ever EFFECTIVE.

Grep the container log:

    docker compose logs app | grep HVR-AUDIT
    docker compose logs app | grep "HVR-AUDIT.*EFFECTIVE"     # the deciding line

The second command returning nothing after a representative period is the
evidence to delete on. One hit is the evidence to keep.

## Safety

Every call is wrapped so instrumentation can never break the flow it observes —
the same rule `behaviour_capture.py` follows. A failure here logs and returns.

## Removal checklist

1. Delete this file.
2. Remove the `from app.domain.onboarding.hvr_audit import audit_mutation`
   import and the five `audit_mutation(...)` calls in `verification.py`.
3. `python backend/tests/contract_check.py` confirms nothing else referenced it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TAG = "HVR-AUDIT"


def audit_mutation(
    what: str,
    *,
    email: str,
    before: Any,
    after: Any,
    site: str,
) -> None:
    """
    Record one state change attempted by `handle_verification_response`.

    Args:
        what:   which field, e.g. "document_stage" or "ki_verification".
        email:  whose record. Written as-is — this is the operator's own log,
                not the pseudonymised behavioural capture.
        before: the value already stored, read immediately before the write.
        after:  the value being written.
        site:   a short marker for the call site, so a hit is traceable to a
                line without a stack trace.

    Never raises.
    """
    try:
        redundant = _same(before, after)
        verdict = "REDUNDANT" if redundant else "EFFECTIVE"
        line = (
            f"[{TAG}] {verdict} {what} site={site} email={email} "
            f"before={before!r} after={after!r}"
        )
        # EFFECTIVE is the finding; make it visible at WARNING so it survives a
        # log level of WARNING and stands out in a grep.
        (logger.info if redundant else logger.warning)(line)
    except Exception as exc:  # pragma: no cover - instrumentation must not throw
        logger.debug(f"[{TAG}] audit failed: {exc}")


def _ki_status_before(email: str, member_name: str | None) -> str:
    """
    Read a member's stored verification status before this function overwrites it.

    Without this the KI site would have nothing to compare against and would log
    EFFECTIVE every time, drowning the one signal that matters. Returns
    "(unknown)" when the record cannot be read — which is not counted as
    evidence either way.

    Never raises.
    """
    try:
        if not member_name:
            return "(no-member)"
        from app.services.chatupload_helpers import load_member_progress

        progress = load_member_progress(email) or {}
        for member in progress.get("members", []):
            if not isinstance(member, dict):
                continue
            if str(member.get("name", "")).strip().lower() == member_name.strip().lower():
                return str(
                    member.get("verification_status")
                    or member.get("status")
                    or ("verified" if member.get("verified") else "unverified")
                )
        return "(not-found)"
    except Exception as exc:  # pragma: no cover - instrumentation must not throw
        logger.debug(f"[{TAG}] could not read KI status: {exc}")
        return "(unknown)"


def _same(before: Any, after: Any) -> bool:
    """Loose equality — the stored value may be a string where the write is a bool."""
    if before is after:
        return True
    if isinstance(before, str) and isinstance(after, str):
        return before.strip().lower() == after.strip().lower()
    return bool(before == after)


__all__ = ["audit_mutation", "TAG"]
