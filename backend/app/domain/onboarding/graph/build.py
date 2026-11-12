"""
Stage 4 (skeleton) / Stage 9 (durable checkpointer) — the compiled StateGraph.

Wiring only. Every node function this module registers already exists in
`graph/nodes/*.py`, ported and (where `graph/pending.py` is involved)
parity-checked in Stages 2/3/6/7/8; nothing here decides what a node does,
only what order they run in and which conditional routes between them.

Graph shape
-----------
    START
      -> classify_account                         (Stage 6 ownership interrupt)
      -> [route_by_ownership]                      (conditional edge)
           -> unsupported_account -> END
           -> collect_commercial_only        -\\
           -> collect_moa_ejari_identity       \\
           -> collect_moa_ejari (members.py)    +-> as_ki_role_selection
           -> collect_member_eids             -/
      -> as_ki_role_selection    (Stage 7 interrupt; no-ops if not pending)
      -> ki_loop_prompt          (Stage 7 interrupt; no-ops if not pending)
      -> ki_role_assignment      (Stage 7 interrupt; no-ops if not pending)
      -> ki_details               (Stage 7 interrupt; no-ops if not pending)
      -> mismatch_role_resolution (Stage 7 interrupt; no-ops if not pending)
      -> fatca_declaration       (Stage 8 interrupt; no-ops if not pending)
      -> pep_declaration         (Stage 8 interrupt; no-ops if not pending)
      -> product_package         (Stage 8 interrupt; no-ops if not pending)
      -> self_declaration        (Stage 8 interrupt; no-ops if not pending)
      -> finalize
      -> END

The chain from `as_ki_role_selection` through `self_declaration` is
unconditional edges, not a conditional router — each of those nodes checks
its own `graph.pending` predicate (or, for FATCA/PEP, the equivalent inline
`OnboardingState` check — see `nodes/compliance.py`'s docstring) and returns
`{}` immediately if nothing is pending, so the chain behaves like
`pending.all_pending()`'s own iteration: the first node whose predicate is
True is the one that actually pauses the graph (via `interrupt()`) for this
invocation. This mirrors the ordering `pending.ALL_CHECKS` already
documents as "matches the frontend's own priority."

Checkpointer
------------
`build_graph()` takes a checkpointer argument rather than hard-coding one so
Stage 9 (swap `MemorySaver` for `PostgresSaver`) is a call-site change, not
a rewrite of this module. `onboarding_graph` (module-level) uses
`MemorySaver` — adequate for the smoke test and for shadow-mode comparison
(Stage 10), where nothing yet depends on state surviving a process restart;
Stage 9 introduces a second, Postgres-backed entry point for anything that
does.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, START, END

from app.domain.onboarding.graph.state import OnboardingState
from app.domain.onboarding.graph.routing import (
    route_by_ownership,
    NODE_UNSUPPORTED_ACCOUNT,
    NODE_COLLECT_COMMERCIAL_ONLY,
    NODE_COLLECT_MOA_EJARI_IDENTITY,
    NODE_COLLECT_MOA_EJARI,
    NODE_COLLECT_MEMBER_EIDS,
)
from app.domain.onboarding.graph.nodes import documents as _documents
from app.domain.onboarding.graph.nodes import members as _members
from app.domain.onboarding.graph.nodes import key_individuals as _ki
from app.domain.onboarding.graph.nodes import compliance as _compliance
from app.domain.onboarding.graph.nodes import completion as _completion

logger = logging.getLogger(__name__)

# Node names not already defined in routing.py (those four + unsupported are
# reused as-is so route_by_ownership's return value can be used directly as
# an edge target).
NODE_CLASSIFY_ACCOUNT = "classify_account"
NODE_AS_KI_ROLE_SELECTION = "as_ki_role_selection"
NODE_KI_LOOP_PROMPT = "ki_loop_prompt"
NODE_KI_ROLE_ASSIGNMENT = "ki_role_assignment"
NODE_KI_DETAILS = "ki_details"
NODE_MISMATCH_ROLE_RESOLUTION = "mismatch_role_resolution"
NODE_FATCA_DECLARATION = "fatca_declaration"
NODE_PEP_DECLARATION = "pep_declaration"
NODE_PRODUCT_PACKAGE = "product_package"
NODE_SELF_DECLARATION = "self_declaration"
NODE_FINALIZE = "finalize"


def build_graph(checkpointer=None):
    """
    Construct and compile the onboarding `StateGraph`.

    `checkpointer=None` compiles without one (LangGraph then requires an
    explicit `config={"configurable": {"thread_id": ...}}` per call and
    keeps no state between calls — useful for the parity/smoke tests, which
    invoke the graph once per case and compare output directly, not for
    resuming an interrupt across two separate calls). Pass a real
    checkpointer (`MemorySaver`, or Stage 9's `PostgresSaver`) for anything
    that needs `interrupt()`/`Command(resume=...)` to actually work.
    """
    workflow = StateGraph(OnboardingState)

    # ── nodes ────────────────────────────────────────────────────────────
    workflow.add_node(NODE_CLASSIFY_ACCOUNT, _documents.classify_account)
    workflow.add_node(NODE_UNSUPPORTED_ACCOUNT, _documents.unsupported_account)
    workflow.add_node(NODE_COLLECT_COMMERCIAL_ONLY, _documents.collect_commercial_only)
    workflow.add_node(NODE_COLLECT_MOA_EJARI_IDENTITY, _documents.collect_moa_ejari_identity)
    # Stage 7 override — see module docstring and members.py's own docstring.
    workflow.add_node(NODE_COLLECT_MOA_EJARI, _members.collect_moa_ejari)
    workflow.add_node(NODE_COLLECT_MEMBER_EIDS, _documents.collect_member_eids)

    workflow.add_node(NODE_AS_KI_ROLE_SELECTION, _ki.as_ki_role_selection)
    workflow.add_node(NODE_KI_LOOP_PROMPT, _ki.ki_loop_prompt)
    workflow.add_node(NODE_KI_ROLE_ASSIGNMENT, _ki.ki_role_assignment)
    workflow.add_node(NODE_KI_DETAILS, _ki.ki_details)
    workflow.add_node(NODE_MISMATCH_ROLE_RESOLUTION, _ki.mismatch_role_resolution)

    workflow.add_node(NODE_FATCA_DECLARATION, _compliance.fatca_declaration)
    workflow.add_node(NODE_PEP_DECLARATION, _compliance.pep_declaration)
    workflow.add_node(NODE_PRODUCT_PACKAGE, _compliance.product_package)
    workflow.add_node(NODE_SELF_DECLARATION, _compliance.self_declaration)

    workflow.add_node(NODE_FINALIZE, _completion.finalize)

    # ── edges ────────────────────────────────────────────────────────────
    workflow.add_edge(START, NODE_CLASSIFY_ACCOUNT)

    workflow.add_conditional_edges(
        NODE_CLASSIFY_ACCOUNT,
        route_by_ownership,
        {
            NODE_UNSUPPORTED_ACCOUNT: NODE_UNSUPPORTED_ACCOUNT,
            NODE_COLLECT_COMMERCIAL_ONLY: NODE_COLLECT_COMMERCIAL_ONLY,
            NODE_COLLECT_MOA_EJARI_IDENTITY: NODE_COLLECT_MOA_EJARI_IDENTITY,
            NODE_COLLECT_MOA_EJARI: NODE_COLLECT_MOA_EJARI,
            NODE_COLLECT_MEMBER_EIDS: NODE_COLLECT_MEMBER_EIDS,
        },
    )

    workflow.add_edge(NODE_UNSUPPORTED_ACCOUNT, END)

    # Every document-collection node feeds into the same pending-action
    # chain — which of them ran doesn't change what's checked next; that's
    # entirely a function of the state each left behind.
    for doc_node in (
        NODE_COLLECT_COMMERCIAL_ONLY,
        NODE_COLLECT_MOA_EJARI_IDENTITY,
        NODE_COLLECT_MOA_EJARI,
        NODE_COLLECT_MEMBER_EIDS,
    ):
        workflow.add_edge(doc_node, NODE_AS_KI_ROLE_SELECTION)

    # The pending-action chain — see module docstring for why this is a
    # sequence of unconditional edges rather than a conditional router.
    workflow.add_edge(NODE_AS_KI_ROLE_SELECTION, NODE_KI_LOOP_PROMPT)
    workflow.add_edge(NODE_KI_LOOP_PROMPT, NODE_KI_ROLE_ASSIGNMENT)
    workflow.add_edge(NODE_KI_ROLE_ASSIGNMENT, NODE_KI_DETAILS)
    workflow.add_edge(NODE_KI_DETAILS, NODE_MISMATCH_ROLE_RESOLUTION)
    workflow.add_edge(NODE_MISMATCH_ROLE_RESOLUTION, NODE_FATCA_DECLARATION)
    workflow.add_edge(NODE_FATCA_DECLARATION, NODE_PEP_DECLARATION)
    workflow.add_edge(NODE_PEP_DECLARATION, NODE_PRODUCT_PACKAGE)
    workflow.add_edge(NODE_PRODUCT_PACKAGE, NODE_SELF_DECLARATION)
    workflow.add_edge(NODE_SELF_DECLARATION, NODE_FINALIZE)
    workflow.add_edge(NODE_FINALIZE, END)

    return workflow.compile(checkpointer=checkpointer)


def _default_graph():
    """
    Module-level default — `MemorySaver`, see the module docstring's
    "Checkpointer" section for why this isn't `PostgresSaver` yet.
    Constructed lazily (not at import time) so importing this module never
    requires `langgraph.checkpoint.memory` to succeed before it's needed —
    matches the rest of this package's "entirely inert until a caller
    actually reaches for it" design (see `graph/__init__.py`).
    """
    from langgraph.checkpoint.memory import MemorySaver

    return build_graph(checkpointer=MemorySaver())


class _LazyGraph:
    """
    Defers `build_graph()` until first attribute access, so
    `from graph.build import onboarding_graph` stays cheap (no MemorySaver
    allocation, no node-module imports beyond what Python's own import
    machinery already did) for callers that only need the module to exist
    — e.g. Stage 10's shadow-mode wiring, which imports this module behind
    an `if LANGGRAPH_ENABLED` check that may never actually fire in a given
    process.
    """

    def __init__(self):
        self._graph = None

    def _get(self):
        if self._graph is None:
            self._graph = _default_graph()
        return self._graph

    def __getattr__(self, name):
        return getattr(self._get(), name)


onboarding_graph = _LazyGraph()

# Process-wide compiled graph bound to the real (Stage 9) checkpointer —
# distinct from `onboarding_graph` above, which is MemorySaver-only and
# exists for the smoke test / anything that doesn't need durability. Callers
# that actually invoke the graph against real users (Stage 10's shadow-mode
# comparison, Stage 11's channel cutover) should use `get_graph()`, not
# `onboarding_graph`, once LANGGRAPH_PG_DSN is configured — see
# `checkpointer.py`'s module docstring for why this distinction matters.
_durable_graph = None


async def get_graph():
    """
    Return the process-wide graph, compiled against
    `checkpointer.get_checkpointer()` on first call. Idempotent — the graph
    itself is stateless (all mutable state lives in the checkpointer), so
    the same compiled object is safe to reuse across concurrent requests
    the same way a single FastAPI app instance already is.
    """
    global _durable_graph

    if _durable_graph is None:
        from app.domain.onboarding.graph.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()
        _durable_graph = build_graph(checkpointer=checkpointer)
    return _durable_graph


__all__ = [
    "build_graph",
    "get_graph",
    "onboarding_graph",
    "NODE_CLASSIFY_ACCOUNT",
    "NODE_AS_KI_ROLE_SELECTION",
    "NODE_KI_LOOP_PROMPT",
    "NODE_KI_ROLE_ASSIGNMENT",
    "NODE_KI_DETAILS",
    "NODE_MISMATCH_ROLE_RESOLUTION",
    "NODE_FATCA_DECLARATION",
    "NODE_PEP_DECLARATION",
    "NODE_PRODUCT_PACKAGE",
    "NODE_SELF_DECLARATION",
    "NODE_FINALIZE",
]
