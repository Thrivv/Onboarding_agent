"""
Adopt the DomainError hierarchy at the route layer.

A refactoring tool, not a test.

C2 shipped `domain/exceptions.py`, one translation layer in
`api/error_handlers.py`, and contract check 13. It did not adopt any of it:
`app/api` still raises `HTTPException` 139 times. This converts those raises
and, at the same time, stops the 500s that forward raw exception text to the
browser.

TWO CHANGES, AND ONLY ONE OF THEM IS INVISIBLE

  1. `HTTPException(404, "No user")` -> `NotFoundError("No user")`
     The response body is byte-identical. The handler returns FastAPI's own
     `{"detail": ...}` plus an additive `"code"` key, and the four frontend
     sites that read `error.response?.data?.detail` are unaffected.

  2. `HTTPException(500, detail=str(e))` -> `DomainError(context=str(e))`
     The response body CHANGES. The client now gets "An internal error
     occurred." instead of whatever the driver said, and the original text
     goes to the log line instead. That is the entire point — the current
     idiom forwards file paths, driver errors and occasionally a connection
     string straight to the browser — but it is a user-visible change and was
     signed off as such.

THE TRAP THIS TOOL EXISTS TO AVOID

46 of the 139 raises sit inside a `try` that has BOTH `except HTTPException`
and a broad `except Exception`. Convert the raise and leave the handler alone,
and the deliberate 404 falls through to the broad handler and is re-raised as
a 500. That is precisely the bug C2 found in `documents.py::get_extracted_data`
— reproduced 46 times in one commit.

So every `except HTTPException` that guards a converted raise is widened to
`except (HTTPException, DomainError)`. Contract check 13 is the independent
confirmation: it fails if any broad handler discards a deliberate status.

Usage:
    python backend/tests/adopt_domain_errors.py --report
    python backend/tests/adopt_domain_errors.py --dry-run
    python backend/tests/adopt_domain_errors.py --apply
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend" / "app" / "api"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)

STATUS_MAP = {
    400: "ValidationError",
    401: "AuthError",
    403: "PermissionError_",
    404: "NotFoundError",
    409: "ConflictError",
    500: "DomainError",
    502: "UpstreamError",
}

# 503 has no subclass. Inventing one, or bending it to UpstreamError's 502,
# would change a status code to tidy an import — the wrong trade. Left alone.
UNMAPPED = {503}

EXC_IMPORT = "app.domain.exceptions"


def _status_of(call: ast.Call) -> int | None:
    node = None
    if call.args:
        node = call.args[0]
    for kw in call.keywords:
        if kw.arg == "status_code":
            node = kw.value
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    return None


def _detail_of(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "detail":
            return kw.value
    if len(call.args) > 1:
        return call.args[1]
    return None


def _leaks_exception_text(node: ast.expr | None, source: str) -> bool:
    """Does this detail expression carry raw exception text to the client?

    Covers `str(e)`, and f-strings that interpolate the caught exception —
    `f"Upload failed: {e}"` leaks exactly as much as `str(e)` does.
    """
    if node is None:
        return False
    text = ast.get_source_segment(source, node) or ""
    if re.search(r"\bstr\s*\(\s*e\w*\s*\)", text):
        return True
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                inner = ast.get_source_segment(source, part.value) or ""
                if re.fullmatch(r"e\w*", inner.strip()):
                    return True
    return False


def plan_file(path: Path):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    conversions = []  # (raise_node, call, new_class, mode, detail_src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        call = node.exc
        if getattr(call.func, "id", getattr(call.func, "attr", "")) != "HTTPException":
            continue
        status = _status_of(call)
        if status is None or status in UNMAPPED or status not in STATUS_MAP:
            continue
        detail = _detail_of(call)
        detail_src = ast.get_source_segment(source, detail) if detail else None
        mode = "context" if _leaks_exception_text(detail, source) else "detail"
        conversions.append((node, call, STATUS_MAP[status], mode, detail_src))

    if not conversions:
        return None

    converted_lines = {n.lineno for n, _c, _k, _m, _d in conversions}

    # Widen every `except HTTPException` guarding a converted raise.
    widenings = []
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        body_lines = set()
        for st in t.body:
            for sub in ast.walk(st):
                body_lines.add(getattr(sub, "lineno", -1))
        if not (body_lines & converted_lines):
            continue
        for h in t.handlers:
            if h.type is None:
                continue
            htext = ast.get_source_segment(source, h.type) or ""
            if htext.strip() == "HTTPException":
                widenings.append(h.type)

    return source, tree, conversions, widenings


def apply_file(path: Path):
    planned = plan_file(path)
    if planned is None:
        return None
    source, _tree, conversions, widenings = planned

    lines = [ln.encode("utf-8") for ln in source.split("\n")]

    # (start_line, start_col, end_line, end_col, replacement)
    # Byte offsets throughout: ast column offsets ARE byte offsets, and this
    # codebase has multi-byte characters in route strings. Slicing decoded str
    # by these numbers corrupts any line containing one.
    edits = []

    for _node, call, cls, mode, detail_src in conversions:
        if mode == "detail":
            new = f"{cls}({detail_src})" if detail_src else f"{cls}()"
        else:
            new = f"{cls}(context={detail_src})"
        edits.append(
            (call.lineno, call.col_offset, call.end_lineno, call.end_col_offset, new)
        )

    for node in widenings:
        edits.append(
            (
                node.lineno,
                node.col_offset,
                node.end_lineno,
                node.end_col_offset,
                "(HTTPException, DomainError)",
            )
        )

    # Last edit first, so earlier line numbers and offsets stay valid. A span
    # that covers several lines collapses to one — that is why the first
    # attempt at this, which spliced a single line and hunted for the closing
    # paren by hand, left `)aise HTTPException(` behind.
    for start_l, start_c, end_l, end_c, new in sorted(edits, reverse=True):
        i, j = start_l - 1, end_l - 1
        head = lines[i][:start_c]
        tail = lines[j][end_c:]
        lines[i : j + 1] = [head + new.encode("utf-8") + tail]

    out = "\n".join(b.decode("utf-8") for b in lines)

    needed = sorted({c[2] for c in conversions} | ({"DomainError"} if widenings else set()))
    tree2 = ast.parse(out)
    existing = next(
        (n for n in tree2.body if isinstance(n, ast.ImportFrom) and n.module == EXC_IMPORT),
        None,
    )
    if existing:
        merged = sorted({a.name for a in existing.names} | set(needed))
        stmt = "from {} import (\n{},\n)".format(
            EXC_IMPORT, ",\n".join(f"    {n}" for n in merged)
        )
        ol = out.split("\n")
        out = "\n".join(ol[: existing.lineno - 1] + [stmt] + ol[existing.end_lineno :])
    else:
        last = 0
        for n in tree2.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                last = max(last, n.end_lineno)
        stmt = "from {} import (\n{},\n)".format(
            EXC_IMPORT, ",\n".join(f"    {n}" for n in needed)
        )
        ol = out.split("\n")
        ol.insert(last, stmt)
        out = "\n".join(ol)

    return source, out, conversions, widenings


def verify(after: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(after)
    except SyntaxError as e:
        return False, f"does not parse: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = getattr(node.exc.func, "id", getattr(node.exc.func, "attr", ""))
            if name in STATUS_MAP.values():
                # a converted raise must never still carry status_code=
                for kw in node.exc.keywords:
                    if kw.arg == "status_code":
                        return False, f"line {node.lineno}: status_code survived conversion"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("  ADOPT DomainError AT THE ROUTE LAYER")
    print("=" * 72)

    results = []
    for path in sorted(API.rglob("*.py")):
        r = apply_file(path)
        if r is None:
            continue
        source, out, conversions, widenings = r
        ok, why = verify(out)
        results.append((path, source, out, conversions, widenings, ok, why))

    total = sum(len(c) for _p, _s, _o, c, _w, _ok, _w2 in results)
    ctx = sum(1 for _p, _s, _o, c, _w, _ok, _w2 in results for x in c if x[3] == "context")
    wid = sum(len(w) for _p, _s, _o, _c, w, _ok, _w2 in results)

    print(f"\n{DIM}plan{RESET}")
    for path, _s, _o, conversions, widenings, ok, why in results:
        rel = path.relative_to(API)
        mark = f"{GREEN}ok{RESET}" if ok else f"{RED}FAIL{RESET}"
        n_ctx = sum(1 for c in conversions if c[3] == "context")
        print(
            f"  {mark}  {len(conversions):>3} raises "
            f"({n_ctx:>2} leak-fixes), {len(widenings):>2} guards widened   {rel}"
        )
        if not ok:
            print(f"        {RED}{why}{RESET}")

    print(
        f"\n  {total} raises converted, of which {ctx} stop leaking exception "
        f"text\n  {wid} `except HTTPException` widened to also catch DomainError"
    )
    print(
        f"  {DIM}503 left as HTTPException on purpose — no subclass, and bending "
        f"it to 502 would change a status code{RESET}"
    )

    if any(not ok for *_x, ok, _w in results):
        print(f"\n{RED}verification failed — nothing written{RESET}")
        return 1

    if not args.apply:
        print(f"\n{YELLOW}dry run — nothing written.{RESET} Re-run with --apply")
        return 0

    for path, _s, out, _c, _w, _ok, _w2 in results:
        path.write_text(out, encoding="utf-8")
    print(f"\n  {DIM}wrote {len(results)} files{RESET}")
    print("\n" + "=" * 72)
    print(f"  {GREEN}APPLIED{RESET} — check 13 is the real gate here:")
    print("    python backend/tests/contract_check.py")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
