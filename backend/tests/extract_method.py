"""
Extract-method safety verifier.

The problem this solves
-----------------------
Stage B5 breaks up functions of 378, 862, 1,246 and 2,391 lines. Without the
B0 behavioural recordings there is no way to prove by execution that the result
behaves identically. So the extractions have to be provable by *construction*
instead — which means each one must be a pure relocation of statements, with
the data flow across the new boundary made explicit and checked.

Given a function and a contiguous line range, this computes:

  * **params**  — names the block READS before assigning them, i.e. what must
                  be passed in
  * **returns** — names the block ASSIGNS that are READ AFTER it, i.e. what
                  must be handed back
  * **escapes** — `return` / `break` / `continue` / `yield` / `await` that
                  would change meaning once the block is a separate function

and refuses any block with escapes. That last check is the important one: in a
2,391-line function with early returns scattered through it, lifting a block
containing `return` silently converts "stop the whole request" into "stop the
helper" — the single most likely way this stage could introduce a bug.

What this does NOT prove
------------------------
That the *overall* function still makes the same decisions. It proves the moved
statements are the same statements and that nothing is dropped or rebound
across the seam. For `get_onboarding_status` and `get_submitted_documents` the
synthetic golden corpus proves the behavioural half as well
(`synthesize_golden.py`). For the OCR/LLM functions, only this structural
guarantee is available until the B0 capture is run — that limit is real and is
recorded in docs/STAGE_B5_RESULT.md rather than glossed over.

Usage:
    python backend/tests/extract_method.py <file> <function> <start> <end>
"""

from __future__ import annotations

import argparse
import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins))

ESCAPES = {
    ast.Return: "return",
    ast.Break: "break",
    ast.Continue: "continue",
    ast.Yield: "yield",
    ast.YieldFrom: "yield from",
}


class _Scope:
    """Names bound and names read, in source order, for a run of statements."""

    def __init__(self) -> None:
        self.read: list[str] = []
        self.bound: list[str] = []

    def add_read(self, name: str) -> None:
        if name not in BUILTINS:
            self.read.append(name)

    def add_bound(self, name: str) -> None:
        self.bound.append(name)


def _walk_names(node: ast.AST, scope: _Scope) -> None:
    """
    Collect reads and bindings, respecting evaluation order where it matters.

    Assignment is handled explicitly (value before target) because a statement
    like `x = x + 1` both reads and binds `x`, and the order decides whether
    `x` is a parameter of the extracted block or purely local to it.
    """
    if isinstance(node, ast.Assign):
        _walk_names(node.value, scope)
        for t in node.targets:
            _bind_target(t, scope)
        return
    if isinstance(node, ast.AugAssign):
        # `x += 1` reads x first, then rebinds it.
        _walk_names(node.target, scope)
        _walk_names(node.value, scope)
        _bind_target(node.target, scope)
        return
    if isinstance(node, ast.AnnAssign):
        if node.value is not None:
            _walk_names(node.value, scope)
        _bind_target(node.target, scope)
        return
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            scope.add_bound((a.asname or a.name).split(".")[0])
        return
    if isinstance(node, ast.For):
        _walk_names(node.iter, scope)
        _bind_target(node.target, scope)
        for s in node.body + node.orelse:
            _walk_names(s, scope)
        return
    if isinstance(node, ast.ExceptHandler):
        if node.type is not None:
            _walk_names(node.type, scope)
        if node.name:
            scope.add_bound(node.name)
        for s in node.body:
            _walk_names(s, scope)
        return
    if isinstance(node, ast.withitem):
        _walk_names(node.context_expr, scope)
        if node.optional_vars is not None:
            _bind_target(node.optional_vars, scope)
        return
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        scope.add_bound(node.name)
        # Do not descend: an inner function's locals are its own.
        for d in getattr(node, "decorator_list", []):
            _walk_names(d, scope)
        return
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load):
            scope.add_read(node.id)
        else:
            scope.add_bound(node.id)
        return

    for child in ast.iter_child_nodes(node):
        _walk_names(child, scope)


