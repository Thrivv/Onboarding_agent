# backend/app/config.py
"""
Single source of truth for every environment variable this application reads.

Before this module was expanded, configuration was read with 63 separate
``os.getenv()`` calls spread across 20 modules. That had three consequences:

  * No one place showed what the app needs to run. ``.env.docker`` had 44
    variables and nothing tied them to the code that consumed them.
  * The same key was read with **different defaults in different modules**, so
    behaviour depended on which module happened to do the lookup (see
    INCONSISTENT DEFAULTS below).
  * Nothing was validated at startup. A missing OPENROUTER_API_KEY (now
    AWS_BEARER_TOKEN_BEDROCK) surfaced as a confusing 401/403 in the middle of
    a customer's onboarding rather than as a clear error at boot.

Design notes
------------
1. **Backward compatible.** The module-level names that existed before
   (``SUPABASE_URL``, ``SUPABASE_API_KEY``, ``PASSWORD_SECRET_KEY``,
   ``SMTP_*``, ``FROM_EMAIL``) are still exported with identical values, so
   ``from app.config import PASSWORD_SECRET_KEY`` keeps working.

2. **Import-time failure is preserved exactly.** Missing Supabase credentials
   raised ``ValueError`` at import before, and still do. Nothing that used to
   boot has been made to refuse to boot — keys that were never validated are
   reported by :func:`validate_startup_config` as warnings, not failures.

3. **Where modules disagreed on a default, the disagreement is preserved at
   the call site.** Those keys are exposed here raw (no default) and each
   consumer keeps its own explicit fallback. Collapsing them to one value would
   have silently changed behaviour for whichever module lost. They are listed
   under INCONSISTENT DEFAULTS for a deliberate decision later.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()  # Load from .env file in project root (if present)

# Fallback: this repo doesn't check in a backend/.env — real values (incl.
# SUPABASE_URL / SUPABASE_API_KEY) live in the repo-root .env.docker, which
# Docker Compose normally injects. When running the backend locally/outside
# Docker, load it here too so config doesn't blow up with missing creds.
_repo_root_env_docker = Path(__file__).resolve().parents[2] / ".env.docker"
if _repo_root_env_docker.exists():
    load_dotenv(_repo_root_env_docker, override=False)


# ── typed readers ────────────────────────────────────────────────────────────
def env_str(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"{key}={raw!r} is not an integer — using default {default}")
        return default


def env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"{key}={raw!r} is not a number — using default {default}")
        return default


def env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


# ============================================================================
# CORE — Supabase
# ============================================================================
SUPABASE_URL = env_str("SUPABASE_URL")
SUPABASE_API_KEY = env_str("SUPABASE_API_KEY")
SUPABASE_SERVICE_ROLE_KEY = env_str("SUPABASE_SERVICE_ROLE_KEY")

# Preserved verbatim from the original module — this is the ONLY hard failure
# at import time, and it behaved this way before.
if not SUPABASE_URL or not SUPABASE_API_KEY:
    raise ValueError("Supabase credentials are not set in the .env file")

# ============================================================================
# SECURITY
# ============================================================================
# Pepper mixed into every password hash (see app/services/auth_service.py).
# This USED to default to the hardcoded, publicly-visible string
# "mysecretkeyforhashing1234" when the env var was unset — meaning a missing
# PASSWORD_SECRET_KEY silently downgraded every account's password protection
# to a known value, with no error and no log line. Treated the same as the
# Supabase credentials above: a hard failure at import time is the correct
# behaviour for a secret this load-bearing. Generate one with, e.g.:
#     openssl rand -hex 32
PASSWORD_SECRET_KEY = env_str("PASSWORD_SECRET_KEY")
if not PASSWORD_SECRET_KEY:
    raise ValueError(
        "PASSWORD_SECRET_KEY is not set. This is the pepper mixed into every "
        "stored password hash — it must be a long random secret, not a "
        "default. Set it in your environment before starting the app "
        "(e.g. `openssl rand -hex 32`)."
    )

# httpOnly session cookie name + attributes (see app/api/routes/auth.py).
# SESSION_COOKIE_SECURE defaults to True — only disable it (via env) for a
# plain-HTTP local dev setup, never in anything reachable over the network.
SESSION_COOKIE_NAME = env_str("SESSION_COOKIE_NAME", "session_id")
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
SESSION_COOKIE_SAMESITE = env_str("SESSION_COOKIE_SAMESITE", "lax")

# TEST-ENVIRONMENT ONLY. When true, email_otp_service.verify_otp() accepts
# ANY 6-digit numeric input instead of checking it against the code that was
# actually generated and emailed — so QA/local testing isn't blocked on
# receiving real emails. Defaults to False so any deployment that doesn't
# explicitly opt in stays secure. NEVER set this true anywhere a real user
# can reach: with it on, anyone who knows a target's email address can
# "verify" that email or complete a password reset without ever receiving
# the OTP that was supposedly required.
OTP_BYPASS_ENABLED = env_bool("OTP_BYPASS_ENABLED", False)
if OTP_BYPASS_ENABLED:
    logger.warning(
        "[CONFIG] OTP_BYPASS_ENABLED=true — verify_otp() will accept ANY "
        "6-digit code. This must ONLY be set in an isolated test/QA "
        "environment, never anywhere real users can reach."
    )

# OTP EMAIL CONTENT — off by default (prompt-remediation Phase 1, item #2).
# email_otp_service._generate_email_content_via_llm() used to build the
# verification-email prompt by interpolating the LIVE 6-digit OTP and the
# recipient's real email address directly into the text sent to the model —
# a bearer-secret credential leaving the process boundary into an LLM
# provider purely so the model could phrase a paragraph around it, with the
# subject/body parsed back out of free-form text via a brittle
# "SUBJECT:"/"BODY:" convention. The OTP has no legitimate reason to ever
# reach the model: the hardcoded template in _fallback_email_content()
# already renders it correctly. That template is now the default path.
# This flag opts BACK IN to LLM-authored email copy, but only through
# _generate_email_copy_via_llm(), which asks the model to write around a
# placeholder token and substitutes the real OTP in afterwards — the digits
# and the recipient address never appear in the prompt sent upstream.
OTP_EMAIL_LLM_PERSONALIZATION_ENABLED = env_bool("OTP_EMAIL_LLM_PERSONALIZATION_ENABLED", False)

# BRAND NAME — the single product identity every LLM prompt uses when it
# names the assistant to the customer (prompt-remediation Phase 1, item #3).
#
# Before this setting existed, four different names were hardcoded across
# LLM prompts with no shared source of truth: "MyBank" (message_generator.py,
# enforced by its own post-hoc regex correction), "DigiOB" (onboarding_chat_
# service.py, handle_reply.py, document_messaging.py -- "Digital OnBoarding"
# spelled out, evidently a generic placeholder that was never replaced),
# "Thrivv Bank" (conversation.py, document_expiry_validator.py, and the
# dead chat.py::build_chat_prompt), and "Thrivv"/"Thrivv.ai" -- which is
# also the ONLY one of the four with independent confirmation elsewhere in
# the repo: frontend/package.json ("thrivv-onboarding-frontend"),
# frontend/public/manifest.json ("Thrivv.ai Onboarding Agent"), and
# frontend/public/index.html's <title>. That makes "Thrivv" the default
# here, not a guess -- it is what the product's own frontend already calls
# itself. Every prompt that used to hardcode one of the other three names
# now reads BRAND_NAME instead, so they can never disagree with each other
# or with the frontend again. Override per-deployment (e.g. a white-labeled
# bank client) by setting BRAND_NAME in the environment -- nothing else
# needs to change.
BRAND_NAME = env_str("BRAND_NAME", "Thrivv") or "Thrivv"

# Multilingual chat/UI kill switch (.env.docker). When true (default), users
# can toggle between English, Arabic and Spanish everywhere the language
# toggle appears. When false, the frontend hides the toggle and locks to
# English, and the backend also refuses any non-English `language` value
# server-side (see app/utils/language.py's normalize_language()) so the
# restriction can't be bypassed by a stale client or a direct API call.
# Flip this and restart the `app` container — no rebuild needed, since it's
# read at runtime, not baked into the frontend build.
LANGUAGE_TOGGLE_ENABLED = env_bool("LANGUAGE_TOGGLE_ENABLED", True)

# TEXTRACT AnalyzeID — off by default (prompt-remediation Phase 1, item #4).
# When true, specialized_ocr/passport_extractor.py tries Amazon Textract's
# AnalyzeID API first for passport pages -- structured field extraction
# that never sends the document image to a third-party LLM provider -- and
# only falls back to the existing vision-LLM call if Textract is
# unavailable or its result is missing a mandatory field (see
# app/services/textract_id_client.py for the full design and its coverage
# caveat re: UAE Emirates ID). Defaults to False so this ships mergeable
# in any environment, including ones without Textract IAM permissions
# configured -- turning it on requires nothing else in code, only this
# flag plus working AWS credentials for the textract:AnalyzeID action.
TEXTRACT_ANALYZE_ID_ENABLED = env_bool("TEXTRACT_ANALYZE_ID_ENABLED", False)

# MODEL TIERING — off by default (prompt-remediation Phase 2). The app
# currently sends every task (chat, message generation, and all five
# document extractors) to the same single Bedrock model
# (bedrock_client.MODEL_ID, Claude Haiku). dumps/docs/bedrock-final-
# recommendation.md's own analysis (Section 3) singles out Trade License
# and MOA extraction as the two tasks with real multi-step reasoning load
# (UBO/ownership-structure inference, bilingual EN/AR structured
# extraction) where a stronger model is the most justified place to spend
# more per call -- and explicitly recommends validating on real documents
# before trusting a stronger model as primary (its own roadmap, Section
# 10), which is exactly what an opt-in flag is for.
#
# When enabled, trade_extractor.py and moa_extractor.py request
# BEDROCK_REASONING_MODEL_ID instead of the default Haiku model.
# bedrock_client.post() resolves the matching invoke URL for that model id
# and automatically retries against the default (Haiku) model if the
# reasoning-tier call itself fails (wrong/unavailable model id, access
# denied, etc.) — so turning this on can only add a fallback attempt, never
# remove the one that already works today.
MODEL_TIERING_ENABLED = env_bool("MODEL_TIERING_ENABLED", False)

# Bedrock cross-region "global" inference profile id for the reasoning-tier
# model. Defaults to Claude Sonnet 4.5's published Bedrock id, following
# the exact naming pattern of the Haiku id already hardcoded in
# bedrock_client.py (global.anthropic.claude-haiku-4-5-20251001-v1:0) --
# see AWS's Sonnet 4.5-on-Bedrock announcement referenced in
# dumps/docs/architecture/bedrock-claude-pii-json-storage.md. This default
# is NOT verified against a live Bedrock model-list call from this
# environment; confirm it resolves in your account/region before turning
# MODEL_TIERING_ENABLED on, or override it here if AWS's exact id differs.
BEDROCK_REASONING_MODEL_ID = env_str(
    "BEDROCK_REASONING_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

# ============================================================================
# API SURFACE
# ============================================================================
API_BASE_PATH = (env_str("API_BASE_PATH", "/onboarding/ai/api") or "").rstrip("/")
ALLOWED_ORIGINS = env_str("ALLOWED_ORIGINS", "")
LOG_LEVEL = (env_str("LOG_LEVEL", "INFO") or "INFO").upper()

# ============================================================================
# SMTP / EMAIL   ── see INCONSISTENT DEFAULTS
# ============================================================================
# Exposed raw (no default) because config.py and email_sender.py used None
# while email_otp_service.py used "smtp.gmail.com" / "". Each consumer keeps
# its own fallback so behaviour is unchanged.
SMTP_SERVER = env_str("SMTP_SERVER")
SMTP_PORT = env_int("SMTP_PORT", 587)
SMTP_USERNAME = env_str("SMTP_USERNAME")
SMTP_PASSWORD = env_str("SMTP_PASSWORD")
FROM_EMAIL = env_str("FROM_EMAIL")

# IMAP — inbound reply listener (reply-loop container)
IMAP_HOST = env_str("IMAP_HOST")
IMAP_PORT = env_int("IMAP_PORT", 993)
IMAP_USER = env_str("IMAP_USER")
IMAP_PASSWORD = env_str("IMAP_PASSWORD")

# ============================================================================
# LLM — AWS Bedrock
# ============================================================================
# Every model call in the app (document extraction, vision OCR, and
# onboarding chat/message generation) goes through AWS Bedrock's Anthropic
# Messages API, authenticated with a Bedrock API key (bearer token), not IAM
# credentials. app/services/bedrock_client.py is the single place that builds
# the Bedrock request; app/services/llm_client.py is the shared call helper
# everything else imports. Model ID and region are fixed in
# bedrock_client.py rather than read from here.
#
# There is only one provider and one model now, so the old two-provider
# fallback (OpenRouter primary/fallback models, plus an optional independent
# SECONDARY_LLM_* provider for when OpenRouter itself was down) has been
# removed rather than pointed at Bedrock — a single-provider outage isn't
# something a second env-configured provider fixes, and it added retry-loop
# complexity that no longer reflects how this app calls its LLM.
AWS_BEARER_TOKEN_BEDROCK = env_str("AWS_BEARER_TOKEN_BEDROCK")
LLM_CALL_TIMEOUT_SECONDS = env_int("LLM_CALL_TIMEOUT_SECONDS", 45)
MESSAGE_GEN_MAX_RETRIES = env_int("MESSAGE_GEN_MAX_RETRIES", 2)

# ============================================================================
# DOCUMENT EXTRACTION
# ============================================================================
DOC_EXTRACTION_MAX_RETRIES = env_int("DOC_EXTRACTION_MAX_RETRIES", 3)
EJARI_API_TIMEOUT_SECONDS = env_int("EJARI_API_TIMEOUT_SECONDS", 60)
MOA_API_TIMEOUT_SECONDS = env_int("MOA_API_TIMEOUT_SECONDS", 60)
TRADE_LICENSE_API_TIMEOUT_SECONDS = env_int("TRADE_LICENSE_API_TIMEOUT_SECONDS", 60)
BVI_API_TIMEOUT_SECONDS = env_int("BVI_API_TIMEOUT_SECONDS", 90)
PASSPORT_API_TIMEOUT_SECONDS = env_int("PASSPORT_API_TIMEOUT_SECONDS", 60)

# ============================================================================
# STORAGE PATHS
# ============================================================================
DOCUMENTS_PATH = env_str("DOCUMENTS_PATH")
EXTERNAL_FILE_PATH = env_str("EXTERNAL_FILE_PATH")
USER_DOCS_BASE = env_str("USER_DOCS_BASE", "/tmp/user_docs")
FRONTEND_LOG_DIR = env_str("FRONTEND_LOG_DIR", "/var/log/frontend")

# ============================================================================
# CROSS-VALIDATION
# ============================================================================
CROSS_VALIDATION_CORPORATE_SINGLE = env_bool("CROSS_VALIDATION_CORPORATE_SINGLE", True)
CROSS_VALIDATION_CORPORATE_PARTNERSHIP = env_bool(
    "CROSS_VALIDATION_CORPORATE_PARTNERSHIP", False
)
CROSS_VALIDATION_DEBUG_LOGGING = env_bool("CROSS_VALIDATION_DEBUG_LOGGING", True)
FUZZY_MATCH_THRESHOLD = env_float("FUZZY_MATCH_THRESHOLD", 0.85)

# EID / SurePass. The two EID_VALIDATION_* keys are read dynamically by
# eid_validation.py (the key name is chosen from account_type + ownership_type),
# so they stay a runtime lookup there — they are listed here for discoverability
# and for .env.example generation.
SUREPASS_JWT_TOKEN = env_str("SUREPASS_JWT_TOKEN", "")
SUREPASS_API_URL = env_str("SUREPASS_API_URL")
EID_VALIDATION_KEYS = (
    "EID_VALIDATION_CORPORATE_SINGLE",
    "EID_VALIDATION_CORPORATE_PARTNERSHIP",
)

# ============================================================================
# EXTERNAL INTEGRATIONS
# ============================================================================
# API_BASE_URL: email_sender defaults to http://localhost:7000; handle_reply
# reads it with no default because it falls back to public-IP auto-detection.
# Left raw so that logic is untouched.
API_BASE_URL = env_str("API_BASE_URL")

# ============================================================================
# RUNTIME
# ============================================================================
UVICORN_WORKERS = env_int("UVICORN_WORKERS", 1)
SESSION_TIMEOUT = env_int("SESSION_TIMEOUT", 3600)
INACTIVITY_THRESHOLD_MINUTES = env_int("INACTIVITY_THRESHOLD_MINUTES", 30)
SESSION_TOKEN_EXPIRY_HOURS = env_int("SESSION_TOKEN_EXPIRY_HOURS", 24)

# ============================================================================
# ORCHESTRATION — LangGraph
# ============================================================================
# Migration stages, see docs/langgraph-migration/. Off by default: every
# stage up to and including the channel cutover (Stage 11) is written behind
# this flag, so a deployment that never sets it sees no behaviour change at
# all — same rule the rest of this module follows for anything load-bearing.
#
# LANGGRAPH_PG_DSN is the direct Postgres connection string for the
# checkpointer (Project Settings -> Database -> Connection string in
# Supabase — NOT the SUPABASE_URL/SUPABASE_API_KEY REST credentials above,
# which cannot be used for a raw Postgres connection). Only required once
# Stage 9 is reached; earlier stages run the graph with an in-memory
# checkpointer and never read this value.
LANGGRAPH_ENABLED = env_bool("LANGGRAPH_ENABLED", False)
LANGGRAPH_PG_DSN = env_str("LANGGRAPH_PG_DSN")

# PII log masking — kill switch for app/utils/pii_masker.py's use in log
# lines that print extracted document fields (preview.py, normalizer.py,
# core.py, conversation.py). Defaults on; set to false only to temporarily
# restore raw logging while debugging an extraction issue.
PII_LOG_MASKING_ENABLED = env_bool("PII_LOG_MASKING_ENABLED", True)

# Stage 11 — a second, independent gate on top of LANGGRAPH_ENABLED. With
# only LANGGRAPH_ENABLED=true, the graph package runs in shadow mode only
# (graph/build.py compiles, stages.py's get_onboarding_status() cross-checks
# routing/pending decisions against it and logs any drift — see Stage 10 —
# but nothing user-facing is ever driven by the graph's answer). Flipping
# THIS flag on top is what lets `graph/channel_cutover.py`'s resume hook in
# conversation.py / handle_reply.py actually resume a paused graph thread
# instead of falling through to the legacy handler for a given request.
# Kept separate deliberately: a deployment can run shadow-mode comparison
# in production for as long as it wants — building confidence beyond the
# synthetic 14,688-case corpus in tests/langgraph_parity_check.py before
# ever letting the graph make a real decision — without also opting into
# the cutover the moment it enables the checkpointer.
LANGGRAPH_CHANNEL_CUTOVER = env_bool("LANGGRAPH_CHANNEL_CUTOVER", False)


# ============================================================================
# STARTUP VALIDATION
# ============================================================================
# Keys without which a user-facing feature silently fails. These were NEVER
# validated before, so they are reported as warnings rather than raised — the
# rule for this refactor is that nothing which used to boot may stop booting.
_IMPORTANT_KEYS: tuple[tuple[str, str], ...] = (
    ("AWS_BEARER_TOKEN_BEDROCK", "document extraction, vision OCR, and all AI-generated messages"),
    ("SMTP_SERVER", "outbound email (verification, completion, OTP)"),
    ("SMTP_USERNAME", "outbound email authentication"),
    ("SMTP_PASSWORD", "outbound email authentication"),
    ("FROM_EMAIL", "outbound email sender address"),
    ("IMAP_HOST", "the reply-loop container's inbound email polling"),
    ("IMAP_USER", "the reply-loop container's inbound email polling"),
    ("IMAP_PASSWORD", "the reply-loop container's inbound email polling"),
)


def validate_startup_config() -> list[str]:
    """
    Log a warning for every important-but-unset key. Returns the missing keys.

    Called from both entrypoints so a misconfigured deployment announces itself
    at boot instead of halfway through a customer's onboarding.
    """
    missing = [key for key, _ in _IMPORTANT_KEYS if not os.getenv(key)]
    if missing:
        logger.warning("=" * 70)
        logger.warning("CONFIGURATION: %d important variable(s) are not set", len(missing))
        for key, purpose in _IMPORTANT_KEYS:
            if key in missing:
                logger.warning("  %-24s -> %s will not work", key, purpose)
        logger.warning("=" * 70)
    else:
        logger.info("[CONFIG] All important environment variables are set")

    # Conditional on LANGGRAPH_ENABLED rather than in _IMPORTANT_KEYS above —
    # unlike every other entry there, this one is only load-bearing once the
    # LangGraph migration reaches Stage 9 (the Postgres checkpointer). A
    # deployment with the flag off should not see a warning for a variable
    # it has no reason to set yet.
    if LANGGRAPH_ENABLED and not LANGGRAPH_PG_DSN:
        logger.warning(
            "[CONFIG] LANGGRAPH_ENABLED=true but LANGGRAPH_PG_DSN is not set — "
            "the onboarding graph has no durable checkpointer and will lose all "
            "in-flight state on restart."
        )

    if LANGGRAPH_CHANNEL_CUTOVER and not LANGGRAPH_ENABLED:
        logger.warning(
            "[CONFIG] LANGGRAPH_CHANNEL_CUTOVER=true but LANGGRAPH_ENABLED=false — "
            "the cutover flag has no effect until LANGGRAPH_ENABLED is also true."
        )
    if LANGGRAPH_CHANNEL_CUTOVER and not LANGGRAPH_PG_DSN:
        logger.warning(
            "[CONFIG] LANGGRAPH_CHANNEL_CUTOVER=true but LANGGRAPH_PG_DSN is not "
            "set — real users would be resumed against an in-memory checkpointer "
            "that loses their paused state on every restart. Set LANGGRAPH_PG_DSN "
            "before enabling the cutover outside of local testing."
        )

    return missing
