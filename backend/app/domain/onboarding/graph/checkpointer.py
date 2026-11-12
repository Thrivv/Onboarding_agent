"""
Stage 9 — the durable checkpointer.

`build.py`'s module-level `onboarding_graph` uses `MemorySaver`, which loses
every paused thread's state on process restart — fine for the smoke test
(a single process, start to finish, in one `pytest`/script run) and fine
for Stage 10's shadow-mode comparison (nothing yet depends on a paused
graph surviving a restart), but not something to point a real user's
in-flight interrupt at: a user paused on the ownership-choice card who
happens to hit a backend redeploy would lose that pause entirely and have
to restart onboarding.

This module builds an `AsyncPostgresSaver` against `config.LANGGRAPH_PG_DSN`
when it's set, with the connection lifecycle owned by whoever calls
`get_checkpointer()` / `close_checkpointer()` — intended to be the FastAPI
app's startup/shutdown lifespan hooks (Stage 11 wires that call; this module
only provides the two functions, deliberately not importing or modifying
`app/main.py` itself, since that is exactly the kind of "prepare as a
reviewable diff" change Stage 12 calls out).

Falls back to `MemorySaver` with a loud warning when `LANGGRAPH_PG_DSN`
isn't set — the same fallback `config.validate_startup_config()` already
warns about at boot (see `config.py`'s `LANGGRAPH_ENABLED` block) — so a
misconfigured deployment degrades to "works but not durable" rather than
failing to start.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module-level singletons. `_checkpointer_cm` is the async context manager
# object itself (needs to stay alive for the checkpointer's connection pool
# to stay open) — kept separately from `_checkpointer` (the object nodes
# actually use) because `AsyncPostgresSaver.from_conn_string()` returns a
# context manager, not the saver directly; entering it is what yields the
# usable saver.
_checkpointer_cm: Optional[Any] = None
_checkpointer: Optional[Any] = None


async def get_checkpointer() -> Any:
    """
    Return the process-wide checkpointer, constructing it on first call.

    Idempotent — safe to call from every request path that needs a graph
    (Stage 10's shadow-mode comparison, Stage 11's channel cutover) without
    each one opening its own connection pool.
    """
    global _checkpointer_cm, _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    from app.config import LANGGRAPH_PG_DSN

    if not LANGGRAPH_PG_DSN:
        logger.warning(
            "[graph.checkpointer] LANGGRAPH_PG_DSN is not set — falling back "
            "to MemorySaver. This process's in-flight onboarding interrupts "
            "will NOT survive a restart. Set LANGGRAPH_PG_DSN before relying "
            "on this in anything but local/smoke testing."
        )
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
        return _checkpointer

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(LANGGRAPH_PG_DSN)
    _checkpointer = await _checkpointer_cm.__aenter__()
    # Creates the checkpoint tables if they don't exist yet. Safe to call on
    # every startup — idempotent, same as any other `CREATE TABLE IF NOT
    # EXISTS`-style migration.
    await _checkpointer.setup()
    logger.info("[graph.checkpointer] AsyncPostgresSaver ready (LANGGRAPH_PG_DSN configured)")
    return _checkpointer


async def close_checkpointer() -> None:
    """
    Release the checkpointer's connection pool. Call from the FastAPI app's
    shutdown lifespan hook; safe to call even if `get_checkpointer()` was
    never called (no-op) or only ever returned a `MemorySaver` (no-op —
    `MemorySaver` holds no external connection).
    """
    global _checkpointer_cm, _checkpointer

    if _checkpointer_cm is not None:
        try:
            await _checkpointer_cm.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning(f"[graph.checkpointer] error closing AsyncPostgresSaver: {exc}")

    _checkpointer_cm = None
    _checkpointer = None


__all__ = ["get_checkpointer", "close_checkpointer"]
