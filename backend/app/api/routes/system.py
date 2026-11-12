# backend/app/api/routes/system.py
# ============================================================================
# SYSTEM / RUNTIME CONFIG — DigiOB Digital OnBoarding Platform
# ============================================================================
# GET /system/config — tells the frontend which runtime feature flags are
# currently on, so the UI can match server-side behavior instead of guessing.
#
# Today this carries exactly one flag: LANGUAGE_TOGGLE_ENABLED (see
# app/config.py and app/utils/language.py — normalize_language() is the
# real, server-side enforcement of this; this endpoint only lets the
# frontend know it should hide the toggle rather than show one that does
# nothing). Set LANGUAGE_TOGGLE_ENABLED in .env.docker and restart the
# `app`/`reply-loop` containers (no rebuild needed) to flip it.
#
# Deliberately public (no auth, no session cookie required) — the language
# toggle has to render correctly on the login/signup pages too, before any
# session exists. Read-only and cheap, so no rate limiting either.
# ============================================================================

import logging

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from app import config
from app.utils.language import normalize_language, SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/config")
async def get_runtime_config():
    """Public runtime feature flags the frontend needs at page load."""
    return {
        "language_toggle_enabled": bool(config.LANGUAGE_TOGGLE_ENABLED),
    }


# ----------------------------------------------------------------------------
# Account-level UI language (see supabase/migrations/
# 20260923000000_add_preferred_language_to_users.sql). Same access model as
# the other onboarding endpoints (email in the request, no session check).
# Both fail open: if the column hasn't been migrated yet, or Supabase is
# unreachable, the toggle still works — it just isn't remembered on the
# account.
# ----------------------------------------------------------------------------

class UserLanguageRequest(BaseModel):
    email: EmailStr
    language: str


@router.post("/user-language")
async def save_user_language(req: UserLanguageRequest):
    language = normalize_language(req.language)
    try:
        from app.repositories.user_repository import UserRepository
        UserRepository.update_by_email(req.email, {"preferred_language": language})
        return {"success": True, "language": language}
    except Exception as e:
        logger.warning(f"[LANG] Could not persist preferred_language for {req.email}: {e}")
        return {"success": False, "language": language}


@router.get("/user-language/{email}")
async def get_user_language(email: str):
    try:
        from app.services.supabase_client import get_user_by_email
        user = get_user_by_email(email) or {}
        saved = (user.get("preferred_language") or "").lower()
        if saved in SUPPORTED_LANGUAGES:
            return {"language": normalize_language(saved)}
    except Exception as e:
        logger.warning(f"[LANG] Could not read preferred_language for {email}: {e}")
    return {"language": None}
