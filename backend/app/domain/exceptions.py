"""
Domain error hierarchy — framework-free.

Nothing here imports FastAPI. Domain code raises these; exactly one place
(`app/api/error_handlers.py`) turns them into HTTP responses. That is the whole
point: the rule "a missing user is a 404" is stated once, at the boundary,
instead of at each of the 46 call sites that currently build their own
`HTTPException(404, ...)`.

Two fields matter and they are deliberately separate:

- ``detail``   — safe to send to the client. Never interpolate an upstream
                 exception into it.
- ``context``  — for the log line only. Put the messy internals here.

That split exists because the dominant idiom in the route layer today is
``raise HTTPException(status_code=500, detail=str(e))``, which forwards
whatever the underlying library said — driver errors, file paths, occasionally
a connection string — straight to the browser. `DomainError` makes the safe
thing the default rather than the thing you have to remember.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """
    Base for every expected failure in the business layer.

    ``status_code`` is advisory: it is what the translation layer will use
    unless a route catches the error and decides otherwise. Subclasses set it;
    callers should not need to.
    """

    status_code: int = 500
    #: Sent to the client when the subclass does not override `detail`.
    default_detail: str = "An internal error occurred."

    def __init__(
        self,
        detail: str | None = None,
        *,
        context: Any = None,
        code: str | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        self.context = context
        #: Stable machine-readable tag, e.g. "not_found". Lets the frontend
        #: branch on the kind of failure without string-matching `detail`.
        self.code = code or self.__class__.__name__
        super().__init__(self.detail)

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.context is None:
            return self.detail
        return f"{self.detail} ({self.context})"


class NotFoundError(DomainError):
    """A record that the caller named does not exist."""

    status_code = 404
    default_detail = "Not found."


class ValidationError(DomainError):
    """The request was well-formed but the values are not usable."""

    status_code = 400
    default_detail = "Invalid request."


class AuthError(DomainError):
    """The caller is not authenticated, or the credential did not verify."""

    status_code = 401
    default_detail = "Not authorised."


class PasswordResetRequiredError(DomainError):
    """
    The account's stored credential predates the current password-hashing
    scheme (or was invalidated by the migration script) and can never verify
    successfully — the caller must go through POST /auth/request-password-reset
    and POST /auth/reset-password instead of retrying login.

    Deliberately a distinct code from AuthError so the frontend can route the
    user to the reset flow instead of just showing "wrong password" — see
    `code` on DomainError and AuthContext.jsx's handling of it.
    """

    status_code = 403
    default_detail = (
        "For your security we've upgraded how passwords are protected. "
        "Please reset your password to continue."
    )


class PermissionError_(DomainError):
    """
    Authenticated, but not allowed to touch this record.

    Named with a trailing underscore so it cannot shadow the builtin
    ``PermissionError`` — a real hazard here, because a shadowed builtin is
    exactly the class of bug contract check 5 exists to catch.
    """

    status_code = 403
    default_detail = "Not permitted."


class ConflictError(DomainError):
    """The operation contradicts the current state (duplicate, wrong stage)."""

    status_code = 409
    default_detail = "Conflicts with the current state."


class UpstreamError(DomainError):
    """
    A third party we depend on failed: Supabase, AWS Bedrock, SMTP, OCR.

    502 rather than 500 on purpose — it tells the caller the fault is not in
    this service, and it keeps genuine internal bugs visible in the 500 rate
    instead of buried under provider flakiness.
    """

    status_code = 502
    default_detail = "An upstream service is unavailable."


class StorageError(DomainError):
    """Reading or writing the document store failed."""

    status_code = 500
    default_detail = "Could not read or write the document store."


__all__ = [
    "DomainError",
    "NotFoundError",
    "ValidationError",
    "AuthError",
    "PasswordResetRequiredError",
    "PermissionError_",
    "ConflictError",
    "UpstreamError",
    "StorageError",
]
