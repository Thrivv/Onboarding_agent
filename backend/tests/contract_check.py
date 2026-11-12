"""
Contract check — the regression safety net for the refactor.

Run this before and after every refactoring step. It answers one question:
"is the observable surface of this application identical to the baseline?"

Deliberately dependency-free (standard library only, no pytest, no fastapi) so
it runs identically on a dev machine, in CI, or inside the Docker image, and
needs no credentials.

Checks
  1. ROUTES      every path/method/handler/signature matches baseline/routes.json
  2. SYNTAX      every Python file parses
  3. IMPORTS     every intra-app `from app.x import y` resolves to a real module
  4. ENDPOINTS   every API path declared in config/endpoints.js maps to a real route
  5. SHADOWING   duplicate top-level defs (silently dead code) — new ones fail
  6. NAMES       no undefined or used-before-bound names at import time
  7. MODULES     every relative import in the React app resolves to a real file
  8. ENTRYPOINTS files referenced by Docker/compose/supervisor still exist
  9. EXPORTS     every named JS import resolves to a real export in its target
 10. CAPTURE     the four B0 @capture decorators are still attached
 11. CSS         @layer has its @tailwind directive in-file; url() paths resolve
 12. DOC PATHS   nothing builds the documents dir by hand from an email

Checks 4, 6 and 9 were each added AFTER a bug of that class slipped past a
green suite. That is the operating rule for this file: when something gets
through, add the check that would have caught it, then deliberately re-break
the code to prove the new check fires.

  - 6 exists because Stage A5 shipped a NameError to the container.
  - 6 was then extended, because B1 shipped the same class of bug again: the
    check skipped `def` statements, but a function's decorators, annotations
    and defaults are evaluated at import time.
  - 4 was rewritten in B6: it scanned inline `api.get('/path')` literals, and
    once those moved behind config/endpoints.js it was passing vacuously.
  - 9 was added in B7 after ~157 import specifiers were generated
    mechanically while splitting AIAssistant.jsx.
  - 10 was added after B4 silently dropped all four @capture decorators, and
    the verbatim hash check missed it because ast.get_source_segment() ignores
    decorators too — the check shared a blind spot with the transformation.
  - 11 was added after the B9 CSS split failed the Docker build: @layer was
    separated from its @tailwind directive. Nine checks were green; none of
    them compiled anything.

Pre-existing problems are listed in baseline/known_issues.json and reported as
KNOWN rather than FAIL, so that a regression introduced by a refactoring step
is never lost in the noise of issues that were already there.

Usage:
    python backend/tests/contract_check.py             # verify against baseline
    python backend/tests/contract_check.py --update    # re-baseline (deliberate change)

Exit code is 0 when the contract is intact, 1 otherwise — safe to use as a
gate in a build script.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_routes import collect as collect_routes  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND_SRC = ROOT / "frontend" / "src"
APP = BACKEND / "app"
BASELINE = Path(__file__).resolve().parent / "baseline"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

failures: list[str] = []
warnings: list[str] = []
known: list[str] = []


def _load_known() -> dict:
    f = BASELINE / "known_issues.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


KNOWN = _load_known()
KNOWN_FE_PATHS = {e["path"] for e in KNOWN.get("frontend_endpoints", [])}
KNOWN_SHADOWED = {
    (e["file"], e["name"]) for e in KNOWN.get("shadowed_definitions", [])
}
# Pre-existing NameErrors, each recorded with its impact in known_issues.json.
KNOWN_UNDEFINED = {
    n.strip()
    for e in KNOWN.get("undefined_names", [])
    for n in str(e["name"]).split("/")
}


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {msg}")


def note_known(msg: str) -> None:
    print(f"  {DIM}KNOWN {msg}{RESET}")
    known.append(msg)


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")
    failures.append(msg)


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {msg}")
    warnings.append(msg)


def python_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


# ---------------------------------------------------------------- 1. ROUTES
def check_routes(update: bool) -> None:
    print(f"\n{DIM}[1/13] API route surface{RESET}")
    current = collect_routes()
    baseline_file = BASELINE / "routes.json"

    if update or not baseline_file.exists():
        BASELINE.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        ok(f"baseline written — {len(current)} routes")
        return

    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))

    def key(r: dict) -> tuple[str, str]:
        return (r["method"], r["path"])

    base_map = {key(r): r for r in baseline}
    curr_map = {key(r): r for r in current}

    removed = sorted(set(base_map) - set(curr_map))
    added = sorted(set(curr_map) - set(base_map))

    for m, p in removed:
        fail(f"ROUTE REMOVED: {m} {p}  (was -> {base_map[(m, p)]['handler']})")
    for m, p in added:
        fail(f"ROUTE ADDED: {m} {p}  (-> {curr_map[(m, p)]['handler']})")

    # A handler may legitimately move module during the refactor; its *name*
    # and signature changing is what would signal a behavioural edit.
    for k in sorted(set(base_map) & set(curr_map)):
        b, c = base_map[k], curr_map[k]
        if b["handler"] != c["handler"]:
            fail(f"HANDLER RENAMED: {k[0]} {k[1]}: {b['handler']} -> {c['handler']}")
        if b["params"] != c["params"]:
            fail(f"SIGNATURE CHANGED: {k[0]} {k[1]}: {b['params']} -> {c['params']}")
        if b["is_async"] != c["is_async"]:
            fail(f"ASYNC CHANGED: {k[0]} {k[1]}: async={b['is_async']} -> {c['is_async']}")
        if b["module"] != c["module"]:
            print(f"  {DIM}move{RESET}  {k[0]} {k[1]}: {b['module']} -> {c['module']}")

    if not removed and not added:
        ok(f"all {len(current)} routes match baseline")


# ---------------------------------------------------------------- 2. SYNTAX
def check_syntax() -> None:
    print(f"\n{DIM}[2/13] Python syntax{RESET}")
    bad = 0
    for path in python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            fail(f"syntax error {path.relative_to(ROOT)}:{e.lineno}: {e.msg}")
            bad += 1
    if not bad:
        ok(f"{len(python_files())} files parse cleanly")


# --------------------------------------------------------------- 3. IMPORTS
def check_imports() -> None:
    print(f"\n{DIM}[3/13] Internal import resolution{RESET}")
    modules = set()
    for path in python_files():
        rel = path.relative_to(BACKEND).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.add(".".join(parts))

    broken = 0
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("app"):
                continue
            if node.module in modules:
                continue
            # `from app.pkg import module_name` — target may be a submodule
            if any(f"{node.module}.{a.name}" in modules for a in node.names):
                continue
            fail(f"unresolved import in {path.relative_to(ROOT)}: '{node.module}'")
            broken += 1
    if not broken:
        ok("all intra-app imports resolve")


# -------------------------------------------------------------- 4. FRONTEND
def _normalise(path: str) -> str:
    """`/chatupload/ki/list/${encodeURIComponent(x)}` -> `/chatupload/ki/list/{p}`"""
    path = re.sub(r"\$\{[^}]*\}", "{p}", path)
    path = path.split("?")[0]
    return path.rstrip("/")


def check_frontend_endpoints() -> None:
    print(f"\n{DIM}[4/13] Frontend -> backend endpoint integrity{RESET}")
    routes = collect_routes()
    base = "/onboarding/ai/api"

    backend_paths = set()
    for r in routes:
        p = r["path"]
        p = p[len(base):] if p.startswith(base) else p
        backend_paths.add(_normalise(re.sub(r"\{[^}]+\}", "{p}", p)))

    found: dict[str, list[str]] = defaultdict(list)

    # Primary source since Stage B6: every path the frontend can call is
    # declared in config/endpoints.js. Both forms appear there —
    #     KEY: '/some/path',
    #     KEY: (email) => `/some/path/${enc(email)}`,
    # — so match any single- or back-quoted string that starts with a slash.
    endpoints_js = FRONTEND_SRC / "config" / "endpoints.js"
    if endpoints_js.exists():
        text = endpoints_js.read_text(encoding="utf-8")
        # Strip comments first — the module docstring quotes example paths, and
        # matching those would report phantom endpoints.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        literal_re = re.compile(r"""[`'"](/[A-Za-z0-9_\-./${}()?=]*)[`'"]""")
        for raw in literal_re.findall(text):
            found[_normalise(raw)].append("frontend/src/config/endpoints.js")
    else:
        fail("frontend/src/config/endpoints.js is missing — B6 contract lost")

    # Belt and braces: a stray inline call outside the endpoints module would
    # bypass the check above entirely, so still scan for the old pattern. This
    # should find nothing; if it does, that call site skipped the API layer.
    call_re = re.compile(r"""api\.(get|post|put|delete|patch)\(\s*[`'"]([^`'"]+)""")
    strays: list[str] = []
    for f in list(FRONTEND_SRC.rglob("*.jsx")) + list(FRONTEND_SRC.rglob("*.js")):
        if f.name == "client.js":
            continue
        for _, raw in call_re.findall(f.read_text(encoding="utf-8", errors="replace")):
            rel = str(f.relative_to(ROOT))
            found[_normalise(raw)].append(rel)
            strays.append(f"{_normalise(raw)}  ({rel})")

    missing = 0
    for path, callers in sorted(found.items()):
        if path in backend_paths:
            continue
        msg = f"frontend calls '{path}' — no matching backend route ({callers[0]})"
        if path in KNOWN_FE_PATHS:
            note_known(msg)
        else:
            fail(msg)
            missing += 1

    for s in strays:
        note_known(f"inline api call bypassing config/endpoints.js: {s}")

    if not missing:
        ok(f"{len(found)} distinct endpoints declared by frontend resolve (or are known)")


# ------------------------------------------------------------- 5. SHADOWING
def check_shadowed_definitions() -> None:
    print(f"\n{DIM}[5/13] Duplicate (shadowing) definitions{RESET}")
    total = 0
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        seen: dict[str, list[int]] = defaultdict(list)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name].append(node.lineno)
        for name, lines in sorted(seen.items()):
            if len(lines) <= 1:
                continue
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            msg = (
                f"{rel}: '{name}' defined {len(lines)}x "
                f"at lines {lines} — only the last is live"
            )
            if (rel, name) in KNOWN_SHADOWED:
                note_known(msg)
            else:
                # NEW shadowing introduced by a refactoring step is a regression.
                fail(f"NEW SHADOWED DEFINITION: {msg}")
                total += 1
    if not total:
        ok("no new shadowed definitions")