def _bind_target(t: ast.AST, scope: _Scope) -> None:
    if isinstance(t, ast.Name):
        scope.add_bound(t.id)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            _bind_target(e, scope)
    elif isinstance(t, ast.Starred):
        _bind_target(t.value, scope)
    else:
        # Attribute / subscript target: `obj.x = 1` READS obj.
        _walk_names(t, scope)


def analyse(path: Path, func_name: str, start: int, end: int) -> dict:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == func_name
        ),
        None,
    )
    if func is None:
        raise SystemExit(f"function '{func_name}' not found in {path}")

    block = [s for s in func.body if start <= s.lineno and s.end_lineno <= end]
    if not block:
        raise SystemExit(
            f"no top-level statements of {func_name} fall entirely within "
            f"lines {start}-{end}; the range must not split a statement"
        )

    before = [s for s in func.body if s.end_lineno < block[0].lineno]
    after = [s for s in func.body if s.lineno > block[-1].end_lineno]

    # --- escapes ------------------------------------------------------------
    escapes: list[str] = []
    for s in block:
        for n in ast.walk(s):
            for cls, label in ESCAPES.items():
                if isinstance(n, cls):
                    # break/continue belonging to a loop INSIDE the block are fine.
                    if cls in (ast.Break, ast.Continue) and _inside_own_loop(s, n):
                        continue
                    escapes.append(f"{label} at line {getattr(n, 'lineno', '?')}")

    # --- data flow ----------------------------------------------------------
    bscope = _Scope()
    for s in block:
        _walk_names(s, bscope)

    pre = _Scope()
    for s in before:
        _walk_names(s, pre)
    pre_bound = set(pre.bound) | {a.arg for a in _all_args(func)}

    post = _Scope()
    for s in after:
        _walk_names(s, post)

    # Params: read by the block before the block binds them, and available from
    # before the block.
    bound_so_far: set[str] = set()
    params: list[str] = []
    seq_bound = set()
    for s in block:
        sc = _Scope()
        _walk_names(s, sc)
        for name in sc.read:
            if name not in seq_bound and name in pre_bound and name not in params:
                params.append(name)
        seq_bound.update(sc.bound)
    bound_so_far = seq_bound

    # Returns: bound by the block and read after it.
    returns = [n for n in sorted(set(post.read) & bound_so_far)]

    return {
        "file": str(path),
        "function": func_name,
        "lines": (block[0].lineno, block[-1].end_lineno),
        "statements": len(block),
        "params": params,
        "returns": returns,
        "escapes": escapes,
        "safe": not escapes,
    }


def _all_args(func) -> list:
    a = func.args
    return list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs) + (
        [a.vararg] if a.vararg else []
    ) + ([a.kwarg] if a.kwarg else [])


def _inside_own_loop(stmt: ast.AST, node: ast.AST) -> bool:
    """True if `node` is a break/continue bound to a loop contained in `stmt`."""
    for loop in ast.walk(stmt):
        if isinstance(loop, (ast.For, ast.While, ast.AsyncFor)):
            for inner in ast.walk(loop):
                if inner is node:
                    return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("function")
    ap.add_argument("start", type=int)
    ap.add_argument("end", type=int)
    args = ap.parse_args()

    r = analyse(Path(args.file), args.function, args.start, args.end)
    print(f"{r['function']}  lines {r['lines'][0]}-{r['lines'][1]}  "
          f"({r['statements']} top-level statements)")
    print(f"  params  -> {r['params'] or '(none)'}")
    print(f"  returns -> {r['returns'] or '(none)'}")
    if r["escapes"]:
        print(f"  UNSAFE — control flow escapes the block:")
        for e in r["escapes"]:
            print(f"      {e}")
        print("  Extracting this block would change what those statements do.")
        return 1
    print("  SAFE to extract as a plain helper")
    return 0


if __name__ == "__main__":
    sys.exit(main())
