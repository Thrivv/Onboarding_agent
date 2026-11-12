"""
Onboarding routes — was `app/api/routes/chatupload.py` (9,137 lines).

Assembly only. This module owns the `/chatupload` prefix and the tag, and
mounts six sub-routers that each hold one domain's endpoints:

    compliance.py       9 endpoints   FATCA, PEP, self-declaration
    products.py         3 endpoints   product package
    ownership.py        4 endpoints   ownership type, UBO, role mismatch
    key_individuals.py  8 endpoints   the KI loop
    conversation.py     8 endpoints   start / chat / resume / logs / health
    upload.py           6 endpoints   the upload pipeline and readbacks

Why the prefix lives here and not in the sub-routers
----------------------------------------------------
Every sub-router is created bare (`APIRouter()`). If each one declared
`prefix="/chatupload"` and this module also applied it, every path would be
served at `/chatupload/chatupload/...` — silently, with no error, and the
frontend would 404 across the board. Declaring it once, here, makes that
impossible.

The mount order matters only where paths could overlap; these six sets are
disjoint, so the order below is simply the order the plan splits them in
(ascending risk).

Path compatibility
------------------
All 38 endpoints keep their exact path, method, request and response shape. The
`chatupload` name survives in the URL because renaming it would break the
frontend; renaming the URL is a separate, deliberate change, not part of a move.
"""

from fastapi import APIRouter

from app.api.routes.onboarding import (
    compliance,
    conversation,
    key_individuals,
    ownership,
    products,
    upload,
)

router = APIRouter(prefix="/chatupload", tags=["Chat & Upload"])

router.include_router(compliance.router)
router.include_router(products.router)
router.include_router(ownership.router)
router.include_router(key_individuals.router)
router.include_router(conversation.router)
router.include_router(upload.router)

__all__ = ["router"]
