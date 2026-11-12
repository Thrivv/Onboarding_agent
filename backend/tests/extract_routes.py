"""
Static route extractor — builds the authoritative API surface inventory.

Why static (AST) rather than importing the FastAPI app: importing `app.main`
pulls in supabase, opencv, PyMuPDF, SMTP config and live credentials. This
parses the source instead, so the inventory can be regenerated at any point
during the refactor without a running environment.

The output is the regression contract. If a refactoring step changes a single
path, method, or handler signature, the diff against the baseline shows it.

Usage:
    python backend/tests/extract_routes.py                  # print inventory
    python backend/tests/extract_routes.py --json out.json  # machine-readable
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTES_DIR = BACKEND / "app" / "api" / "routes"
MAIN_PY = BACKEND / "app" / "main.py"

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


def _literal(node: ast.AST) -> str | None:
    """Return a string literal's value, or None if it isn't a plain literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # f-strings such as f"{BASE_PATH}/chat" — render BASE_PATH as its default
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                inner = value.value
                if isinstance(inner, ast.Name):
                    parts.append("{" + inner.id + "}")
                else:
                    parts.append("{?}")
        return "".join(parts)
    return None


def get_base_path() -> str:
    """Read the BASE_PATH default straight out of main.py."""
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "BASE_PATH" not in targets:
                continue
            # os.getenv("API_BASE_PATH", "/onboarding/ai/api").rstrip("/")
            for sub in ast.walk(node.value):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "getenv"
                    and len(sub.args) >= 2
                ):
                    default = _literal(sub.args[1])
                    if default:
                        return default.rstrip("/")
    return "/onboarding/ai/api"


def _router_prefix_in(path: Path) -> str:
    """The prefix declared by the APIRouter(...) call in one file, or ""."""
    prefix = ""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "APIRouter"
        ):
            for kw in node.keywords:
                if kw.arg == "prefix":
                    prefix = _literal(kw.value) or ""
    return prefix


def _subrouter_prefixes(init_py: Path) -> dict[str, str]:
    """
    For a route PACKAGE, map submodule name -> the prefix its parent applies
    when mounting it via `router.include_router(sub.router, prefix=...)`.

    Sub-routers in this codebase are created bare and the package `__init__`
    owns the shared prefix, but a per-submodule prefix is supported so that
    adding one later cannot silently escape the inventory.
    """
    mounts: dict[str, str] = {}
    tree = ast.parse(init_py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and node.args
        ):
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
            continue
        sub = target.value.id
        extra = ""
        for kw in node.keywords:
            if kw.arg == "prefix":
                extra = _literal(kw.value) or ""
        mounts[sub] = extra
    return mounts


def get_router_prefixes() -> dict[str, str]:
    """module name -> prefix declared in its own APIRouter(...) call."""
    prefixes: dict[str, str] = {}
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        prefixes[path.stem] = _router_prefix_in(path)
    # Route PACKAGES (a directory with __init__.py) declare their prefix in the
    # __init__ and mount bare sub-routers. `onboarding/` is the first of these,
    # created when chatupload.py was split in Stage B4.
    for pkg in sorted(ROUTES_DIR.iterdir()):
        init_py = pkg / "__init__.py"
        if pkg.is_dir() and init_py.exists():
            prefixes[pkg.name] = _router_prefix_in(init_py)
    return prefixes


def get_mount_prefixes(base_path: str) -> dict[str, str]:
    """module name -> extra prefix supplied by main.py's include_router call."""
    mounts: dict[str, str] = {}
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
        ):
            continue
        if not node.args:
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
            continue
        module = target.value.id
        mount = ""
        for kw in node.keywords:
            if kw.arg != "prefix":
                continue
            # Two forms appear in main.py: `prefix=BASE_PATH` (a bare Name) and
            # `prefix=f"{BASE_PATH}/chat"` (an f-string). Resolve both to the
            # same concrete string so every module's paths render consistently.
            if isinstance(kw.value, ast.Name) and kw.value.id == "BASE_PATH":
                mount = base_path
            else:
                mount = (_literal(kw.value) or "").replace("{BASE_PATH}", base_path)
        mounts[module] = mount
    return mounts


def collect() -> list[dict]:
    base_path = get_base_path()
    router_prefixes = get_router_prefixes()
    mount_prefixes = get_mount_prefixes(base_path)

    # Build the work list: (label, file, full prefix before the decorator path).
    # A flat module contributes one entry; a route package contributes one per
    # submodule, carrying the package prefix plus any per-submodule prefix.
    targets: list[tuple[str, Path, str]] = []

    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = path.stem
        if module not in mount_prefixes:
            continue  # router exists but is never mounted
        targets.append(
            (module, path, mount_prefixes[module] + router_prefixes.get(module, ""))
        )

    for pkg in sorted(ROUTES_DIR.iterdir()):
        if not (pkg.is_dir() and (pkg / "__init__.py").exists()):
            continue
        if pkg.name not in mount_prefixes:
            continue
        pkg_prefix = mount_prefixes[pkg.name] + router_prefixes.get(pkg.name, "")
        sub_prefixes = _subrouter_prefixes(pkg / "__init__.py")
        for sub in sorted(pkg.glob("*.py")):
            if sub.name == "__init__.py":
                continue
            targets.append(
                (
                    f"{pkg.name}/{sub.stem}",
                    sub,
                    pkg_prefix + sub_prefixes.get(sub.stem, ""),
                )
            )

    routes: list[dict] = []
    for module, path, prefix in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                if not (
                    isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id == "router"
                ):
                    continue
                method = deco.func.attr.lower()
                if method not in HTTP_METHODS:
                    continue
                tail = _literal(deco.args[0]) if deco.args else ""
                full = f"{prefix}{tail}".replace("//", "/")
                routes.append(
                    {
                        "method": method.upper(),
                        "path": full,
                        "module": module,
                        "handler": node.name,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "params": [a.arg for a in node.args.args],
                    }
                )

    routes.sort(key=lambda r: (r["path"], r["method"]))
    return routes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", metavar="FILE", help="write inventory as JSON")
    args = parser.parse_args()

    routes = collect()

    if args.json:
        Path(args.json).write_text(
            json.dumps(routes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Wrote {len(routes)} routes -> {args.json}")
        return 0

    current = None
    for r in routes:
        if r["module"] != current:
            current = r["module"]
            print(f"\n--- {current}.py ---")
        flag = "" if r["is_async"] else "  [SYNC]"
        print(f"  {r['method']:7} {r['path']:65} -> {r['handler']}{flag}")
    print(f"\nTotal: {len(routes)} routes across {len({r['module'] for r in routes})} modules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
