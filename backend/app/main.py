# backend/app/main.py

from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import traceback
import time
import uuid

# ============================================================================
# LOGGING — must be configured BEFORE the route modules are imported
# ============================================================================
# The setup itself lives in app/logging_config.py so that BOTH entrypoints can
# use it — this API process and the reply-loop process launched by
# docker-compose as `python -m app.services.reply_loop`, which never imports
# this module and therefore previously had no logging configuration at all.
# See the docstring there for the full explanation.
#
# ORDER MATTERS, and this is deliberate rather than stylistic. logging.basicConfig()
# is a no-op once the root logger already has handlers. The route imports below
# pull in app/services/specialized_ocr/trade_extractor.py, which used to call
# basicConfig() itself at import time. Because those imports previously sat
# ABOVE this block, trade_extractor won the race and configured root logging
# for the entire application — which is why production logs showed
# "[INFO] <message>" with no timestamp, no logger name and no [request_id],
# instead of the format configured here. The request-id correlation built into
# the middleware below was therefore never actually visible. Configuring here
# first, and removing basicConfig from trade_extractor, fixes that.
#
# `disable_uvicorn_access=True` is passed only here: EVERY request used to
# produce 4 log lines — this app's own middleware printed "📥 <method> <path>"
# + "   Client: ..." + "📤 <method> <path> - Status: ..." (3 lines), AND
# uvicorn's default access logger printed a 4th for the same request. The
# middleware below already logs method, path, status, client, origin, duration
# and request id, so uvicorn's separate access log is pure duplication.
import logging  # noqa: E402
from app.logging_config import setup_logging, request_id_ctx  # noqa: E402

setup_logging(disable_uvicorn_access=True)
# Take our OWN logger so these messages are attributed to app.main rather than
# to app.logging_config.
logger = logging.getLogger(__name__)

from app.api.routes import chat, onboarding, register, documents, auth, otp  # noqa: E402
from app.api.routes import frontend_logs, system  # noqa: E402
from app.services.session_service import SessionService  # noqa: E402
from app.api.error_handlers import register_error_handlers  # noqa: E402
from app import config
# Stage B0 behavioural capture — temporary, remove after B5 sign-off.
from app.utils.behaviour_capture import (  # noqa: E402
    ENABLED as _capture_enabled,
    record_http,
)

# ============================================================================
# BASE PATH — all API routes are served under this prefix (e.g. /onboarding/ai/api)
# ============================================================================
BASE_PATH = config.API_BASE_PATH

# ============================================================================
# RATE LIMITER
# ============================================================================

limiter = Limiter(key_func=get_remote_address)

# ============================================================================
# POLLING LOG COALESCING
# ============================================================================
# The frontend chat UI polls several read-only "status" endpoints on a fixed
# interval for the entire lifetime of a session (fatca/pep/self-declaration/
# product-package status, plus document-status). Logging each call
# individually filled production logs with 50+ near-identical lines per
# session for a single user, with nothing in the per-call diffs worth
# tracing on their own. Instead of logging these immediately, the middleware
# below buffers counts here and one summary line per endpoint is flushed
# every POLL_LOG_FLUSH_SECONDS. Everything else (uploads, submits, and any
# non-2xx response — including from these same paths) still logs
# immediately via the branch in log_requests_and_errors; only the noisy,
# side-effect-free successful polls get collapsed.
POLL_LOG_FLUSH_SECONDS = 30


# Substrings, not suffixes: each of these paths is followed by the user's
# email/session id (e.g. ".../fatca/status/n@test.com"), so matching on
# endswith() would never fire.
_POLLING_PATH_MARKERS = (
    "/fatca/status/",
    "/pep/status/",
    "/self-declaration/status/",
    "/product-package/status/",
    "/document-status/",
)

_poll_log_lock = asyncio.Lock()
# key: (method, path) -> {count, total_ms, min_ms, max_ms, last_status,
#                          client, origin}
_poll_log_buffer: dict[tuple[str, str], dict] = {}


