"""
Stage 11 — the channel-cutover resume hook.

Deliberately narrow. This does NOT attempt to re-route `chat_conversational`
(free-text NLU, ~860 lines) or `handle_reply.process_user_reply` (~1,950
lines covering attachment handling, OCR triggering, and every reply
shape) through the graph — that would mean re-verifying the entire surface
those two functions cover, and this migration's whole discipline (Stage 3's
14,688-case parity check, the smoke test's real interrupt/resume round trip
against live Postgres, Stage 10's shadow-mode comparison run against 3,000
live `get_onboarding_status()` calls) has only established confidence in
one specific slice: the eight `graph.pending` predicates and the routing
decision built on `stage_table.resolve_stage()`.

What this module actually does: given an email and a raw answer payload
(the same shape `interrupt()` already returns to whichever node paused —
`{"ownership_type": ..., "partnership_details": ...}` for the ownership
card, `{"selected_package": ..., "availed_products": ...}` for the product
package card, etc.), check whether that user's graph thread is CURRENTLY
paused on an interrupt (`graph.aget_state(config).next` non-empty and
`.tasks[0].interrupts` non-empty), and if so, resume it with
`Command(resume=answer)` instead of the caller invoking the legacy
card-specific route handler directly.

Because every interrupt node in `graph/nodes/*.py` calls that SAME legacy
route handler on resume (see `key_individuals.py` / `compliance.py` — this
was deliberate from Stage 6 onward, not a Stage 11 addition), resuming the
graph and calling the handler directly produce IDENTICAL side effects.
Cutover only changes who is calling it and what tracks the "what's the
user waiting on" state afterward (the checkpointer, instead of a
`pending_action`-style breadcrumb file lookup on the next request) — it
does not change what gets written to Supabase or disk.

Wire this into `conversation.py` / `handle_reply.py` by calling
`maybe_resume_paused_thread(email, answer)` at the point each already
identifies "this is a response to card X" and would otherwise call that
card's route handler directly; if it returns non-`None`, use that result
instead of the direct call. `LANGGRAPH_CHANNEL_CUTOVER` defaults `False`
(see `config.py`), so until a deployment explicitly opts in, this function
always returns `None` immediately and every call site that guards on it
falls through to the unmodified legacy path — nothing about this module
changes behaviour for anyone until both `LANGGRAPH_ENABLED` and
`LANGGRAPH_CHANNEL_CUTOVER` are set.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def maybe_resume_paused_thread(email: str, answer: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Resume `email`'s graph thread with `answer` if — and only if — it is
    currently paused on an interrupt. Returns the graph's resulting state
    dict (same shape `graph.build.build_graph().ainvoke()` returns) on
    success, or `None` when the cutover is disabled, the thread isn't
    actually paused, or resuming raised — in every `None` case the caller
    is expected to fall through to its existing legacy handling unchanged.

    Never raises. A failure in the graph path must never be able to block
    a real user's onboarding — the entire reason Stage 10 ran shadow-only
    for as long as it did before this function was written.
    """
    try:
        from app.config import LANGGRAPH_ENABLED, LANGGRAPH_CHANNEL_CUTOVER

        if not (LANGGRAPH_ENABLED and LANGGRAPH_CHANNEL_CUTOVER):
            return None

        from langgraph.types import Command

        from app.domain.onboarding.graph.build import get_graph

        graph = await get_graph()
        config = {"configurable": {"thread_id": email}}

        snapshot = await graph.aget_state(config)
        is_paused = bool(snapshot.next) and any(
            getattr(task, "interrupts", None) for task in snapshot.tasks
        )
        if not is_paused:
            logger.debug(f"[graph.cutover] {email}: no paused thread — falling through to legacy handler")
            return None

        logger.info(f"[graph.cutover] {email}: resuming paused thread at {snapshot.next}")
        result = await graph.ainvoke(Command(resume=answer), config=config)
        return result

    except Exception as exc:
        logger.error(f"[graph.cutover] {email}: resume failed, falling through to legacy handler: {exc}")
        return None


__all__ = ["maybe_resume_paused_thread"]
