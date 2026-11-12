"""
Stage 1 — the shared state every node reads and writes.

Every field below already exists somewhere today: a Supabase `users` column,
a JSON breadcrumb file under `user_docs_path(email)`, or a local variable
`get_onboarding_status()` recomputes on every call. Nothing here is new
information — this is that same information collected into one typed,
checkpointed object instead of five things re-derived from disk on every
request. See the "Target state model" section of the architecture analysis
for the field-by-field mapping this was designed against.

Deliberately excluded: document bytes, OCR output, tampering reports. Those
stay on disk under `user_docs_path(email)` exactly as today — `doc_status`
here is the same orchestration-relevant summary `check_documents_status()`
already returns, not a copy of the underlying files.
"""

from __future__ import annotations

import operator
from typing import Any, Literal, Optional, TypedDict

from typing_extensions import Annotated


class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class OnboardingState(TypedDict, total=False):
    # ── identity — mirrors the Supabase `users` row ─────────────────────────
    email: str
    ref_no: Optional[str]                 # users.ref_no — see db_migration_ref_no.sql;
                                           # this is also the graph's thread_id (Stage 9)
    account_type: Optional[str]           # "Corporate" | None
    ownership_type: Optional[str]         # "Single Owner" | "Partnership" |
                                           # "Multiple Owners" | None

    # ── stage — two distinct fields, deliberately not collapsed into one ────
    #
    # `document_stage` is the RAW value persisted on the `users` row (what
    # upload.py and member_expansion.py write and branch on directly) — it is
    # the only field that can hold "corporate_shareholder_docs".
    #
    # `stage` is stage_table.resolve_stage()'s REPORTED stage — the value
    # get_onboarding_status() puts in its response for the frontend. Read
    # resolve_stage()'s own docstring closely: for Multiple Owners/Partnership,
    # any `document_stage` other than "identification" — including
    # "corporate_shareholder_docs" — resolves to STAGE_MEMBER_EIDS. The two
    # fields are the same value in most cases, but collapsing them into one
    # field would silently lose the Type-2 (corporate-shareholder) sub-stage
    # distinction that `collect_member_eids` (Stage 7) needs to tell "still
    # collecting a CoI" apart from "collecting member EIDs" — a distinction
    # resolve_stage() itself does not make, by design (see stage_table.py).
    document_stage: Optional[str]         # identification | corporate_shareholder_docs |
                                           # member_eids | so_member_eids | fatca | pep |
                                           # product_package | self_declaration | complete
    stage: str                            # resolve_stage()'s reported stage — always one of
                                           # identification | so_member_eids | member_eids
    required_documents: list[str]         # resolve_stage()'s other return value

    # ── documents — was per-file output.json scanned by check_documents_status()
    #    / get_submitted_documents() on every call ──────────────────────────
    doc_status: dict[str, bool]           # {"commercial": True, "moa": False, ...}
    submitted_documents: list[dict[str, Any]]

    # ── members / KI — was member_progress.json + key_individuals table ────
    members: list[str]
    verified_members: list[str]
    ubo_names: list[str]
    expanded_members: list[dict[str, Any]]   # Type-2 (corporate-shareholder) only
    pending_coi: list[str]                   # Type-2 only — corps still awaiting CoI
    key_individuals: list[dict[str, Any]]    # load_key_individuals(email) snapshot
    ki_loop_done: bool

    # ── compliance — was fatca_status / pep_status / *.json disk flags ──────
    # Values match fatca_service.get_fatca_status_disk_only() /
    # pep_service.get_pep_status_disk_only() exactly — not renamed, so a state
    # field can be compared against the legacy function's return value directly.
    fatca_status: Literal["not_started", "not_applicable", "completed"]
    pep_status: Literal["not_started", "completed"]
    product_package: Optional[str]
    self_declaration_signed: bool

    # ── conversation — was the Supabase `conversations` table, reloaded in
    #    full on every turn by onboarding_chat_service._load_chat_history() ──
    messages: Annotated[list[ChatTurn], operator.add]
    channel: Literal["chat", "email"]

    # ── the interrupt payload currently being waited on, if any — replaces
    #    mismatch_pending.json / pending_ki_role_assignment.json /
    #    ownership_ambiguous.json as one shape instead of four (Section 7 of
    #    the architecture analysis) ──────────────────────────────────────────
    pending_action: Optional[dict[str, Any]]

    # ── transient — Stage 5. Set by the upload route on the single invoke()
    #    call carrying a new file, consumed and cleared by the document node
    #    that handles it within that same call. Never left populated across
    #    a checkpoint: an UploadFile (an open file handle) is not something a
    #    durable checkpointer can serialize, so this must not still be set by
    #    the time a node returns control to the caller (END or an interrupt).
    upload: Optional[dict[str, Any]]      # {"file": UploadFile, "member_name": str|None,
                                           #  "language": str, "precomputed_tampering_result": Any}


__all__ = ["OnboardingState", "ChatTurn"]
