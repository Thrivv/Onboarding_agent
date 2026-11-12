"""
app/services/bedrock_client.py
===============================
Single place that talks to AWS Bedrock. Replaces OpenRouter as the transport
for every LLM call in this app (document extraction, vision OCR, and
onboarding chat/message generation).

Why a drop-in `post()` instead of rewriting every call site
-------------------------------------------------------------
Every LLM call site in this codebase (llm_client.py, ocr_service.py, the
specialized_ocr extractors, and tampering/services/llm_service.py) already
builds an OpenAI-style chat-completions payload —
    {"model": ..., "messages": [...], "temperature": ..., "max_tokens": ...}
— and posts it with `requests.post(url, headers=headers, json=payload,
timeout=timeout)`, then reads the reply back as
`response.json()["choices"][0]["message"]["content"]`.

`post()` below matches that exact call signature and response shape, so
every call site only has to swap its `requests.post(...)` for
`bedrock_client.post(...)` — nothing about payload construction, retry
loops, or response parsing at the call sites needs to change. Internally it:
  1. translates the OpenAI-style payload into Bedrock's Anthropic Messages
     format (pulls any system-role message out to the top-level `system`
     field, converts `image_url` data-URL blocks to Bedrock's base64 image
     blocks),
  2. calls the Bedrock Anthropic Messages "invoke" endpoint using the
     AWS_BEARER_TOKEN_BEDROCK API key (Bedrock API keys — not IAM
     credentials/SigV4), and
  3. hands back a small object that responds to .status_code / .json() /
     .raise_for_status() / .text like a requests.Response, so existing
     status-code checks (429/500/502/503/504 retry logic, etc.) keep
     working unchanged.

Model + region
--------------
This migration uses a single model for every task (chat, text extraction,
and vision extraction) — Claude Haiku via Bedrock's cross-region "global"
inference profile, in ap-south-1 (Mumbai), matching the reference
implementation this was adapted from. The incoming `model` field in the
OpenAI-style payload is accepted (for call-site compatibility) but ignored:
Bedrock selects the model from the invoke URL, not a request field.
"""

import os
import re
import time
import json as _json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── Auth ─────────────────────────────────────────────────────────────────────
# Read lazily (at call time, not import time) so this doesn't care whether
# app.config (which loads .env.docker via python-dotenv for local/non-Docker
# runs) has already been imported first — in the real deployment, Docker
# Compose's env_file already puts this straight into the process environment
# before Python even starts, so this only matters for ad-hoc local runs.
def _token() -> str:
    return os.getenv("AWS_BEARER_TOKEN_BEDROCK") or ""


# ── Model + endpoint ─────────────────────────────────────────────────────────
REGION = "ap-south-1"
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
INVOKE_URL = f"https://bedrock-runtime.{REGION}.amazonaws.com/model/{MODEL_ID}/invoke"


def _invoke_url_for(model_id: str) -> str:
    return f"https://bedrock-runtime.{REGION}.amazonaws.com/model/{model_id}/invoke"


def _resolve_invoke_url(requested_model: Optional[str]) -> str:
    """
    Model tiering (prompt-remediation Phase 2). Every call site still sends
    a "model" field in its OpenAI-style payload -- historically ignored
    entirely (see the module docstring's "single model for every task"
    note). It is now honoured for exactly one case: config.
    MODEL_TIERING_ENABLED is on AND the requested model is
    config.BEDROCK_REASONING_MODEL_ID (currently requested only by
    trade_extractor.py and moa_extractor.py). Every other requested value
    -- including the same MODEL_ID, the generic TEXT_PRIMARY/VISION_PRIMARY
    placeholders, or anything else -- still resolves to the default
    INVOKE_URL exactly as before, so this is a no-op change unless a
    caller explicitly opts in.
    """
    from app import config  # local import: avoids a hard import-time
                             # dependency from this low-level client module
                             # on app.config for every caller that doesn't
                             # need tiering
    if (
        config.MODEL_TIERING_ENABLED
        and requested_model
        and requested_model == config.BEDROCK_REASONING_MODEL_ID
    ):
        return _invoke_url_for(requested_model)
    return INVOKE_URL

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)


