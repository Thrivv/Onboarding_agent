# backend/app/repositories/key_individual_repository.py
"""
Queries against the `key_individuals` table.

Key individuals (KIs) are the owners, partners, directors and signatories
identified from a company's MOA and trade licence. The four query shapes here
correspond to the four points in the KI lifecycle where the record changes:

  1. `upsert`            — a KI is first identified, or re-identified on re-upload
  2. `attach_document`   — their Emirates ID is uploaded and verified
  3. `update_by_id`      — details are corrected or a role is assigned

Uses the **service-role client**, as `key_individual_service` did: these rows are
written on the user's behalf by backend extraction, not by the user's session.
"""

from __future__ import annotations

import logging
from typing import Any

from app.repositories.base import supabase_service

logger = logging.getLogger(__name__)

TABLE = "key_individuals"


class KeyIndividualRepository:
    """Query methods for the `key_individuals` table. Stateless; all methods static."""

    @staticmethod
    def upsert(record: dict) -> Any:
        """
        Insert a KI, or replace it if the same `id` already exists.

        `on_conflict="id"` is what makes document re-upload safe: re-extracting
        the same MOA produces the same deterministic KI ids, so the second pass
        updates the existing rows instead of duplicating every partner.
        """
        return supabase_service.table(TABLE).upsert(record, on_conflict="id").execute()

    @staticmethod
    def attach_document(ki_id: Any, document_id: Any, status: str) -> Any:
        """
        Link a verified identity document to a KI and record the outcome.

        Kept as its own method rather than folded into `update_by_id`: this pair
        of fields always moves together, and naming it makes the KI verification
        step greppable.
        """
        return (
            supabase_service.table(TABLE)
            .update({"document_id": document_id, "verification_status": status})
            .eq("id", ki_id)
            .execute()
        )

    @staticmethod
    def update_by_id(ki_id: Any, fields: dict) -> Any:
        """
        Update arbitrary fields on one KI.

        Two callers use this — the name/details matcher and the role assignment
        step. Their payloads are built from onboarding logic, so they stay at
        the call sites.
        """
        return supabase_service.table(TABLE).update(fields).eq("id", ki_id).execute()
