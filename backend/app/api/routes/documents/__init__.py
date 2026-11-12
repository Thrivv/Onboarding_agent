"""
Document routes — was app/api/routes/documents.py (2,635 lines).

Assembly only, mirroring the pattern already used for
app/api/routes/onboarding/__init__.py: this module owns the
"/documentupload" prefix and the tag, and mounts three bare sub-routers.

    core.py       document requirements, the upload pipeline, health
    preview.py    preview / download / raw file / extracted-data / history
    status.py     confirmation, validation, member-list, status

Why the prefix lives here and not in the sub-routers
------------------------------------------------------
Every sub-router is created bare (`APIRouter()`). If a sub-router also
declared `prefix="/documentupload"`, paths would double up silently. Declaring
it once, here, makes that impossible — same reasoning as
app/api/routes/onboarding/__init__.py.

Path compatibility
-------------------
All 15 endpoints keep their exact path, method, request and response shape.
Verified with `python backend/tests/contract_check.py` (ROUTES check), which
diffs the declared route surface against backend/tests/baseline/routes.json.
"""

from fastapi import APIRouter

from app.api.routes.documents import core, preview, status

router = APIRouter(prefix="/documentupload", tags=["Document Upload"])

router.include_router(core.router)
router.include_router(preview.router)
router.include_router(status.router)

__all__ = ["router"]
