"""
reference_service.py — Unique Reference Number Service
Generates and manages persistent session reference IDs issued after
the Self-Declaration step of the MyBank onboarding flow.

Reference ID format: MBK-YYYYMMDD-XXXXXX  (e.g. MBK-20260406-A3F9C2)

Lifecycle:
  1. Generated immediately after self_declaration.json is saved.
  2. Stored in Supabase table `chat_references` (user_email, ref_id,
     session_snapshot, created_at, expires_at).
  3. Returned to the frontend and displayed prominently to the user.
  4. User can resume a prior session by submitting the ref_id via
     POST /api/chat/resume.

Expiry:  References expire after REFERENCE_TTL_DAYS (default 30).
         Expired / invalid ref_ids are rejected with a clear message.
"""

import json
import uuid
import string
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from app.services.supabase_client import supabase_service
from app.repositories.chat_session_repository import ChatReferenceRepository
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REFERENCE_TTL_DAYS: int = 30
MAX_HISTORY_MESSAGES: int = 50   # messages stored in session snapshot


# ---------------------------------------------------------------------------
# Reference ID generation
# ---------------------------------------------------------------------------

def _generate_ref_id() -> str:
    """
    Build a human-readable reference ID:
        MBK-YYYYMMDD-XXXXXX
    where XXXXXX is an uppercase alphanumeric token (excluding ambiguous
    characters 0/O/I/1 to improve readability).
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    charset = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0, I, 1, O
    token = "".join(random.choices(charset, k=6))
    return f"MBK-{today}-{token}"


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def generate_reference(
    email: str,
    session_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create and persist a new reference ID for this user.

    Args:
        email:            User's email address (primary key for lookup).
        session_snapshot: Optional dict containing onboarding state and
                          recent chat history to restore when resuming.

    Returns:
        {
            "success": True,
            "ref_id":  "MBK-20260406-A3F9C2",
            "expires_at": "<ISO-8601 UTC>"
        }
    """
    ref_id = _generate_ref_id()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=REFERENCE_TTL_DAYS)

    record = {
        "ref_id":           ref_id,
        "user_email":       email,
        "session_snapshot": json.dumps(session_snapshot or {}),
        "created_at":       now.isoformat(),
        "expires_at":       expires_at.isoformat(),
        "is_active":        True,
    }

    try:
        # Upsert: replace any existing active reference for this user so they
        # always have exactly one current reference ID.
        ChatReferenceRepository.delete_for_user(email)
        ChatReferenceRepository.insert(record)
        logger.info(f"[REF] Reference generated for {email}: {ref_id}")
    except Exception as e:
        logger.warning(f"[REF] Supabase write failed: {e}")
        # Still return the generated ref_id so the frontend can display it.

    return {
        "success":    True,
        "ref_id":     ref_id,
        "expires_at": expires_at.isoformat(),
    }


def resolve_reference(ref_id: str) -> Dict[str, Any]:
    """
    Validate a reference ID and return the associated session data.

    Returns:
        On success:
            {
                "valid": True,
                "email": "<user_email>",
                "session_snapshot": { ... },
                "ref_id": "<ref_id>",
                "expires_at": "<ISO-8601>"
            }
        On failure:
            {
                "valid": False,
                "reason": "<human-readable reason>"
            }
    """
    if not ref_id or not ref_id.startswith("MBK-"):
        return {"valid": False, "reason": "Invalid reference number format."}

    try:
        res = ChatReferenceRepository.get_active(ref_id)

        rows = res.data if res and res.data else []
        if not rows:
            return {
                "valid":  False,
                "reason": "This reference number was not found. Please check and try again.",
            }

        row = rows[0]

        # Check expiry
        expires_at_str = row.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                # Mark as inactive
                try:
                    ChatReferenceRepository.deactivate(ref_id)
                except Exception:
                    pass
                return {
                    "valid":  False,
                    "reason": (
                        "This reference number has expired (references are valid for "
                        f"{REFERENCE_TTL_DAYS} days). Please contact support or start "
                        "a new session."
                    ),
                }

        snapshot_raw = row.get("session_snapshot", "{}")
        try:
            snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
        except Exception:
            snapshot = {}

        logger.info(f"[REF] Resolved reference {ref_id} for {row.get('user_email')}")
        return {
            "valid":            True,
            "email":            row.get("user_email"),
            "ref_id":           ref_id,
            "expires_at":       expires_at_str,
            "session_snapshot": snapshot,
        }

    except Exception as e:
        logger.warning(f"[REF] Supabase lookup failed: {e}")
        return {
            "valid":  False,
            "reason": "We were unable to retrieve your session. Please try again.",
        }


def build_session_snapshot(
    email: str,
    user_data: Dict[str, Any],
    conversation_history: Optional[List[Dict]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a snapshot dict that captures key onboarding state for storage.

    Args:
        email:                User's email.
        user_data:            Row from the `users` table.
        conversation_history: List of recent { role, content } message dicts.
        extra:                Any additional state to persist.

    Returns:
        Snapshot dict ready to be serialised and stored.
    """
    from app.services.fatca_service import get_fatca_status_disk_only
    from app.services.pep_service import get_pep_status_disk_only
    from app.services.product_package_service import get_package_status

    # Trim history to the most recent N messages to keep snapshot lean.
    history = (conversation_history or [])[-MAX_HISTORY_MESSAGES:]

    snapshot = {
        "email":            email,
        "name":             user_data.get("name", ""),
        "account_type":     user_data.get("account_type", ""),
        "ownership_type":   user_data.get("ownership_type", ""),
        "onboarding_step":  user_data.get("onboarding_step", ""),
        "document_stage":   user_data.get("document_stage", ""),
        "fatca_status":     get_fatca_status_disk_only(email),
        "pep_status":       get_pep_status_disk_only(email),
        "package_status":   get_package_status(email),
        "self_decl_done":   True,   # snapshot only created after self-declaration
        "conversation_history": history,
        "snapshot_at":      datetime.now(timezone.utc).isoformat(),
    }

    if extra:
        snapshot.update(extra)

    return snapshot


def get_reference_for_user(email: str) -> Optional[str]:
    """
    Return the current active reference ID for a user, if one exists.
    Returns None if none found or all expired.
    """
    try:
        res = ChatReferenceRepository.get_active_for_user(email)

        rows = res.data if res and res.data else []
        if not rows:
            return None

        row = rows[0]
        expires_at_str = row.get("expires_at", "")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_at:
                return None

        return row.get("ref_id")
    except Exception as e:
        logger.warning(f"[REF] get_reference_for_user failed: {e}")
        return None
