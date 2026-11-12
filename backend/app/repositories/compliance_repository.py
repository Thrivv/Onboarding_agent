# backend/app/repositories/compliance_repository.py
"""
Queries against the compliance tables: `fatca_declarations`, `pep_declarations`
and `product_packages`.

All of these use the **service-role client**. That is not incidental — these
tables carry declaration data written on behalf of the user by backend
services, and the anon client does not have the row-level-security grants to
write them. Using the wrong client here fails silently (the write simply
affects zero rows), so the client is fixed in this module rather than left to
the caller.

FATCA and PEP share one shape
-----------------------------
Unlike most of the "duplicates" found during this refactor, these two really
are the same three operations on two tables:

    delete().eq("user_email", …)      # clear any previous declaration
    insert(record)                    # write the new one
    select("*").eq("user_email", …).limit(1)

`fatca_service` and `pep_service` each implemented all three independently and
identically. They are expressed here as one parameterised base with two named
subclasses, so the shared shape lives in one place while `FatcaRepository` and
`PepRepository` stay distinct names at the call sites.

Note the delete-then-insert pairing: it is how both services implement "replace
the declaration". It is not wrapped in a transaction, and was not before —
preserving that is deliberate. Making it atomic is a behaviour change and
belongs to a later stage, not to a move.
"""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.base import supabase_service

logger = logging.getLogger(__name__)


class _DeclarationRepository:
    """
    Shared implementation for the two declaration tables.

    Subclasses set `TABLE`. Not used directly.
    """

    TABLE: str = ""

    @classmethod
    def delete_for_user(cls, email: str) -> Any:
        """Remove any existing declaration for this user."""
        return supabase_service.table(cls.TABLE).delete().eq("user_email", email).execute()

    @classmethod
    def insert(cls, record: dict) -> Any:
        """Write a new declaration row."""
        return supabase_service.table(cls.TABLE).insert(record).execute()

    @classmethod
    def get_for_user(cls, email: str) -> Any:
        """
        Fetch the user's declaration.

        `.limit(1)` rather than `.single()` — the callers check
        `if result.data:` and index `[0]`, and must not raise when the user has
        not declared yet.
        """
        return (
            supabase_service.table(cls.TABLE)
            .select("*")
            .eq("user_email", email)
            .limit(1)
            .execute()
        )


class FatcaRepository(_DeclarationRepository):
    """`fatca_declarations` — Foreign Account Tax Compliance Act responses."""

    TABLE = "fatca_declarations"


class PepRepository(_DeclarationRepository):
    """`pep_declarations` — Politically Exposed Person responses."""

    TABLE = "pep_declarations"


class ProductPackageRepository:
    """`product_packages` — the package a user selected during onboarding."""

    TABLE = "product_packages"

    @staticmethod
    def upsert(record: dict) -> Any:
        """
        Insert or replace this user's package selection.

        `on_conflict="user_email"` makes re-selection idempotent: a user who
        changes their package overwrites the existing row instead of creating a
        second one. That conflict target is part of the contract with the table's
        unique constraint — it is not a tuning knob.
        """
        return (
            supabase_service.table(ProductPackageRepository.TABLE)
            .upsert(record, on_conflict="user_email")
            .execute()
        )
