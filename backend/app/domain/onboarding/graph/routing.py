"""
Stage 2 — the routing decision, ported with zero independent branch logic.

`route_by_ownership` does not re-implement `stage_table.resolve_stage()`'s
branches — it calls it and maps the (required_documents, stage) tuple it
already returns onto a node name. This is deliberate: Stage 3's parity check
exists specifically to prove this file introduces no drift, and the only way
to prove that with confidence is for there to be nothing here TO drift —
every predicate below is copied from `resolve_stage()`'s own docstring, not
independently reasoned about.

One nuance resolve_stage() itself creates, not this file: for Multiple
Owners/Partnership, any `document_stage` other than "identification" —
including "corporate_shareholder_docs" — resolves to STAGE_MEMBER_EIDS.
`route_by_ownership` therefore sends BOTH raw stages to the same node,
`collect_member_eids`; that node (Stage 7) is responsible for telling a
Type-2 CoI collection sub-step apart from ordinary member-EID collection,
the same way `member_expansion.check_and_expand_members` and `upload.py`
already do it today — by reading `document_stage` directly, not through
resolve_stage()'s collapsed `stage` value.
"""

from __future__ import annotations

from app.domain.onboarding.graph.state import OnboardingState
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_SINGLE,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
    resolve_stage,
)

# Node names — must match the node names registered in graph/build.py (Stage 4+).
NODE_UNSUPPORTED_ACCOUNT = "unsupported_account"
NODE_COLLECT_COMMERCIAL_ONLY = "collect_commercial_only"
NODE_COLLECT_MOA_EJARI_IDENTITY = "collect_moa_ejari_identity"
NODE_COLLECT_MOA_EJARI = "collect_moa_ejari"
NODE_COLLECT_MEMBER_EIDS = "collect_member_eids"


def route_by_ownership(state: OnboardingState) -> str:
    """
    Decide which document-collection node handles this state right now.

    Mirrors `stage_table.py`'s own four branches in the same order as its
    docstring lists them:

        1. Corporate, ownership not yet classified -> commercial only
        2. Corporate, Single Owner                  -> moa/ejari/identity,
                                                         then member EIDs
        3. Corporate, Partnership/Multiple Owners    -> moa/ejari,
                                                         then member EIDs
        4. anything else                             -> unsupported
    """
    account_type = state.get("account_type")
    ownership_type = state.get("ownership_type")
    document_stage = state.get("document_stage")

    # ── Branch 1 — ownership not yet classified ─────────────────────────────
    # resolve_stage() special-cases this itself (`not ownership`), but the
    # node split (collect_commercial_only vs. collect_moa_ejari_identity /
    # collect_moa_ejari) needs to be decided here, one level up, because both
    # of those other two nodes are reached with a *known* ownership_type.
    if account_type == ACCOUNT_CORPORATE and not ownership_type:
        return NODE_COLLECT_COMMERCIAL_ONLY

    # ── Branch 4 — anything resolve_stage() itself falls through on ─────────
    if account_type != ACCOUNT_CORPORATE:
        return NODE_UNSUPPORTED_ACCOUNT

    required_documents, resolved_stage = resolve_stage(
        account_type, ownership_type, document_stage
    )

    # ── Branches 2 and 3's "member EID collection" arm ───────────────────────
    # Reached once resolve_stage() reports STAGE_MEMBER_EIDS (Partnership /
    # Multiple Owners, any document_stage past "identification" — see the
    # module docstring) or STAGE_SO_MEMBER_EIDS (Single Owner, explicitly).
    if resolved_stage in (STAGE_MEMBER_EIDS, STAGE_SO_MEMBER_EIDS):
        return NODE_COLLECT_MEMBER_EIDS

    # ── Branches 2 and 3's "identification" arm ──────────────────────────────
    # resolved_stage is STAGE_IDENTIFICATION here — resolve_stage() only ever
    # returns three distinct stage values, and the first two are handled above.
    if ownership_type == OWNERSHIP_SINGLE:
        return NODE_COLLECT_MOA_EJARI_IDENTITY
    return NODE_COLLECT_MOA_EJARI


__all__ = [
    "route_by_ownership",
    "NODE_UNSUPPORTED_ACCOUNT",
    "NODE_COLLECT_COMMERCIAL_ONLY",
    "NODE_COLLECT_MOA_EJARI_IDENTITY",
    "NODE_COLLECT_MOA_EJARI",
    "NODE_COLLECT_MEMBER_EIDS",
]
