# backend/app/domain/onboarding/stage_table.py
"""
The onboarding stage table — which documents an account owes, and when.

This is the heart of the product, and until Stage C1 it existed only as a chain
of nested `if account_type == ... and ownership == ...` branches inside
`get_onboarding_status`. Reading it meant tracing conditionals; changing it
meant hoping you had found every branch.

Stated as data instead, the whole flow fits on one screen:

    Corporate, ownership not yet known
        -> commercial only. The auto-classifier fills ownership in once the
           licence is verified, and the next call falls through to a row below.

    Corporate, Single Owner
        identification   -> commercial, moa, ejari, identity
        so_member_eids   -> (none — EID collection is driven by member progress)

    Corporate, Partnership / Multiple Owners
        identification   -> commercial, ejari, moa
        anything else    -> (none — stage becomes member_eids)

    anything else        -> (none)

Why a table rather than a state machine class
---------------------------------------------
The resolution is a pure lookup: (account_type, ownership, document_stage) in,
(required documents, stage) out. There is no transition logic here — advancing
between stages is done elsewhere, by the upload pipeline and the KI loop. A
class with one method would have added ceremony without adding meaning.

Verification
------------
Behaviour is pinned by `backend/tests/synthesize_golden.py` — 709 distinct
cases covering every combination of account type, ownership, stage, uploaded
documents and breadcrumb files. This module was written to reproduce the
previous conditionals exactly, and the corpus confirms it does.

`identity` is a virtual requirement, satisfied by EITHER an Emirates ID or a
passport. That rule is applied by the caller, not encoded here.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

# Document-stage names. These were bare string literals scattered across three
# modules; a typo in one silently changed the flow.
STAGE_IDENTIFICATION = "identification"
STAGE_SO_MEMBER_EIDS = "so_member_eids"
STAGE_MEMBER_EIDS = "member_eids"
STAGE_CORPORATE_SHAREHOLDER_DOCS = "corporate_shareholder_docs"

# Ownership types, as stored on the user record.
OWNERSHIP_SINGLE = "Single Owner"
OWNERSHIP_PARTNERSHIP = "Partnership"
OWNERSHIP_MULTIPLE = "Multiple Owners"
MULTI_OWNER_TYPES = (OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE)

ACCOUNT_CORPORATE = "Corporate"


class StageRequirement(NamedTuple):
    """What a given account owes right now."""

    required_documents: list[str]
    stage: str


def resolve_stage(
    account_type: Optional[str],
    ownership: Optional[str],
    document_stage: Optional[str],
) -> StageRequirement:
    """
    Resolve (account_type, ownership, document_stage) to the documents required
    and the stage to report.

    Returns fresh lists every call — the caller mutates the result, and a shared
    list in a module-level table would leak state between requests. That is the
    one hazard of expressing this as data rather than code, so it is handled
    here rather than left to callers to remember.
    """
    # ── Corporate, ownership not yet classified ──────────────────────────────
    # Only the commercial licence is requested. The auto-classifier sets
    # ownership_type once that licence verifies, and the next call lands on one
    # of the branches below.
    if account_type == ACCOUNT_CORPORATE and not ownership:
        return StageRequirement(["commercial"], STAGE_IDENTIFICATION)

    # ── Corporate, Single Owner ──────────────────────────────────────────────
    if account_type == ACCOUNT_CORPORATE and ownership == OWNERSHIP_SINGLE:
        if document_stage == STAGE_SO_MEMBER_EIDS:
            # EID collection is driven by member progress, not by a document
            # list, so nothing is "required" in the document sense here.
            return StageRequirement([], STAGE_SO_MEMBER_EIDS)
        # Flow order: Commercial -> MOA -> Ejari -> EID/Passport (role card -> KI loop)
        return StageRequirement(
            ["commercial", "moa", "ejari", "identity"], STAGE_IDENTIFICATION
        )

    # ── Corporate, Partnership / Multiple Owners ─────────────────────────────
    if account_type == ACCOUNT_CORPORATE and ownership in MULTI_OWNER_TYPES:
        if document_stage == STAGE_IDENTIFICATION:
            return StageRequirement(
                ["commercial", "ejari", "moa"], STAGE_IDENTIFICATION
            )
        return StageRequirement([], STAGE_MEMBER_EIDS)

    # ── Anything else ────────────────────────────────────────────────────────
    # Non-Corporate accounts have no document flow defined. Reported as
    # `identification` with nothing required, which is what the previous
    # `else` branch did.
    return StageRequirement([], STAGE_IDENTIFICATION)
