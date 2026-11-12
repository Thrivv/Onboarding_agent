"""
`_find_latest_unverified_document` — newest unconfirmed document for a user.

Moved verbatim out of verification.py in B5. Originally extracted from
handle_verification_response in B5b; this move gives it its own module.

Framework-free: no FastAPI import.
"""

from __future__ import annotations

from __future__ import annotations
import logging
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import traceback
from app.services.message_generator import MessageGenerator, ai_message_gen
from app.services.document_messaging import (
    # generate_dynamic_valid_document_response is not called here — it is
    # re-exported from this module and imported by documentpage.py.
    generate_dynamic_valid_document_response,
    generate_dynamic_invalid_document_response,
    generate_welcome_message,
    generate_ai_reasoning_for_invalid_document,
    generate_unknown_document_reasoning,
    format_extraction_message,
    extract_document_text_for_reasoning,
)
from app.services.chatupload_helpers import (
    user_docs_path,
    member_progress_path,
    get_display_document_name,
    get_allowed_document_types,
    check_documents_status,
    should_request_document,
    load_member_progress,
    get_remaining_required_documents,
    insert_conversation_log,
    
)
from app.services.fatca_service import (
    save_fatca, load_fatca, get_fatca_status, get_fatca_status_disk_only, fatca_json_path
)
from app.services.pep_service import (
    save_pep, load_pep, get_pep_status, get_pep_status_disk_only,
    validate_pep_data, pep_json_path,
)
from app.services.key_individual_service import (
    load_key_individuals, save_key_individual, update_ki_verification,
    update_ki_verification_by_name,
    save_moa_member_as_status, update_member_ubo_status, get_ki_summary,
    ki_json_path, is_account_owner,
)
from app.services.product_package_service import (
    is_package_done, save_package_selection, get_package_selection,
    get_package_status, recommend_package_from_nob,
)
from app.services.cross_validator import CrossValidator
from app.services.supabase_client import supabase, get_user_by_email
from app.services.ocr_service import process_document
from app.services.email_sender import (
    send_email,
    send_tampering_rejection_email,
    send_manual_review_email_tampering,
    send_validation_failed_email,
    send_validation_passed_email,
    send_document_verification_email,
    # send_onboarding_completion_email is not called here — it is re-exported
    # from this module and imported by documentpage.py.
    send_onboarding_completion_email,
    send_corporate_shareholder_request_email,   # TYPE-2
    send_ubo_identified_email,                  # TYPE-2
)
from app.services.eid_validation import validate_eid_before_confirmation
from app.utils.behaviour_capture import capture
from app.domain.onboarding.stages import get_onboarding_status, update_user_onboarding_status
from app.domain.onboarding.confirmation import is_confirmation
from app.domain.onboarding.hvr_audit import audit_mutation, _ki_status_before  # noqa: F401
from app.domain.onboarding.stage_table import (
    OWNERSHIP_SINGLE,
    STAGE_SO_MEMBER_EIDS,
)

logger = logging.getLogger(__name__)


def _find_latest_unverified_document(email: str, user_data: dict) -> dict:
    """
    Scan the user's documents directory for the most recent document that has
    been extracted but not yet confirmed by the user.

    Extracted verbatim from `handle_verification_response` in Stage B5b. The
    statements are unchanged; only their location is.

    Seam verified with `backend/tests/extract_method.py`: the block reads only
    `email` and `user_data`, writes the five values returned below, and
    contains no control flow that escapes it.

    Scope note — why only 87 lines came out of a 1,246-line function
    ---------------------------------------------------------------
    `handle_verification_response` contains **29 `return` statements at up to
    10 levels of nesting**. Almost every block in it exits the request from
    somewhere inside a conditional, so lifting it out would turn "reply to the
    user and stop" into "return from the helper and carry on" — a behaviour
    change that no amount of care makes safe without tests to catch it.

    This one block is the exception: a self-contained scan with a single exit.
    The rest waits for the B0 behavioural capture. See docs/STAGE_B5_RESULT.md.
    """
    root = user_docs_path(email)

    # ✅ Pre-load known member folder names to skip during main-user scan
    known_member_folders = set()
    mp_pre = load_member_progress(email)
    if mp_pre:
        for mn in mp_pre.get("members", []):
            known_member_folders.add(mn)

    latest_doc = None
    latest_time = None
    latest_doc_type = None
    latest_member_name = None
    latest_extracted_data = None

    # ── Single Owner so_member_eids: only member EIDs matter here.
    # Ejari may already be uploaded (user did it early) but must NOT be verified
    # until stage returns to 'identification'. Skipping it from the main-user scan
    # prevents "verify" from marking Ejari verified before the EID.
    _so_eids_stage = (
        user_data.get("ownership_type") == OWNERSHIP_SINGLE and
        user_data.get("document_stage") == STAGE_SO_MEMBER_EIDS
    )
    _EJARI_TYPES = {"ejari", "tenancy", "tenancy contract", "ejari contract", "ejari tenancy contract"}

    # Scan main (non-member) documents
    for item in root.iterdir():
        # ✅ Skip the legacy "members" sentinel AND any real member-named folders
        if not item.is_dir() or item.name in known_member_folders or item.name == "members":
            continue

        out = item / "output.json"
        if not out.exists():
            continue

        try:
            with open(out, "r", encoding="utf-8") as f:
                analysis = json.load(f)

            if not analysis.get("human_verified", False) and analysis.get("is_valid", False):
                # ── so_member_eids guard: skip Ejari until EIDs are done ──────
                _dt = analysis.get("document_type", "").lower()
                if _so_eids_stage and _dt in _EJARI_TYPES:
                    logger.info(f"[VERIFY] ⏭ so_member_eids: skipping Ejari doc (member EIDs must be verified first)")
                    continue

                created = analysis.get("created_at", "")
                if not latest_time or created > latest_time:
                    latest_time = created
                    latest_doc = out
                    latest_doc_type = analysis.get("document_type", "document")
                    latest_member_name = None
                    latest_extracted_data = analysis.get("extracted_data") or analysis.get("extracted_fields", {})
        except Exception:
            pass

    # ✅ Scan member documents
    mp = load_member_progress(email)
    if mp:
        member_names = mp.get("members", [])
        for member_name in member_names:
            member_dir = user_docs_path(email) / member_name
            if not member_dir.exists():
                continue

            for item in member_dir.iterdir():
                if not item.is_dir():
                    continue

                out = item / "output.json"
                if not out.exists():
                    continue

                try:
                    with open(out, "r", encoding="utf-8") as f:
                        analysis = json.load(f)

                    if not analysis.get("human_verified", False) and analysis.get("is_valid", False):
                        created = analysis.get("created_at", "")
                        if not latest_time or created > latest_time:
                            latest_time = created
                            latest_doc = out
                            latest_doc_type = analysis.get("document_type", "document")
                            latest_member_name = member_name
                            latest_extracted_data = analysis.get("extracted_data") or analysis.get("extracted_fields", {})
                except Exception:
                    pass

    return {
        "analysis": analysis,
        "latest_doc": latest_doc,
        "latest_doc_type": latest_doc_type,
        "latest_member_name": latest_member_name,
        "latest_extracted_data": latest_extracted_data,
    }
