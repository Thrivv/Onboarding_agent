"""
Stage 7 — member expansion for the Multiple Owners / Partnership path.

Overrides `graph.nodes.documents.collect_moa_ejari` (the node
`graph.routing.route_by_ownership` sends every Partnership/Multiple-Owners
account to while `document_stage` is "identification" or
"corporate_shareholder_docs") to also run
`member_expansion.check_and_expand_members` after processing an uploaded
document — the same trigger `upload.py`'s single-file and bulk paths run
today (see `upload.py` around line 2058, "MULTIPLE OWNER (Type-1 and
Type-2): auto-trigger member expansion").

`check_and_expand_members` is a plain function, not a FastAPI route handler
— it already does its own Supabase write (`update_user_onboarding_status`)
and disk write (`save_member_progress`) internally, exactly like the legacy
route does today. This node's job is only to decide *whether* to call it
(reproducing `upload.py`'s gate) and fold its return value into
`OnboardingState` — nothing about expansion, UBO percentage calculation, or
CoI matching is reimplemented here.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.onboarding.graph.state import OnboardingState

logger = logging.getLogger(__name__)


async def collect_moa_ejari(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 7 replacement for `documents.collect_moa_ejari`, wired into
    `graph/build.py` for `NODE_COLLECT_MOA_EJARI` (Partnership / Multiple
    Owners only — `route_by_ownership` never sends a Single Owner account
    here, so this node does not need to re-check ownership_type before
    deciding whether to *route* here, only before deciding whether to
    *expand*, mirroring `upload.py`'s own belt-and-suspenders check).
    """
    from app.domain.onboarding.graph.nodes.documents import _process_document_raw

    updates, result = await _process_document_raw(state)

    upload = state.get("upload")
    if not upload or not result:
        # No file on this invocation, or process_uploaded_document raised —
        # nothing new to check readiness against.
        return updates

    from app.domain.onboarding.stage_table import (
        ACCOUNT_CORPORATE,
        OWNERSHIP_MULTIPLE,
        OWNERSHIP_PARTNERSHIP,
        STAGE_IDENTIFICATION,
        STAGE_CORPORATE_SHAREHOLDER_DOCS,
    )

    # Reproduces upload.py's exact gate (see module docstring) so this node
    # fires on precisely the same uploads the legacy route would trigger
    # expansion on — not "any successful upload while Multiple Owners."
    doc_type = (result.get("document_type") or "unknown").lower() if isinstance(result, dict) else "unknown"
    is_valid = bool(result.get("is_valid")) if isinstance(result, dict) else False
    clean_member_name = upload.get("member_name")
    document_stage = state.get("document_stage")
    account_type = state.get("account_type")
    ownership_type = state.get("ownership_type")

    should_check_expansion = (
        is_valid
        and not clean_member_name
        and doc_type in (
            "ejari", "tenancy", "moa", "memorandum",
            "certificate_of_incorporation", "coi",
        )
        and document_stage in (STAGE_IDENTIFICATION, STAGE_CORPORATE_SHAREHOLDER_DOCS)
        and account_type == ACCOUNT_CORPORATE
        and ownership_type in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
    )
    if not should_check_expansion:
        return updates

    from app.domain.onboarding.member_expansion import check_and_expand_members

    email = state["email"]
    user = {
        "account_type": account_type,
        "ownership_type": ownership_type,
        "document_stage": document_stage,
    }
    try:
        expansion = check_and_expand_members(email, user, upload.get("language", "english"))
    except Exception as exc:
        logger.error(f"[graph.members.collect_moa_ejari] expansion failed for {email}: {exc}")
        expansion = None

    if not expansion:
        # Not ready yet (missing documents, or extraction found nothing) —
        # upload.py falls back to the same "type Okay in chat" safety net
        # in this case; this node just leaves the state as the plain
        # document-processing result and lets the next status check
        # re-evaluate readiness.
        return updates

    logger.info(
        f"[graph.members.collect_moa_ejari] {email}: auto-triggered -> "
        f"{len(expansion['members'])} members"
    )

    merged = dict(updates)
    merged["members"] = expansion["members"]
    merged["ubo_names"] = expansion["ubo_names"]
    merged["expanded_members"] = expansion.get("expanded_members")
    # check_and_expand_members already persisted this to Supabase via
    # update_user_onboarding_status — this just brings the in-memory/
    # checkpointed state in line with what's now on disk, the same way
    # every other field here mirrors a write some other function already
    # made.
    merged["document_stage"] = expansion.get("new_stage", document_stage)
    merged["messages"] = [{"role": "assistant", "content": expansion["message"]}]
    return merged


__all__ = ["collect_moa_ejari"]
