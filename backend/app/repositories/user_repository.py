# backend/app/repositories/user_repository.py
"""
All queries against the `users` table.

This is the largest slice of B2: **47 inline query chains across 15 modules**,
and — unlike the `sessions` and `conversations` tables — they are genuinely
heterogeneous. Nineteen distinct shapes appear:

  * `select("*")` vs. seven different narrow column lists
  * `.single()` (raises when there is no row, returns a bare object)
    vs. `.limit(1)` (returns a one-element list)
    vs. neither (returns every match)
  * `count="exact"` head-style counts with four different filters
  * plain `.update(...).eq("email", …)` against two *different clients*

The design rule for this file
-----------------------------
**One method per query shape, not one per table.** `.single()` and `.limit(1)`
do not return the same structure — a caller written against one will break
against the other, silently, at runtime. So each variant keeps its own named
method. Where the only difference is the column list, the column list is a
parameter and the named wrappers below record which lists are actually used.

Nothing here changes a query. Every chain is the same chain, in the same order,
with the same arguments as the code it replaced.

The `client` parameter
----------------------
Three groups of callers do not use the default anon client:

  * `chatupload` (3 sites) uses `supabase_service`,
    the service-role client that bypasses row-level security
  * `tampering_service.update_user_tampering_status` receives its client as a
    function argument from the caller

Rather than hard-code one client, every method takes an optional `client` and
defaults to the anon client — which is what the majority of call sites used.
Passing the wrong client here would change what RLS permits, so it is explicit
at every site that needs the service role.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.repositories.base import supabase, supabase_service

logger = logging.getLogger(__name__)

TABLE = "users"

# Column lists used by more than one caller, named so intent is visible at the
# call site rather than being an anonymous string.
COLUMNS_ALL = "*"
COLUMNS_ADMIN_DIRECTORY = (
    "id, email, name, phone_number, business_name, role, account_type, "
    "ownership_type, onboarding_step, created_at"
)


def _client(client: Any = None) -> Any:
    """Resolve the client to use. Defaults to the anon client, as most callers did."""
    return client if client is not None else supabase


class UserRepository:
    """Query methods for the `users` table. Stateless; all methods static."""

    # ------------------------------------------------------------------
    # Reads — full row
    # ------------------------------------------------------------------

    @staticmethod
    def get_by_email(email: str, *, client: Any = None) -> Any:
        """
        `select("*").eq("email", …)` with no limit — returns a LIST response.

        The most common shape by far (6 call sites: login, session verify,
        chat's `get_user_by_email`, the email sender, the reply handler, and
        `supabase_client.get_user_by_email`). Callers index `response.data[0]`
        after checking `response.data`, so the list form matters.
        """
        return _client(client).table(TABLE).select(COLUMNS_ALL).eq("email", email).execute()

    @staticmethod
    def get_by_email_limit_one(email: str, *, client: Any = None) -> Any:
        """
        `select("*").eq("email", …).limit(1)` — still a list response, but the
        database is told to stop after one row.

        Kept separate from :meth:`get_by_email` rather than merged: the wire
        result differs, and `onboarding_chat_service` relies on the cheap form
        because it runs on every chat turn.
        """
        return (
            _client(client)
            .table(TABLE)
            .select(COLUMNS_ALL)
            .eq("email", email)
            .limit(1)
            .execute()
        )

    # ------------------------------------------------------------------
    # Reads — narrow column lists
    # ------------------------------------------------------------------

    @staticmethod
    def select_by_email(
        email: str,
        *columns: str,
        single: bool = False,
        limit: Optional[int] = None,
        client: Any = None,
    ) -> Any:
        """
        The narrow-column builder behind the wrappers below.

        Args:
            *columns: passed straight through to `.select()`. Note that one
                caller (`handle_reply`) passes four *separate* arguments rather
                than one comma-joined string; PostgREST joins them itself, and
                that call is preserved as-is rather than being rewritten.
            single: append `.single()`. This is not a convenience — `.single()`
                returns a bare object instead of a list and **raises** when the
                row is missing. Four callers depend on that; the rest must not
                get it.
            limit: append `.limit(n)`.
        """
        query = _client(client).table(TABLE).select(*columns).eq("email", email)
        if single:
            query = query.single()
        if limit is not None:
            query = query.limit(limit)
        return query.execute()

    @staticmethod
    def get_name(email: str, *, client: Any = None) -> Any:
        """`select("name")` — used by the email sender and the reply handler."""
        return UserRepository.select_by_email(email, "name", client=client)

    @staticmethod
    def get_id(email: str, *, client: Any = None) -> Any:
        """`select("id")` — tampering logging resolves the user id this way."""
        return UserRepository.select_by_email(email, "id", client=client)

    @staticmethod
    def get_email_if_exists(email: str, *, client: Any = None) -> Any:
        """
        `select("email")` — the signup duplicate check.

        Selecting only the key column keeps the existence test from pulling a
        password hash across the wire.
        """
        return UserRepository.select_by_email(email, "email", client=client)

    @staticmethod
    def get_ref_no(email: str, *, client: Any = None) -> Any:
        """`select("ref_no").single()` — document filenames embed the reference."""
        return UserRepository.select_by_email(email, "ref_no", single=True, client=client)

    @staticmethod
    def get_confirmation_flag(email: str, *, client: Any = None) -> Any:
        """`select("document_confirmation_sent").single()` — guards duplicate sends."""
        return UserRepository.select_by_email(
            email, "document_confirmation_sent", single=True, client=client
        )

    @staticmethod
    def get_identity_summary(email: str, *, client: Any = None) -> Any:
        """
        `select("name", "dob", "account_type", "ownership_type")`.

        Passed as four separate arguments at the original call site in
        `handle_reply`; kept that way deliberately.
        """
        return UserRepository.select_by_email(
            email, "name", "dob", "account_type", "ownership_type", client=client
        )

    @staticmethod
    def get_product_profile(email: str, *, client: Any = None) -> Any:
        """
        `select("nature_of_business, annual_turnover, ownership_type").limit(1)`
        — the three fields product-package recommendation scores on.
        """
        return UserRepository.select_by_email(
            email,
            "nature_of_business, annual_turnover, ownership_type",
            limit=1,
            client=client,
        )

    # ------------------------------------------------------------------
    # Reads — counts and listings (admin dashboard)
    # ------------------------------------------------------------------

    @staticmethod
    def count_all(*, client: Any = None) -> Any:
        """
        `select("id", count="exact")` — total users, counted server-side.

        Note the `"id"` rather than `"*"`: PostgREST still returns the matching
        rows alongside the count, so selecting one narrow column keeps the
        payload small. A now-deleted duplicate of this function in
        `supabase_client` fetched every column and counted in Python.
        """
        return _client(client).table(TABLE).select("id", count="exact").execute()

    @staticmethod
    def count_where(column: str, value: Any, *, client: Any = None) -> Any:
        """
        `select("id", count="exact").eq(column, value)`.

        Covers the three equality counts on the dashboard: verified users
        (`onboarding_step == "verification_complete"`), corporate accounts
        (`account_type == "Corporate"`), and the per-step breakdown.
        """
        return (
            _client(client)
            .table(TABLE)
            .select("id", count="exact")
            .eq(column, value)
            .execute()
        )

    @staticmethod
    def count_created_since(since_iso: str, *, client: Any = None) -> Any:
        """
        `select("id", count="exact").gte("created_at", …)` — today's and this
        week's signups differ only in the boundary they pass.
        """
        return (
            _client(client)
            .table(TABLE)
            .select("id", count="exact")
            .gte("created_at", since_iso)
            .execute()
        )

    @staticmethod
    def list_directory(*, client: Any = None) -> Any:
        """
        The admin user list: a fixed column set ordered newest-first.

        Deliberately narrow — it must never return `password_hash`, which
        `select("*")` would.
        """
        return (
            _client(client)
            .table(TABLE)
            .select(COLUMNS_ADMIN_DIRECTORY)
            .order("created_at", desc=True)
            .execute()
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @staticmethod
    def insert(user_data: dict, *, client: Any = None) -> Any:
        """Insert a user row. Callers own id generation and date coercion."""
        return _client(client).table(TABLE).insert(user_data).execute()

    @staticmethod
    def update_by_email(email: str, fields: dict, *, client: Any = None) -> Any:
        """
        `update(fields).eq("email", …)` — every one of the 20 update sites.

        They differ only in the payload and in which client they use, so this is
        the one genuine consolidation in this file. The payloads stay at the
        call sites: they encode onboarding state transitions
        (`document_stage`, `onboarding_step`) that belong with the logic that
        decides them, not with the data access.
        """
        return _client(client).table(TABLE).update(fields).eq("email", email).execute()

    @staticmethod
    def update_by_email_as_service(email: str, fields: dict) -> Any:
        """
        The same update, executed with the **service-role** client so it bypasses
        row-level security.

        Given its own name rather than a boolean flag because choosing the wrong
        client here does not fail loudly — it silently updates nothing.
        """
        return UserRepository.update_by_email(email, fields, client=supabase_service)
