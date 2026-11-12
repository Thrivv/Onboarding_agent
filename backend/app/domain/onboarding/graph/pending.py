"""
Stage 2 — the eight "what is the user waiting on right now" checks, ported
from `stages._resolve_pending_actions()`.

Each function below returns either `None` (nothing pending) or a dict shaped
like the `interrupt()` payload Stage 6/7/8 will eventually pass verbatim —
so porting the *decision* now (this stage) and wiring it to an actual
`interrupt()` call later (Stage 6+) are two separate, independently
verifiable steps, matching the "move verbatim first" rule the rest of this
codebase already follows.

Where the source data already lives on `OnboardingState` (key_individuals,
members, ki_loop_done, fatca_status, pep_status, product_package,
self_declaration_signed) these read the state, not disk — that is the actual
win Stage 8/9 delivers (no re-reading breadcrumb files on every call once the
checkpointer holds this). Four checks still read a breadcrumb file directly:
`ownership_ambiguous`, `ki_role_assignment_pending`, `mismatch_role_pending`,
and part of `as_ki_selection_pending` (the Single-Owner "SO_OWNER" branch
needs one field off the Commercial License's own extraction, which is not
duplicated onto `OnboardingState` because nothing else needs it). Those four
are exactly the ones this state model does not yet cover — Stage 7 replaces
each of them with state populated by the corresponding node instead of a
disk read, at which point these functions lose their disk access entirely
and this comment can be deleted.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.domain.onboarding.graph.state import OnboardingState
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)

logger = logging.getLogger(__name__)


def ownership_ambiguous(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `ownership_selection_pending` computation."""
    from app.services.chatupload_helpers import user_docs_path

    if (user_docs_path(email) / "ownership_ambiguous.json").exists():
        return {"type": "ownership_choice"}
    return None


def as_ki_selection_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `_resolve_pending_actions` MOA/SO-owner block."""
    ownership_type = state.get("ownership_type")
    doc_status = state.get("doc_status") or {}
    existing_kis = state.get("key_individuals") or []

    is_multi_owner = ownership_type in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)

    if is_multi_owner:
        if not doc_status.get("moa", False):
            return None
        if any(k.get("source") == "MOA_EXTRACTED" for k in existing_kis):
            return None
        ownership_map = {
            m.get("name"): (m.get("effective_percentage") or m.get("effective_pct"))
            for m in (state.get("expanded_members") or [])
            if m.get("name")
        }
        return {
            "type": "as_ki_selection",
            "source": "MOA_EXTRACTED",
            "members": state.get("members") or [],
            "ubo_names": state.get("ubo_names") or [],
            "ownership_map": ownership_map,
        }

    if state.get("account_type") == ACCOUNT_CORPORATE:
        if not doc_status.get("ejari", False):
            return None
        if any(k.get("source") == "SO_OWNER" for k in existing_kis):
            return None

        # From here the legacy code's `as_ki_selection_pending` is ALREADY
        # True — owner-name extraction below only enriches the payload's
        # `members` list and is allowed to fail (or find nothing) without
        # changing that. Mirroring this exactly matters: an earlier version
        # of this function returned None when extraction failed, which the
        # full-space parity check caught as a real divergence — the legacy
        # AS/KI selection card is still supposed to show up (with an empty
        # member list for the user to fill in) even when the Commercial
        # License couldn't be parsed for an owner name.
        members: list[dict[str, Any]] = []
        try:
            from app.domain.onboarding.documents import _find_commercial_output

            _, comm_data = _find_commercial_output(email)
            if comm_data:
                ef = comm_data.get("extracted_fields", {})
                owner_block = (
                    ef.get("owner")
                    or ef.get("english", {}).get("owner")
                    or {
                        "name_english": ef.get("english", {}).get("owner_name", ""),
                        "share_percentage": "100%",
                        "role": "Owner",
                    }
                )
                owner_name = (owner_block.get("name_english") or owner_block.get("name", "")).strip()
                if owner_name:
                    members = [
                        {
                            "name": owner_name,
                            "share_percentage": owner_block.get("share_percentage", "100%"),
                            "role": owner_block.get("role", "Owner"),
                            "nationality": owner_block.get("nationality_english", ""),
                        }
                    ]
        except Exception as exc:
            logger.warning(f"[graph.pending] could not resolve SO owner for {email}: {exc}")

        return {
            "type": "as_ki_selection",
            "source": "SO_OWNER",
            "members": members,
            "ubo_names": [],
            "ownership_map": {},
        }

    return None


def ki_loop_prompt_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """
    Ported from stages.py's `ki_loop_prompt_pending` — "add another AS/KI?".

    Legacy only builds `members_info` at all once `stage` (resolve_stage()'s
    reported stage, not the raw `document_stage`) has already reached
    STAGE_MEMBER_EIDS / STAGE_SO_MEMBER_EIDS — a fully-populated
    `member_progress.json` sitting on disk while the account is still in
    "identification" is not a state the real upload pipeline can produce
    (members are never even resolved until the identification stage's own
    documents are verified), but the parity check in
    `tests/langgraph_parity_check.py` generates the combination anyway, and
    caught this: without the same stage gate, this function fired a
    "ki_loop_prompt" the legacy code would not have, on exactly that
    otherwise-unreachable combination. Keeping the gate is what makes this
    function behave identically to legacy on every input, not just the
    reachable ones.
    """
    if state.get("stage") not in (STAGE_MEMBER_EIDS, STAGE_SO_MEMBER_EIDS):
        return None
    total = len(state.get("members") or [])
    verified = len(state.get("verified_members") or [])
    if total > 0 and verified >= total and not state.get("ki_loop_done"):
        return {"type": "ki_loop_prompt"}
    return None


def product_package_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `product_package_pending` computation."""
    if not state.get("ki_loop_done"):
        return None
    if state.get("product_package"):
        return None
    fatca_ready = state.get("fatca_status") in ("completed", "not_applicable")
    pep_ready = state.get("pep_status") == "completed"
    if fatca_ready and pep_ready:
        return {"type": "product_package"}
    return None


