"""
B5 — split domain/onboarding/verification.py into a package, verbatim.

A refactoring tool, not a test. Sits alongside extract_method.py and
extract_routes.py.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT

verification.py is 2,261 lines holding exactly three top-level functions:

    process_uploaded_document          862 lines, 12 returns
    _find_latest_unverified_document   118 lines,  1 return
    handle_verification_response      1181 lines, 29 returns

This script moves each into its own module under a `verification/` package.
The import path `app.domain.onboarding.verification` is unchanged, so no
caller is touched. Every moved function is SHA-1 compared against the source
before the write is accepted.

It does NOT split the bodies. Both large functions are dominated by a single
825-line block, and cutting those into helpers is a rewrite, not a move — the
rule from Stages A and B is `move verbatim first, tidy second, never both in
one step`. Worse, nothing currently protects such a rewrite: the 709-case
golden corpus covers get_onboarding_status, not these two. Body-level
decomposition needs its own corpus first, exactly as C3 does.

So this delivers what is provable today: one file per function, byte-identical
bodies, and the FastAPI import confined to the one module that needs it.

DECORATORS ARE PART OF THE MOVE

ast.get_source_segment() excludes decorators. B4 lost all four @capture
decorators to precisely that blind spot, and the hash check missed it because
it shared the blind spot. This script slices from the first decorator line,
and asserts the decorator text survives.

Usage:
    python backend/tests/split_verification.py --dry-run   # show the plan
    python backend/tests/split_verification.py --apply     # write the package
    python backend/tests/split_verification.py --verify    # re-prove hashes
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "app" / "domain" / "onboarding" / "verification.py"
PKG = ROOT / "backend" / "app" / "domain" / "onboarding" / "verification"
MANIFEST = ROOT / "backend" / "tests" / "baseline" / "b5_verification_split.json"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)

# function name -> (module file, needs the fastapi import)
PLAN = {
    "process_uploaded_document": ("document_processing.py", True),
    "_find_latest_unverified_document": ("latest_document.py", False),
    "handle_verification_response": ("response_handling.py", False),
}

# response_handling calls the helper, so it needs one intra-package import.
EXTRA_IMPORTS = {
    "response_handling.py": (
        "from app.domain.onboarding.verification.latest_document import (\n"
        "    _find_latest_unverified_document,\n"
        ")\n"
    ),
}

MODULE_HEADERS = {
    "document_processing.py": '''"""
`process_uploaded_document` — OCR, extraction and validation of one upload.

Moved verbatim out of verification.py in B5. 862 lines, 12 returns, and one
825-line retry loop that has NOT been decomposed: that is a rewrite, and
nothing covers it yet. See backend/tests/split_verification.py.

This is the only module in app/domain that imports FastAPI, and only for the
`UploadFile` annotation on the `uploaded_file` parameter. That is a signature
coupling, not a logic one, but it is the reason domain/__init__.py cannot
claim the layer is framework-free. Confining it here means the other two
modules split out of verification.py are genuinely clean.
"""''',
    "latest_document.py": '''"""
`_find_latest_unverified_document` — newest unconfirmed document for a user.

Moved verbatim out of verification.py in B5. Originally extracted from
handle_verification_response in B5b; this move gives it its own module.

Framework-free: no FastAPI import.
"""''',
    "response_handling.py": '''"""
`handle_verification_response` — what happens when a user confirms in chat.

Moved verbatim out of verification.py in B5. 1,181 lines, 29 returns at up to
five levels of nesting, still in one function.

READ THIS BEFORE CHANGING ANYTHING HERE

This function is under review for deletion, not improvement. The chat
confirmation path it serves looks vestigial: the email channel never calls it,
its one live caller is conversation.py, and upload.py performs the same stage
transitions itself. domain/onboarding/hvr_audit.py instruments all five
mutation sites and tags each write REDUNDANT or EFFECTIVE.

    Nothing EFFECTIVE over a representative period  => delete this module.
    One EFFECTIVE                                   => it is load bearing.

Decomposing the body before that question is answered risks spending real
effort on code that is about to be removed — and doing it unprotected, since
the 709-case golden corpus covers get_onboarding_status, not this.

Framework-free: no FastAPI import.
"""''',
}

INIT_TEMPLATE = '''"""
Verification — document processing and chat-confirmation handling.

Was a single 2,261-line module. Split into one module per function in B5;
every function moved byte-identical, proven by SHA-1 in
backend/tests/split_verification.py.

    document_processing.py   process_uploaded_document          862 lines
    latest_document.py       _find_latest_unverified_document   118 lines
    response_handling.py     handle_verification_response      1181 lines

The import path is unchanged — `from app.domain.onboarding.verification
import process_uploaded_document` still resolves — so nothing that imported
the old module needed touching.

WHAT B5 DID NOT DO

The two large functions were moved, not decomposed. Each is dominated by a
single 825-line block, and splitting those bodies is a rewrite rather than a
move. Two reasons it was left:

  1. `move verbatim first, tidy second, never both in one step` — the rule
     that held through Stages A and B.
  2. Nothing covers it. The 709-case golden corpus exercises
     get_onboarding_status; neither of these functions is in it. A body-level
     split today would be an unprotected rewrite, the same objection that
     stopped C3.