# ------------------------------------------------ 5b. UNDEFINED / EARLY NAMES
def _bound_names(tree: ast.AST) -> set[str]:
    """Every name this module binds, anywhere, by any means."""
    bound: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                bound.add(a.asname or a.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
            args = getattr(n, "args", None)
            if args:
                for a in (list(args.args) + list(args.posonlyargs)
                          + list(args.kwonlyargs)):
                    bound.add(a.arg)
                for a in (args.vararg, args.kwarg):
                    if a:
                        bound.add(a.arg)
        elif isinstance(n, (ast.Name, ast.arg)):
            if isinstance(n, ast.arg):
                bound.add(n.arg)
            elif isinstance(n.ctx, (ast.Store, ast.Del)):
                bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
        elif isinstance(n, ast.Lambda):
            for a in n.args.args:
                bound.add(a.arg)
    return bound


def _scoped_undefined(tree: ast.Module, builtins_: "set[str]") -> "list[tuple[str, int]]":
    """
    Report Load-context names not bound in their own scope chain.

    ## Why this replaced the flat version

    `_bound_names` walks the whole module and collects every binding anywhere,
    so a name imported *inside one function* counted as bound for the entire
    file. C4 hit this exactly: `mail/messages.py` had

        def send_member_documents_confirmation_email(...):
            import os          # line 937 — local to THIS function

    and ~18 uses of `os.path` in *other* functions that had no such import.
    Check 6 saw `os` bound and passed. The container then raised
    `NameError: name 'os' is not defined` the first time a completion email was
    sent — which the caller catches and logs as a warning, so the flow returned
    200 and nothing looked wrong.

    That is the **third** time this class of bug has cleared a green suite
    (A5's `config`, B1's decorators, now C4's `os`). The flat walk was the
    reason it could.

    ## Semantics

    A `Load` of `x` inside function F resolves if `x` is bound in F, in any
    enclosing function, at module level, or is a builtin. Module-level bindings
    count regardless of line order, because a function body runs after import.
    `global`/`nonlocal` promote the name to the module scope for this purpose.

    Deliberately conservative: when unsure, stay silent. A check that cries
    wolf gets ignored, and this one has to be trusted.
    """
    problems: list[tuple[str, int]] = []

    def bindings_of(node: ast.AST, *, is_module: bool) -> "set[str]":
        """Names bound directly in this scope — not descending into child scopes."""
        out: set[str] = set()

        def walk(n: ast.AST, top: bool = False) -> None:
            for child in ast.iter_child_nodes(n):
                # A nested function/class creates its own scope; only its NAME
                # binds here.
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out.add(child.name)
                    continue
                if isinstance(child, ast.Lambda):
                    continue
                if isinstance(child, ast.Import):
                    for a in child.names:
                        out.add(a.asname or a.name.split(".")[0])
                elif isinstance(child, ast.ImportFrom):
                    for a in child.names:
                        out.add(a.asname or a.name)
                elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                    out.add(child.id)
                elif isinstance(child, ast.ExceptHandler) and child.name:
                    out.add(child.name)
                elif isinstance(child, (ast.Global, ast.Nonlocal)):
                    out.update(child.names)
                walk(child)

        if not is_module:
            args = getattr(node, "args", None)
            if args:
                for a in (list(args.args) + list(getattr(args, "posonlyargs", []))
                          + list(args.kwonlyargs)):
                    out.add(a.arg)
                for a in (args.vararg, args.kwarg):
                    if a:
                        out.add(a.arg)
        walk(node)
        return out

    module_scope = bindings_of(tree, is_module=True) | builtins_

    def visit(node: ast.AST, chain: "list[set[str]]") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = bindings_of(child, is_module=False)
                # Comprehension and walrus targets anywhere inside also bind.
                for sub in ast.walk(child):
                    if isinstance(sub, ast.comprehension):
                        for t in ast.walk(sub.target):
                            if isinstance(t, ast.Name):
                                inner.add(t.id)
                    elif isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                        inner.add(sub.target.id)
                visit(child, chain + [inner])
                continue
            if isinstance(child, ast.ClassDef):
                visit(child, chain + [bindings_of(child, is_module=False)])
                continue
            if isinstance(child, ast.Lambda):
                largs = {a.arg for a in child.args.args}
                visit(child, chain + [largs])
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if not any(child.id in scope for scope in chain):
                    problems.append((child.id, child.lineno))
            visit(child, chain)

    visit(tree, [module_scope])
    return problems


def check_undefined_names() -> None:
    """
    Catch two failure modes that a plain syntax check cannot see, and that a
    Docker build only reveals at container start:

      1. A name is referenced but never imported or defined  -> NameError
      2. A module-level name is used ABOVE the line that binds it -> NameError

    Both are exactly what a mechanical refactor produces when an import is
    added in the wrong place. This check exists because Stage A5 shipped
    `config.SUPABASE_SERVICE_ROLE_KEY` into six modules whose `from app import
    config` landed below the first use — the suite was green while the API
    container crash-looped on NameError.
    """
    print(f"\n{DIM}[6/13] Undefined / used-before-defined names{RESET}")
    builtins_ = set(dir(__builtins__)) | set(
        getattr(__builtins__, "__dict__", {}).keys()
    ) | {"__name__", "__file__", "__doc__", "__package__", "self", "cls"}

    problems = 0
    for path in python_files():
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        bound = _bound_names(tree) | builtins_

        # (1) referenced but never bound — SCOPE-AWARE.
        # The old flat check treated a function-local `import os` as binding
        # `os` for the whole module. See _scoped_undefined for the C4 bug that
        # exposed it.
        seen_here: set[tuple[str, int]] = set()
        for name, lineno in _scoped_undefined(tree, builtins_):
            if (name, lineno) in seen_here:
                continue
            seen_here.add((name, lineno))
            msg = (f"undefined name '{name}' at "
                   f"{path.relative_to(ROOT)}:{lineno}")
            if name in KNOWN_UNDEFINED:
                note_known(msg)
            else:
                fail(msg)
                problems += 1

        # (2) module-level use before binding
        module_binds: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    name = a.asname or a.name.split(".")[0]
                    module_binds.setdefault(name, node.lineno)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                module_binds.setdefault(node.name, node.lineno)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in ast.walk(node):
                    if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                        module_binds.setdefault(t.id, node.lineno)

        def _import_time_nodes(node: ast.AST):
            """
            Yield the parts of a module-level statement that are EVALUATED at
            import time.

            For a plain statement that is the whole thing. For a def/class it is
            NOT the body — that runs later and may legitimately reference names
            defined further down — but it IS the decorators, the parameter
            annotations, the return annotation and the default values, all of
            which are evaluated the moment the `def` executes.

            Skipping defs wholesale is what let Stage B1 ship a NameError:
            `async def handler(request: SomeSchema)` with the import for
            `SomeSchema` placed below it. The suite was green; the container
            crash-looped on import.
            """
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from node.decorator_list
                args = node.args
                for a in (list(args.args) + list(args.posonlyargs)
                          + list(args.kwonlyargs) + [args.vararg, args.kwarg]):
                    if a is not None and a.annotation is not None:
                        yield a.annotation
                yield from [d for d in args.defaults if d is not None]
                yield from [d for d in args.kw_defaults if d is not None]
                if node.returns is not None:
                    yield node.returns
            elif isinstance(node, ast.ClassDef):
                yield from node.decorator_list
                yield from node.bases
            else:
                yield node

        for node in tree.body:
            for part in _import_time_nodes(node):
                for n in ast.walk(part):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                        bind_line = module_binds.get(n.id)
                        if bind_line is not None and bind_line > n.lineno:
                            fail(f"'{n.id}' used at {path.relative_to(ROOT)}:{n.lineno} "
                                 f"but only bound at line {bind_line} — NameError at import")
                            problems += 1

    if not problems:
        ok(f"{len(python_files())} modules — no undefined or early-used names")


# --------------------------------------------------- 7. FRONTEND MODULE GRAPH
IMPORT_RE = re.compile(
    r"""import\s+(?:(?P<clause>[^'"]+?)\s+from\s+)?['"](?P<src>[^'"]+)['"]""",
    re.MULTILINE,
)
EXTS = ("", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.jsx")


def check_frontend_modules() -> None:
    """
    Resolve every relative import in the React app to a real file.

    This is the check that guards Stage B: when AIAssistant.jsx is split into
    ~40 files, a single mistyped or forgotten import path is the most likely
    way to break the build. Catching it here is far cheaper than catching it
    in a Docker build.
    """
    print(f"\n{DIM}[7/13] Frontend module graph{RESET}")
    if not FRONTEND_SRC.exists():
        warn("frontend/src not found — skipped")
        return

    files = [p for p in FRONTEND_SRC.rglob("*") if p.suffix in (".js", ".jsx")]
    unresolved = 0
    imported: set[Path] = set()

    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in IMPORT_RE.finditer(text):
            src = m.group("src")
            if not src.startswith("."):
                continue  # package import — npm's problem, not ours
            target = (f.parent / src).resolve()
            hit = next(
                (
                    c
                    for c in (Path(str(target) + e) for e in EXTS)
                    if c.is_file()
                ),
                None,
            )
            if hit:
                imported.add(hit)
            else:
                fail(f"unresolved import '{src}' in {f.relative_to(ROOT)}")
                unresolved += 1

    if not unresolved:
        ok(f"{len(files)} frontend modules — all relative imports resolve")

    # Orphans: reachable by nobody. Entry points are legitimately un-imported.
    entries = {
        (FRONTEND_SRC / "index.js").resolve(),
        (FRONTEND_SRC / "App.jsx").resolve(),
    }
    orphans = sorted(
        p.relative_to(ROOT)
        for p in files
        if p.resolve() not in imported and p.resolve() not in entries
    )
    for o in orphans:
        warn(f"orphaned module (imported by nothing): {o}")


# ------------------------------------------------------------ 7. ENTRYPOINTS
NAMED_IMPORT_RE = re.compile(
    r"""import\s+(?:(\w+)\s*,\s*)?\{([^}]*)\}\s*from\s*['"](\.[^'"]+)['"]""", re.S
)
NAMED_EXPORT_BLOCK_RE = re.compile(r"export\s*\{([^}]*)\}")
NAMED_EXPORT_DECL_RE = re.compile(
    r"export\s+(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)"
)


def check_frontend_exports() -> None:
    """
    Every named import must resolve to a real export in the target module.

    Check 7 proves the FILE exists; this proves the SYMBOL does. They are
    different failures: `import { KiLoopCard } from './cards/KiLoopCard'`
    resolves fine as a path and still crashes at runtime with
    "KiLoopCard is not a function" if the module forgot to export it.

    This exists because Stage B7 generated ~157 import specifiers
    mechanically while splitting AIAssistant.jsx into 35 modules. Generated
    imports are exactly the kind that look right and aren't.

    Regex rather than a JS parser: no Node dependency, and the codebase only
    uses the two plain export forms below.
    """
    print(f"\n{DIM}[9/13] Frontend named exports{RESET}")
    if not FRONTEND_SRC.exists():
        warn("frontend/src not found — skipped")
        return

    files = [p for p in FRONTEND_SRC.rglob("*") if p.suffix in (".js", ".jsx")]
    exports: dict[Path, set[str]] = {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        names: set[str] = set()
        for block in NAMED_EXPORT_BLOCK_RE.findall(text):
            for n in block.split(","):
                n = n.strip()
                if not n or n == "default":
                    continue
                names.add(n.split(" as ")[-1].strip())
        names.update(NAMED_EXPORT_DECL_RE.findall(text))
        exports[f.resolve()] = names

    def resolve(frm: Path, spec: str) -> Path | None:
        base = (frm.parent / spec).resolve()
        for ext in EXTS:
            cand = Path(str(base) + ext)
            if cand.resolve() in exports:
                return cand.resolve()
        return None

    problems = 0
    checked = 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for _default, block, spec in NAMED_IMPORT_RE.findall(text):
            target = resolve(f, spec)
            if target is None:
                continue  # a non-JS asset or a path check 7 already reported
            for raw in block.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                wanted = raw.split(" as ")[0].strip()
                checked += 1
                if wanted not in exports[target]:
                    rel = f.relative_to(ROOT)
                    fail(
                        f"MISSING EXPORT: {rel} imports '{wanted}' from '{spec}' "
                        f"but that module does not export it"
                    )
                    problems += 1

    if not problems:
        ok(f"{checked} named imports resolve to real exports")


def check_capture_instrumentation() -> None:
    """
    The four B0 `@capture(...)` decorators must still be attached.

    This exists because Stage B4 silently removed all four. The helper
    extractor sliced each function from `node.lineno` — which is the `def`
    line, with decorators sitting ABOVE it — so the decorators were left
    behind. The route extractor handled decorators explicitly; the helper
    extractor did not.

    The verbatim hash check did not catch it, because
    `ast.get_source_segment()` ALSO excludes decorators: old and new were
    compared with the same blind spot on both sides, and matched perfectly.

    That is the real lesson here, and it generalises beyond `@capture`: a
    verification that shares a blind spot with the transformation it is
    checking proves nothing. This check looks for the decorators by name, at
    source level, so it cannot share that blind spot.
    """
    print(f"\n{DIM}[10/13] B0 capture instrumentation{RESET}")
    expected = {
        "get_submitted_documents",
        "get_onboarding_status",
        "process_uploaded_document",
        "handle_verification_response",
    }
    # Anchored to line start so a COMMENTED-OUT decorator does not count.
    # The first version of this check used an unanchored pattern and happily
    # passed against `# @capture("get_onboarding_status")` — caught only
    # because the "deliberately re-break it" step was actually performed.
    # Writing a check is not the same as knowing it works.
    decorator_re = re.compile(
        r'^[ \t]*@capture\(\s*["\']([^"\']+)["\']\s*\)[ \t]*$', re.M
    )
    found: set[str] = set()
    for path in python_files():
        found.update(decorator_re.findall(path.read_text(encoding="utf-8")))

    missing = expected - found
    for name in sorted(missing):
        fail(
            f"@capture(\"{name}\") is gone — B0 behavioural capture would "
            f"silently record nothing for it, and B5 would be unverifiable"
        )
    if not missing:
        ok(f"all {len(expected)} @capture decorators attached")


def check_css_layers() -> None:
    """
    Any CSS file using `@layer <name>` must also contain `@tailwind <name>`.

    PostCSS resolves Tailwind layers **per file**. The B9 split moved a
    `@layer components` block into `styles/tampering.css` while the
    `@tailwind components` directive stayed in `styles/base.css`, and the
    production build died with:

        `@layer components` is used but no matching `@tailwind components`
        directive is present

    Nine checks were green at the time. None of them compiled CSS — the
    "order preserved" verification compared TEXT, and the text was fine; it
    was the Tailwind semantics that broke. Same lesson as the duplicate
    `export default`: static agreement is not compilation.
    """
    print(f"\n{DIM}[11/13] CSS layers and asset paths{RESET}")
    if not FRONTEND_SRC.exists():
        warn("frontend/src not found — skipped")
        return

    layer_re = re.compile(r"^\s*@layer\s+([A-Za-z-]+)", re.M)
    problems = 0
    checked = 0
    for css in sorted(FRONTEND_SRC.rglob("*.css")):
        text = css.read_text(encoding="utf-8", errors="replace")
        layers = set(layer_re.findall(text))
        if not layers:
            continue
        checked += 1
        for layer in sorted(layers):
            if f"@tailwind {layer}" not in text:
                fail(
                    f"{css.relative_to(ROOT)}: uses '@layer {layer}' but has no "
                    f"'@tailwind {layer}' directive — the build will fail"
                )
                problems += 1

    # --- relative url() asset paths -----------------------------------------
    # Second failure from the same B9 split: a rule carrying
    # `url("../public/background500.jpg")` moved from src/ down into
    # src/styles/, so the path needed one more `../`. webpack resolves these at
    # build time and fails hard; nothing static was watching them.
    url_re = re.compile(r"""url\(\s*['"]?(\.[^)'"]+)['"]?\s*\)""")
    for css in sorted(FRONTEND_SRC.rglob("*.css")):
        text = css.read_text(encoding="utf-8", errors="replace")
        for rel in url_re.findall(text):
            target = (css.parent / rel.split("?")[0].split("#")[0]).resolve()
            checked += 1
            if not target.exists():
                fail(
                    f"{css.relative_to(ROOT)}: url('{rel}') does not resolve "
                    f"({target}) — the build will fail"
                )
                problems += 1

    if not problems:
        ok(f"{checked} @layer directive(s) and CSS asset path(s) resolve")

    # This suite is deliberately dependency-free, so it cannot parse JS scopes.
    # That gap let eight undefined `email` references through to a Docker build
    # in B6. The node script below closes it and takes about a second.
    checker = ROOT / "frontend" / "scripts" / "check-undefined.cjs"
    if checker.exists():
        print(
            f"  {DIM}note{RESET}  JS scope analysis is NOT covered here — run:\n"
            f"          cd frontend && node scripts/check-undefined.cjs"
        )
    else:
        warn("frontend/scripts/check-undefined.cjs is missing — no no-undef coverage")


HARDCODED_DOCS_PATH = re.compile(
    r"""["']backend["']\s*,\s*["']documents["']|backend/documents/id/\{(?:email|to_email|from_email|user_email)\}"""
)


def check_document_paths() -> None:
    """
    No module may build the documents directory by hand from an EMAIL.

    The real layout is `{DOCUMENTS_PATH}/{ref_no}`. Sixteen call sites across
    handle_reply, chat and email_sender instead built
    `os.path.join("backend", "documents", "id", <email>)` — relative, missing
    the `sme` segment, and keyed on email rather than ref_no. Every one of them
    resolved to a directory that does not exist, so the functions silently
    returned "nothing found".

    The damage was invisible because it was symmetrical-looking but wasn't:
    `save_member_progress` WROTE to the correct path while `get_member_progress`
    READ from the broken one, so member progress was saved and never seen again.
    That is why Type-1 multiple-owner member extraction never produced members.

    Predates the refactor — confirmed present in the pre-Stage-A snapshot.

    `user_docs_path(email)` is the one correct resolver. Candidate LISTS that
    try the config-driven path first and fall back to legacy locations
    (cross_validator, eid_validation, domain/documents/discovery) are fine and
    are not matched by this check — they look up, they do not write.
    """
    print(f"\n{DIM}[12/13] Document path construction{RESET}")
    problems = 0
    for path in python_files():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not HARDCODED_DOCS_PATH.search(line):
                continue
            # Candidate-list fallbacks are legitimate; they are Path(...) entries
            # inside a list of alternatives, not the primary resolution.
            if "Path(f\"" in line or "Path(f'" in line:
                continue
            fail(
                f"{rel}:{i} builds the documents path by hand — "
                f"use user_docs_path(email) instead"
            )
            problems += 1
    if not problems:
        ok("no hand-built email-keyed document paths")


def check_swallowed_status_codes() -> None:
    """
    A broad `except` must not swallow a deliberate status code.

    `HTTPException` and `DomainError` are both subclasses of `Exception`, so:

        try:
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            ...
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    reports a missing user as a 500. The 404 is written, reviewed, and then
    silently discarded three lines later. Nothing else in the suite sees it:
    the route still exists, the signature is unchanged, the names all resolve.
    Only the status code is wrong, and only at runtime.

    Found once, in `documents.py::get_extracted_data` (fixed in C2). The check
    exists so the pattern cannot come back — and it is the fifth time the rule
    has applied: when something slips past a green suite, add the check that
    would have caught it, then re-break the code to prove the check fires.

    A Try is fine if it has an `except HTTPException` / `except DomainError`
    handler, or if the broad handler re-raises bare (`raise`) or tests
    `isinstance(..., HTTPException)`.
    """
    print(f"\n{DIM}[13/13] Swallowed status codes{RESET}")

    # Status-bearing raises are NOT just `HTTPException(status_code=...)`.
    # Every DomainError subclass carries a status_code as a class attribute, so
    # `raise NotFoundError(...)` is equally a deliberate 404. Read the subclass
    # names out of the source rather than hardcoding them here — otherwise this
    # check goes blind the moment someone adds a new one, which is exactly how
    # it failed the first time it was written.
    def domain_error_names() -> "dict[str, str]":
        found: dict[str, str] = {}
        src = BACKEND / "app" / "domain" / "exceptions.py"
        if not src.exists():
            return found
        for node in ast.walk(ast.parse(src.read_bytes())):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if node.name != "DomainError" and not (bases & ({"DomainError"} | set(found))):
                continue
            status = "?"
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == "status_code"
                    and isinstance(stmt.value, ast.Constant)
                ):
                    status = str(stmt.value.value)
                elif (
                    isinstance(stmt, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "status_code" for t in stmt.targets
                    )
                    and isinstance(stmt.value, ast.Constant)
                ):
                    status = str(stmt.value.value)
            found[node.name] = status
        return found

    DOMAIN_ERRORS = domain_error_names()
    # Names that mean "a status code was chosen on purpose".
    STATUS_RAISERS = {"HTTPException"} | set(DOMAIN_ERRORS)
    # Names that, as an `except` clause, mean the author thought about this.
    GUARD_NAMES = {"HTTPException", "DomainError"} | set(DOMAIN_ERRORS)

    def raised_name(node: ast.AST) -> str | None:
        """The exception CLASS raised, not just its status code.

        Version 3 of this check needed this and did not have it. See the
        comment above is_guarded().
        """
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            return None
        fn = node.exc.func
        if isinstance(fn, ast.Name) and fn.id in STATUS_RAISERS:
            return fn.id
        return None

    def raises_status(node: ast.AST) -> str | None:
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            return None
        fn = node.exc.func
        if not (isinstance(fn, ast.Name) and fn.id in STATUS_RAISERS):
            return None
        if fn.id in DOMAIN_ERRORS:
            return DOMAIN_ERRORS[fn.id]
        for kw in node.exc.keywords:
            if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        if node.exc.args and isinstance(node.exc.args[0], ast.Constant):
            return str(node.exc.args[0].value)
        return "?"

    def walk_all(nodes) -> "list[ast.AST]":
        out = []
        for n in nodes:
            out.extend(ast.walk(n))
        return out

    def handler_names(h: ast.ExceptHandler) -> "set[str]":
        ty = h.type
        if isinstance(ty, ast.Name):
            return {ty.id}
        if isinstance(ty, ast.Tuple):
            return {e.id for e in ty.elts if isinstance(e, ast.Name)}
        return set()

    def catches(guard: "set[str]", raised: str) -> bool:
        """Would this except clause actually catch that exception?

        THIS IS VERSION 3 OF THIS CHECK AND THE REASON FOR IT

        Version 2 asked only whether SOME guard name appeared anywhere in the
        try's handlers. That was true enough while every deliberate status was
        an `HTTPException`. The moment 138 raises became `NotFoundError`,
        `ValidationError` and friends, `except HTTPException:` still counted as
        a guard — for exceptions it cannot catch. The check went green on 28
        try blocks that were, at that instant, silently converting 404s into
        500s.

        It was caught by narrowing one guard back by hand and watching the
        check fail to notice. Which is the rule, again: a check that returns
        zero has told you nothing until you have watched it fail.

        Guarding is now type-aware. `except HTTPException` guards only
        HTTPException; `except DomainError` guards every subclass; `except
        NotFoundError` guards exactly that one.
        """
        if raised == "HTTPException":
            return "HTTPException" in guard
        if raised in DOMAIN_ERRORS:
            return "DomainError" in guard or raised in guard
        return bool(guard & GUARD_NAMES)

    def is_guarded(try_node: ast.Try, handler: ast.ExceptHandler) -> bool:
        raised_names = {
            n for n in (raised_name(x) for x in walk_all(try_node.body)) if n
        }
        if raised_names:
            covered = {
                r
                for r in raised_names
                if any(catches(handler_names(hh), r) for hh in try_node.handlers)
            }
            if covered == raised_names:
                return True
        for n in walk_all(handler.body):
            if isinstance(n, ast.Raise) and n.exc is None:
                return True
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "isinstance"
                and any(isinstance(a, ast.Name) and a.id in GUARD_NAMES for a in ast.walk(n))
            ):
                return True
        return False

    problems = 0
    for path in python_files():
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue  # check 2 reports this
        for try_node in ast.walk(tree):
            if not isinstance(try_node, ast.Try):
                continue
            body_codes = sorted(
                {c for c in (raises_status(n) for n in walk_all(try_node.body)) if c}
            )
            if not body_codes:
                continue
            for handler in try_node.handlers:
                names = handler_names(handler)
                broad = handler.type is None or names <= {"Exception", "BaseException"} and names
                if not broad:
                    continue
                caught_codes = sorted(
                    {c for c in (raises_status(n) for n in walk_all(handler.body)) if c}
                )
                if not caught_codes or is_guarded(try_node, handler):
                    continue
                fail(
                    f"{rel}:{handler.lineno} broad `except` swallows status "
                    f"{','.join(body_codes)} and re-raises {','.join(caught_codes)} — "
                    f"add `except DomainError: raise` above it"
                )
                problems += 1
    if not problems:
        ok("no broad handler discards a deliberate status code")


def check_entrypoints() -> None:
    print(f"\n{DIM}[8/13] Deployment entrypoints{RESET}")
    # Module paths launched by docker-compose / supervisor must keep existing.
    required = {
        "app.services.reply_loop": "docker-compose.yml (reply-loop container command)",
        "app.main": "uvicorn / supervisord",
    }
    for module, why in required.items():
        rel = Path(*module.split(".")).with_suffix(".py")
        if not (BACKEND / rel).exists():
            fail(f"MISSING ENTRYPOINT {module} ({rel}) — required by {why}")
        else:
            ok(f"{module} present  {DIM}({why}){RESET}")

    for cfg in ("docker-compose.yml", "Dockerfile", "supervisord.conf", "nginx-combined.conf"):
        if not (ROOT / cfg).exists():
            fail(f"MISSING CONFIG {cfg} — referenced by the build")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="re-baseline (deliberate change)")
    args = parser.parse_args()

    print("=" * 72)
    print("  CONTRACT CHECK — Thrivv Onboarding Agent")
    print("=" * 72)

    check_routes(args.update)
    check_syntax()
    check_imports()
    check_frontend_endpoints()
    check_shadowed_definitions()
    check_undefined_names()
    check_frontend_modules()
    check_entrypoints()
    check_frontend_exports()
    check_capture_instrumentation()
    check_css_layers()
    check_document_paths()
    check_swallowed_status_codes()

    print("\n" + "=" * 72)
    if failures:
        print(f"  {RED}{len(failures)} FAILURE(S){RESET} — do not proceed until resolved")
        for f in failures:
            print(f"    - {f}")
    else:
        print(f"  {GREEN}CONTRACT INTACT{RESET} — API surface identical to baseline")
    if warnings:
        print(f"  {YELLOW}{len(warnings)} warning(s){RESET}")
    if known:
        print(
            f"  {DIM}{len(known)} known pre-existing issue(s) — see "
            f"baseline/known_issues.json{RESET}"
        )
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
