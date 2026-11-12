"""
System endpoints (frontend error reporting).

Moved verbatim from app/api/routes/frontend_logs.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel


class FrontendErrorRequest(BaseModel):
    message: str
    stack: str | None = None
    source: str | None = None       # e.g. "window.onerror" | "unhandledrejection" | "error-boundary"
    url: str | None = None          # page the error happened on
    componentStack: str | None = None
    userAgent: str | None = None
    email: str | None = None        # best-effort, if a session/user is known client-side
