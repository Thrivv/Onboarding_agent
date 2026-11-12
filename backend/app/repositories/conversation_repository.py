# backend/app/repositories/conversation_repository.py
"""
All queries against the `conversations` table.

Consolidates 24 inline query chains that were spread across 7 modules:

    app/api/routes/chat.py                 4
    app/api/routes/chatupload.py           7
    app/api/routes/register.py             2
    app/services/chatupload_helpers.py     1
    app/services/handle_reply.py           3
    app/services/onboarding_chat_service.py 3
    app/services/supabase_client.py        4

Twelve of those were SELECTs and every one of them built the same chain in the
same order:

    .select(columns) -> .eq("user_email", …) -> [.eq("channel", …)]
                     -> [.eq("role", …)] -> .order("timestamp", desc=…) -> [.limit(n)]

They differ only in which optional links are present and in the column list, so
they share one builder (`list_messages`) with explicit keyword arguments. The
named wrappers below record the shapes actually observed at call sites, so a
reader can see what the application really asks for without decoding argument
combinations.

Return convention
-----------------
Every method returns the **raw Supabase response object**, not `.data`. Call
sites variously check `if result.data`, take `len(response.data)`, or index
`response.data[0]`; returning the response keeps all of them working unchanged.

Column lists are passed through verbatim. `"role, message, timestamp"` and
`"role, message, timestamp, metadata"` are different requests — the second
carries the metadata blob the chat UI renders cards from — so they are not
merged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.repositories.base import supabase

logger = logging.getLogger(__name__)

TABLE = "conversations"

# Column sets observed at call sites, named so intent is visible.
COLUMNS_ALL = "*"
COLUMNS_TRANSCRIPT = "role, message, timestamp"
COLUMNS_TRANSCRIPT_WITH_METADATA = "role, message, timestamp, metadata"


class ConversationRepository:
    """Query methods for the `conversations` table. Stateless; all methods static."""

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @staticmethod
    def insert(entry: dict) -> Any:
        """
        Insert a single conversation log row.

        The payload shape is left to the caller because it genuinely varies:
        some callers write only `user_email/role/message/timestamp`, others add
        `channel` and a `metadata` blob.
        """
        return supabase.table(TABLE).insert(entry).execute()

    @staticmethod
    def insert_many(entries: list) -> Any:
        """
        Insert several rows in one call.

        Used by `onboarding_chat_service`, which persists the user turn and the
        assistant turn together so their timestamps cannot interleave with a
        concurrent write.
        """
        return supabase.table(TABLE).insert(entries).execute()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    @staticmethod
    def list_messages(
        user_email: str,
        *,
        columns: str = COLUMNS_ALL,
        channel: Optional[str] = None,
        role: Optional[str] = None,
        descending: bool = False,
        limit: Optional[int] = None,
    ) -> Any:
        """
        The one SELECT builder. Every read below is this chain with a different
        subset of the optional links.

        Args:
            columns:    passed straight to `.select()`. See the COLUMNS_* names.
            channel:    when given, adds `.eq("channel", channel)`.
            role:       when given, adds `.eq("role", role)`.
            descending: `.order("timestamp", desc=…)`. Newest-first only where
                        the caller wants the latest row; everything rendering a
                        transcript reads oldest-first.
            limit:      when given, adds `.limit(limit)`. Omitting it means the
                        caller genuinely wanted every row — two call sites do.
        """
        query = supabase.table(TABLE).select(columns).eq("user_email", user_email)

        if channel is not None:
            query = query.eq("channel", channel)
        if role is not None:
            query = query.eq("role", role)

        query = query.order("timestamp", desc=descending)

        if limit is not None:
            query = query.limit(limit)

        return query.execute()

    @staticmethod
    def list_all(user_email: str) -> Any:
        """
        Every message for a user, oldest first, no limit.

        Callers: `GET /chat/history/{user_email}`, and the reply-loop building
        LLM context from the last few turns.
        """
        return ConversationRepository.list_messages(user_email)

    @staticmethod
    def list_for_channel(
        user_email: str,
        channel: Optional[str] = None,
        *,
        limit: int = 100,
        descending: bool = False,
    ) -> Any:
        """
        Messages on one channel, or all channels when `channel` is None.

        The optional channel exists because two call sites build this query
        conditionally rather than as a fixed chain — `chatupload.get_chat_logs`
        treats the sentinel `"all"` as no filter, and
        `supabase_client.get_conversation_history` takes `channel` as an
        optional argument. Both are expressed here as `channel=None`.
        """
        return ConversationRepository.list_messages(
            user_email, channel=channel, descending=descending, limit=limit
        )

    @staticmethod
    def list_chat_transcript(
        user_email: str,
        *,
        limit: int = 100,
        with_metadata: bool = True,
    ) -> Any:
        """
        The `chat` channel transcript used to rehydrate the UI on resume.

        `with_metadata` is True for the two session-resume endpoints, which need
        the metadata blob to re-render cards; the plain transcript form is used
        where only the text matters.
        """
        columns = (
            COLUMNS_TRANSCRIPT_WITH_METADATA if with_metadata else COLUMNS_TRANSCRIPT
        )
        return ConversationRepository.list_messages(
            user_email, columns=columns, channel="chat", limit=limit
        )

    @staticmethod
    def list_chat_messages(user_email: str, *, limit: int = 100) -> Any:
        """Full rows (`*`) on the `chat` channel, oldest first."""
        return ConversationRepository.list_messages(
            user_email, channel="chat", limit=limit
        )

    @staticmethod
    def list_agent_chat_messages(
        user_email: str, *, limit: Optional[int] = None
    ) -> Any:
        """
        Agent-authored messages on the `chat` channel.

        Both callers use this to find stale generic welcome messages and delete
        them. One caps at 5 rows, the other reads all of them — hence the
        optional limit.
        """
        return ConversationRepository.list_messages(
            user_email, channel="chat", role="agent", limit=limit
        )

    @staticmethod
    def list_transcript(user_email: str, *, limit: Optional[int] = None) -> Any:
        """
        `role, message, timestamp` across all channels, oldest first.

        Used by `onboarding_chat_service`, which filters email-style rows out in
        Python afterwards rather than at the query level.
        """
        return ConversationRepository.list_messages(
            user_email, columns=COLUMNS_TRANSCRIPT, limit=limit
        )

    @staticmethod
    def latest(user_email: str) -> Any:
        """The single most recent message for a user."""
        return ConversationRepository.list_messages(
            user_email, descending=True, limit=1
        )

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    @staticmethod
    def update_metadata(message_id: Any, metadata: dict) -> Any:
        """
        Replace a row's `metadata` column outright.

        Used by GET /conversation-logs's `?language=` cache-fill (Phase 2,
        docs/language-mirroring-verdict.html) to persist a newly-computed
        translation onto `metadata.translations.<language>` so a later
        request for the same conversation + language is a plain read instead
        of another LLM call.

        Supabase's `.update()` only touches the columns given here — role,
        message, timestamp etc. are untouched — but the `metadata` JSONB
        column itself is replaced wholesale, not deep-merged server-side.
        Callers must pass the *complete* metadata dict they want stored
        (read the row, merge in the new key, then call this), not just the
        new key on its own.
        """
        return supabase.table(TABLE).update({"metadata": metadata}).eq("id", message_id).execute()

    # ------------------------------------------------------------------
    # Deletes
    # ------------------------------------------------------------------

    @staticmethod
    def delete_by_id(message_id: Any) -> Any:
        """Delete one message by primary key. Used by the stale-welcome cleanup."""
        return supabase.table(TABLE).delete().eq("id", message_id).execute()

    @staticmethod
    def delete_for_user(user_email: str) -> Any:
        """Delete a user's entire conversation history."""
        return supabase.table(TABLE).delete().eq("user_email", user_email).execute()
