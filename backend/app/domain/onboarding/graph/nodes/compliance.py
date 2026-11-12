"""
Stage 8 — FATCA, PEP, product package and self-declaration.

FATCA and PEP have no dedicated `graph.pending` predicate (`pending.py`'s
`ALL_CHECKS` only covers the eight "pending card" checks
`_resolve_pending_actions()` computes) — legacy surfaces them a different
way, as `fatca_trigger` / `pep_trigger` booleans returned directly by
whichever handler ran just before (`ki_loop_finalize`, `pep_submit`, etc.),
computed inline from `fatca_status`/`pep_status` rather than through a
breadcrumb file or KI-record scan. The two interrupt gates below
(`fatca_declaration`, `pep_declaration`) reproduce that inline condition —
"not started yet" — directly off `OnboardingState`, which is the same
source `graph.adapters.state_from_user` already populates those two fields
from (`fatca_service.get_fatca_status_disk_only` /
`pep_service.get_pep_status_disk_only`).

`product_package` and `self_declaration` DO have `graph.pending` predicates
(`pending.product_package_pending`, `pending.self_declaration_pending`), so
those two nodes gate on the same functions Stage 2/3 already ported and
parity-checked.

Every resume path below calls the real route handler — `fatca_not_applicable`
/ `fatca_submit`, `pep_not_applicable` / `pep_submit`, `save_product_package`,
`self_declaration_confirm` — exactly as `graph.nodes.key_individuals`
established. `self_declaration_confirm` in particular does a great deal
(cross-validation, SurePass, completion email, marking
`onboarding_complete`) — none of that is reimplemented here; this node only
decides when to call it and folds the `crossValidation` result into state.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.domain.onboarding.graph.pending import (
    product_package_pending,
    self_declaration_pending,
)
from app.domain.onboarding.graph.state import OnboardingState

logger = logging.getLogger(__name__)


async def _refresh(email: str, channel: str) -> dict[str, Any]:
    """Reload OnboardingState from Supabase + disk — mirrors key_individuals._refresh."""
    from app.repositories.user_repository import UserRepository
    from app.domain.onboarding.graph.adapters import state_from_user

    try:
        result = UserRepository.get_by_email_limit_one(email)
        user = result.data[0] if result.data else {}
    except Exception as exc:
        logger.error(f"[graph.compliance] could not reload user {email}: {exc}")
        user = {}
    return dict(state_from_user(email, user, channel=channel))


def _with_message(state: dict[str, Any], message: Any) -> dict[str, Any]:
    if message:
        state["messages"] = [{"role": "assistant", "content": message}]
    return state


async def fatca_declaration(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 8. Only reachable once the KI loop is done (see
    `graph/build.py`'s edges) — mirrors the point at which legacy first
    starts asking about FATCA (`ki_loop_finalize`'s `fatca_trigger`, or the
    equivalent inline check in `stages.py` for accounts that reach this
    point without going through the KI loop finalize call).
    """
    email = state["email"]
    if state.get("fatca_status") != "not_started":
        return {}

    pending = {"type": "fatca_declaration"}
    answer = interrupt(pending)

    message = None
    if not answer.get("applicable", True):
        from app.api.routes.onboarding.compliance import fatca_not_applicable
        from app.schemas.compliance import FatcaNoRequest

        try:
            result = await fatca_not_applicable(FatcaNoRequest(email=email))
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.fatca_declaration] fatca_not_applicable failed for {email}: {exc}")
    else:
        from app.api.routes.onboarding.compliance import fatca_submit
        from app.schemas.compliance import FatcaYesRequest

        form_fields = {k: v for k, v in answer.items() if k != "applicable"}
        try:
            result = await fatca_submit(FatcaYesRequest(email=email, **form_fields))
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.fatca_declaration] fatca_submit failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def pep_declaration(state: OnboardingState) -> dict[str, Any]:
    """Stage 8. Reached once FATCA is resolved (completed or not_applicable)."""
    email = state["email"]
    fatca_ready = state.get("fatca_status") in ("completed", "not_applicable")
    if not fatca_ready or state.get("pep_status") != "not_started":
        return {}

    pending = {"type": "pep_declaration"}
    answer = interrupt(pending)

    message = None
    from app.schemas.compliance import PepRequest

    if answer.get("not_a_pep"):
        from app.api.routes.onboarding.compliance import pep_not_applicable

        try:
            result = await pep_not_applicable(PepRequest(email=email))
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.pep_declaration] pep_not_applicable failed for {email}: {exc}")
    else:
        from app.api.routes.onboarding.compliance import pep_submit

        try:
            result = await pep_submit(
                PepRequest(
                    email=email,
                    domestic_pep=answer.get("domestic_pep"),
                    foreign_pep=answer.get("foreign_pep"),
                )
            )
            message = result.get("message")
        except Exception as exc:
            logger.error(f"[graph.pep_declaration] pep_submit failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def product_package(state: OnboardingState) -> dict[str, Any]:
    """Stage 8. Gated by `pending.product_package_pending` (Stage 2/3-verified)."""
    email = state["email"]
    pending = product_package_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)

    from app.api.routes.onboarding.products import save_product_package
    from app.schemas.products import ProductPackageSaveRequest

    message = None
    try:
        result = await save_product_package(
            ProductPackageSaveRequest(
                email=email,
                selected_package=answer.get("selected_package", ""),
                availed_products=answer.get("availed_products", []),
            )
        )
        message = result.get("message")
    except Exception as exc:
        logger.error(f"[graph.product_package] save_product_package failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    return _with_message(fresh, message)


async def self_declaration(state: OnboardingState) -> dict[str, Any]:
    """
    Stage 8. Gated by `pending.self_declaration_pending`. The real handler,
    `self_declaration_confirm`, is where onboarding actually completes
    (cross-validation, SurePass, `update_user_onboarding_status(...,
    "onboarding_complete")`, completion email) — this node only records
    whether that happened, via the same `crossValidation.onboarding_complete`
    flag the legacy frontend already reads off the response.
    """
    email = state["email"]
    pending = self_declaration_pending(email, state)
    if pending is None:
        return {}

    answer = interrupt(pending)

    from app.api.routes.onboarding.compliance import self_declaration_confirm
    from app.schemas.compliance import SelfDeclConfirmRequest

    message = None
    onboarding_complete = False
    try:
        result = await self_declaration_confirm(
            SelfDeclConfirmRequest(email=email, language=answer.get("language", "english"))
        )
        message = result.get("message")
        cv = result.get("crossValidation") or {}
        onboarding_complete = bool(cv.get("onboarding_complete"))
        # crossValidation's own message (pass/fail detail, including any
        # mismatch list) is more useful to surface than the generic
        # "confirming your self-declaration" ack above it — mirrors what
        # the legacy chat UI actually shows the user next.
        if cv.get("message"):
            message = cv["message"]
    except Exception as exc:
        logger.error(f"[graph.self_declaration] self_declaration_confirm failed for {email}: {exc}")

    fresh = await _refresh(email, state.get("channel", "chat"))
    fresh["self_declaration_signed"] = onboarding_complete
    return _with_message(fresh, message)


__all__ = [
    "fatca_declaration",
    "pep_declaration",
    "product_package",
    "self_declaration",
]
