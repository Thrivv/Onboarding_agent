"""
Stage 7 — the five Key-Individual / mismatch interrupt nodes.

Each node below follows the exact pattern `graph.nodes.documents.classify_account`
established for the ownership-ambiguous interrupt (Stage 6): check the same
`graph.pending` predicate `_resolve_pending_actions()` already uses, pause
via `interrupt()` with that predicate's own payload, and on resume `await`
the real FastAPI route handler with a constructed Pydantic request — never
re-derive what that handler does internally (Supabase writes, breadcrumb
files, member_progress.json, KI record shape) in this module.

After the handler returns, every node re-loads the full state from Supabase
+ disk via `graph.adapters.state_from_user` (the same helper
`classify_account` refreshes from) rather than hand-patching individual
fields — the handlers above touch enough different pieces of disk/Supabase
state (member_progress, key_individuals.json, users.document_stage,
fatca.json/pep.json in ki_loop_finalize's case) that re-deriving from source
is both simpler and less likely to drift than tracking each handler's side
effects field-by-field here.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.domain.onboarding.graph.pending import (
    as_ki_selection_pending,
    ki_details_pending,
    ki_loop_prompt_pending,
    ki_role_assignment_pending,
    mismatch_role_pending,
)
from app.domain.onboarding.graph.state import OnboardingState

logger = logging.getLogger(__name__)


async def _refresh(email: str, channel: str) -> dict[str, Any]:
    """Reload OnboardingState from Supabase + disk — see module docstring."""
    from app.repositories.user_repository import UserRepository
    from app.domain.onboarding.graph.adapters import state_from_user

    try:
        result = UserRepository.get_by_email_limit_one(email)
        user = result.data[0] if result.data else {}
    except Exception as exc:
        logger.error(f"[graph.key_individuals] could not reload user {email}: {exc}")
        user = {}
    return dict(state_from_user(email, user, channel=channel))


def _with_message(state: dict[str, Any], message: Any) -> dict[str, Any]:
    if message:
        state["messages"] = [{"role": "assistant", "content": message}]
    return state


async def as_ki_role_selection(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7. Covers both branches `pending.as_ki_selection_pending` returns:
    MOA_EXTRACTED (Partnership/Multiple Owners — resumes into
    `ki_moa_as_selection`) and SO_OWNER (Single Owner — resumes into
    `ki_so_as_selection`). Which real handler to call is decided by the
    payload's own `source` field, exactly the field the frontend card
    already switches on to know which form to render.
    """
    email = state["email"]
    pending = as_ki_selection_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)
    message = None

    if pending.get("source") == "MOA_EXTRACTED":
        from app.api.routes.onboarding.key_individuals import ki_moa_as_selection
        from app.schemas.key_individuals import MoaAsRequest

        try:
            result = await ki_moa_as_selection(
                MoaAsRequest(
                    email=email,
                    member_role_map=answer.get("member_role_map"),
                    member_as_map=answer.get("member_as_map"),
                )
            )
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.as_ki_role_selection] ki_moa_as_selection failed for {email}: {exc}")
    else:  # "SO_OWNER"
        from app.api.routes.onboarding.key_individuals import ki_so_as_selection
        from app.schemas.key_individuals import SoAsSelectionRequest

        try:
            result = await ki_so_as_selection(
                SoAsSelectionRequest(
                    email=email,
                    owner_role=answer.get("owner_role", "AS"),
                    owner_is_as=answer.get("owner_is_as"),
                )
            )
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.as_ki_role_selection] ki_so_as_selection failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def ki_loop_prompt(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7. "Would you like to add another AS/Key Individual?" Only the
    "No, proceed" answer calls a real handler (`ki_loop_finalize`) — "Yes"
    just resumes the graph with nothing further to persist here, because
    the actual addition happens through `as_ki_role_selection` /
    `ki_role_assignment` / `ki_details` the next time the user uploads a
    document or fills in a KI's details; this predicate simply re-fires
    (correctly — see `pending.ki_loop_prompt_pending`'s docstring) once
    that next round completes.
    """
    email = state["email"]
    pending = ki_loop_prompt_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)
    if answer.get("add_another"):
        return {}

    from app.api.routes.onboarding.key_individuals import ki_loop_finalize
    from app.schemas.key_individuals import KiLoopFinalizeRequest

    message = None
    try:
        result = await ki_loop_finalize(KiLoopFinalizeRequest(email=email))
        message = result.get("message")
    except Exception as exc:
        logger.error(f"[graph.ki_loop_prompt] ki_loop_finalize failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def ki_role_assignment(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7. Ported from `pending_ki_role_assignment.json` — fires once an
    EID/Passport has been OCR'd for a not-yet-registered individual and the
    frontend needs the user to say whether they're an Authorised Signatory
    or a plain Member before `ki_add_ai` can save them.
    """
    email = state["email"]
    pending = ki_role_assignment_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)

    from app.api.routes.onboarding.key_individuals import ki_add_ai
    from app.schemas.key_individuals import KiAiAddRequest

    message = None
    try:
        data = pending.get("data") or {}
        result = await ki_add_ai(
            KiAiAddRequest(
                email=email,
                role=answer.get("role", "MEMBER"),
                document_id=answer.get("document_id", data.get("document_id", "")),
                extracted_data=answer.get("extracted_data", data.get("extracted_data", {})),
            )
        )
        message = result.get("message")
    except Exception as exc:
        logger.error(f"[graph.ki_role_assignment] ki_add_ai failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def ki_details(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7. Fires when an `AI_ADDED` KI has been verified but is still
    missing contact details (`phone_number` empty) — resumes into
    `ki_contact_info`.
    """
    email = state["email"]
    pending = ki_details_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)

    from app.api.routes.onboarding.key_individuals import ki_contact_info
    from app.schemas.key_individuals import KiContactInfoRequest

    message = None
    try:
        result = await ki_contact_info(
            KiContactInfoRequest(
                email=email,
                ki_name=answer.get("ki_name", pending.get("ki_name", "")),
                system_role=answer.get("system_role", ""),
                contact_email=answer.get("contact_email", ""),
                phone_number=answer.get("phone_number", ""),
                share_percentage=answer.get("share_percentage"),
            )
        )
        message = result.get("message")
    except Exception as exc:
        logger.error(f"[graph.ki_details] ki_contact_info failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def mismatch_role_resolution(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7. Ported from `mismatch_pending.json` — fires when a Commercial
    License / Ejari name doesn't match the registered user, and the user
    needs to say what role that extracted person actually holds.
    """
    email = state["email"]
    pending = mismatch_role_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)

    from app.api.routes.onboarding.ownership import mismatch_assign_role
    from app.schemas.ownership import MismatchRoleRequest

    message = None
    try:
        data = pending.get("data") or {}
        result = await mismatch_assign_role(
            MismatchRoleRequest(
                email=email,
                extracted_name=data.get("extracted_name", ""),
                extracted_business_name=data.get("extracted_business_name"),
                assigned_role=answer.get("assigned_role", ""),
                mobile_number=answer.get("mobile_number", ""),
                id_type=answer.get("id_type", "EID"),
                id_number=answer.get("id_number", ""),
            )
        )
        message = result.get("message")
    except Exception as exc:
        logger.error(f"[graph.mismatch_role_resolution] mismatch_assign_role failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


__all__ = [
    "as_ki_role_selection",
    "ki_loop_prompt",
    "ki_role_assignment",
    "ki_details",
    "mismatch_role_resolution",
]