def _is_pollable(method: str, path: str, status_code: int) -> bool:
    """Only collapse successful, side-effect-free GET polls."""
    return (
        method == "GET"
        and 200 <= status_code < 300
        and any(marker in path for marker in _POLLING_PATH_MARKERS)
    )


async def _record_poll(method, path, status_code, duration_ms, client_host, origin):
    key = (method, path)
    async with _poll_log_lock:
        entry = _poll_log_buffer.get(key)
        if entry is None:
            entry = {
                "count": 0,
                "total_ms": 0,
                "min_ms": duration_ms,
                "max_ms": duration_ms,
            }
            _poll_log_buffer[key] = entry
        entry["count"] += 1
        entry["total_ms"] += duration_ms
        entry["min_ms"] = min(entry["min_ms"], duration_ms)
        entry["max_ms"] = max(entry["max_ms"], duration_ms)
        entry["last_status"] = status_code
        entry["client"] = client_host
        entry["origin"] = origin


async def _flush_poll_log_buffer():
    async with _poll_log_lock:
        if not _poll_log_buffer:
            return
        items = list(_poll_log_buffer.items())
        _poll_log_buffer.clear()

    for (method, path), entry in items:
        count = entry["count"]
        avg_ms = entry["total_ms"] // count
        if count == 1:
            # Nothing to collapse this cycle — keep the original single-line
            # format so it still reads like every other request log line.
            logger.info(
                f"{method} {path} -> {entry['last_status']} ({avg_ms}ms) | "
                f"client={entry['client']} origin={entry['origin']}"
            )
        else:
            logger.info(
                f"{method} {path} -> {entry['last_status']} x{count} "
                f"(avg {avg_ms}ms, min {entry['min_ms']}ms, max {entry['max_ms']}ms) "
                f"in last {POLL_LOG_FLUSH_SECONDS}s | "
                f"client={entry['client']} origin={entry['origin']}"
            )


async def _poll_log_flush_loop():
    """Background task: flush the polling-request summary buffer on a fixed
    interval so a burst of identical status polls becomes one line instead
    of one line per request. See POLLING LOG COALESCING above."""
    while True:
        await asyncio.sleep(POLL_LOG_FLUSH_SECONDS)
        try:
            await _flush_poll_log_buffer()
        except Exception as e:
            logger.error(f"[POLL-LOG] flush error: {e}")

# ============================================================================
# LIFESPAN
# ============================================================================

