# backend/app/repositories/session_repository.py
"""
All queries against the `sessions` table.

Consolidates 10 inline query chains that were split across
`app/api/routes/auth.py` (5) and `app/services/session_service.py` (5). Four of
them were near-duplicates implementing the same operation in both places.

One difference between those duplicates is REAL and is preserved:
`session_service` selected `"*, users(*)"` — joining the user row — while
`auth` selected `"*"`. Those return different structures, so `get_active()`
takes an explicit `with_user` flag rather than picking one.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.repositories.base import supabase

logger = logging.getLogger(__name__)

TABLE = "sessions"


class SessionRepository:
    """Query methods for the `sessions` table. Stateless; all methods static."""

    @staticmethod
    def create(session_data: dict) -> Any:
        """Insert a new session row. Returns the raw Supabase response."""
        return supabase.table(TABLE).insert(session_data).execute()

    @staticmethod
    def get_active(session_id: str, *, with_user: bool = False) -> Any:
        """
        Fetch an active session by id.

        Args:
            with_user: when True, join the related user row (`"*, users(*)"`).
                `session_service` relied on the joined form; `auth` did not.
                The two responses are shaped differently, so the caller states
                which it wants instead of the repository guessing.
        """
        columns = "*, users(*)" if with_user else "*"
        return (
            supabase.table(TABLE)
            .select(columns)
            .eq("session_id", session_id)
            .eq("is_active", True)
            .execute()
        )

    @staticmethod
    def deactivate(session_id: str) -> Any:
        """Mark a session inactive (logout / expiry)."""
        return (
            supabase.table(TABLE)
            .update({"is_active": False})
            .eq("session_id", session_id)
            .execute()
        )

    @staticmethod
    def touch(session_id: str, when_iso: str) -> Any:
        """Update `last_activity` — used to extend an active session."""
        return (
            supabase.table(TABLE)
            .update({"last_activity": when_iso})
            .eq("session_id", session_id)
            .execute()
        )

    @staticmethod
    def delete_expired(before_iso: str) -> Any:
        """Hard-delete sessions whose `expires_at` is in the past."""
        return supabase.table(TABLE).delete().lt("expires_at", before_iso).execute()
