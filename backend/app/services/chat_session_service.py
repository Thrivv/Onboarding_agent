"""
chat_session_service.py — Chat Session & Reference Number Service

Manages the chat_sessions table and generates user-facing reference numbers
for session continuity after onboarding self-declaration.

Reference format:  REF-YYYY-XXXXXX   (e.g. REF-2026-A3F9C2)

Table: public.chat_sessions
  id               UUID PK
  user_id          UUID FK → users.id
  user_email       TEXT
  reference_number TEXT UNIQUE
  last_message_id  UUID (nullable)
  is_active        BOOLEAN
  created_at       TIMESTAMPTZ
  updated_at       TIMESTAMPTZ

SQL to create the table (run once in Supabase):
──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES public.users(id) ON DELETE CASCADE,
    user_email       TEXT NOT NULL,
    reference_number TEXT NOT NULL UNIQUE,
    last_message_id  UUID,
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE public.conversations
ADD COLUMN IF NOT EXISTS chat_session_id UUID
REFERENCES public.chat_sessions(id) ON DELETE CASCADE;
──────────────────────────────────────────────
"""

import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from app.services.supabase_client import supabase, supabase_service
from app.repositories.chat_session_repository import ChatSessionRepository
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # excludes 0/O/I/1 for readability


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_reference_number() -> str:
    """
    Generate a unique, human-readable reference number.
    Format: REF-YYYY-XXXXXX   (e.g. REF-2026-A3F9C2)
    """
    year = datetime.now(timezone.utc).year
    token = "".join(random.choices(CHARSET, k=6))
    return f"REF-{year}-{token}"


def _ensure_unique(candidate: str) -> str:
    """Re-roll if the candidate already exists (extremely rare)."""
    try:
        res = ChatSessionRepository.reference_exists(candidate)
        if res.data:
            return _ensure_unique(_generate_reference_number())
    except Exception:
        pass
    return candidate


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_chat_session(user_id: str, user_email: str) -> Dict[str, Any]:
    """
    Create a new chat session with a unique reference number.
    Called immediately after the self-declaration step is confirmed.

    Deactivates any existing active session for the same user first so
    there is always at most one active session per user.

    Returns:
        {
            "success": bool,
            "reference_number": "REF-2026-XXXXXX",
            "session_id": "<uuid>",
        }
    """
    reference_number = _ensure_unique(_generate_reference_number())
    now = datetime.now(timezone.utc).isoformat()

    # Deactivate previous active sessions (non-fatal)
    try:
        ChatSessionRepository.deactivate_all_for_user(user_email, now)
    except Exception as e:
        logger.warning(f"[CHAT-SESSION] Could not deactivate old sessions: {e}")

    record = {
        "user_id":          user_id,
        "user_email":       user_email,
        "reference_number": reference_number,
        "is_active":        True,
        "created_at":       now,
        "updated_at":       now,
    }

    try:
        result = ChatSessionRepository.insert(record)
        session_id = result.data[0]["id"] if result.data else None
        logger.info(f"[CHAT-SESSION] Created session {reference_number} for {user_email}")
        return {
            "success":          True,
            "reference_number": reference_number,
            "session_id":       session_id,
        }
    except Exception as e:
        logger.error(f"[CHAT-SESSION] DB insert failed: {e}")
        # Still return the generated number so the frontend can display it
        return {
            "success":          False,
            "reference_number": reference_number,
            "session_id":       None,
        }


def validate_reference_number(reference_number: str) -> Dict[str, Any]:
    """
    Validate a reference number and return the linked session data.

    Returns on success:
        { "valid": True, "session_id": ..., "user_email": ..., "user_id": ...,
          "reference_number": ..., "created_at": ... }

    Returns on failure:
        { "valid": False, "reason": "<human-readable message>" }
    """
    if not reference_number:
        return {"valid": False, "reason": "Please enter your reference number."}

    ref = reference_number.strip().upper()

    if not ref.startswith("REF-") or len(ref) < 14:
        return {
            "valid":  False,
            "reason": "Invalid format. Reference numbers look like REF-2026-A3F9C2.",
        }

    try:
        res = ChatSessionRepository.get_active_by_reference(ref)

        rows = res.data if res and res.data else []
        if not rows:
            return {
                "valid":  False,
                "reason": "This reference number was not found. Please check and try again.",
            }

        session = rows[0]
        logger.info(f"[CHAT-SESSION] Validated {ref} → {session.get('user_email')}")
        return {
            "valid":            True,
            "session_id":       session["id"],
            "user_email":       session["user_email"],
            "user_id":          session.get("user_id"),
            "reference_number": ref,
            "created_at":       session.get("created_at"),
        }

    except Exception as e:
        logger.error(f"[CHAT-SESSION] validate_reference_number error: {e}")
        return {
            "valid":  False,
            "reason": "Unable to validate your reference number. Please try again.",
        }


def get_active_reference_for_user(user_email: str) -> Optional[str]:
    """
    Return the active reference_number for a user, or None if none exists.
    Used by start-conversation to surface the ref number to a returning user.
    """
    try:
        res = ChatSessionRepository.get_latest_reference_for_user(user_email)
        rows = res.data or []
        return rows[0]["reference_number"] if rows else None
    except Exception as e:
        logger.warning(f"[CHAT-SESSION] get_active_reference_for_user error: {e}")
        return None
