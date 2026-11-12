"""
app/i18n — deterministic, pre-translated system messages (EN / AR / ES).

Why this exists (docs/multilingual-flow-approach.html, rule 2):
fixed system messages ("Your MOA has been validated...", "All 4 individuals
are confirmed...") used to be written as `ES if language == "spanish" else EN`
pairs — Arabic silently got English, and on a language toggle the only way
to show them in the new language was an LLM translation round-trip.

Now every such message is a `LocalizedStr`: a normal `str` (so every existing
caller keeps working unchanged — f-strings, concatenation, JSON responses)
that ALSO carries all three renderings. `insert_conversation_log()` stores
those renderings in the row's `metadata.i18n`, and `/conversation-logs?
language=xx` serves the stored rendering directly — instant, exact, and
reviewable by compliance, with no LLM call on the toggle path.

Two entry points:
  * localized(language, en=..., es=..., ar=...)  — inline variants at the
    call site (used for the ~40 migrated upload/member-expansion messages).
  * render_message(key, language, **params)      — named templates from
    app/i18n/messages.py (used for new/shared messages).

Names, ID numbers, company names and percentages are passed in as params /
already-interpolated values and are never translated.
"""

import contextvars
from typing import Dict, Optional

LANGS = ("english", "arabic", "spanish")

# Set per request by main.py from the X-I18n-Pseudo header (test-only
# pseudo-locale: every localized string renders as ⟦english⟧ so untranslated
# text and English-keyed UI logic are visible in a single run).
pseudo_locale: contextvars.ContextVar = contextvars.ContextVar("i18n_pseudo_locale", default=False)


class LocalizedStr(str):
    """A str rendered in one language that remembers its other renderings."""

    variants: Dict[str, str]
    key: Optional[str]

    def __new__(cls, text: str, variants: Dict[str, str], key: Optional[str] = None):
        obj = super().__new__(cls, text)
        obj.variants = dict(variants)
        obj.key = key
        return obj

    def in_language(self, language: str) -> str:
        return self.variants.get(language) or self.variants.get("english") or str(self)


def _pick(language: str) -> str:
    from app.utils.language import normalize_language
    return normalize_language(language)


def localized(language, *, en: str, es: Optional[str] = None, ar: Optional[str] = None,
              key: Optional[str] = None) -> LocalizedStr:
    variants = {"english": en, "spanish": es or en, "arabic": ar or en}
    lang = _pick(language)
    text = variants[lang]
    if pseudo_locale.get():
        variants = {k: f"⟦{v}⟧" for k, v in variants.items()}
        text = variants["english"]
    return LocalizedStr(text, variants, key)


def _in(value, lang: str):
    """A param's rendering in `lang`: LocalizedStr params follow the target
    language (e.g. a translated summary block or doc name); anything else is
    data and is used as-is."""
    if isinstance(value, LocalizedStr):
        return value.in_language(lang)
    return value


def render_message(key: str, language=None, **params) -> LocalizedStr:
    """Render catalog template `key` (app/i18n/messages.py) in all languages."""
    from app.i18n.messages import MESSAGES
    tpl = MESSAGES[key]
    rendered = {
        lang: tpl.get(lang, tpl["english"]).format(**{k: _in(v, lang) for k, v in params.items()})
        for lang in LANGS
    }
    return localized(language, en=rendered["english"], es=rendered["spanish"],
                     ar=rendered["arabic"], key=key)


def concat(language, *parts, sep: str = "") -> LocalizedStr:
    """Join LocalizedStr / plain-str parts, keeping every language's rendering."""
    rendered = {lang: sep.join(str(_in(p, lang)) for p in parts) for lang in LANGS}
    return localized(language, en=rendered["english"], es=rendered["spanish"], ar=rendered["arabic"])


def doc_label(english_display: str, language=None) -> LocalizedStr:
    """Localized document display name (keyed by its English display name)."""
    from app.i18n.messages import doc_name
    return localized(language, en=english_display,
                     es=doc_name(english_display, "spanish"),
                     ar=doc_name(english_display, "arabic"))


def members_summary(rows, header_key: str, language=None) -> LocalizedStr:
    """'\n\n**Registered Individuals:**\n1. **NAME** — Role | Share | Status'
    rendered per language. rows: dicts with name, is_as, is_ubo, share,
    verified. Returns an empty LocalizedStr when there are no rows."""
    if not rows:
        return localized(language, en="", es="", ar="")
    header = render_message(header_key, language)
    lines = []
    for idx, r in enumerate(rows, 1):
        role = render_message("role.as" if r.get("is_as") else "role.member", language)
        if r.get("is_ubo"):
            role = concat(language, role, render_message("role.ubo_suffix", language))
        status = render_message("status.verified" if r.get("verified") else "status.pending", language)
        lines.append(render_message("summary.row", language, idx=idx, name=r.get("name", ""),
                                    role=role, share=r.get("share", "—"), status=status))
    return concat(language, "\n\n**", header, "**\n", concat(language, *lines, sep="\n"))


def i18n_metadata(message) -> Optional[dict]:
    """Metadata fragment to persist for a message, or None for plain str."""
    if isinstance(message, LocalizedStr):
        out = {"i18n": message.variants}
        if message.key:
            out["message_key"] = message.key
        return out
    return None
