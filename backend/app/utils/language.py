"""
app/utils/language.py
======================
Single source of truth for validating/normalizing the `language` field that
arrives on chat, upload and compliance requests.

Before this module existed, every caller hand-rolled its own
`if language not in ["english", "spanish", "arabic"]: language = "english"`
check — 24 near-identical copies across message_generator.py, conversation.py,
upload.py and response_handling.py (see docs/multilingual-support-plan.html).
That was already fragile (easy to add a language somewhere and miss a copy);
it became untenable once the LANGUAGE_TOGGLE_ENABLED kill switch was added,
since enforcing a feature flag would have meant touching all 24 sites again.
Now there is exactly one place to change either.
"""

import contextvars

from app import config

SUPPORTED_LANGUAGES = ["english", "arabic", "spanish"]

# Language of the request currently being handled. Set once per request by
# the HTTP middleware in main.py from the `X-User-Language` header, which the
# frontend's axios interceptor attaches to EVERY call. This is what lets an
# endpoint whose request schema has no `language` field (ki/loop-finalize,
# ki/verify, ownership, product-package, ...) still answer in the user's
# language: call `normalize_language(None)` / `request_language()` and it
# resolves to the header value instead of silently defaulting to English.
current_request_language: contextvars.ContextVar = contextvars.ContextVar(
    "current_request_language", default=None
)


def language_from_header(raw) -> str:
    """Map an X-User-Language header value (english/arabic/spanish or
    en/ar/es) onto SUPPORTED_LANGUAGES; returns None when absent/unknown."""
    v = (raw or "").strip().lower()
    short = {"en": "english", "ar": "arabic", "es": "spanish"}
    v = short.get(v, v)
    return v if v in SUPPORTED_LANGUAGES else None


def request_language() -> str:
    """The current request's language (header-derived), normalized."""
    return normalize_language(None)


def normalize_language(language) -> str:
    """
    Returns a value guaranteed to be one of SUPPORTED_LANGUAGES.

    - Missing/unrecognized input falls back to "english" — unchanged
      behaviour from every one of the 24 checks this replaces.
    - When LANGUAGE_TOGGLE_ENABLED (.env.docker) is off, ANY non-English
      value also falls back to "english". This is enforced here, server-side
      — not just by hiding the toggle in the UI — so a request that bypasses
      the frontend (a stale client, a direct API call) can't get Arabic or
      Spanish content while the feature is switched off.
    """
    value = (language or "").strip().lower()
    if value not in SUPPORTED_LANGUAGES:
        # No usable explicit value -> fall back to the request's header
        # language (see current_request_language) before English.
        value = current_request_language.get() or "english"
    if not config.LANGUAGE_TOGGLE_ENABLED and value != "english":
        value = "english"
    return value
import json
import logging
import re as _re

logger = logging.getLogger(__name__)

_LANGUAGE_DISPLAY_NAMES = {
    "english": "English",
    "arabic": "Arabic",
    "spanish": "Spanish",
}


def detect_and_translate_input(message: str, target_language: str) -> dict:
    """
    Detects the language a user typed `message` in and, if it differs from
    `target_language` (the chat's currently active/selected language), asks
    the LLM to translate it into `target_language` before it is handed to
    the rest of the pipeline (verification-keyword matching, prompt
    building, conversation logging, etc.) — so the active language stays
    authoritative no matter what language the user actually types in.

    Reuses the same Bedrock-backed LLM gateway every other message in this
    app goes through (app.services.run_model.call_local_llm) rather than
    adding a separate translation service or library.

    Returns:
        {
            "detected_language": one of SUPPORTED_LANGUAGES, or "unknown" if
                the model's response couldn't be parsed,
            "translated_message": the text to use downstream — the
                translation when one was needed and produced, otherwise
                `message` unchanged,
            "was_translated": True only when translation actually ran and
                changed the text handed downstream,
        }

    Fails open: any error (LLM call failure, malformed response, etc.) is
    logged and swallowed, returning the original message untouched with
    was_translated=False — a translation hiccup should never block a user
    from chatting.
    """
    fallback = {
        "detected_language": "unknown",
        "translated_message": message,
        "was_translated": False,
    }

    if not message or not message.strip():
        return fallback

    target_language = target_language if target_language in SUPPORTED_LANGUAGES else "english"
    target_display = _LANGUAGE_DISPLAY_NAMES[target_language]

    try:
        from app.services.run_model import call_local_llm

        system_prompt = (
            "You are a language detection and translation engine embedded in a "
            "banking onboarding chat system. You only ever respond with a single "
            "JSON object - no markdown, no commentary, no code fences."
        )

        prompt = f"""Detect the language of the USER MESSAGE below and translate it into {target_display}.

The chat's active language is {target_display}. Supported languages are English, Arabic, and Spanish.

Rules:
- If the message is already in {target_display}, "translated_text" should be the message unchanged.
- Preserve names, numbers, email addresses, document names, and any other proper nouns exactly as written - do not translate them.
- Also keep unchanged: file names (e.g. "eid - Copy.png"), ID / license / reference numbers (e.g. 784-1999-0405761-1, REF-2026-BX64P8), percentages, dates, and people's or companies' names written in capitals.
- Keep markdown (**bold**), line breaks and numbered-list structure ("1. NAME — 48%") exactly as in the source.
- Keep the tone and intent of the message; do not answer it or add anything, only translate it.

USER MESSAGE:
\"\"\"{message}\"\"\"

Respond with ONLY this JSON object:
{{"detected_language": "english|arabic|spanish|other", "translated_text": "<message translated into {target_display}>"}}"""

        raw = call_local_llm(prompt, system_prompt=system_prompt, temperature=0.1)

        # Occasionally wrapped in ```json fences despite the instruction not
        # to - strip them before parsing.
        cleaned = _re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=_re.MULTILINE).strip()
        parsed = json.loads(cleaned)

        detected = str(parsed.get("detected_language", "")).strip().lower()
        translated_text = parsed.get("translated_text")

        if not translated_text or not isinstance(translated_text, str):
            return fallback

        if detected not in SUPPORTED_LANGUAGES:
            detected = "unknown"

        was_translated = translated_text.strip() != message.strip()

        return {
            "detected_language": detected,
            "translated_message": translated_text,
            "was_translated": was_translated,
        }

    except Exception as e:
        logger.warning(f"[LANGUAGE] detect_and_translate_input failed, using original message: {e}")
        return fallback


