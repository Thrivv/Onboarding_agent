"""
One-shot migration: remove decorative emoji from logger.* messages.

Why
---
Emoji in log lines do not survive the trip to a Windows console or a log
aggregator. On the deployment console ✅ renders as `Γ£à` and 🚀 as `≡ƒÜÇ`,
which makes the logs materially harder to read. They also complicate grep
patterns.

Separately, three modules contain genuinely corrupted text — UTF-8 bytes that
were at some point decoded as cp1252 and re-saved ("mojibake"), e.g. 📋 stored
as `ðŸ“‹`. Those runs are detected by round-tripping them back through cp1252;
if the result is pure emoji, the run is removed like any other emoji.

Scope — deliberately narrow
---------------------------
ONLY string literals inside `logger.debug/info/warning/error(...)` calls are
touched. Emails, chat replies and any other user-facing text are left exactly
as they are: those emoji are a product decision, not a logging one.

Usage:
    python backend/tests/strip_log_emoji.py --dry-run
    python backend/tests/strip_log_emoji.py --apply
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Pictographs, dingbats and symbol blocks — this covers ✅ (U+2705),
# ❌ (U+274C), ⚠ (U+26A0), 📋 (U+1F4CB), 🚀 (U+1F680) and friends.
# Arrows (U+2190-21FF) and box-drawing are NOT stripped: they are used
# structurally in separator lines and read fine everywhere.
EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"
    "☀-➿"
    "⬀-⯿"
    "️‍ℹ〰]+"
)

# Characters that mojibake produces when UTF-8 is misread as cp1252.
# Mojibake detection is done with an explicit ordinal predicate rather than a
# regex character class. The class has to span the whole Latin-1 supplement
# INCLUDING the C1 control range — ⚠️ is E2 9A A0 EF B8 8F, whose cp1252
# reading is U+00E2, U+0161, U+00A0, U+00EF, U+00B8, U+008F — and writing
# literal U+0080..U+009F control characters into source is fragile: they do not
# survive editing reliably, which silently produced a class that matched only
# part of each run and left half the corruption behind.
_CP1252_SPECIALS = set("€‚ƒ„…†‡ˆ‰"
                       "Š‹ŒŽ‘’“”•"
                       "–—˜™š›œžŸ")


def _is_moji_char(ch: str) -> bool:
    """A character that could be one byte of a UTF-8 sequence read as cp1252."""
    return 0x80 <= ord(ch) <= 0xFF or ch in _CP1252_SPECIALS


def _is_continuation(ch: str) -> bool:
    """Looks like a UTF-8 continuation byte (0x80-0xBF) read as cp1252."""
    if ch in _CP1252_SPECIALS:
        return True  # cp1252 maps 0x80-0x9F to these printable characters
    return 0x80 <= ord(ch) <= 0xBF


def _is_multibyte_lead(ch: str) -> bool:
    """
    Looks like the FIRST byte of a 3- or 4-byte UTF-8 sequence.

    This is the discriminator that makes deleting unrepairable runs safe.
    Emoji are always 3 bytes (0xE2 ... for symbols like ⚠ ✅ ❌) or 4 bytes
    (0xF0 0x9F ... for pictographs like 📋 🚀). Accented Latin letters are
    2-byte sequences with a 0xC2-0xDF lead, so they are excluded here and a
    genuinely mis-encoded "café" is never touched.
    """
    return 0xE0 <= ord(ch) <= 0xF4


def _moji_runs(text: str):
    """Yield (start, end) of every maximal run of 2+ mojibake-ish characters."""
    i, n = 0, len(text)
    while i < n:
        if _is_moji_char(text[i]):
            j = i
            while j < n and _is_moji_char(text[j]):
                j += 1
            if j - i >= 2:
                yield i, j
            i = j
        else:
            i += 1

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _repair(run: str) -> str | None:
    """
    Undo one mojibake round-trip, or None if this isn't mojibake.

    cp1252 is tried first because it is what actually produced most of this
    corruption, but several of its byte values (0x81, 0x8D, 0x8F, 0x90, 0x9D)
    are undefined and refuse to encode. latin-1 covers the full U+0000–U+00FF
    range and rescues those cases — ⚠️ is one of them.
    """
    for codec in ("cp1252", "latin-1"):
        try:
            return run.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return None


_E = EMOJI.pattern.rstrip("+")  # the character class, without the quantifier


def clean(text: str) -> str:
    """
    Remove emoji from a logger.* call's source text.

    Whitespace handling is deliberately narrow: only a space DIRECTLY adjacent
    to a removed emoji is taken with it. An earlier version tidied whitespace
    across the whole call and mangled real code — `"=" * 60` became `"="* 60`
    and `'Enabled' if cond` became `'Enabled'if cond`, because the substitution
    could not tell string content from Python syntax. Deleted emoji plus one
    neighbouring space is all that is ever needed, and it cannot touch anything
    else.
    """
    # 1. corrupted emoji: repair each run, drop it only if it really was emoji.
    #    Processed right-to-left so earlier offsets stay valid.
    for start, end in reversed(list(_moji_runs(text))):
        run = text[start:end]
        repaired = _repair(run)

        if repaired is not None:
            # Round-tripped cleanly: delete only if it really was emoji.
            drop = bool(EMOJI.fullmatch(repaired))
        else:
            # Unrepairable. This corruption lost bytes on the way — the 0xA0 in
            # ⚠️ (E2 9A A0 ...) became a plain space, so the run no longer
            # decodes. Fall back to shape: a 3/4-byte lead followed only by
            # continuation bytes is a mangled emoji, never a word.
            # A run may hold SEVERAL mangled sequences back to back — 🗑️ is
            # F0 9F 97 91 EF B8 8F, i.e. a 4-byte pictograph immediately
            # followed by the 3-byte variation selector. Requiring every
            # trailing character to be a continuation byte rejected that,
            # because the 0xEF starting the second sequence is itself a lead.
            # So: lead first, then continuation-or-lead throughout.
            drop = (
                _is_multibyte_lead(run[0])
                and all(
                    _is_continuation(c) or _is_multibyte_lead(c) for c in run[1:]
                )
            )

        if drop:
            tail = end
            if tail < len(text) and text[tail] == " ":
                tail += 1  # take the adjacent space with it
            text = text[:start] + text[tail:]
        # else: genuine accented text (café, naïve) — leave alone

    # 2. well-formed emoji, taking at most one adjacent space with it
    text = re.sub(rf"{_E}+ ", "", text)   # emoji then space
    text = re.sub(rf" {_E}+", "", text)   # space then emoji
    text = re.sub(rf"{_E}+", "", text)    # bare emoji
    return text


def is_log_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LOG_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    )


def migrate(path: Path, apply: bool) -> int:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    src_b = src.encode("utf-8")
    # ast col_offset is a BYTE offset; these files are full of multi-byte
    # characters, so all slicing is done on bytes.
    blens = [len(l.encode("utf-8")) for l in src.splitlines(keepends=True)]

    def off(line: int, col: int) -> int:
        return sum(blens[: line - 1]) + col

    edits = []
    for node in ast.walk(tree):
        if not is_log_call(node):
            continue
        s = off(node.lineno, node.col_offset)
        e = off(node.end_lineno, node.end_col_offset)
        seg = src_b[s:e].decode("utf-8")
        new = clean(seg)
        if new != seg:
            edits.append((s, e, new.encode("utf-8")))

    if not edits:
        return 0
    for s, e, nb in sorted(edits, reverse=True):
        src_b = src_b[:s] + nb + src_b[e:]

    out = src_b.decode("utf-8")
    ast.parse(out)  # never write anything that doesn't parse
    if apply:
        path.write_text(out, encoding="utf-8")
    return len(edits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (a.apply or a.dry_run):
        ap.error("pass --dry-run or --apply")

    total = 0
    for p in sorted(APP.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        n = migrate(p, apply=a.apply)
        if n:
            print(f"  {n:5d}  {p.relative_to(APP.parent)}")
            total += n
    print(f"\n  {'APPLIED' if a.apply else 'DRY RUN'} — {total} log calls cleaned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
