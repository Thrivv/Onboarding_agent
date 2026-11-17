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
  * Nothing was validated at startup. A missing OPENROUTER_API_KEY surfaced as
    a confusing 401 in the middle of a customer's onboarding rather than as a
    clear error at boot.

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
PASSWORD_SECRET_KEY = env_str("PASSWORD_SECRET_KEY", "mysecretkeyforhashing1234")

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
# LLM / OpenRouter   ── see INCONSISTENT DEFAULTS
# ============================================================================
# Exposed raw: consumers previously used "" , None, or the placeholder string
# "sk-or-v1-..." as the fallback. The placeholder is NOT a real credential —
# it is a 12-character redaction — but it does mean a missing key surfaces as
# a 401 from OpenRouter rather than a clear configuration error.
OPENROUTER_API_KEY = env_str("OPENROUTER_API_KEY")
OPENROUTER_API_URL = env_str(
    "OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions"
)
LLM_VISION_PRIMARY = env_str("LLM_VISION_PRIMARY", "qwen/qwen2.5-vl-72b-instruct")
LLM_VISION_FALLBACK = env_str("LLM_VISION_FALLBACK", "qwen/qwen-2.5-vl-7b-instruct")
LLM_TEXT_PRIMARY = env_str("LLM_TEXT_PRIMARY", "meta-llama/llama-3.3-70b-instruct")
LLM_TEXT_FALLBACK = env_str("LLM_TEXT_FALLBACK", "qwen/qwen-2.5-72b-instruct")
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
GROWX_BASE_URL = env_str("GROWX_BASE_URL", "https://demo.growx.global")
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
# STARTUP VALIDATION
# ============================================================================
# Keys without which a user-facing feature silently fails. These were NEVER
# validated before, so they are reported as warnings rather than raised — the
# rule for this refactor is that nothing which used to boot may stop booting.
_IMPORTANT_KEYS: tuple[tuple[str, str], ...] = (
    ("OPENROUTER_API_KEY", "document extraction and all AI-generated messages"),
    ("SMTP_SERVER", "outbound email (verification, completion, OTP)"),
    ("SMTP_USERNAME", "outbound email authentication"),
    ("SMTP_PASSWORD", "outbound email authentication"),
    ("FROM_EMAIL", "outbound email sender address"),
    ("IMAP_HOST", "the reply-loop container's inbound email polling"),
    ("IMAP_USER", "the reply-loop container's inbound email polling"),
    ("IMAP_PASSWORD", "the reply-loop container's inbound email polling"),
    ("GROWX_BASE_URL", "GrowX submission"),
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
    return missing
