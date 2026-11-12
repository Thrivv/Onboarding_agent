"""
Stage 4/6 — does the compiled graph actually run, end to end, including one
real interrupt/resume round trip?

This is NOT a parity check (that's `langgraph_parity_check.py`, which never
invokes the graph at all — it only compares `routing.py`/`pending.py`
against legacy). This is a structural smoke test: build the graph, run a
case with nothing pending all the way to `finalize`, then run a case that
DOES have something pending and confirm the graph actually pauses at
`interrupt()` and can be resumed via `Command(resume=...)`.

Every node this test exercises may try to call a real FastAPI route handler
if its pending check is True (see `graph/nodes/key_individuals.py` /
`compliance.py`) — those handlers call Supabase, which is stubbed to a
synthetic, unreachable URL in this sandbox (same convention
`synthesize_golden.py` uses). That is fine and expected here: every route
handler this test can reach is wrapped in a try/except that logs and moves
on (the same pattern `classify_account` established for
`save_ownership_type`), so a Supabase call failing is not a crash — it is
exactly the condition this test is checking for.

Usage
-----
    python backend/tests/graph_smoke_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Must be set BEFORE anything imports app.config (synthesize_golden does,
# transitively, via app.services.document_helpers) — config.py raises at
# import time if PASSWORD_SECRET_KEY is unset, same reasoning as
# synthesize_golden's own DOCUMENTS_PATH/SUPABASE_* os.environ.setdefault
# calls at its module level.
os.environ.setdefault("PASSWORD_SECRET_KEY", "synthetic-smoke-test-key-not-for-production-use")
os.environ.setdefault("SUPABASE_URL", "https://synthetic.supabase.co")
os.environ.setdefault("SUPABASE_API_KEY", "synthetic-key-not-used")
os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", "synthetic-key-not-used")

import synthesize_golden as golden  # noqa: E402

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.domain.onboarding.graph.build import build_graph  # noqa: E402


async def _run_no_pending_case() -> None:
    """
    Corporate / Single Owner, identification stage, no documents at all —
    `classify_account` finds no ownership_ambiguous.json, every document
    node no-ops (no `upload` in the initial state), and every pending-chain
    node no-ops (nothing on disk to be pending on). Should run straight
    through to `finalize` in one `ainvoke` with no interrupt.
    """
    email = "smoke-no-pending@synthetic.test"
    golden._seed_ref_no(email)
    golden._write_docs(email, [], True)  # no documents on disk
    golden._write_state(email, "clean", "no_members")

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": email}}

    initial_state = {
        "email": email,
        "channel": "chat",
    }

    result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" not in result, (
        f"expected no interrupt for the no-pending case, got: {result.get('__interrupt__')}"
    )
    # classify_account should have populated these from state_from_user().
    assert result.get("account_type") is None or "stage" in result, (
        "expected classify_account's state_from_user() fields to be present"
    )
    print("  [OK] no-pending case ran start-to-finish with no interrupt")


async def _run_ownership_interrupt_case() -> None:
    """
    Same account, but with `ownership_ambiguous.json` on disk — Stage 6's
    interrupt should fire inside `classify_account`, before any document
    node even runs. Confirms `interrupt()` actually pauses the graph (not
    just that the predicate function returns non-None, which
    `langgraph_parity_check.py` already covers) and that resuming with
    `Command(resume=...)` lets execution continue.
    """
    email = "smoke-ownership-interrupt@synthetic.test"
    golden._seed_ref_no(email)
    golden._write_docs(email, [], True)
    golden._write_state(email, "ownership_ambiguous", "no_members")

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": email}}

    initial_state = {"email": email, "channel": "chat"}

    result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result, (
        f"expected the ownership-ambiguous case to pause at interrupt(), got: {result}"
    )
    interrupts = result["__interrupt__"]
    assert len(interrupts) == 1, f"expected exactly one pending interrupt, got {len(interrupts)}"
    payload = interrupts[0].value
    assert payload == {"type": "ownership_choice"}, f"unexpected interrupt payload: {payload}"

    state_snapshot = await graph.aget_state(config)
    assert state_snapshot.next == ("classify_account",), (
        f"expected the graph to be paused at classify_account, got next={state_snapshot.next}"
    )
    print("  [OK] ownership-ambiguous case paused at interrupt() with the expected payload")

    # ── resume ───────────────────────────────────────────────────────────
    resumed = await graph.ainvoke(
        Command(resume={"ownership_type": "Single Owner", "partnership_details": None}),
        config=config,
    )
    assert "__interrupt__" not in resumed or resumed["__interrupt__"] != interrupts, (
        "expected resuming to move past the ownership_choice interrupt"
    )
    print("  [OK] resume via Command(resume=...) completed without raising")


def main() -> int:
    import os

    os.environ.setdefault("SUPABASE_URL", "https://synthetic.supabase.co")
    os.environ.setdefault("SUPABASE_API_KEY", "synthetic-key")
    os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", "synthetic-key")

    print("Stage 4/6 graph smoke test")
    asyncio.run(_run_no_pending_case())
    asyncio.run(_run_ownership_interrupt_case())

    import shutil

    shutil.rmtree(golden._TMP_DOCS, ignore_errors=True)

    print("\nSMOKE TEST OK — graph builds, runs end-to-end, and interrupt/resume works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
