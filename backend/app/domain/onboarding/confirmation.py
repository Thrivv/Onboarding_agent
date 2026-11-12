r"""
Does this chat message mean "yes, that's right"?

(Raw docstring: it contains ``\b`` and ``\*``. Without the `r` prefix Python
reads ``\*`` as an invalid escape — a SyntaxWarning on 3.12+ — and, more
quietly, turns ``\b`` into a literal backspace character inside the text.)

One implementation, used by both callers. There were two divergent copies —
`conversation.py:317` (which gates whether `handle_verification_response` is
called at all) and `verification.py:1107` (which decides what it does once
called). They had different keywords, so a message could pass one and fail the
other.

## Why this matters more than it looks

`handle_verification_response` is not a message generator. It calls
`update_user_onboarding_status` at four sites and
`update_ki_verification_by_name` at one. **A message that reads as
confirmation advances the onboarding stage and can mark a key individual
verified.**

The old test was a plain substring scan:

    is_verification = any(keyword in user_message.lower() for keyword in KEYWORDS)

which produced, on real input:

| user typed | old result | why |
|---|---|---|
| `not correct` | **confirmed** | contains `correct` |
| `looks broken` | **confirmed** | `ok` inside `lo-ok-s` |
| `my business name` | **confirmed** | `si` inside `bu-si-ness` |
| `the address is missing` | confirmed* | `si` inside `mis-si-ng` |

\* only reachable through `verification.py`; `conversation.py` additionally
requires ≤ 3 words, which happened to filter the 4-word cases but not the
2-word ones.

So a user **rejecting** a document with "not correct" advanced their own
onboarding. That is the bug this module exists to remove.

## The rules

1. **Whole words only.** `\b`-anchored, so `ok` no longer matches inside
   `looks` and `si` no longer matches inside `business`.
2. **Negation wins.** If the message contains a negation, it is NOT a
   confirmation, whatever else it contains. `not correct` is a rejection.
3. **Longest phrase first**, so `looks good` is matched as a phrase rather
   than relying on the bare word `good`.

Deliberately conservative: when a message is ambiguous, return False. A missed
confirmation costs the user one more click; a false confirmation silently moves
their application forward.
"""

from __future__ import annotations

import re
import unicodedata

# Multi-word phrases are checked first so they win over their component words.
CONFIRMATION_PHRASES: tuple[str, ...] = (
    # English
    "looks good",
    "sounds good",
    "that's right",
    "thats right",
    "all good",
    # Spanish
    "se ve bien",
    "de acuerdo",
    "esta bien",
)

CONFIRMATION_WORDS: tuple[str, ...] = (
    # English — union of the two lists this replaces
    "ok", "okay", "yes", "yep", "yeah", "yup",
    "confirm", "confirmed", "correct", "verify", "verified",
    "approve", "approved", "sure", "fine", "right", "good", "perfect",
    # Spanish
    "vale", "si", "claro",
    "confirmar", "confirmado", "correcto", "verificar", "verificado",
    "aprobar", "aprobado", "bien", "perfecto",
)

# If any of these appear, the message is a rejection or a question — never a
# confirmation. `no` and `not` are the ones that actually fire in practice.
NEGATION_PHRASES: tuple[str, ...] = (
    "not correct",
    "no es",
    "no está",
    "no esta",
)

NEGATION_WORDS: tuple[str, ...] = (
    # English
    "no", "not", "dont", "doesnt", "isnt", "wasnt", "cant", "wont",
    "never", "nope", "nah", "wrong", "incorrect", "mistake", "error",
    "change", "fix", "edit", "update", "missing", "different",
    # Spanish
    "incorrecto", "equivocado", "mal", "cambiar", "corregir", "falta",
)


def _normalise(message: str) -> str:
    """
    Lowercase, strip accents, and flatten apostrophes.

    Accent stripping means `sí` and `si` are one token, so Spanish users get
    the same behaviour whether or not they typed the accent. Apostrophes are
    removed so `don't` matches the `dont` entry rather than needing both.
    """
    text = (message or "").lower().strip()
    text = text.replace("'", "").replace("’", "")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _contains_word(text: str, term: str) -> bool:
    """Whole-word / whole-phrase match. This is the fix."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def is_negation(message: str) -> bool:
    """True if the message reads as a rejection, correction, or complaint."""
    text = _normalise(message)
    if not text:
        return False
    if any(p in text for p in NEGATION_PHRASES):
        return True
    return any(_contains_word(text, w) for w in NEGATION_WORDS)


def is_confirmation(message: str, *, max_words: int | None = None) -> bool:
    """
    True only if the message is an unambiguous "yes".

    Args:
        message: what the user typed.
        max_words: if set, messages longer than this are never confirmations.
            `conversation.py` passes 3 — a long sentence that happens to
            contain "ok" is prose, not an approval. Kept as a parameter rather
            than hard-coded because `verification.py` has no such limit and the
            two call sites should not silently diverge again.

    Returns:
        bool. False for empty, negated, or over-length messages.
    """
    text = _normalise(message)
    if not text:
        return False

    if is_negation(message):
        return False

    if max_words is not None and len(text.split()) > max_words:
        return False

    if any(p in text for p in CONFIRMATION_PHRASES):
        return True

    return any(_contains_word(text, w) for w in CONFIRMATION_WORDS)


__all__ = [
    "is_confirmation",
    "is_negation",
    "CONFIRMATION_WORDS",
    "CONFIRMATION_PHRASES",
    "NEGATION_WORDS",
    "NEGATION_PHRASES",
]
