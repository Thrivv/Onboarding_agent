# backend/app/logging_config.py
"""
Shared logging setup for every process that runs this application.

Why this module exists
----------------------
The configuration below used to live at module scope in ``app/main.py``. That
worked for the API container, where uvicorn imports ``app.main`` and the
config runs as a side effect of that import.

It did NOT work for the second container. ``docker-compose.yml`` launches the
reply-loop as::

    python -u -m app.services.reply_loop

which never imports ``app.main`` — so ``logging.basicConfig()`` was never
called in that process. Python's root logger then has no handlers, and
anything below WARNING is discarded silently. Roughly 525 log statements in
the modules reachable from ``reply_loop`` (``handle_reply``, ``ocr_service``,
``document_helpers``, ``email_sender``, ``supabase_client``, …) run in exactly
that process.

While those statements were ``print()`` they went to stdout regardless and
Docker captured them. Converting them to ``logger.*`` without configuring
logging in that process would have made all 525 disappear. Hence: one setup
function, called by both entrypoints.

Usage
-----
    from app.logging_config import setup_logging
    setup_logging()

Safe to call more than once — the second call is a no-op.
"""

from __future__ import annotations

import contextvars
import logging
import os

# ── Request correlation ──────────────────────────────────────────────────────
# request_id_ctx makes the same short id shown in the access-log line
# ([a1b2c3d4]) available to every logger.* call made anywhere down the call
# stack while that request is being handled — without having to thread a
# request_id parameter through every function. RequestIdFilter reads it and
# stamps it onto every log record; the format string below renders it.
# Outside a request (startup, background tasks with no parent request, and the
# whole reply-loop process) it just shows "-".
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


# ── Line format ──────────────────────────────────────────────────────────────
# LOG_STYLE picks how much prefix each line carries. Default is "plain": just
# the message, because under docker-compose every line already arrives prefixed
# with the container name and the prefix made real messages hard to read at a
# glance.
#
#   plain (default)  GET /onboarding/ai/api/... -> 200 (4ms) | client=...
#   full             2026-07-28 16:40:18,724 - app.main - INFO - [52ff744d] - GET ...
#
# What "plain" costs, so the choice is made knowingly:
#
#   - **Level disappears.** A WARNING and an INFO look identical. `[SELF-DECL]
#     Completion email failed: ...` was found precisely because it was tagged
#     WARNING among INFO lines.
#   - **Request id disappears.** `[52ff744d]` is what lets you follow one
#     request across the dozens of lines it emits — worth a lot when two
#     onboardings run concurrently, as they do in a capture run. Restoring that
#     correlation was a Stage A fix; it had never worked before.
#   - **Timestamps disappear** from the app's own output. Docker still has them:
#     `docker compose logs -t` prints its own, and they are what the container
#     recorded rather than what the app formatted.
#
# Set LOG_STYLE=full in .env.docker and recreate the container to get it back.
# No rebuild needed — this is read at import, like LOG_LEVEL.
_LOG_STYLES = {
    "plain": "%(message)s",
    "full": "%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s",
}

LOG_FORMAT = _LOG_STYLES.get(
    os.getenv("LOG_STYLE", "plain").strip().lower(), _LOG_STYLES["plain"]
)

# Third-party HTTP client chatter, silenced without lowering our own level.
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "filelock")

_configured = False


def setup_logging(*, disable_uvicorn_access: bool = False) -> None:
    """
    Configure root logging for the current process.

    LOG_LEVEL is read from the environment (.env.docker) so verbosity can be
    changed with a container restart instead of a code change and rebuild.
    Default stays INFO — one line per request, plus real warnings and errors.
    Set LOG_LEVEL=DEBUG when you need the per-field/per-document dumps that
    individual services gate behind logger.debug().

    Args:
        disable_uvicorn_access: only the API process should pass True. See the
            note in ``main.py`` — the custom middleware there already logs
            method, path, status, client, origin, duration and request id, so
            uvicorn's separate access log is pure duplication. The reply-loop
            process has no uvicorn, so it leaves this alone.

    Returns:
        None. Callers must take their own ``logging.getLogger(__name__)`` —
        returning a logger from here caused every message emitted by main.py to
        be attributed to ``app.logging_config`` instead of ``app.main``, which
        defeats the point of having the logger name in the format string.
    """
    global _configured

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    if not _configured:
        logging.basicConfig(level=level, format=LOG_FORMAT)
        for handler in logging.root.handlers:
            handler.addFilter(RequestIdFilter())

        for noisy in _NOISY_LOGGERS:
            logging.getLogger(noisy).setLevel(logging.ERROR)

        _configured = True

    if disable_uvicorn_access:
        logging.getLogger("uvicorn.access").disabled = True

    logging.getLogger(__name__).info(
        f"[LOGGING] Log level set to {level_name} (from LOG_LEVEL env var)"
    )
