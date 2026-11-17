"""
app/services/llm_client.py
==========================
Centralized LLM client for ALL OpenRouter API calls.

SINGLE SOURCE OF TRUTH for model names and the OpenRouter endpoint. Every
value below comes from .env.docker, so a model can be swapped with a container
restart instead of a code change + rebuild. Do NOT re-declare model names in
individual extractors — import them from here.

Env vars (see the "LLM MODEL ROUTING" block in .env.docker):
    OPENROUTER_API_URL
    LLM_VISION_PRIMARY / LLM_VISION_FALLBACK   — EID, Passport (image based)
    LLM_TEXT_PRIMARY   / LLM_TEXT_FALLBACK     — Commercial, COI, MOA, Ejari,
                                                 BVI, and message generation

Usage
-----
  from app.services.llm_client import (
      TEXT_PRIMARY, TEXT_FALLBACK,
      VISION_PRIMARY, VISION_FALLBACK,
      OPENROUTER_API_URL,
      call_text_llm, call_vision_llm,
      is_identity_doc,
  )
"""

import time
import logging
import requests
from typing import Optional
from app import config

logger = logging.getLogger(__name__)

# ── API endpoint ─────────────────────────────────────────────────────────────
OPENROUTER_API_URL = config.OPENROUTER_API_URL

# ── Default per-model call timeout ───────────────────────────────────────────
# Configurable via LLM_CALL_TIMEOUT_SECONDS in .env.docker — change + restart
# the container to raise/lower without editing code. Previously hardcoded at
# 120s per model; call_text_llm/call_vision_llm each try 2 models in sequence,
# so a hung primary could take up to 2x this before falling back. Lowered
# default to 45s so a stuck call fails over to the fallback model (and,
# further up the stack, to the fallback template text) much faster.
DEFAULT_LLM_TIMEOUT_SECONDS = config.LLM_CALL_TIMEOUT_SECONDS

# ── Vision models  (EID / Passport only) ─────────────────────────────────────
# Default is qwen2.5-vl-72b, matching what ocr_service has actually been using.
# The previous hardcoded default here was meta-llama/llama-3.2-11b-vision-instruct,
# which ocr_service had already abandoned with the note "llama-3.2-11b returning
# 404" — it survived only because nothing outside this module imported it.
VISION_PRIMARY  = config.LLM_VISION_PRIMARY
VISION_FALLBACK = config.LLM_VISION_FALLBACK

# ── Text models  (Commercial, COI, MOA, Ejari, BVI, everything else) ─────────
TEXT_PRIMARY    = config.LLM_TEXT_PRIMARY
TEXT_FALLBACK   = config.LLM_TEXT_FALLBACK

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
    key = config.OPENROUTER_API_KEY or ""
    if not key:
        raise ValueError("[LLM_CLIENT] OPENROUTER_API_KEY is not set")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


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
    Call a text-only LLM (no image).
    Tries TEXT_PRIMARY first, falls back to TEXT_FALLBACK automatically.
    """
    for model in [TEXT_PRIMARY, TEXT_FALLBACK]:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            resp = requests.post(
                OPENROUTER_API_URL,
                headers=_headers(),
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
            # A 200 response with a null/empty completion (seen under
            # concurrent load — see ocr_service.call_api_with_retry for the
            # same failure mode) used to be returned as-is here, silently
            # skipping the fallback model below. Treat it as a failure so it
            # falls through to the next model in the loop instead.
            if not result or not result.strip():
                raise RuntimeError(f"{model} returned empty/null completion content")
            logger.info(f"[LLM_CLIENT] text call OK — model={model}")
            return result
        except Exception as e:
            logger.warning(f"[LLM_CLIENT] {model} failed: {e}. Trying fallback…")
            time.sleep(2)

    raise RuntimeError("[LLM_CLIENT] All text models failed")


def call_vision_llm(
    image_b64_url: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.1,
    timeout: int = DEFAULT_LLM_TIMEOUT_SECONDS,
) -> str:
    """
    Call a vision LLM with a base64-encoded image data-URL.
    Tries VISION_PRIMARY first, falls back to VISION_FALLBACK automatically.
    """
    for model in [VISION_PRIMARY, VISION_FALLBACK]:
        try:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_b64_url}},
            ]
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": content})

            resp = requests.post(
                OPENROUTER_API_URL,
                headers=_headers(),
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
            # Same empty-content guard as call_text_llm above — see its comment.
            if not result or not result.strip():
                raise RuntimeError(f"{model} returned empty/null completion content")
            logger.info(f"[LLM_CLIENT] vision call OK — model={model}")
            return result
        except Exception as e:
            logger.warning(f"[LLM_CLIENT] {model} failed: {e}. Trying fallback…")
            time.sleep(2)

    raise RuntimeError("[LLM_CLIENT] All vision models failed")
