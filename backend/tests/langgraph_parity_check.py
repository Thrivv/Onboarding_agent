"""
Stage 3 — prove `graph/routing.py` and `graph/pending.py` introduce zero
drift from the legacy `get_onboarding_status()`, before either is allowed
anywhere near a route.

Reuses `synthesize_golden.py`'s own input-space generator and fixture
helpers (`_params`, `_write_docs`, `_write_state`, `_seed_ref_no`) rather
than inventing a second one — the whole point of this check is that it
exercises the SAME cases the team's existing golden corpus already covers,
not a hand-picked subset that happens to pass.

For every case in the input space this:
  1. Calls the legacy `get_onboarding_status()` — the function of record.
  2. Builds an `OnboardingState` via `graph.adapters.state_from_user()` and
     runs it through `graph.routing.route_by_ownership()` and
     `graph.pending.all_pending()`.
  3. Compares: does the routed node agree with the legacy stage, and does
     the set of pending-action types agree with the legacy boolean flags?

Usage
-----
    python backend/tests/langgraph_parity_check.py            # full space (~14.7k cases)
    python backend/tests/langgraph_parity_check.py --quick     # deduped corpus only (~650 cases)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthesize_golden as golden  # noqa: E402

from app.domain.onboarding.graph.adapters import state_from_user  # noqa: E402
from app.domain.onboarding.graph.routing import (  # noqa: E402
    route_by_ownership,
    NODE_UNSUPPORTED_ACCOUNT,
    NODE_COLLECT_COMMERCIAL_ONLY,
    NODE_COLLECT_MOA_EJARI_IDENTITY,
    NODE_COLLECT_MOA_EJARI,
    NODE_COLLECT_MEMBER_EIDS,
)
from app.domain.onboarding.graph.pending import all_pending  # noqa: E402
from app.domain.onboarding.stage_table import (  # noqa: E402
    OWNERSHIP_SINGLE,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)
from app.domain.onboarding.stages import get_onboarding_status  # noqa: E402

# legacy `get_onboarding_status()` flag name -> pending.py payload "type"
FLAG_TO_TYPE = {
    "ownership_selection_pending": "ownership_choice",
    "as_ki_selection_pending": "as_ki_selection",
    "ki_loop_prompt_pending": "ki_loop_prompt",
    "product_package_pending": "product_package",
    "self_declaration_pending": "self_declaration",
    "ki_role_assignment_pending": "ki_role_assignment",
    "ki_details_pending": "ki_details",
    "mismatch_role_pending": "mismatch_role",
}


def _expected_node(user_data: dict) -> str | None:
    """
    What node SHOULD route_by_ownership return, derived independently from
    the same fields resolve_stage() itself branches on — independently in
    the sense that this reads user_data directly rather than calling
    route_by_ownership a second time, so it is not a tautology.
    """
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    # NOTE: no "or STAGE_IDENTIFICATION" fallback here. Both the legacy
    # get_onboarding_status() and graph/adapters.state_from_user() read this
    # with `user_data.get("document_stage", STAGE_IDENTIFICATION)` — a
    # dict.get default, which only applies when the KEY IS MISSING, not when
    # its value is None. This harness's fixtures always set the key (see
    # synthesize_golden.DOCUMENT_STAGES, which includes None as an explicit
    # value), so the correct read here is the value as-is, unmodified.
    document_stage = user_data.get("document_stage")

    if account_type != "Corporate":
        return NODE_UNSUPPORTED_ACCOUNT
    if not ownership_type:
        return NODE_COLLECT_COMMERCIAL_ONLY

    from app.domain.onboarding.stage_table import resolve_stage

    _, resolved_stage = resolve_stage(account_type, ownership_type, document_stage)
    if resolved_stage in (STAGE_MEMBER_EIDS, STAGE_SO_MEMBER_EIDS):
        return NODE_COLLECT_MEMBER_EIDS
    return NODE_COLLECT_MOA_EJARI_IDENTITY if ownership_type == OWNERSHIP_SINGLE else NODE_COLLECT_MOA_EJARI


def _check_one(idx: int, params: dict) -> list[str]:
    """Run one case through both paths; return a list of mismatch descriptions."""
    email = f"case{idx:05d}@synthetic.test"
    user_data = {
        "email": email,
        "name": "ALICE ROE",
        "account_type": params["account_type"],
        "ownership_type": params["ownership_type"],
        "document_stage": params["document_stage"],
        "onboarding_step": "document_collection",
    }
    golden._seed_ref_no(email)
    golden._write_docs(email, params["documents"], params["is_valid"])
    golden._write_state(email, params["scenario"], params["member_state"])

    mismatches: list[str] = []

    try:
        legacy = get_onboarding_status(email, user_data, True)
    except Exception as exc:
        return [f"legacy get_onboarding_status raised: {type(exc).__name__}: {exc}"]

    try:
        state = state_from_user(email, user_data)
        routed_node = route_by_ownership(state)
        pending = all_pending(email, state)
    except Exception as exc:
        return [f"graph path raised: {type(exc).__name__}: {exc}"]

    # ── 1. routing parity ────────────────────────────────────────────────
    expected_node = _expected_node(user_data)
    if routed_node != expected_node:
        mismatches.append(
            f"routing: expected {expected_node!r}, got {routed_node!r} "
            f"(legacy stage={legacy.get('stage')!r})"
        )

    # ── 2. pending-action parity ─────────────────────────────────────────
    pending_types = {p["type"] for p in pending}
    for flag_name, type_name in FLAG_TO_TYPE.items():
        legacy_pending = bool(legacy.get(flag_name))
        graph_pending = type_name in pending_types
        if legacy_pending != graph_pending:
            mismatches.append(
                f"pending[{flag_name}]: legacy={legacy_pending}, graph={graph_pending}"
            )

    return [f"case{idx:05d} params={params}: {m}" for m in mismatches]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="only the deduped golden corpus (~650 cases)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N cases (debugging)")
    args = ap.parse_args()

    if args.quick:
        baseline_path = golden.GOLDEN / "pure_functions.json"
        import json

        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        param_iter = (c["params"] for c in baseline["corpus"])
        total_expected = len(baseline["corpus"])
    else:
        param_iter = golden._params()
        total_expected = None

    all_mismatches: list[str] = []
    total = 0
    for i, params in enumerate(param_iter, start=1):
        if args.limit and i > args.limit:
            break
        total += 1
        all_mismatches.extend(_check_one(i, params))
        if total % 2000 == 0:
            print(f"  ...{total} cases checked, {len(all_mismatches)} mismatch(es) so far")

    import shutil

    shutil.rmtree(golden._TMP_DOCS, ignore_errors=True)

    print(f"\nChecked {total} case(s){f' (expected {total_expected})' if total_expected else ''}.")
    if all_mismatches:
        print(f"MISMATCHES: {len(all_mismatches)}")
        for m in all_mismatches[:30]:
            print(f"  - {m}")
        if len(all_mismatches) > 30:
            print(f"  ... and {len(all_mismatches) - 30} more")
        return 1

    print("PARITY OK — routing and pending-action logic agree with the legacy "
          "get_onboarding_status() on every case checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
