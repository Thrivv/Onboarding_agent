# backend/app/repositories/chat_session_repository.py
"""
Queries against `chat_sessions` and `chat_references`.

Two tables, one module, because they solve the same problem from two angles:
letting a user come back to an unfinished onboarding without logging in again.

  * `chat_sessions`   — a reference number tied to a session snapshot
  * `chat_references` — a shorter-lived `ref_id` handed out in emails

They are kept as separate classes because their key columns differ
(`reference_number` vs `ref_id`) and mixing them up would resolve to the wrong
user's session.

Both use the **service-role client**, as `chat_session_service` and
`reference_service` did — these rows are read during resume, before the caller
has an authenticated session.

A note on `is_active`
---------------------
Neither table hard-deletes on expiry; both flip `is_active` to False and leave
the row. Every read therefore filters on `.eq("is_active", True)`, and that
filter is baked into the read methods rather than left optional — an
unfiltered read would resurrect superseded sessions.
"""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.base import supabase_service

logger = logging.getLogger(__name__)

CHAT_SESSIONS = "chat_sessions"
CHAT_REFERENCES = "chat_references"


class ChatSessionRepository:
    """Query methods for the `chat_sessions` table."""

    @staticmethod
    def reference_exists(candidate: str) -> Any:
        """
        `select("id").eq("reference_number", …).limit(1)` — the collision check
        run while generating a new reference number.

        Selects only `id` because the caller needs existence, not content.
        """
        return (
            supabase_service.table(CHAT_SESSIONS)
            .select("id")
            .eq("reference_number", candidate)
            .limit(1)
            .execute()
        )

    @staticmethod
    def deactivate_all_for_user(user_email: str, now_iso: str) -> Any:
        """
        Retire every active session for a user before issuing a new one, so a
        user never has two live reference numbers pointing at different
        snapshots.
        """
        return (
            supabase_service.table(CHAT_SESSIONS)
            .update({"is_active": False, "updated_at": now_iso})
            .eq("user_email", user_email)
            .eq("is_active", True)
            .execute()
        )

    @staticmethod
    def insert(record: dict) -> Any:
        """Create a new chat session row."""
        return supabase_service.table(CHAT_SESSIONS).insert(record).execute()

    @staticmethod
    def get_active_by_reference(ref: str) -> Any:
        """Resolve a reference number to its active session (full row)."""
        return (
            supabase_service.table(CHAT_SESSIONS)
            .select("*")
            .eq("reference_number", ref)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

    @staticmethod
    def get_latest_reference_for_user(user_email: str) -> Any:
        """
        The user's current reference number — newest active row, one column.

        Ordered `created_at` descending because a user may have several rows if
        deactivation ever failed part-way; newest wins.
        """
        return (
            supabase_service.table(CHAT_SESSIONS)
            .select("reference_number")
            .eq("user_email", user_email)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )


class ChatReferenceRepository:
    """Query methods for the `chat_references` table."""

    @staticmethod
    def delete_for_user(email: str) -> Any:
        """
        Drop a user's existing references before issuing a new one.

        This table *does* hard-delete on reissue, unlike `chat_sessions` which
        soft-deactivates. The difference is preserved as found.
        """
        return (
            supabase_service.table(CHAT_REFERENCES)
            .delete()
            .eq("user_email", email)
            .execute()
        )

    @staticmethod
    def insert(record: dict) -> Any:
        """Create a new reference row."""
        return supabase_service.table(CHAT_REFERENCES).insert(record).execute()

    @staticmethod
    def get_active(ref_id: str) -> Any:
        """Resolve a `ref_id` to its active row (full row, including expiry)."""
        return (
            supabase_service.table(CHAT_REFERENCES)
            .select("*")
            .eq("ref_id", ref_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

    @staticmethod
    def get_active_for_user(email: str) -> Any:
        """
        `select("ref_id, expires_at")` — used to reuse a still-valid reference
        instead of minting a new one on every email.
        """
        return (
            supabase_service.table(CHAT_REFERENCES)
            .select("ref_id, expires_at")
            .eq("user_email", email)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

    @staticmethod
    def deactivate(ref_id: str) -> Any:
        """Retire a reference once it has been consumed or has expired."""
        return (
            supabase_service.table(CHAT_REFERENCES)
            .update({"is_active": False})
            .eq("ref_id", ref_id)
            .execute()
        )