async def _session_cleanup_loop():
    """Background task: clean up expired sessions every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            SessionService.cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"[CLEANUP] Session cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("DigiOB Digital OnBoarding API Starting...")
    logger.info("=" * 60)
    allowed = get_allowed_origins()
    logger.info(f"CORS allowed origins: {allowed}")
    logger.info("=" * 60)

    # Announce a misconfigured deployment at boot rather than halfway through a
    # customer's onboarding. Warns only — it never blocks startup, because none
    # of these keys was validated before and nothing that used to boot should
    # stop booting. (Supabase credentials remain a hard failure, raised at
    # import time in app/config.py exactly as before.)
    config.validate_startup_config()

    # Run an immediate cleanup on startup, then schedule periodic cleanup
    try:
        SessionService.cleanup_expired_sessions()
    except Exception as e:
        logger.warning(f"[STARTUP] Session cleanup skipped: {e}")

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    poll_log_task = asyncio.create_task(_poll_log_flush_loop())

    yield

    cleanup_task.cancel()
    poll_log_task.cancel()
    # Don't drop whatever polls accumulated since the last periodic flush.
    await _flush_poll_log_buffer()
    logger.info("DigiOB API shutting down.")

app = FastAPI(
    title="DigiOB Digital OnBoarding API",
    version="2.0.0",
    description="DigiOB — Secure Digital OnBoarding Platform",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Domain errors -> HTTP, in one place. See app/api/error_handlers.py.
register_error_handlers(app)

# ============================================================================
# CORS CONFIGURATION
# ============================================================================

def get_allowed_origins() -> list[str]:
    """
    Build the CORS allowlist from the ALLOWED_ORIGINS environment variable.
    Always includes Docker-internal origins for container networking.
    In production set ALLOWED_ORIGINS to your real frontend URL(s).
    """
    defaults = [
        "http://localhost:9000",
        "http://127.0.0.1:9000",
        "http://frontend:9000",
    ]
    custom = config.ALLOWED_ORIGINS or ""
    if custom:
        defaults.extend([o.strip() for o in custom.split(",") if o.strip()])
    return defaults

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-User-Language", "X-I18n-Pseudo"],
)

# ============================================================================
# MIDDLEWARE - ERROR LOGGING
# ============================================================================

@app.middleware("http")
async def log_requests_and_errors(request: Request, call_next):
    """Log each request as a SINGLE line (method, path, status, client, origin,
    duration, request id) instead of the previous 3 separate lines — makes it
    possible to tell requests apart at a glance instead of scanning matching
    📥/📤 pairs, and the request id lets you confirm whether a repeated block
    elsewhere in the logs is genuinely N separate calls or one call whose
    business logic itself prints its own block more than once."""
    # Skip logging for health checks to reduce noise
    if request.url.path == "/health":
        return await call_next(request)

    client_host = request.client.host if request.client else "unknown"
    origin = request.headers.get("origin", "no-origin")
    request_id = uuid.uuid4().hex[:8]
    request.state.request_id = request_id
    # Make request_id available to every logger.* call made while handling
    # this request (see RequestIdFilter in app/logging_config.py) without
    # passing it around.
    ctx_token = request_id_ctx.set(request_id)
    # Per-request UI language (X-User-Language, set by the frontend's axios
    # interceptor on every call) -> contextvar read by normalize_language().
    from app.utils.language import current_request_language, language_from_header
    lang_token = current_request_language.set(
        language_from_header(request.headers.get("x-user-language"))
    )
    from app.i18n import pseudo_locale
    pseudo_token = pseudo_locale.set(request.headers.get("x-i18n-pseudo") == "1")
    started_at = time.monotonic()

    try:
        response = await call_next(request)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        if _is_pollable(request.method, request.url.path, response.status_code):
            # Buffered and flushed as one summary line — see POLLING LOG
            # COALESCING above. Anything not matched here (uploads, submits,
            # non-2xx) still falls through to the immediate log line.
            await _record_poll(
                request.method, request.url.path, response.status_code,
                duration_ms, client_host, origin,
            )
        else:
            logger.info(
                f"{request.method} {request.url.path} -> "
                f"{response.status_code} ({duration_ms}ms) | client={client_host} origin={origin}"
            )
        response.headers["X-Request-ID"] = request_id

        # ── Stage B0 behavioural capture (temporary) ─────────────────────────
        # Records the request/response contract of the two large conversational
        # endpoints so their decomposition in B5 can be proven behaviour-
        # identical. Captured HERE rather than with a decorator on the handlers
        # because both take Form/File parameters, and FastAPI builds its request
        # model by introspecting the handler signature — wrapping them is an
        # avoidable risk. Inert unless CAPTURE_BEHAVIOUR=1.
        # REMOVE once B5 is signed off.
        if _capture_enabled and any(
            request.url.path.endswith(p)
            for p in ("/upload-conversational", "/chat-conversational")
        ):
            try:
                record_http(
                    path=request.url.path,
                    method=request.method,
                    status=response.status_code,
                    request_summary={
                        "query": dict(request.query_params),
                        "content_type": request.headers.get("content-type", ""),
                    },
                    response_summary={"status": response.status_code},
                    ms=duration_ms,
                )
            except Exception:
                pass  # capture must never affect the response

        return response

    except Exception as e:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        logger.error(
            f"{request.method} {request.url.path} -> "
            f"ERROR ({duration_ms}ms) | client={client_host} origin={origin} | {e}"
        )
        logger.error(traceback.format_exc())

        return JSONResponse(
            content={"detail": "Internal server error", "request_id": request_id},
            status_code=500,
        )
    finally:
        request_id_ctx.reset(ctx_token)
        current_request_language.reset(lang_token)
        pseudo_locale.reset(pseudo_token)

# ============================================================================
# CORS PREFLIGHT HANDLER
# ============================================================================

@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str) -> Response:
    """Handle CORS preflight requests globally"""
    logger.info(f"CORS Preflight: /{rest_of_path}")
    return Response(status_code=200)

# ============================================================================
# ROUTER REGISTRATION - FIXED ORDER
# ============================================================================

# All routes served under BASE_PATH (default: /onboarding/ai/api)

# 1. Authentication routes at {BASE_PATH}/auth/*
app.include_router(auth.router, prefix=BASE_PATH, tags=["Authentication"])
logger.info(f"Registered: {BASE_PATH}/auth/* routes")

# 2. Registration routes at {BASE_PATH}/register/*
app.include_router(register.router, prefix=BASE_PATH, tags=["Registration"])
logger.info(f"Registered: {BASE_PATH}/register/* routes")

# 3. Chat routes at {BASE_PATH}/chat/*
app.include_router(chat.router, prefix=f"{BASE_PATH}/chat", tags=["Chat"])
logger.info(f"Registered: {BASE_PATH}/chat/* routes")

# 4. Chat upload routes (has its own prefix in the router definition)
app.include_router(onboarding.router, prefix=BASE_PATH, tags=["Chat Upload"])
logger.info(f"Registered: {BASE_PATH}/chatupload/* routes")

# 5. Document page routes (has its own prefix in the router definition)
app.include_router(documents.router, prefix=BASE_PATH, tags=["Documents"])
logger.info(f"Registered: {BASE_PATH}/documentupload/* routes")

# 6. OTP routes at {BASE_PATH}/otp/*
app.include_router(otp.router, prefix=BASE_PATH, tags=["OTP"])
logger.info(f"Registered: {BASE_PATH}/otp/* routes")

# 7. Frontend error logging at {BASE_PATH}/logs/frontend
app.include_router(frontend_logs.router, prefix=BASE_PATH, tags=["Frontend Logs"])
logger.info(f"Registered: {BASE_PATH}/logs/* routes")

# 8. Runtime/system config at {BASE_PATH}/system/config (public — language
#    toggle enable/disable flag, see app/api/routes/system.py)
app.include_router(system.router, prefix=BASE_PATH, tags=["System"])
logger.info(f"Registered: {BASE_PATH}/system/* routes")

# ❌ REMOVED DUPLICATE REGISTRATION

# ============================================================================
# HEALTH CHECK & ROOT ENDPOINTS
# ============================================================================

@app.get("/health")
@app.get(f"{BASE_PATH}/health")
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    return {
        "status": "healthy",
        "message": "API is running",
        "version": "2.0.0"
    }

@app.get("/")
@app.get(BASE_PATH)
async def root():
    """Root endpoint - API information"""
    return {
        "message": "DigiOB Digital OnBoarding API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "base_path": BASE_PATH,
        "endpoints": {
            "auth": [f"{BASE_PATH}/auth/signup", f"{BASE_PATH}/auth/login", f"{BASE_PATH}/auth/logout"],
            "register": [f"{BASE_PATH}/register/signup", f"{BASE_PATH}/register/*"],
            "otp": [f"{BASE_PATH}/otp/generate-otp", f"{BASE_PATH}/otp/verify-otp"],
            "chat": [f"{BASE_PATH}/chat/*"],
            "documents": [f"{BASE_PATH}/documentupload/*"],
            "chatupload": [f"{BASE_PATH}/chatupload/*"]
        }
    }

