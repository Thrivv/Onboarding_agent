"""
Adopt the stage / ownership / account-type constants from stage_table.py.

A refactoring tool, not a test. Sits alongside extract_method.py,
extract_routes.py and split_verification.py.

C1 made the document-requirement logic a declarative table and exported named
constants for the values it keys on. It did not adopt them at the call sites.
Until it does, a typo in a stage string is still a silent runtime bug — the
exact risk C1 existed to remove, only half removed.

WHY THIS IS SAFE, STATED PRECISELY

Every constant is defined as exactly the literal it replaces:

    STAGE_IDENTIFICATION = "identification"
    OWNERSHIP_SINGLE     = "Single Owner"

So each substitution is value-identical by construction. The rewritten code
cannot behave differently — it can only fail to import, which contract check 6
catches, or shadow a name, which check 5 catches. That is what makes 286 sites
a mechanical change rather than a risky one.

WHAT IS DELIBERATELY SKIPPED

  f-strings          a Constant inside a JoinedStr cannot become a Name
                     without restructuring the literal. Not worth it.
  raw strings        r"Single Owner" is a regex pattern, not a domain value.
  docstrings         a module/function docstring that happens to equal a
                     constant is documentation, not a comparison.
  specialized_ocr/   the OCR layer detects ownership from a document and
                     happens to use the same words. That is a coincidence of
                     vocabulary, not a shared definition. Importing the domain
                     table into an extractor would mean an OCR change needs a
                     domain change, and would point a low-level integration at
                     a higher layer. Left alone on purpose.

Usage:
    python backend/tests/adopt_stage_constants.py --dry-run
    python backend/tests/adopt_stage_constants.py --apply
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
STAGE_TABLE = "app.domain.onboarding.stage_table"

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)

LITERALS = {
    "identification": "STAGE_IDENTIFICATION",
    "so_member_eids": "STAGE_SO_MEMBER_EIDS",
    "member_eids": "STAGE_MEMBER_EIDS",
    "corporate_shareholder_docs": "STAGE_CORPORATE_SHAREHOLDER_DOCS",
    "Single Owner": "OWNERSHIP_SINGLE",
    "Partnership": "OWNERSHIP_PARTNERSHIP",
    "Multiple Owners": "OWNERSHIP_MULTIPLE",
    "Corporate": "ACCOUNT_CORPORATE",
}

# Relative to backend/app. See the module docstring for the reasoning.
SKIP_FILES = {
    "domain/onboarding/stage_table.py",  # where the constants are defined
    "services/specialized_ocr/trade_extractor.py",  # independent OCR vocabulary
    "services/specialized_ocr/moa_extractor.py",
    "services/specialized_ocr/ejari_extractor.py",
    "services/specialized_ocr/bvi_extractor.py",
    "services/specialized_ocr/corporate_shareholder_detector.py",
    "services/specialized_ocr/passport_extractor.py",
}


def collect_targets(tree: ast.AST, source: str) -> list[ast.Constant]:
    """Constants safe to replace with a name."""
    skip: set[int] = set()

    for node in ast.walk(tree):
        # f-string pieces: replacing them means restructuring the literal
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    skip.add(id(sub))
        # docstrings
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                skip.add(id(body[0].value))

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if node.value not in LITERALS or id(node) in skip:
            continue
        segment = ast.get_source_segment(source, node) or ""
        # raw strings are regex patterns here, not domain values
        if segment[:2].lower() in ("r'", 'r"'):
            continue
        # only simple one-line literals — anything else is not worth the risk
        if node.lineno != node.end_lineno:
            continue
        out.append(node)
    return out


def rewrite_source(source: str, targets: list[ast.Constant]) -> str:
    """Replace literals with names, working on BYTES.

    ast column offsets are byte offsets, and this codebase contains multi-byte
    characters (Arabic strings, box-drawing characters in banner comments). A
    naive str slice by col_offset corrupts any line containing them. This is a
    documented trap in docs/HANDOFF.md; it is not hypothetical.
    """
    lines = source.split("\n")
    byte_lines = [ln.encode("utf-8") for ln in lines]

    # last first, so earlier offsets stay valid
    for node in sorted(targets, key=lambda n: (n.lineno, n.col_offset), reverse=True):
        i = node.lineno - 1
        raw = byte_lines[i]
        replacement = LITERALS[node.value].encode("utf-8")
        byte_lines[i] = raw[: node.col_offset] + replacement + raw[node.end_col_offset :]

    return "\n".join(b.decode("utf-8") for b in byte_lines)


def insert_import(source: str, names: set[str]) -> str:
    """Add the stage_table import, merging into an existing one if present.

    stages.py already does `from ...stage_table import resolve_stage`. Adding a
    second ImportFrom for the same module is legal but sloppy, and it broke the
    first version of verify() below — which is how it was noticed.
    """
    tree = ast.parse(source)
    existing = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.module == STAGE_TABLE
        ),
        None,
    )

    if existing is not None:
        merged = sorted({a.name for a in existing.names} | names)
        inner = ",\n".join(f"    {n}" for n in merged)
        stmt = f"from {STAGE_TABLE} import (\n{inner},\n)"
        lines = source.split("\n")
        return "\n".join(
            lines[: existing.lineno - 1] + [stmt] + lines[existing.end_lineno :]
        )

    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = max(last, node.end_lineno)
    ordered = sorted(names)
    if len(ordered) == 1:
        stmt = f"from {STAGE_TABLE} import {ordered[0]}"
    else:
        inner = ",\n".join(f"    {n}" for n in ordered)
        stmt = f"from {STAGE_TABLE} import (\n{inner},\n)"

    lines = source.split("\n")
    lines.insert(last, stmt)
    return "\n".join(lines)


def verify(before: str, after: str, path: Path) -> tuple[bool, str]:
    """Prove the rewrite is value-identical.

    Constant-fold the new module's Names back to their literals and compare
    the resulting AST dumps. If they differ anywhere other than at an intended
    substitution, the rewrite changed meaning and is rejected.
    """
    try:
        tree_after = ast.parse(after)
    except SyntaxError as e:
        return False, f"does not parse: {e}"

    reverse = {v: k for k, v in LITERALS.items()}

    class Folder(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name):
            if isinstance(node.ctx, ast.Load) and node.id in reverse:
                return ast.copy_location(ast.Constant(value=reverse[node.id]), node)
            return node

    def strip_stage_table_imports(tree: ast.AST) -> ast.AST:
        """Remove stage_table imports from BOTH sides before comparing.

        The first version dropped them from the rewritten tree only, which
        silently deleted stages.py's pre-existing `import resolve_stage` and
        reported a meaning change that had not happened. Imports are checked
        by contract check 6 and by actually importing the package; this
        comparison is about the expressions.
        """
        tree.body = [
            n
            for n in tree.body
            if not (isinstance(n, ast.ImportFrom) and n.module == STAGE_TABLE)
        ]
        return tree

    folded = strip_stage_table_imports(Folder().visit(tree_after))
    tree_before = strip_stage_table_imports(ast.parse(before))

    if ast.dump(folded) == ast.dump(tree_before):
        return True, ""
    return False, "AST differs after folding the constants back — meaning changed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("  ADOPT STAGE CONSTANTS")
    print("=" * 72)

    total = 0
    changed_files = 0
    skipped_reasons: dict[str, int] = {}
    failures = []
    plan = []

    for path in sorted(APP.rglob("*.py")):
        rel = str(path.relative_to(APP)).replace("\\", "/")
        if rel in SKIP_FILES:
            skipped_reasons[rel] = -1
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        targets = collect_targets(tree, source)
        if not targets:
            continue

        names = {LITERALS[n.value] for n in targets}
        rewritten = rewrite_source(source, targets)
        rewritten = insert_import(rewritten, names)

        ok, why = verify(source, rewritten, path)
        if not ok:
            failures.append(f"{rel}: {why}")
            continue

        plan.append((path, rel, len(targets), sorted(names), rewritten))
        total += len(targets)
        changed_files += 1

    print(f"\n{DIM}plan{RESET}")
    for _path, rel, n, names, _new in plan:
        print(f"  {n:>4}  {rel}")
    print(f"\n  {total} substitutions across {changed_files} files")

    if skipped_reasons:
        print(f"\n{DIM}skipped on purpose{RESET}")
        for rel in sorted(skipped_reasons):
            print(f"        {rel}")

    if failures:
        print(f"\n{RED}{len(failures)} file(s) failed verification — none written{RESET}")
        for f in failures:
            print(f"    - {f}")
        return 1

    print(
        f"\n  {GREEN}all {changed_files} rewrites are value-identical{RESET}"
        f"  {DIM}(constants folded back, AST compared){RESET}"
    )

    if not args.apply:
        print(f"\n{YELLOW}dry run — nothing written.{RESET} Re-run with --apply")
        return 0

    for path, rel, _n, _names, new in plan:
        path.write_text(new, encoding="utf-8")
    print(f"\n  {DIM}wrote {changed_files} files{RESET}")
    print("\n" + "=" * 72)
    print(f"  {GREEN}APPLIED{RESET} — now run:")
    print("    python backend/tests/contract_check.py")
    print("    python backend/tests/synthesize_golden.py")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
