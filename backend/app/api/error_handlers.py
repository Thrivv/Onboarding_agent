"""
The one place domain errors become HTTP responses.

Registered from `main.py` via `register_error_handlers(app)`. Routes should
raise `DomainError` subclasses and let this decide the status code; they should
not each re-derive "missing user means 404".

## Response shape

Identical to FastAPI's own `HTTPException` output plus one additive key:

```json
{"detail": "Not found.", "code": "NotFoundError"}
```

`detail` is what the frontend already reads — `AuthContext.jsx`,
`OnboardingPage.jsx`, `Signup.jsx` and `ProductPackageCard.jsx` all do
`error.response?.data?.detail`. Keeping that key identical is why this is a
safe addition rather than a contract change. `code` is new and currently unread
by the frontend; it is there so error handling can eventually branch on the
kind of failure instead of matching on English prose.

## What is deliberately NOT here

There is no catch-all `Exception` handler. Adding one would change the response
of every unhandled error in all 87 routes at once, and that is a user-visible
change in the crash path — the same category as C5, which is gated on Srini's
sign-off. Until then, unhandled exceptions keep falling through to Starlette's
default 500.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import DomainError

logger = logging.getLogger(__name__)


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """
    Log the messy version, return the safe one.

    The `context` field is written to the log and never to the response body.
    That asymmetry is the reason this layer exists: the idiom it replaces,
    `raise HTTPException(500, detail=str(e))`, sends the internal message to the
    client instead.
    """
    log = logger.error if exc.status_code >= 500 else logger.warning
    log(
        "%s %s -> %d %s%s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.code,
        f": {exc.context}" if exc.context is not None else "",
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach the domain-error translation to `app`. Called once, from main."""
    app.add_exception_handler(DomainError, domain_error_handler)