`handle_verification_response` additionally may not survive at all — see the
header of response_handling.py and domain/onboarding/hvr_audit.py.
"""

from app.domain.onboarding.verification.document_processing import (
    process_uploaded_document,
)
from app.domain.onboarding.verification.latest_document import (
    _find_latest_unverified_document,
)
from app.domain.onboarding.verification.response_handling import (
    handle_verification_response,
)

__all__ = [
    "process_uploaded_document",
    "_find_latest_unverified_document",
    "handle_verification_response",
]
'''


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _slice_with_decorators(lines: list[str], node: ast.FunctionDef) -> str:
    """Source text of a function INCLUDING its decorators.

    ast.get_source_segment() drops decorators. B4 lost four @capture
    decorators to that, and the verbatim hash check did not notice because it
    used the same function. Slicing by line from the first decorator is the
    fix; the assertion in extract() is the proof.
    """
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    # decorator lineno points at the expression, not the '@' — walk back to it
    while start > 1 and lines[start - 2].lstrip().startswith("@"):
        start -= 1
    if node.decorator_list and not lines[start - 1].lstrip().startswith("@"):
        start -= 1
    return "\n".join(lines[start - 1 : node.end_lineno])


def parse_source():
    src = SRC.read_text(encoding="utf-8")
    lines = src.split("\n")
    tree = ast.parse(src)
    funcs, imports, module_stmts = {}, [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        elif not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        ):
            module_stmts.append(node)
    return src, lines, tree, funcs, imports, module_stmts


def build_import_block(lines: list[str], imports: list, include_fastapi: bool) -> str:
    """Every module-level import, verbatim, optionally minus fastapi.

    Deliberately not pruned per-function. Working out which imports each
    function needs is a static-analysis judgement call, and this codebase has
    shipped a NameError to the container twice by trusting one (A5, then B1).
    An unused import is free; a missing one is an outage. Pruning is a
    separate, checkable step.
    """
    out = []
    for node in imports:
        text = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        if not include_fastapi and "from fastapi import" in text:
            continue
        out.append(text)
    return "\n".join(out)


def extract():
    src, lines, tree, funcs, imports, module_stmts = parse_source()

    missing = set(PLAN) - set(funcs)
    if missing:
        print(f"{RED}FAIL{RESET}  functions not found: {sorted(missing)}")
        return None
    extra = set(funcs) - set(PLAN)
    if extra:
        print(f"{RED}FAIL{RESET}  unplanned top-level functions: {sorted(extra)}")
        print("        refusing to move — every function must have a destination")
        return None

    module_tail = "\n".join(
        "\n".join(lines[n.lineno - 1 : n.end_lineno]) for n in module_stmts
    )

    built = {}
    for name, (filename, needs_fastapi) in PLAN.items():
        node = funcs[name]
        body = _slice_with_decorators(lines, node)

        # Proof 1 — decorators survived the slice.
        for dec in node.decorator_list:
            dec_text = ast.unparse(dec).split("(")[0]
            if f"@{dec_text}" not in body:
                print(f"{RED}FAIL{RESET}  {name}: decorator @{dec_text} lost in slice")
                return None

        parts = [
            MODULE_HEADERS[filename],
            "",
            "from __future__ import annotations",
            "",
            build_import_block(lines, imports, needs_fastapi),
        ]
        if filename in EXTRA_IMPORTS:
            parts.append(EXTRA_IMPORTS[filename])
        parts += ["", module_tail, "", "", body, ""]
        built[filename] = ("\n".join(parts), name, _sha(body), body)

    return built, funcs, src


def verify_bodies(built, funcs, label: str) -> bool:
    """Re-parse each generated module and hash the function back out.

    A round trip: text in, module written, module parsed, function sliced
    again, hash compared. If the write mangled anything — encoding, line
    endings, a stray indent — the hashes diverge.
    """
    ok = True
    print(f"\n{DIM}{label}{RESET}")
    for filename, (content, name, expected_sha, _body) in built.items():
        try:
            sub_tree = ast.parse(content)
        except SyntaxError as e:
            print(f"  {RED}FAIL{RESET}  {filename}: does not parse — {e}")
            ok = False
            continue
        sub_lines = content.split("\n")
        found = None
        for node in sub_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                found = node
        if found is None:
            print(f"  {RED}FAIL{RESET}  {filename}: {name} missing after write")
            ok = False
            continue
        actual_sha = _sha(_slice_with_decorators(sub_lines, found))
        if actual_sha == expected_sha:
            n_lines = len(_slice_with_decorators(sub_lines, found).split("\n"))
            print(
                f"  {GREEN}PASS{RESET}  {name} — {n_lines} lines byte-identical "
                f"{DIM}{actual_sha[:12]}{RESET}"
            )
        else:
            print(
                f"  {RED}FAIL{RESET}  {name} — {expected_sha[:12]} != {actual_sha[:12]}"
            )
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the package")
    parser.add_argument("--dry-run", action="store_true", help="show the plan only")
    parser.add_argument("--verify", action="store_true", help="re-prove an applied split")
    args = parser.parse_args()

    print("=" * 72)
    print("  B5 — SPLIT verification.py")
    print("=" * 72)

    if args.verify:
        if not PKG.is_dir():
            print(f"{YELLOW}nothing to verify — {PKG.name}/ does not exist{RESET}")
            return 1

        # Compare against the hashes recorded at --apply time, when the
        # original 2,261-line file still existed. Without this the command
        # would print hashes and compare them to nothing — a check that
        # cannot fail, which this project has already been bitten by twice.
        if not MANIFEST.exists():
            print(f"{RED}FAIL{RESET}  no manifest at {MANIFEST.relative_to(ROOT)}")
            print("        --verify has nothing to compare against. Re-run --apply")
            print("        from the pre-split snapshot, or restore the manifest.")
            return 1
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
        print(
            f"{DIM}against {MANIFEST.name}, recorded {recorded.get('recorded_at', '?')}"
            f" from a {recorded.get('source_lines', '?')}-line source{RESET}"
        )

        ok = True
        for name, (filename, _) in PLAN.items():
            path = PKG / filename
            if not path.exists():
                print(f"  {RED}FAIL{RESET}  {filename} missing")
                ok = False
                continue
            content = path.read_text(encoding="utf-8")
            sub_tree = ast.parse(content)
            sub_lines = content.split("\n")
            fn = next(
                (
                    n
                    for n in sub_tree.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == name
                ),
                None,
            )
            if fn is None:
                print(f"  {RED}FAIL{RESET}  {name} not in {filename}")
                ok = False
                continue
            body = _slice_with_decorators(sub_lines, fn)
            actual = _sha(body)
            expected = recorded.get("functions", {}).get(name, {}).get("sha1")
            n_lines = len(body.split(chr(10)))
            if expected is None:
                print(f"  {RED}FAIL{RESET}  {name}: not in the manifest")
                ok = False
            elif actual == expected:
                print(
                    f"  {GREEN}PASS{RESET}  {name:<34} {n_lines:>5} lines "
                    f"{DIM}{actual[:12]}{RESET}"
                )
            else:
                print(
                    f"  {RED}FAIL{RESET}  {name}: body changed since the split "
                    f"({expected[:12]} -> {actual[:12]})"
                )
                print(
                    f"        {DIM}If deliberate, that is fine — but it is an "
                    f"edit, not a move. Re-record the manifest on purpose.{RESET}"
                )
                ok = False
        if ok:
            print(f"\n  {GREEN}VERBATIM{RESET} — every moved function still byte-identical")
        return 0 if ok else 1

    result = extract()
    if result is None:
        return 1
    built, funcs, src = result

    print(f"\n{DIM}source{RESET}")
    print(f"  {SRC.relative_to(ROOT)} — {len(src.split(chr(10)))} lines")
    print(f"\n{DIM}plan{RESET}")
    for filename, (content, name, sha, body) in built.items():
        print(
            f"  {filename:<26} {name:<34} "
            f"{len(body.split(chr(10))):>5} lines  {DIM}{sha[:12]}{RESET}"
        )

    if not verify_bodies(built, funcs, "verbatim proof (pre-write round trip)"):
        print(f"\n{RED}ABORTED{RESET} — nothing written")
        return 1

    if not args.apply:
        print(f"\n{YELLOW}dry run — nothing written.{RESET} Re-run with --apply")
        return 0

    PKG.mkdir(exist_ok=True)
    for filename, (content, _name, _sha_, _body) in built.items():
        (PKG / filename).write_text(content, encoding="utf-8")
        print(f"  {DIM}wrote {(PKG / filename).relative_to(ROOT)}{RESET}")
    (PKG / "__init__.py").write_text(INIT_TEMPLATE, encoding="utf-8")
    print(f"  {DIM}wrote {(PKG / '__init__.py').relative_to(ROOT)}{RESET}")

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "recorded_at": date.today().isoformat(),
                "source": str(SRC.relative_to(ROOT)),
                "source_lines": len(src.split("\n")),
                "note": (
                    "SHA-1 of each function INCLUDING decorators, taken while the "
                    "original single-file module still existed. --verify compares "
                    "against these. A mismatch means an edit, not a move."
                ),
                "functions": {
                    name: {
                        "module": filename,
                        "sha1": sha,
                        "lines": len(body.split("\n")),
                    }
                    for filename, (_c, name, sha, body) in built.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  {DIM}wrote {MANIFEST.relative_to(ROOT)}{RESET}")

    backup = SRC.with_suffix(".py.b5-backup")
    shutil.copy2(SRC, backup)
    SRC.unlink()
    print(f"  {DIM}removed {SRC.relative_to(ROOT)} (backup: {backup.name}){RESET}")

    print("\n" + "=" * 72)
    print(f"  {GREEN}APPLIED{RESET} — now run, in this order:")
    print("    python backend/tests/split_verification.py --verify")
    print("    python backend/tests/contract_check.py")
    print("    python backend/tests/synthesize_golden.py")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