def _bedrock_headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _convert_content(content):
    """
    Convert one OpenAI-style message `content` value — either a plain string
    or a list of {"type": "text"/"image_url", ...} blocks — into Bedrock's
    Anthropic content-block list.
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks = []
    for part in content:
        part_type = part.get("type")
        if part_type == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif part_type == "image_url":
            url = part.get("image_url", {}).get("url", "")
            match = _DATA_URL_RE.match(url)
            if not match:
                raise ValueError(
                    "bedrock_client: image_url content must be a base64 "
                    "data: URL — Bedrock's Anthropic Messages API does not "
                    "accept a plain image URL."
                )
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": match.group("mime"),
                    "data": match.group("data"),
                },
            })
        else:
            raise ValueError(f"bedrock_client: unsupported content block type {part_type!r}")
    return blocks


def _to_bedrock_payload(openai_payload: dict) -> dict:
    messages = openai_payload.get("messages") or []
    system_text = None
    bedrock_messages = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            # Bedrock takes one top-level `system` string, not a
            # system-role message in the list. Concatenate if more than one
            # ever shows up (no call site currently sends more than one).
            piece = content
            if isinstance(piece, list):
                piece = "".join(b.get("text", "") for b in piece if b.get("type") == "text")
            system_text = piece if system_text is None else f"{system_text}\n{piece}"
            continue
        bedrock_messages.append({"role": role, "content": _convert_content(content)})

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": openai_payload.get("max_tokens") or 4096,
        "temperature": openai_payload.get("temperature", 0.1),
        "messages": bedrock_messages,
    }
    if system_text:
        # Ephemeral prompt caching on the system prompt — same as the
        # reference implementation this was adapted from.
        payload["system"] = [
            {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
        ]
    return payload


class _BedrockResponse:
    """Just enough of `requests.Response` for existing call sites to keep working."""

    def __init__(self, status_code: int, raw_json: Optional[dict], raw_text: str):
        self.status_code = status_code
        self._raw_json = raw_json
        self.text = raw_text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} error from Bedrock: {self.text}"
            )

    def json(self):
        if self._raw_json is not None:
            return self._raw_json
        return _json.loads(self.text)


def check_connection(timeout: int = 6) -> dict:
    """
    Real, minimal connectivity check for the Dashboard's "AWS Bedrock"
    status indicator — NOT wired into Docker's /health (that endpoint is
    polled frequently by the container orchestrator; a live per-poll
    Bedrock call would add cost, latency, and a false "unhealthy/restart"
    signal on a transient Bedrock hiccup that has nothing to do with this
    container's own health). This is called on demand instead, from the
    dashboard's own status endpoint.

    Sends the smallest possible real request — a 1-token completion for a
    single "ping" message — so a genuine auth/network/model failure is
    caught, not just "is the URL reachable".

    Returns:
        {"connected": bool, "detail": str, "latency_ms": int | None}
    """
    if not _token():
        return {
            "connected": False,
            "detail": "AWS_BEARER_TOKEN_BEDROCK is not set",
            "latency_ms": None,
        }

    ping_payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
    }

    started = time.monotonic()
    try:
        resp = requests.post(
            INVOKE_URL, headers=_bedrock_headers(), json=ping_payload, timeout=timeout
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        if resp.status_code == 200:
            return {"connected": True, "detail": "ok", "latency_ms": latency_ms}

        return {
            "connected": False,
            "detail": f"Bedrock returned {resp.status_code}: {resp.text[:200]}",
            "latency_ms": latency_ms,
        }
    except requests.exceptions.Timeout:
        return {
            "connected": False,
            "detail": f"Timed out after {timeout}s",
            "latency_ms": None,
        }
    except requests.exceptions.RequestException as e:
        return {"connected": False, "detail": str(e)[:200], "latency_ms": None}


def post(url=None, headers=None, json=None, timeout=60):
    """
    Drop-in replacement for
        requests.post(url, headers=headers, json=payload, timeout=timeout)
    for every LLM chat-completion call in this app.

    `url` and `headers` are accepted for call-site compatibility (every
    caller still builds and passes them) but ignored — Bedrock's endpoint
    and auth are fixed above, and are not configurable per-call the way
    OpenRouter's were.
    """
    if not _token():
        raise ValueError("[BEDROCK_CLIENT] AWS_BEARER_TOKEN_BEDROCK is not set")

    bedrock_payload = _to_bedrock_payload(json or {})
    requested_model = (json or {}).get("model")
    invoke_url = _resolve_invoke_url(requested_model)

    resp = requests.post(
        invoke_url, headers=_bedrock_headers(), json=bedrock_payload, timeout=timeout
    )

    # Model tiering (Phase 2): a reasoning-tier call that fails (wrong or
    # unavailable model id, access denied, region mismatch, etc.) falls
    # back to the default model automatically, in this one place, rather
    # than requiring every caller that opts into tiering to implement its
    # own dual-model retry. This can only add a fallback attempt on top of
    # what already worked before tiering existed -- it never removes one.
    if resp.status_code != 200 and invoke_url != INVOKE_URL:
        logger.warning(
            f"[BEDROCK_CLIENT] reasoning-tier model call failed "
            f"({resp.status_code}), retrying with default model"
        )
        resp = requests.post(
            INVOKE_URL, headers=_bedrock_headers(), json=bedrock_payload, timeout=timeout
        )

    if resp.status_code != 200:
        return _BedrockResponse(resp.status_code, None, resp.text)

    data = resp.json()
    content_blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

    openai_shape = {
        "choices": [{"message": {"content": text}}],
        "usage": {
            "input_tokens": (data.get("usage") or {}).get("input_tokens"),
            "output_tokens": (data.get("usage") or {}).get("output_tokens"),
        },
    }
    return _BedrockResponse(200, openai_shape, resp.text)
