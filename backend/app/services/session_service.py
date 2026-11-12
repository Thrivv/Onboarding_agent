# backend/app/services/session_service.py

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
import uuid
import logging
from app.services.supabase_client import supabase
from app.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


class SessionService:
    """Session management service"""

    @staticmethod
    def create_session(user_id: str, user_data: Dict, timeout_minutes: int = 300) -> str:
        """Create a new session. Returns session_id."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=timeout_minutes)

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "email": user_data.get("email"),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "is_active": True,
            "last_activity": now.isoformat(),
        }

        try:
            SessionRepository.create(session_data)
            return session_id
        except Exception as e:
            logger.error(f"[SESSION] Failed to create session: {e}")
            raise

    @staticmethod
    def validate_session(session_id: str) -> Optional[Dict]:
        """Validate session and return user data. Returns None if invalid."""
        try:
            # with_user=True keeps the joined `users(*)` shape this method
            # depends on — auth.py deliberately uses the un-joined form.
            result = SessionRepository.get_active(session_id, with_user=True)

            if not result.data:
                return None

            session = result.data[0]
            now = datetime.now(timezone.utc)
            expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))

            if now > expires_at:
                SessionService.invalidate_session(session_id)
                return None

            SessionRepository.touch(session_id, now.isoformat())

            user = session.get("users") or {}
            return {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role", "user"),
                "account_type": user.get("account_type"),
            }

        except Exception as e:
            logger.error(f"[SESSION] Validation error: {e}")
            return None

    @staticmethod
    def invalidate_session(session_id: str):
        """Invalidate a session (logout)."""
        try:
            SessionRepository.deactivate(session_id)
        except Exception as e:
            logger.error(f"[SESSION] Failed to invalidate session: {e}")
            raise

    @staticmethod
    def cleanup_expired_sessions():
        """Delete expired sessions. Call periodically."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            SessionRepository.delete_expired(now)
            logger.info("[SESSION] Expired sessions cleaned up")
        except Exception as e:
            logger.error(f"[SESSION] Failed to cleanup sessions: {e}")