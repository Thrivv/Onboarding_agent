# backend/app/utils/behaviour_capture.py
"""
Temporary instrumentation: record real inputs and outputs of the functions
about to be decomposed in Stage B5.

Why
---
The contract suite can prove that routes, imports, names and signatures are
unchanged. It CANNOT prove that `upload_conversational` (2,394 lines) still
makes the same decisions after being split into eight collaborators. There are
no fixtures for these functions, and constructing them by hand would encode my
assumptions about the logic rather than its actual behaviour.

So: record what really happens during a normal onboarding run, then replay it
against the refactored code and assert identical output.

Safety properties — this must never affect production behaviour
---------------------------------------------------------------
1. **Inert unless switched on.** With CAPTURE_BEHAVIOUR unset, `capture()`
   returns the function unmodified — not even a wrapper frame.
2. **Never raises.** Every recording path is wrapped in its own try/except.
   A serialisation failure records a marker; it never propagates.
3. **Never alters the return value or the exception.** The wrapper returns
   exactly what the wrapped function returned, and re-raises the original
   exception unchanged.
4. **Signature preserved** via functools.wraps, so anything introspecting the
   function (FastAPI included) still sees the original.

DELETE THIS MODULE, and its call sites, once Stage B5 is signed off.

Usage
-----
Add to .env.docker, restart, run the flows, then turn it back off:

    CAPTURE_BEHAVIOUR=1

Recordings appear on the host under  logs/backend/capture/  — one JSONL file
per function, plus `_http.jsonl` for the two conversational endpoints.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENABLED = os.getenv("CAPTURE_BEHAVIOUR", "").strip() in ("1", "true", "yes")

# Default deliberately points at a VOLUME-MOUNTED path.
# The Dockerfile copies only `backend/app` into the image, so
# /app/backend/tests does not exist in the container — writing there would
# create a directory inside the container layer and lose everything the moment
# the container is removed. docker-compose maps ./logs/backend:/var/log/backend,
# so this path surfaces on the host as  logs/backend/capture/.
CAPTURE_DIR = Path(os.getenv("CAPTURE_DIR", "/var/log/backend/capture"))

# Serialised values are truncated: a base64 document is megabytes and adds
# nothing to a behavioural comparison.
MAX_STR = 2000
MAX_ITEMS = 50

_lock = threading.Lock()
_RUN_ID = uuid.uuid4().hex[:8]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _redact(text: str) -> str:
    """Replace email addresses with a stable pseudonym.

    Stable, not random: the same address maps to the same token every time, so
    behaviour that depends on comparing two addresses is still reproducible in
    the recording while the real address never reaches disk.
    """
    def sub(m: re.Match) -> str:
        digest = abs(hash(m.group(0))) % 10_000
        return f"user{digest:04d}@example.test"

    return _EMAIL_RE.sub(sub, text)


def _safe(value: Any, depth: int = 0) -> Any:
    """Best-effort JSON-serialisable rendering. Never raises."""
    try:
        if depth > 6:
            return "<max-depth>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            out = value if len(value) <= MAX_STR else value[:MAX_STR] + f"…<+{len(value)-MAX_STR} chars>"
            return _redact(out)
        if isinstance(value, bytes):
            return f"<bytes len={len(value)}>"
        if isinstance(value, dict):
            items = list(value.items())[:MAX_ITEMS]
            return {str(k): _safe(v, depth + 1) for k, v in items}
        if isinstance(value, (list, tuple, set)):
            seq = list(value)[:MAX_ITEMS]
            return [_safe(v, depth + 1) for v in seq]
        if isinstance(value, Path):
            return _redact(str(value))
        # UploadFile and similar: record only what identifies it
        for attr in ("filename", "name"):
            if hasattr(value, attr):
                return f"<{type(value).__name__} {attr}={_redact(str(getattr(value, attr)))}>"
        return f"<{type(value).__name__}>"
    except Exception:
        return "<unserialisable>"


def _write(name: str, record: dict) -> None:
    """Append one JSONL record. Swallows every error by design."""
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with _lock:
            with open(CAPTURE_DIR / f"{name}.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:  # pragma: no cover - must never affect the caller
        logger.debug(f"[CAPTURE] could not write record for {name}: {e}")


def capture(name: str | None = None):
    """
    Record calls to the decorated function.

    Returns the function UNTOUCHED when capture is disabled, so there is zero
    overhead and zero behavioural surface in normal operation.
    """
    def decorator(func):
        if not ENABLED:
            return func

        label = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = time.monotonic()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                _write(label, {
                    "run": _RUN_ID,
                    "fn": label,
                    "args": [_safe(a) for a in args],
                    "kwargs": {k: _safe(v) for k, v in kwargs.items()},
                    "raised": f"{type(exc).__name__}: {_safe(str(exc))}",
                    "ms": int((time.monotonic() - started) * 1000),
                })
                raise
            _write(label, {
                "run": _RUN_ID,
                "fn": label,
                "args": [_safe(a) for a in args],
                "kwargs": {k: _safe(v) for k, v in kwargs.items()},
                "return": _safe(result),
                "ms": int((time.monotonic() - started) * 1000),
            })
            return result

        return wrapper

    return decorator


def record_http(path: str, method: str, status: int,
                request_summary: Any, response_summary: Any, ms: int) -> None:
    """
    Record an HTTP call from middleware.

    Used for `upload_conversational` and `chat_conversational` instead of the
    decorator: both are FastAPI handlers whose parameters are Form/File
    dependencies, and FastAPI builds its request model by introspecting the
    handler signature. Wrapping them is an unnecessary risk when the HTTP
    request/response pair captures the same contract — arguably better, since
    it is the contract clients actually depend on.
    """
    if not ENABLED:
        return
    _write("_http", {
        "run": _RUN_ID,
        "path": path,
        "method": method,
        "status": status,
        "request": _safe(request_summary),
        "response": _safe(response_summary),
        "ms": ms,
    })
