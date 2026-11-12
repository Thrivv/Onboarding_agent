"""
Stage 1 — translate between the existing disk/Supabase representation and
`OnboardingState`.

Both functions here are thin. `state_from_user` calls exactly the same
read-only helpers `get_onboarding_status()` already calls today
(`check_documents_status`, `get_submitted_documents`, `load_member_progress`,
`load_key_individuals`, `get_fatca_status_disk_only`,
`get_pep_status_disk_only`, `get_package_selection`) — it does not
re-implement any of them. `state_to_status_response` produces the same
response shape `get_onboarding_status()` returns today, so a route can be
switched from one to the other without the frontend noticing (this is what
Stage 10's shadow-mode diff and Stage 11's channel cutover rely on).
"""

from __future__ import annotations

from typing import Any, Optional

from app.domain.onboarding.graph.state import OnboardingState
from app.domain.onboarding.stage_table import resolve_stage, STAGE_IDENTIFICATION


def state_from_user(
    email: str,
    user: dict[str, Any],
    *,
    channel: str = "chat",
) -> OnboardingState:
    """
    Build an `OnboardingState` snapshot from a Supabase `users` row plus the
    documents/breadcrumb files already on disk for this user.

    This is a read, not a resume — it does not touch the checkpointer. Used
    to seed a brand-new thread (first message ever) and by Stage 10's
    shadow-mode comparison, which needs a state to diff without going through
    the graph at all.
    """
    # Imported lazily, matching the existing modules' own lazy-import style
    # for the same functions (see e.g. member_expansion.check_and_expand_members)
    # — keeps this module importable even in contexts that don't have the
    # full service layer wired up (e.g. this file's own unit tests).
    from app.services.chatupload_helpers import (
        check_documents_status,
        load_member_progress,
        user_docs_path,
    )
    from app.domain.onboarding.documents import get_submitted_documents
    from app.services.key_individual_service import load_key_individuals
    from app.services.fatca_service import get_fatca_status_disk_only
    from app.services.pep_service import get_pep_status_disk_only
    from app.services.product_package_service import get_package_selection

    account_type = user.get("account_type")
    ownership_type = user.get("ownership_type")
    document_stage = user.get("document_stage", STAGE_IDENTIFICATION)

    # `stage` is resolve_stage()'s REPORTED stage, not the raw column — see
    # the field-by-field comment in graph/state.py for why both are kept.
    required_documents, stage = resolve_stage(account_type, ownership_type, document_stage)

    doc_status = check_documents_status(email)
    submitted_documents = get_submitted_documents(email)

    member_progress = load_member_progress(email) or {}
    members = member_progress.get("members", [])
    verified_members_raw = member_progress.get("verified_members", [])
    verified_members = [m for m in members if m in verified_members_raw]

    key_individuals = load_key_individuals(email) or []

    fatca_status = get_fatca_status_disk_only(email)
    pep_status = get_pep_status_disk_only(email)

    package_selection = get_package_selection(email) or {}
    product_package = package_selection.get("selected_package")

    ki_loop_done = (user_docs_path(email) / "ki_loop_done.json").exists()
    self_declaration_signed = (user_docs_path(email) / "self_declaration.json").exists()

    return OnboardingState(
        email=email,
        ref_no=user.get("ref_no"),
        account_type=account_type,
        ownership_type=ownership_type,
        document_stage=document_stage,
        stage=stage,
        required_documents=required_documents,
        doc_status=doc_status,
        submitted_documents=submitted_documents,
        members=members,
        verified_members=verified_members,
        ubo_names=member_progress.get("ubo_names", []),
        expanded_members=member_progress.get("expanded_members", []),
        pending_coi=member_progress.get("pending_coi", []),
        key_individuals=key_individuals,
        ki_loop_done=ki_loop_done,
        fatca_status=fatca_status,
        pep_status=pep_status,
        product_package=product_package,
        self_declaration_signed=self_declaration_signed,
        messages=[],
        channel=channel,
        pending_action=None,
    )


def state_to_status_response(state: OnboardingState) -> dict[str, Any]:
    """
    Produce the subset of `get_onboarding_status()`'s response shape that is
    derivable from `OnboardingState` alone — the fields every frontend card
    in `OnboardingPage.jsx` actually reads.

    Deliberately partial: the pending-action flags (`as_ki_selection_pending`,
    `ki_loop_prompt_pending`, ...) are NOT computed here — those come from
    `graph/pending.py` (Stage 2), which is a separate, individually-testable
    module. Merge its output into this dict at the call site rather than
    duplicating that logic here.
    """
    is_complete = state.get("stage") == "complete"
    return {
        "stage": state.get("stage"),
        "required_documents": state.get("required_documents", []),
        "submitted_documents": state.get("submitted_documents", []),
        "members_info": _members_info(state),
        "is_complete": is_complete,
    }


def _members_info(state: OnboardingState) -> Optional[dict[str, Any]]:
    """Mirror `get_onboarding_status()`'s `members_info` shape, or None."""
    members = state.get("members") or []
    if not members:
        return None
    verified = state.get("verified_members") or []
    current_idx = len(verified)  # first not-yet-verified member, same rule
                                  # get_onboarding_status derives from
                                  # member_progress.json's current_index
    return {
        "total": len(members),
        "verified": len(verified),
        "current_member": members[current_idx] if current_idx < len(members) else None,
        "all_members": members,
        "verified_members": verified,
        "pending_members": [m for m in members if m not in verified],
    }


__all__ = ["state_from_user", "state_to_status_response"]
