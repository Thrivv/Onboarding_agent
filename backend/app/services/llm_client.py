"""
app/services/llm_client.py
==========================
Centralized LLM client for every model call in the app.

SINGLE SOURCE OF TRUTH for the model and endpoint. Every text and vision call
in the app goes through AWS Bedrock (see app/services/bedrock_client.py for
the actual request/response translation) using one model —
bedrock_client.MODEL_ID (Claude Haiku) — for every task. Do NOT re-declare
model names or endpoints in individual extractors — import them from here.

TEXT_PRIMARY/TEXT_FALLBACK and VISION_PRIMARY/VISION_FALLBACK are kept as
four separate names, all pointing at the same Bedrock model, purely for
backward compatibility with every extractor that already imports them —
removing them would mean touching every extractor's imports for no behaviour
change. The primary/fallback retry loop below (and the equivalent loops in
ocr_service.py and the extractors) still runs, it just retries the same
model once.

This app previously called OpenRouter (two open-weight models per task,
picked via a "model" field in the request) with an optional independent
SECONDARY_LLM_* provider as a third attempt if both OpenRouter models
failed. Both are gone: there's one provider (Bedrock) and one model now, so
the multi-provider fallback chain no longer applies.

Usage
-----
  from app.services.llm_client import (
      TEXT_PRIMARY, TEXT_FALLBACK,
      VISION_PRIMARY, VISION_FALLBACK,
      LLM_API_URL,
      call_text_llm, call_vision_llm,
      is_identity_doc,
  )
"""

import time
import logging
from typing import Optional
from app import config
from app.services import bedrock_client

logger = logging.getLogger(__name__)

# ── API endpoint ─────────────────────────────────────────────────────────────
# Model selection happens via the Bedrock invoke URL, not a per-call "model"
# field, so there is only one URL for every call site that used to import
# OPENROUTER_API_URL.
LLM_API_URL = bedrock_client.INVOKE_URL

# ── Default per-model call timeout ───────────────────────────────────────────
# Configurable via LLM_CALL_TIMEOUT_SECONDS in .env.docker — change + restart
# the container to raise/lower without editing code. Previously hardcoded at
# 120s per model; call_text_llm/call_vision_llm each try 2 models in sequence,
# so a hung primary could take up to 2x this before falling back. Lowered
# default to 45s so a stuck call fails over to the fallback model (and,
# further up the stack, to the fallback template text) much faster.
DEFAULT_LLM_TIMEOUT_SECONDS = config.LLM_CALL_TIMEOUT_SECONDS

# ── Model  (single Bedrock model for vision + text + chat) ───────────────────
# See the module docstring — these four names all resolve to the same
# bedrock_client.MODEL_ID now that there is one provider and one model.
VISION_PRIMARY  = bedrock_client.MODEL_ID
VISION_FALLBACK = bedrock_client.MODEL_ID
TEXT_PRIMARY    = bedrock_client.MODEL_ID
TEXT_FALLBACK   = bedrock_client.MODEL_ID

# ── Identity doc types that require the vision model ─────────────────────────
IDENTITY_DOC_TYPES = {
    "eid",
    "emirates_id",
    "emirates id",
    "identity card",
    "passport",
    "travel document",
    "travel_document",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _api_key() -> str:
    key = config.AWS_BEARER_TOKEN_BEDROCK or ""
    if not key:
        raise ValueError("[LLM_CLIENT] AWS_BEARER_TOKEN_BEDROCK is not set")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _post_chat_completion(url: str, headers: dict, model: str, messages: list,
                           temperature: float, max_tokens: int, timeout: int) -> str:
    """
    Shared chat-completions call, routed through bedrock_client.post (see
    that module for the OpenAI-shape-in/out translation to Bedrock's
    Anthropic Messages format). Raises on any failure (HTTP error,
    malformed response, empty completion); callers decide what "failure"
    means for their retry loop.
    """
    resp = bedrock_client.post(
        url,
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()["choices"][0]["message"]["content"]
    # A 200 response with a null/empty completion (seen under concurrent
    # load — see ocr_service.call_api_with_retry for the same failure mode)
    # would otherwise be returned as-is, silently skipping the next model in
    # the fallback chain. Treat it as a failure instead.
    if not result or not result.strip():
        raise RuntimeError(f"{model} returned empty/null completion content")
    return result


# ── Public helpers ────────────────────────────────────────────────────────────

def is_identity_doc(doc_type: str) -> bool:
    """Return True when the document type needs the vision model."""
    return doc_type.lower().strip() in IDENTITY_DOC_TYPES


def get_models_for_doc(doc_type: str):
    """Return (primary, fallback) model pair appropriate for doc_type."""
    if is_identity_doc(doc_type):
        return VISION_PRIMARY, VISION_FALLBACK
    return TEXT_PRIMARY, TEXT_FALLBACK


# ── LLM call helpers ──────────────────────────────────────────────────────────

def call_text_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    timeout: int = DEFAULT_LLM_TIMEOUT_SECONDS,
) -> str:
    """
    Call the text LLM (no image), via Bedrock. Retries once (TEXT_PRIMARY,
    then TEXT_FALLBACK — the same Bedrock model both times, see the module
    docstring) before giving up.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for model in [TEXT_PRIMARY, TEXT_FALLBACK]:
        try:
            result = _post_chat_completion(
                LLM_API_URL, _headers(), model, messages, temperature, max_tokens, timeout
            )
            logger.info(f"[LLM_CLIENT] text call OK — model={model}")
            return result
        except Exception as e:
            logger.warning(f"[LLM_CLIENT] {model} failed: {e}. Retrying…")
            time.sleep(2)

    raise RuntimeError("[LLM_CLIENT] All text model attempts failed")


def call_vision_llm(
    image_b64_url: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.1,
    timeout: int = DEFAULT_LLM_TIMEOUT_SECONDS,
) -> str:
    """
    Call the vision LLM with a base64-encoded image data-URL, via Bedrock.
    Retries once (VISION_PRIMARY, then VISION_FALLBACK — the same Bedrock
    model both times, see the module docstring) before giving up.
    """
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_b64_url}},
    ]
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    for model in [VISION_PRIMARY, VISION_FALLBACK]:
        try:
            result = _post_chat_completion(
                LLM_API_URL, _headers(), model, messages, temperature, max_tokens, timeout
            )
            logger.info(f"[LLM_CLIENT] vision call OK — model={model}")
            return result
        except Exception as e:
            logger.warning(f"[LLM_CLIENT] {model} failed: {e}. Retrying…")
            time.sleep(2)

    raise RuntimeError("[LLM_CLIENT] All vision model attempts failed")