def translate_stored_messages_batch(items: list, target_language: str) -> dict:
    """
    Translate a batch of already-sent conversation messages into
    `target_language` in ONE LLM call — the cache-fill path behind
    GET /conversation-logs's `?language=` parameter (Phase 2,
    docs/language-mirroring-verdict.html). Unlike detect_and_translate_input(),
    these rows are already sitting in the database with a (usually) known
    origin language, so this is pure translation, no detection.

    Args:
        items: list of {"id": <row id>, "text": str, "source_language": one
            of SUPPORTED_LANGUAGES, or None/anything else for "unknown"}. An
            item whose source_language already equals target_language is
            skipped — returned as a cache-miss, not sent to the LLM — since
            the caller (the endpoint) already has the right text for it.
        target_language: one of SUPPORTED_LANGUAGES. Callers should run this
            through normalize_language() themselves before calling — this
            function trusts what it's given rather than re-validating.

    Returns:
        {str(id): translated_text} for every item that needed and got a
        translation. IDs are matched explicitly off the model's JSON
        response rather than relying on array order — a batched call
        returning results out of order would otherwise silently attach a
        translation to the wrong row. An id missing from the result means it
        couldn't be translated this round; callers should fail open and keep
        showing that row's original text rather than blocking on it.

    Fails open on the whole batch: any error (LLM call failure, malformed
    JSON, non-list response) returns {} — every item in the batch keeps its
    original text this round, exactly like detect_and_translate_input()'s
    per-message fail-open behaviour.
    """
    target_language = target_language if target_language in SUPPORTED_LANGUAGES else "english"
    target_display = _LANGUAGE_DISPLAY_NAMES[target_language]

    to_translate = [
        item for item in items
        if item.get("text") and item["text"].strip()
        and item.get("source_language") != target_language
    ]
    if not to_translate:
        return {}

    try:
        from app.services.run_model import call_local_llm

        system_prompt = (
            "You are a translation engine embedded in a banking onboarding "
            "chat system. You only ever respond with a single JSON array - "
            "no markdown, no commentary, no code fences."
        )

        items_json = json.dumps(
            [{"id": str(item["id"]), "text": item["text"]} for item in to_translate],
            ensure_ascii=False,
        )

        prompt = f"""Translate each "text" value below into {target_display}.

Rules:
- Preserve names, numbers, email addresses, document names, and any other proper nouns exactly as written - do not translate them.
- Also keep unchanged: file names (e.g. "eid - Copy.png"), ID / license / reference numbers (e.g. 784-1999-0405761-1, REF-2026-BX64P8), percentages, dates, and people's or companies' names written in capitals.
- Keep markdown (**bold**), line breaks and numbered-list structure ("1. NAME — 48%") exactly as in the source.
- Keep the tone and meaning of each message; do not answer, summarize, or add anything - only translate.
- Return every item from the input, in any order, matched by its original "id".

MESSAGES (JSON array):
{items_json}

Respond with ONLY a JSON array of this shape:
[{{"id": "<same id>", "translated_text": "<that message's text translated into {target_display}>"}}, ...]"""

        raw = call_local_llm(prompt, system_prompt=system_prompt, temperature=0.1)

        cleaned = _re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=_re.MULTILINE).strip()
        parsed = json.loads(cleaned)

        if not isinstance(parsed, list):
            logger.warning("[LANGUAGE] translate_stored_messages_batch: response was not a JSON array")
            return {}

        result = {}
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            translated_text = entry.get("translated_text")
            if entry_id is None or not isinstance(translated_text, str) or not translated_text.strip():
                continue
            result[str(entry_id)] = translated_text

        return result

    except Exception as e:
        logger.warning(f"[LANGUAGE] translate_stored_messages_batch failed, no rows translated this round: {e}")
        return {}


def translate_stored_message(text: str, source_language: str, target_language: str) -> str:
    """
    Translate a single already-stored message.

    Thin wrapper around translate_stored_messages_batch() so there is
    exactly one place that builds the translation prompt and parses the
    model's response — matching this module's own "single choke point"
    precedent (see the module docstring). Callers with more than one message
    to translate should call the batch function directly rather than
    looping this one, or they lose the batching this exists for.

    Fails open: returns `text` unchanged if no translation happened
    (already in target_language, empty input, or any error).
    """
    if not text or not text.strip():
        return text
    result = translate_stored_messages_batch(
        [{"id": "single", "text": text, "source_language": source_language}],
        target_language,
    )
    return result.get("single", text)
