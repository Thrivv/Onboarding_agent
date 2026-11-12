# backend/app/api/routes/frontend_logs.py
# ============================================================================
# FRONTEND ERROR LOGGING — DigiOB Digital OnBoarding Platform
# ============================================================================
# POST /logs/frontend — receives client-side JS errors (window.onerror,
# unhandledrejection, React ErrorBoundary catches) and appends them as JSON
# lines to /var/log/frontend/frontend-errors.log (mounted to host at
# ./logs/frontend so they're visible outside the container, same as the
# nginx/backend logs).
#
# No auth required — errors can happen on public pages (login/signup)
# before a session exists. Rate-limited per IP to avoid a broken page from
# flooding the log with retries.
# ============================================================================

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app import config
from app.schemas.system import FrontendErrorRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["Frontend Logs"])
limiter = Limiter(key_func=get_remote_address)

# ── Dedicated file logger ────────────────────────────────────────────────────
# Separate from the app's root logger (which goes to stdout only) so these
# land in their own file. Directory is created defensively in case the
# volume mount / Dockerfile mkdir hasn't run (e.g. local dev outside Docker).
FRONTEND_LOG_DIR = config.FRONTEND_LOG_DIR
os.makedirs(FRONTEND_LOG_DIR, exist_ok=True)

frontend_logger = logging.getLogger("frontend_errors")
frontend_logger.setLevel(logging.INFO)
frontend_logger.propagate = False  # keep out of the main stdout stream

_log_path = os.path.join(FRONTEND_LOG_DIR, "frontend-errors.log")
_handler = RotatingFileHandler(_log_path, maxBytes=10 * 1024 * 1024, backupCount=5)
_handler.setFormatter(logging.Formatter("%(message)s"))
if not frontend_logger.handlers:
    frontend_logger.addHandler(_handler)


# ── Request model ─────────────────────────────────────────────────────────────


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/frontend")
@limiter.limit("30/minute")
async def log_frontend_error(request: Request, payload: FrontendErrorRequest):
    """Append a client-side error report to logs/frontend/frontend-errors.log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client_ip": request.client.host if request.client else "unknown",
        "source": payload.source or "unknown",
        "message": payload.message,
        "stack": payload.stack,
        "componentStack": payload.componentStack,
        "url": payload.url,
        "userAgent": payload.userAgent,
        "email": payload.email,
    }
    frontend_logger.info(json.dumps(entry, ensure_ascii=False))
    logger.info(f"[FRONTEND-ERROR] {payload.source or 'unknown'} @ {payload.url}: {payload.message[:200]}")

    return {"success": True}
