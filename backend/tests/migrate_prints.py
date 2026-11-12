"""
One-shot migration: print() -> logger.<level>() across backend/app.

Kept in the repo rather than run-and-forgotten so the transformation is
auditable — anyone reviewing the Stage A4 diff can read exactly what rule
produced it.

Level is inferred from the message's own prefix, which the codebase already
used consistently:

    [ERROR] ... / leading ❌      -> logger.error
    [WARN] / [WARNING] / ⚠       -> logger.warning
    [DEBUG] ...                  -> logger.debug
    everything else              -> logger.info

The redundant level tag is then stripped from the message, because the log
format already renders the level — "[INFO] [LOGGING] x" becomes "[LOGGING] x".
Domain tags ([KI], [FATCA], [SAVE], [SUCCESS], …) are deliberately KEPT: they
carry meaning, unlike the level tags.

Deliberately NOT done here: stripping decorative emoji from messages. That is
a much larger edit surface across ~1,500 string literals for a cosmetic gain,
and each one risks mangling an f-string. Left as a follow-up.

Usage:
    python backend/tests/migrate_prints.py --dry-run
    python backend/tests/migrate_prints.py --apply
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Only these are stripped — they duplicate the rendered level.
LEVEL_TAG = re.compile(r"^\[(INFO|ERROR|WARN|WARNING|DEBUG)\]\s*", re.I)

# The severity marker is not always at position 0 — the codebase commonly
# writes a domain tag first, e.g. "[PEP] ⚠️ Disk write failed". Anchoring these
# to the start of the string mislabels every such line as INFO, so the emoji
# markers are searched anywhere in the leading literal while the bracket tags
# stay anchored (they are always written first when present).
ERROR_HINTS = (re.compile(r"^\[ERROR\]", re.I), re.compile(r"❌"))
WARN_HINTS = (re.compile(r"^\[WARN(ING)?\]", re.I), re.compile(r"⚠"))
DEBUG_HINTS = (re.compile(r"^\[DEBUG", re.I),)


def leading_literal(node: ast.AST) -> str:
    """The literal text at the start of a print()'s first argument."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                return part.value
            return ""  # starts with an interpolation
    return ""


def level_for(text: str) -> str:
    for pat in ERROR_HINTS:
        if pat.search(text):
            return "error"
    for pat in WARN_HINTS:
        if pat.search(text):
            return "warning"
    for pat in DEBUG_HINTS:
        if pat.search(text):
            return "debug"
    return "info"


def has_logger(src: str) -> bool:
    return bool(re.search(r"^logger\s*=\s*logging\.getLogger", src, re.M))


def ensure_logger(src: str) -> tuple[str, bool]:
    """Add `import logging` / `logger = logging.getLogger(__name__)` if absent."""
    if has_logger(src):
        return src, False

    tree = ast.parse(src)
    needs_import = not re.search(r"^import logging\b", src, re.M)

    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = max(last_import_line, node.end_lineno or node.lineno)

    lines = src.splitlines(keepends=True)
    block = ""
    if needs_import:
        block += "import logging\n"
    block += "\nlogger = logging.getLogger(__name__)\n"

    if last_import_line:
        lines.insert(last_import_line, block)
    else:  # no imports at all — put it after any module docstring
        insert_at = 0
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)):
            insert_at = tree.body[0].end_lineno or 0
        lines.insert(insert_at, block)
    return "".join(lines), True


def find_prints(tree: ast.AST) -> list[ast.Call]:
    """Only bare `print(...)` — never `traceback.print_exc()` etc."""
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "print"
    ]


def offset(byte_lens: list[int], line: int, col: int) -> int:
    """
    Absolute BYTE offset of (line, col).

    ast reports col_offset as a byte offset into the UTF-8 encoding of the
    line, not a character index. This codebase is full of emoji in log strings
    (❌ ⚠️ ✅ 📊 …), each 3-4 bytes, so treating col_offset as a character
    index silently mis-slices every call that follows an emoji on the same
    line. All slicing here is therefore done on bytes.
    """
    return sum(byte_lens[: line - 1]) + col


def migrate(path: Path, apply: bool) -> tuple[int, dict[str, int]]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = find_prints(tree)
    if not calls:
        return 0, {}

    src_bytes = src.encode("utf-8")
    byte_lens = [len(l.encode("utf-8")) for l in src.splitlines(keepends=True)]
    counts: dict[str, int] = {}
    edits = []

    for call in calls:
        start = offset(byte_lens, call.lineno, call.col_offset)
        end = offset(byte_lens, call.end_lineno, call.end_col_offset)
        segment = src_bytes[start:end].decode("utf-8")

        first = call.args[0] if call.args else None
        lit = leading_literal(first) if first is not None else ""
        level = level_for(lit)
        counts[level] = counts.get(level, 0) + 1

        new = re.sub(r"^print\s*\(", f"logger.{level}(", segment, count=1)

        # Strip the now-redundant level tag from inside the string literal.
        tag = LEVEL_TAG.match(lit)
        if tag:
            new = new.replace(lit, lit[tag.end():], 1)

        edits.append((start, end, new.encode("utf-8")))

    for start, end, new_bytes in sorted(edits, reverse=True):
        src_bytes = src_bytes[:start] + new_bytes + src_bytes[end:]

    src = src_bytes.decode("utf-8")
    src, added = ensure_logger(src)

    ast.parse(src)  # refuse to write anything that does not parse
    if apply:
        path.write_text(src, encoding="utf-8")
    if added:
        counts["+logger"] = 1
    return len(calls), counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("pass --dry-run or --apply")

    total = 0
    totals: dict[str, int] = {}
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        n, counts = migrate(path, apply=args.apply)
        if not n:
            continue
        total += n
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        detail = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"  {n:5d}  {path.relative_to(APP.parent)}   {detail}")

    print(f"\n  {'APPLIED' if args.apply else 'DRY RUN'} — {total} print() calls")
    for k, v in sorted(totals.items()):
        print(f"     {k:10} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
