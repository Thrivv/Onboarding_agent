"""
The onboarding flow, expressed as a LangGraph `StateGraph`.

This package is the orchestration layer only. It owns the routing logic that
used to be scattered across `domain/onboarding/stage_table.py`'s callers,
`stages.py`'s pending-action recomputation, and the transition writes in
`api/routes/onboarding/upload.py` / `key_individuals.py` /
`domain/onboarding/verification/response_handling.py`.

It does NOT re-implement anything OCR, tampering-detection, cross-validation,
or message-generation does — every node in `graph/nodes/` calls the existing
service functions in `app.services.*` and `app.domain.onboarding.*` directly.
See docs/langgraph-migration/ for the staged rollout plan this package is
built against; each module below is annotated with which stage introduced it.

Modules
-------
    state.py        Stage 1  — the shared `OnboardingState` TypedDict
    adapters.py      Stage 1  — Supabase/user-dict <-> OnboardingState
    routing.py       Stage 2  — route_by_ownership(), a thin wrapper over
                                 stage_table.resolve_stage()
    pending.py       Stage 2  — the eight pending-action checks, ported from
                                 stages._resolve_pending_actions()
    build.py         Stage 4+ — the compiled StateGraph
    nodes/           Stage 5+ — one module per node group

Entirely inert until a caller imports `graph.build.onboarding_graph` AND
`app.config.LANGGRAPH_ENABLED` is true (Stage 11) — nothing in this package
is imported by any route or by `services/reply_loop.py` before that stage.
"""

from __future__ import annotations
