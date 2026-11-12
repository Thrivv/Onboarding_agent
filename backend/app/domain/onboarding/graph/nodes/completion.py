"""
Stage 8 — the terminal node.

`compliance.self_declaration` is where onboarding actually completes today
(`self_declaration_confirm` runs cross-validation, SurePass, marks
`onboarding_complete`, and sends the completion email) — this module exists
only so `graph/build.py` has a named node to route to after that, for
callers that want one more confirmation read of the final state rather than
trusting the last node's return value. It does no writes of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.onboarding.graph.state import OnboardingState

logger = logging.getLogger(__name__)


async def finalize(state: OnboardingState) -> dict[str, Any]:
    """
    No-op pass-through, kept as its own node (rather than folded into
    `compliance.self_declaration`) so `graph/build.py`'s edge from
    self-declaration to "done" is visible in the graph's own structure —
    a debugging/observability aid (LangGraph Studio, `get_state_history`)
    more than a functional necessity.
    """
    if state.get("self_declaration_signed"):
        logger.info(f"[graph.completion] {state.get('email')}: onboarding complete")
    return {}


__all__ = ["finalize"]