def self_declaration_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `self_declaration_pending` computation."""
    if state.get("product_package") and not state.get("self_declaration_signed"):
        return {"type": "self_declaration"}
    return None


def ki_role_assignment_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `ki_role_assignment_pending` breadcrumb read."""
    from app.services.chatupload_helpers import user_docs_path

    path = user_docs_path(email) / "pending_ki_role_assignment.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning(f"[graph.pending] could not read pending_ki_role_assignment.json: {exc}")
        return None
    return {"type": "ki_role_assignment", "data": data}


def ki_details_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `ki_details_pending` scan of existing KIs."""
    for ki in state.get("key_individuals") or []:
        if ki.get("source") == "AI_ADDED" and not ki.get("phone_number"):
            return {
                "type": "ki_details",
                "ki_name": ki.get("display_name", ""),
                "role": "AS" if ki.get("is_authorised_signatory") else "MEMBER",
            }
    return None


def mismatch_role_pending(email: str, state: OnboardingState) -> Optional[dict[str, Any]]:
    """Ported from stages.py's `mismatch_role_pending` breadcrumb read."""
    from app.services.chatupload_helpers import user_docs_path

    doc_status = state.get("doc_status") or {}
    if not (doc_status.get("ejari", False) or doc_status.get("moa", False)):
        return None
    path = user_docs_path(email) / "mismatch_pending.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning(f"[graph.pending] could not read mismatch_pending.json: {exc}")
        return None
    return {"type": "mismatch_role", "data": data}


#: One check per "pending card" — order matches the frontend's own priority
#: (the same order stages.py computes them in), so the first non-None result
#: from `first_pending()` is the same card the legacy response would surface.
ALL_CHECKS = (
    ownership_ambiguous,
    as_ki_selection_pending,
    ki_loop_prompt_pending,
    ki_role_assignment_pending,
    ki_details_pending,
    mismatch_role_pending,
    product_package_pending,
    self_declaration_pending,
)


def all_pending(email: str, state: OnboardingState) -> list[dict[str, Any]]:
    """Every currently-pending action, for shadow-mode comparison and tests."""
    results = []
    for check in ALL_CHECKS:
        result = check(email, state)
        if result is not None:
            results.append(result)
    return results


__all__ = [
    "ownership_ambiguous",
    "as_ki_selection_pending",
    "ki_loop_prompt_pending",
    "product_package_pending",
    "self_declaration_pending",
    "ki_role_assignment_pending",
    "ki_details_pending",
    "mismatch_role_pending",
    "ALL_CHECKS",
    "all_pending",
]
