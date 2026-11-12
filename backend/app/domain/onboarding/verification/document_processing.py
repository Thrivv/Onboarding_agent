"""
`process_uploaded_document` — OCR, extraction and validation of one upload.

Moved verbatim out of verification.py in B5. 862 lines, 12 returns, and one
825-line retry loop that has NOT been decomposed: that is a rewrite, and
nothing covers it yet. See backend/tests/split_verification.py.

This is the only module in app/domain that imports FastAPI, and only for the
`UploadFile` annotation on the `uploaded_file` parameter. That is a signature
coupling, not a logic one, but it is the reason domain/__init__.py cannot
claim the layer is framework-free. Confining it here means the other two
modules split out of verification.py are genuinely clean.
"""

from __future__ import annotations

from __future__ import annotations
import logging
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import UploadFile, File, Form
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
    STAGE_IDENTIFICATION, OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP,
)

logger = logging.getLogger(__name__)


@capture("process_uploaded_document")
def process_uploaded_document(
    email: str,
    uploaded_file: UploadFile,
    member_name: Optional[str],
    language: str = "english",
    precomputed_tampering_result=None,
) -> dict:
    """
    Process uploaded document with tampering detection + EID validation + AI reasoning for failures.

    precomputed_tampering_result: if the caller (upload_conversational) already
    ran verify_document_authenticity on this same file and got ACCEPT, pass
    that DocumentVerificationResult here so this function reuses it instead
    of re-running the full tampering forensics pass (and re-writing the
    tampering DB row) a second time on a fresh copy of the same file.
    """
    
    MAX_RETRIES = 3
    file_path = None
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(
                f"[process_uploaded_document] attempt {attempt}/{MAX_RETRIES} email={email} "
                f"filename={uploaded_file.filename} member={member_name!r} language={language}"
            )

            # ── Resolve ref_no and build temp document id ──────────────────────
            # Get user data
            user = get_user_by_email(email)
            if not user:
                return {
                    "success": False,
                    "message": "User not found. Please ensure you're registered.",
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False
                }

            account_type = user.get("account_type")
            ownership_type = user.get("ownership_type")
            user_name = user.get("name", "").strip().lower()

            is_member = bool(member_name and member_name.strip())
            clean_member_name = member_name.strip() if is_member else None

            # save_as_member controls PHYSICAL STORAGE ONLY (members/ folder vs
            # document root). is_member/clean_member_name are left untouched
            # for everything else in this function — verification messaging,
            # get_member_index calls elsewhere, etc. — since the SO
            # conversational loop still tracks the owner as its first
            # "member" internally to drive the KiLoopCard / role-assignment
            # flow. Only the owner's own EID/Passport is redirected to save
            # at the document root (EID-{ref_no}/, PP-{ref_no}/) like TL-/
            # POS-, instead of members/MEID-{ref_no}-{n}/.
            save_as_member = is_member and not is_account_owner(email, clean_member_name)

            # ✅ NEW: resolve ref_no for this onboarding request
            from app.services.document_helpers import (
                get_document_ref_no, get_user_documents_path_by_ref,
                build_document_id, get_member_index,
            )
            ref_no = user.get("ref_no") or get_document_ref_no(email)

            # Use a temporary document_id for the initial save + tampering.
            # After OCR identifies doc_type, the folder/file is renamed to the
            # proper prefix-based name (e.g. TL-{ref_no}, EID-{ref_no}, etc.)
            import uuid as _uuid_mod
            temp_doc_id = f"tmp_{_uuid_mod.uuid4().hex[:8]}"
            document_id = temp_doc_id  # updated to proper id after OCR

            base_user_dir = get_user_documents_path_by_ref(ref_no)
            base_user_dir.mkdir(parents=True, exist_ok=True)

            if save_as_member:
                members_dir = base_user_dir / "members"
                members_dir.mkdir(parents=True, exist_ok=True)
                save_dir = members_dir / temp_doc_id
                # ocr_service writes to DOCUMENTS_ROOT/{user_email_for_processing}/{document_id}/
                # We pass ref_no/members so output.json lands under members/
                user_email_for_processing = f"{ref_no}/members"
            else:
                save_dir = base_user_dir / temp_doc_id
                user_email_for_processing = ref_no

            # ✅ CRITICAL FIX #1: Define output_json_path EARLY - needed for expiry validation
            output_json_path = save_dir / "output.json"
            
            # SAVE FILE
            if attempt == 1:
                save_dir.mkdir(parents=True, exist_ok=True)
                file_path = save_dir / uploaded_file.filename
                
                with open(file_path, "wb") as f:
                    content = uploaded_file.file.read()
                    f.write(content)
                logger.info(f"[SUCCESS] File saved: {file_path}")
                
                if not file_path.exists():
                    raise RuntimeError(f"File not saved: {file_path}")
                file_size = file_path.stat().st_size
                if file_size == 0:
                    raise RuntimeError(f"File saved but empty: {file_path}")
                    
            else:
                if file_path and file_path.exists():
                    logger.info(f"Retry {attempt}, reusing file: {file_path}")
                else:
                    raise RuntimeError("File path lost during retry")
            
            # ====================================================================
            # TAMPERING DETECTION
            # ====================================================================
            if attempt == 1:
                if precomputed_tampering_result is not None:
                    # Caller (upload_conversational) already ran verify_document_authenticity
                    # on this same file and only gets here on ACCEPT — reuse that result
                    # instead of re-running the full forensics pass + DB update again.
                    tampering_result = precomputed_tampering_result
                    logger.debug(f"[TAMPERING] {email} reusing precomputed result — skipping duplicate check")
                else:
                    from app.services.tampering_service import verify_document_authenticity, update_user_tampering_status

                    # tampering_service already logs one line with the decision,
                    # score and timing for this call — no need to repeat it here.
                    tampering_result = verify_document_authenticity(
                        file_path=str(file_path),
                        user_email=email,
                        doc_type="unknown",
                        send_notifications=False
                    )

                    # ============================================================
                    # ✅ PASSPORT LENIENCY — applied here so it works regardless
                    # of filename or pre-detection.  Passports are multi-colour
                    # photo booklets and naturally score higher than flat EID cards
                    # on JPEG/ELA forensics.  Any ESCALATE with score < 70 where
                    # the image content looks like a passport is downgraded to ACCEPT.
                    # ============================================================
                    if (tampering_result.decision == "ESCALATE"
                            and tampering_result.overall_tampering_score < 70):
                        try:
                            import re as _re
                            _filename = os.path.basename(str(file_path))

                            # ── Tier 1: filename heuristic (no imports needed) ──────────
                            _stem = _filename.rsplit('.', 1)[0].lower()
                            _full = _filename.lower()
                            _passport_hints = [
                                "passport", "passpt", "_pp_", "_pp.", "_pp", "pp_",
                                "intl_id", "travel_doc"
                            ]
                            _is_passport = any(h in _stem for h in _passport_hints) or \
                                           any(h in _full for h in _passport_hints)
                            logger.info(f"[PASSPORT LENIENCY] Filename check '{_filename}': {_is_passport}")

                            # ── Tier 2: imported helper (may not exist in older builds) ──
                            if not _is_passport:
                                try:
                                    from app.services.specialized_ocr.passport_extractor import is_passport_filename as _ipf
                                    _is_passport = _ipf(_filename)
                                    logger.info(f"[PASSPORT LENIENCY] Module filename check: {_is_passport}")
                                except Exception as _imp_err:
                                    logger.info(f"[PASSPORT LENIENCY] Module import skipped: {_imp_err}")

                            # ── Tier 3: OCR text check ────────────────────────────────────
                            if not _is_passport:
                                try:
                                    from app.services.ocr_service import run_ocr, QWEN_MODEL_NAME
                                    _ocr_text = run_ocr(str(file_path), QWEN_MODEL_NAME) or ""
                                    # MRZ lines are definitive passport signals
                                    _is_passport = (
                                        bool(_re.search(r'P<[A-Z]{3}', _ocr_text)) or
                                        bool(_re.search(r'[A-Z0-9]{9}<\d{7}', _ocr_text)) or
                                        bool(_re.search(r'(?i)passport', _ocr_text)) or
                                        bool(_re.search(r'(?i)republic of india', _ocr_text))
                                    )
                                    logger.info(f"[PASSPORT LENIENCY] OCR text check: {_is_passport}")
                                    if not _is_passport:
                                        try:
                                            from app.services.specialized_ocr.passport_extractor import is_passport_text as _ipt
                                            _is_passport = _ipt(_ocr_text)
                                            logger.info(f"[PASSPORT LENIENCY] Module text check: {_is_passport}")
                                        except Exception:
                                            pass
                                except Exception as _ocr_err:
                                    logger.info(f"[PASSPORT LENIENCY] OCR check skipped: {_ocr_err}")

                            if _is_passport:
                                logger.info(
                                    f"[PASSPORT LENIENCY] ESCALATE ({tampering_result.overall_tampering_score:.1f}) "
                                    f"→ ACCEPT  (passport forensic baseline is naturally higher than EID)"
                                )
                                tampering_result.decision = "ACCEPT"
                                tampering_result.status = "AUTHENTIC"
                                tampering_result.reason = (
                                    "Passport forensic baseline accepted "
                                    "(score within normal range for passport documents)"
                                )
                            else:
                                logger.error(f"[PASSPORT LENIENCY] Not identified as passport — keeping ESCALATE")
                        except Exception as _leniency_err:
                            logger.info(f"[PASSPORT LENIENCY] check failed (non-fatal): {_leniency_err}")

                    if tampering_result.test_report_id:
                        from app.services.supabase_client import get_supabase_client
                        supabase = get_supabase_client()

                        update_user_tampering_status(
                            user_email=email,
                            test_report_id=tampering_result.test_report_id,
                            decision=tampering_result.decision,
                            tampering_score=tampering_result.overall_tampering_score,
                            supabase_client=supabase
                        )

                    # ============================================================
                    # ✅ HANDLE REJECT/ESCALATE - USE MESSAGEGENERATOR
                    # ============================================================
                    if tampering_result.decision in ["REJECT", "ESCALATE"]:
                        logger.info(f"{'REJECT' if tampering_result.decision == 'REJECT' else 'ESCALATE'} [TAMPERING] Generating AI explanation")
                    
                        # ✅ GENERATE AI MESSAGE - NO DATABASE QUERY HERE
                        import app.services.message_generator as msg_gen_module
                    
                        if tampering_result.decision == "REJECT":
                            llm_reasoning_message = msg_gen_module.MessageGenerator.generate_tampering_rejection_message(
                                tampering_result=tampering_result,
                                language=language
                            )
                        else:  # ESCALATE
                            llm_reasoning_message = msg_gen_module.MessageGenerator.generate_tampering_escalation_message(
                                tampering_result=tampering_result,
                                language=language
                            )
                    
                        logger.info(f"[SUCCESS] AI reasoning message generated ({len(llm_reasoning_message)} chars)")
                    
                        # Log to conversation
                        tampering_metadata = {
                            "message_type": "tampering_warning",
                            "decision": tampering_result.decision,
                            "tampering_score": tampering_result.overall_tampering_score,
                            "test_report_id": tampering_result.test_report_id,
                            "display_config": {
                                "format": "warning_banner",
                                "severity": "high" if tampering_result.decision == "REJECT" else "medium"
                            },
                            "language": language
                        }
                    
                        try:
                            insert_conversation_log(
                                user_email=email,
                                role="agent",
                                message=llm_reasoning_message,
                                channel="chat",
                                metadata=tampering_metadata
                            )
                            logger.info(f"[SUCCESS] Tampering message logged")
                        except Exception as log_error:
                            logger.warning(f"Failed to log: {log_error}")
                    
                        # Send email
                        try:
                            from app.services.email_sender import send_tampering_rejection_email, send_manual_review_email_tampering
                        
                            if tampering_result.decision == "REJECT":
                                send_tampering_rejection_email(
                                    user_email=email,
                                    reason=llm_reasoning_message,
                                    test_report_id=tampering_result.test_report_id,
                                    doc_type="document"
                                )
                            else:
                                send_manual_review_email_tampering(
                                    user_email=email,
                                    test_report_id=tampering_result.test_report_id,
                                    doc_type="document"
                                )
                            logger.info(f"[SUCCESS] Email sent")
                        except Exception as email_error:
                            logger.error(f"Email failed: {email_error}")
                    
                        # Delete file
                        try:
                            if file_path.exists():
                                file_path.unlink()
                                logger.info(f"File deleted")
                        except Exception as e:
                            logger.warning(f"Delete failed: {e}")
                    
                        # Return error response
                        return {
                            "success": False,
                            "tampering_detected": True,
                            "decision": tampering_result.decision,
                            "message": llm_reasoning_message,
                            "test_report_id": tampering_result.test_report_id,
                            "tampering_score": tampering_result.overall_tampering_score,
                            "document_type": "unknown",
                            "is_valid": False,
                            "is_complete": False,
                            "language": language
                        }
                
                    logger.debug(f"[TAMPERING] {email} accepted — proceeding to extraction")
            
            # ========================================================================
            # STEP 3: OCR EXTRACTION (Existing logic continues)
            # ========================================================================
            
            # Model is auto-selected inside process_document based on doc_type:
            #   EID / Passport  → vision model (llama-3.2-11b-vision-instruct)
            #   All other docs  → text  model (llama-3.3-70b-instruct)
            logger.debug(f"File exists before process_document: {file_path.exists()}")
            logger.debug(f"File size: {file_path.stat().st_size if file_path.exists() else 'N/A'} bytes")

            # === CALL PROCESS_DOCUMENT ===
            try:
                result = process_document(
                    user_email=user_email_for_processing,
                    document_id=document_id,
                    file_path=str(file_path),
                    is_member=is_member,
                )
            except RuntimeError as api_error:
                error_str = str(api_error).lower()
                is_retryable = any(code in error_str for code in ['400', '429', '502', '503', '504', 'timeout', 'connection'])
                
                logger.error(f"process_document failed: {api_error}")
                logger.debug(f"Error string: {error_str}")
                logger.debug(f"Is retryable: {is_retryable}")
                
                if is_retryable and attempt < MAX_RETRIES:
                    logger.info(f"Retrying after API error (attempt {attempt}/{MAX_RETRIES})...")
                    import time
                    time.sleep(2)
                    continue
                else:
                    # ✅ Use MessageGenerator for error message
                    ai_reasoning = MessageGenerator.friendly_error(
                        error_type="Processing Error",
                        context="OCR service temporarily unavailable",
                        doc_type="document",
                        language=language
                    )
                    
                    return {
                        "success": False,
                        "message": ai_reasoning,
                        "document_type": "unknown",
                        "extracted_data": None,
                        "is_valid": False,
                        "ai_reasoning": ai_reasoning,
                        "language": language
                    }
            
            is_valid = result.get("is_valid", False)
            doc_type = result.get("document_type", "unknown")
            extracted_data = result.get("extracted_data") or result.get("extracted_fields", {})
            raw_text = result.get("raw_text", "")
            validation_result = result.get("validation", {})

            # ✅ CRITICAL FIX: Normalize document type - case-insensitive + type variations
            original_doc_type = doc_type
            doc_type = doc_type.lower().strip()
            
            # Normalize document type variations
            if doc_type in ["tenancy", "tenancy contract", "ejari contract", "ejari tenancy contract", "ejari"]:
                doc_type = "ejari"
            elif doc_type in ["memorandum", "memorandum of association", "moa", "memorandum of articles"]:
                doc_type = "moa"
            elif doc_type in ["trade license", "trade_license", "commercial license", "commercial"]:
                doc_type = "commercial"
            elif doc_type in ["emirates id", "emirates_id", "identity card", "eid"]:
                doc_type = "eid"
            elif doc_type in ["passport", "travel document", "travel_document", "intl_id"]:
                doc_type = "passport"
            
            if original_doc_type != doc_type:
                logger.info(f"Document type normalized: '{original_doc_type}' → '{doc_type}'")

            # ================================================================
            # ✅ NEW: Rename temp folder/file to proper prefix-based convention
            # Now that doc_type is known, build the canonical document_id:
            #   Main user : {PREFIX}{ref_no}          e.g. TL-{ref_no}
            #   Member    : {PREFIX}{ref_no}-{index}  e.g. MEID-{ref_no}-1
            # ================================================================
            if doc_type != "unknown":
                try:
                    _member_idx = None
                    if save_as_member and clean_member_name:
                        _member_idx = get_member_index(email, clean_member_name)

                    # ── Unclaimed identity doc, Multiple Owner/Partnership ──────
                    # An EID/Passport uploaded with no member_name yet (e.g. bulk-
                    # uploaded alongside Ejari/MOA before the member list exists)
                    # used to always land at the document root as EID-{ref_no}/
                    # PP-{ref_no} — the same naming a corporate document like the
                    # Commercial License gets, even though this is a person's
                    # identity document, not a company one. For Partnership/
                    # Multiple Owner accounts specifically, route it into
                    # members/ with the member-doc naming (MEID-{ref_no} /
                    # MPP-{ref_no}, no index yet since the member it belongs to
                    # isn't known) instead — reconcile_unclaimed_identity_docs
                    # later renames it in place to the real MEID-/MPP-{ref_no}-
                    # {index} once the member list is finalized and the OCR'd
                    # name is matched. Single Owner is deliberately excluded:
                    # ownership_type won't match, so the owner's own EID/
                    # Passport keeps saving at the root exactly as before —
                    # that's an intentional, different design (see
                    # get_member_index's docstring), not an oversight.
                    _is_unclaimed_identity = doc_type in ("eid", "passport") and not save_as_member
                    _route_unclaimed_to_members = (
                        _is_unclaimed_identity
                        and ownership_type in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
                    )

                    _naming_is_member = save_as_member or _route_unclaimed_to_members
                    proper_doc_id = build_document_id(doc_type, ref_no, _naming_is_member, _member_idx)

                    if _route_unclaimed_to_members:
                        members_dir = base_user_dir / "members"
                        members_dir.mkdir(parents=True, exist_ok=True)
                        _dest_parent_dir = members_dir
                    else:
                        _dest_parent_dir = save_dir.parent

                    # ── Avoid silently destroying a second person's ID ──────────
                    # An identity document with no member routing yet (e.g. one
                    # of several EIDs bulk-uploaded together before the member
                    # list exists) resolves to the SAME proper_doc_id as any
                    # other unclaimed EID/passport — build_document_id has no
                    # per-file uniqueness for is_member=False (nor, here, for the
                    # index-less MEID-/MPP-{ref_no} placeholder name used above).
                    # Without this check, the rmtree()+rename() below would
                    # delete whichever unclaimed identity document got here
                    # first and silently keep only the last one. Commercial/
                    # Ejari/MOA intentionally keep the overwrite (re-uploading
                    # your own licence SHOULD replace the old copy) — this only
                    # widens the check for the one case where "already
                    # occupied" can legitimately mean "a different person's
                    # document", not "a correction".
                    if _is_unclaimed_identity:
                        _existing_dir = _dest_parent_dir / proper_doc_id
                        if _existing_dir.exists() and _existing_dir != save_dir:
                            proper_doc_id = f"{proper_doc_id}-{_uuid_mod.uuid4().hex[:6]}"
                            logger.info(
                                f"Unclaimed {doc_type} slot already occupied — "
                                f"keeping both, this one saved as {proper_doc_id}"
                            )

                    _ext = Path(file_path).suffix if file_path else ""
                    _new_filename = f"{proper_doc_id}{_ext}"

                    # Rename the temp folder to the proper document_id — a move
                    # into members/ for the rerouted case above, an in-place
                    # rename otherwise (unchanged from before).
                    _new_save_dir = _dest_parent_dir / proper_doc_id
                    if _new_save_dir.exists():
                        import shutil as _shutil
                        _shutil.rmtree(_new_save_dir)
                    save_dir.rename(_new_save_dir)

                    # Rename the file inside the folder
                    _old_file = _new_save_dir / Path(file_path).name if file_path else None
                    _new_file = _new_save_dir / _new_filename
                    if _old_file and _old_file.exists() and _old_file != _new_file:
                        _old_file.rename(_new_file)

                    # Update output.json to reflect new filename and document_id
                    _new_output_json = _new_save_dir / "output.json"
                    if _new_output_json.exists():
                        with open(_new_output_json, "r", encoding="utf-8") as _f:
                            _oj = json.load(_f)
                        _oj["filename"] = _new_filename
                        _oj["document_id"] = proper_doc_id
                        with open(_new_output_json, "w", encoding="utf-8") as _f:
                            json.dump(_oj, _f, indent=2, ensure_ascii=False)

                    # Update tracking variables for the rest of this function
                    document_id = proper_doc_id
                    save_dir = _new_save_dir
                    file_path = _new_file
                    output_json_path = _new_output_json

                    logger.info(f"Document renamed → {proper_doc_id} ({_new_filename})")

                    # ✅ Best-effort mirror to EXTERNAL_FILE_PATH (no-op if unset;
                    # never raises — a mirror failure must not affect the upload).
                    try:
                        from app.services.document_helpers import mirror_to_external_path
                        mirror_to_external_path(save_dir)
                    except Exception as _mirror_err:
                        logger.warning(f"External mirror failed (non-fatal): {_mirror_err}")

                except Exception as _rename_err:
                    # Non-fatal — the file is saved, just under the temp name
                    logger.warning(f"Post-OCR rename failed (temp name kept): {_rename_err}")
            # ── end rename block ─────────────────────────────────────────────
            # ── If doc_type is still unknown, delete the temp folder so it ──
            # ── doesn't accumulate as tmp_xxx clutter in the root dir. ───────
            else:
                try:
                    if save_dir.exists():
                        import shutil as _shutil_unk
                        _shutil_unk.rmtree(save_dir)
                        logger.info(f"[CLEANUP] Removed unknown-type temp folder: {save_dir.name}")
                except Exception as _unk_err:
                    logger.warning(f"Could not clean unknown temp folder: {_unk_err}")

            # Update output.json with normalized document type
            if output_json_path.exists():
                try:
                    with open(output_json_path, "r", encoding="utf-8") as f:
                        output_data = json.load(f)
                    
                    if output_data.get("document_type", "").lower() != doc_type:
                        logger.info(f"Updating output.json: document_type → '{doc_type}'")
                        output_data["document_type"] = doc_type
                        
                        with open(output_json_path, "w", encoding="utf-8") as f:
                            json.dump(output_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.warning(f"Failed to update output.json: {e}")

            logger.info(f"Document processed: type={doc_type}, valid={is_valid}")
                        
            # === HANDLE UNKNOWN DOCUMENT TYPE ===
            if doc_type == "unknown":
                logger.warning(f"Unknown document type detected")
                
                # Get allowed documents for user's account
                allowed_info = get_allowed_document_types(
                    user.get("account_type"),
                    user.get("ownership_type"),
                    user.get("document_stage", STAGE_IDENTIFICATION)
                )
                
                logger.info(f"[UNKNOWN DOC] Required docs: {allowed_info.get('required_docs', [])}")
                
                # ✅ CALL THE INTELLIGENT REASONING FUNCTION WITH LANGUAGE
                ai_error_message = generate_unknown_document_reasoning(
                    raw_text=raw_text,
                    file_path=str(file_path),
                    user_data=user,
                    allowed_info=allowed_info,
                    member_name=clean_member_name,
                    language=language
                )
                
                error_message = ai_error_message
                logger.info(f"[SUCCESS] Unknown document reasoning generated")
                logger.info(f"[SUCCESS] Preview: {error_message[:150]}...")
                
                return {
                    "success": False,
                    "message": error_message,
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False,
                    "ai_reasoning": error_message,
                    "language": language
                }
            
            # === EID VALIDATION LOGIC ===
            if doc_type.lower() == "eid" and is_valid:
                name = (extracted_data.get("Name") or 
                        extracted_data.get("name") or 
                        extracted_data.get("full_name") or 
                        extracted_data.get("Full Name") or "").strip()
                
                id_number = (extracted_data.get("ID Number") or 
                            extracted_data.get("id_number") or 
                            extracted_data.get("card_number") or 
                            extracted_data.get("Card Number") or "").strip()
                
                nationality = (extracted_data.get("Nationality") or 
                              extracted_data.get("nationality") or "").strip()
                
                dob = (extracted_data.get("Date of Birth") or 
                       extracted_data.get("date_of_birth") or 
                       extracted_data.get("DOB") or 
                       extracted_data.get("dob") or "").strip()
                
                logger.debug(f"EID Field Check (Attempt {attempt}):")
                logger.info(f"  - Name: '{name}' (empty: {not name})")
                logger.info(f"  - ID Number: '{id_number}' (empty: {not id_number})")
                logger.info(f"  - Nationality: '{nationality}' (empty: {not nationality})")
                logger.info(f"  - DOB: '{dob}' (empty: {not dob})")
                
                is_placeholder = (
                    "john doe" in name.lower() or
                    "jane doe" in name.lower() or
                    "xxxx" in id_number.lower() or
                    "0000" in id_number or
                    name in ["", "N/A", "null", "none"] or
                    id_number in ["", "N/A", "null", "none"] or
                    "can't identify people" in raw_text.lower() or
                    "unable to provide" in raw_text.lower() or
                    raw_text.strip() in ["unsafe", "unsafe\nS1", ""]
                )
                
                logger.debug(f"Placeholder check: {is_placeholder}")
                
                if is_placeholder:
                    logger.warning(f"Detected placeholder/invalid EID data on attempt {attempt}")
                    
                    if attempt < MAX_RETRIES:
                        logger.info(f"Retrying with different model...")
                        continue
                    else:
                        logger.error(f"All {MAX_RETRIES} attempts failed - EID unreadable")
                        
                        ai_reasoning = generate_ai_reasoning_for_invalid_document(
                            raw_text=raw_text,
                            doc_type="eid",
                            validation_result={"is_valid": False, "issues": ["Could not extract EID fields"]},
                            extracted_fields=extracted_data,
                            expected_fields=["Name", "ID Number", "Nationality", "DOB"],
                            member_name=clean_member_name,
                            language=language
                        )
                        
                        return {
                            "success": False,
                            "message": ai_reasoning,
                            "document_type": doc_type,
                            "extracted_data": extracted_data,
                            "is_valid": False,
                            "ai_reasoning": ai_reasoning,
                            "language": language
                        }
                else:
                    logger.info(f"[SUCCESS] EID data appears valid on attempt {attempt}")
                    
                    # === NAME VALIDATION ===
                    # Corporate Single Owner: name validation is intentionally skipped.
                    # The person uploading the EID may not be the registered account holder.
                    # (Savings accounts, the only type this validation used to run for,
                    # have been removed — name validation on this path is now always off.)
                    if not is_member:
                        should_validate_name = False

                        if should_validate_name:
                            extracted_name = name.lower()
                            
                            logger.debug(f"Name Validation Check:")
                            logger.info(f"  - Account Type: {account_type}")
                            logger.info(f"  - Ownership: {ownership_type}")
                            logger.info(f"  - Registered: '{user_name}'")
                            logger.info(f"  - Extracted: '{extracted_name}'")
                            
                            name_match = False
                            if user_name and extracted_name:
                                user_name_parts = set(user_name.split())
                                extracted_name_parts = set(extracted_name.split())
                                common_parts = user_name_parts.intersection(extracted_name_parts)
                                
                                name_match = (
                                    user_name in extracted_name or 
                                    extracted_name in user_name or
                                    len(common_parts) >= 2 or
                                    (len(common_parts) >= 1 and len(user_name_parts) <= 2)
                                )
                            
                            if not name_match:
                                logger.warning(f"Name mismatch detected")
                                
                                # ✅ output_json_path already defined above, just use it
                                if output_json_path.exists():
                                    try:
                                        with open(output_json_path, "r", encoding="utf-8") as f:
                                            output_data = json.load(f)
                                        output_data["is_valid"] = False
                                        output_data["validation"] = output_data.get("validation", {})
                                        output_data["validation"]["name_mismatch"] = True
                                        output_data["validation"]["validation_reason"] = "Name mismatch with registered user"
                                        with open(output_json_path, "w", encoding="utf-8") as f:
                                            json.dump(output_data, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        logger.error(f"Failed to update output.json: {e}")
                                
                                # ✅ Use MessageGenerator for name mismatch
                                ai_reasoning = MessageGenerator.generate_error_message(
                                    error_type="name_mismatch",
                                    doc_type="eid",
                                    user=user,
                                    error_details={
                                        "issues": [f"Name mismatch: registered '{user_name}' vs extracted '{extracted_name}'"]
                                    },
                                    language=language
                                )
                                
                                return {
                                    "success": False,
                                    "message": ai_reasoning,
                                    "document_type": doc_type,
                                    "extracted_data": extracted_data,
                                    "is_valid": False,
                                    "ai_reasoning": ai_reasoning,
                                    "language": language
                                }
                            else:
                                logger.info(f"[SUCCESS] Name validation passed for EID")
            
            # ✅ CRITICAL FIX #2: Check expiry BEFORE normal validation failure handling
            # === HANDLE VALIDATION FAILURE ===
            if not is_valid:
                # 🆕 CHECK IF FAILURE IS DUE TO EXPIRY
                if output_json_path.exists():
                    try:
                        with open(output_json_path, 'r', encoding='utf-8') as f:
                            saved_data = json.load(f)
                        
                        expiry_val = saved_data.get("expiry_validation")
                        
                        # If document is expired, DON'T retry - return immediately
                        if expiry_val and expiry_val.get("document_status") == "EXPIRED":
                            logger.error(f"[EXPIRY] Document expired - stopping retries")
                            
                            # Map doc_type to validator doc_type
                            doc_type_mapping = {
                                "eid": "eid",
                                "ejari": "ejari",
                                "commercial": "commercial_license",
                                "passport": "passport",
                            }
                            validator_doc_type = doc_type_mapping.get(doc_type, doc_type)
                            
                            # Get the AI-generated message from output.json
                            expiry_message = saved_data.get("status_message")
                            
                            # If no message in output.json, generate one
                            if not expiry_message:
                                try:
                                    from app.services.document_expiry_validator import generate_expiry_failure_message
                                    expiry_message = generate_expiry_failure_message(
                                        doc_type=validator_doc_type,
                                        expiry_date_found=expiry_val.get("expiry_date_found"),
                                        current_date=expiry_val.get("current_date"),
                                        reason=expiry_val.get("expiry_reason")
                                    )
                                except Exception as e:
                                    logger.warning(f"[EXPIRY] Failed to generate message: {e}")
                                    expiry_message = "Document has expired. Please upload a valid document."
                            
                            return {
                                "success": False,
                                "message": expiry_message,
                                "document_type": doc_type,
                                "extracted_data": None,  # 🆕 NO DATA
                                "is_valid": False,
                                "ai_reasoning": expiry_message,
                                "language": language,
                                "expiry_failed": True
                            }
                    except Exception as e:
                        logger.warning(f"Could not check expiry: {e}")
                
                # If not an expiry issue, continue with normal retry logic
                if attempt < MAX_RETRIES:
                    logger.info(f"Validation failed on attempt {attempt}, retrying...")
                    continue
                else:
                    logger.error(f"All {MAX_RETRIES} validation attempts exhausted")
                    
                    ai_reasoning = generate_ai_reasoning_for_invalid_document(
                        raw_text=raw_text,
                        doc_type=doc_type,
                        validation_result=validation_result,
                        extracted_fields=extracted_data,
                        expected_fields=validation_result.get('required_fields', []) if validation_result else [],
                        member_name=clean_member_name,
                        language=language
                    )
                    
                    return {
                        "success": False,
                        "message": ai_reasoning,
                        "document_type": doc_type,
                        "extracted_data": extracted_data,
                        "is_valid": False,
                        "ai_reasoning": ai_reasoning,
                        "language": language
                    }
            
            # === SUCCESS PATH ===
            logger.info(f"[SUCCESS] Document validated successfully on attempt {attempt}")

            # ============================================================================
            # 🆕 CHECK EXPIRY VALIDATION FROM OUTPUT.JSON (for valid documents too)
            # ============================================================================
            expiry_failed = False
            expiry_message = None
            
            if output_json_path.exists():
                try:
                    with open(output_json_path, 'r', encoding='utf-8') as f:
                        saved_data = json.load(f)
                    
                    expiry_val = saved_data.get("expiry_validation")
                    
                    if expiry_val and expiry_val.get("document_status") == "EXPIRED":
                        expiry_failed = True
                        logger.error(f"[EXPIRY] Document expired: {expiry_val.get('expiry_reason')}")
                        
                        # Map doc_type to validator doc_type
                        doc_type_mapping = {
                            "eid": "eid",
                            "ejari": "ejari",
                            "commercial": "commercial_license",
                            "passport": "passport",
                        }
                        validator_doc_type = doc_type_mapping.get(doc_type, doc_type)
                        
                        # Generate AI message
                        try:
                            from app.services.document_expiry_validator import generate_expiry_failure_message
                            expiry_message = generate_expiry_failure_message(
                                doc_type=validator_doc_type,
                                expiry_date_found=expiry_val.get("expiry_date_found"),
                                current_date=expiry_val.get("current_date"),
                                reason=expiry_val.get("expiry_reason")
                            )
                        except Exception as e:
                            logger.warning(f"[EXPIRY] Failed to generate message: {e}")
                            # Use the message from output.json if available
                            expiry_message = saved_data.get("status_message") or "Document has expired. Please upload a valid document."
                            
                except Exception as e:
                    logger.warning(f"Could not check expiry: {e}")
            
            # If expired, return error response
            if expiry_failed:
                logger.error(f"[EXPIRY] Returning expiry error response")
                return {
                    "success": False,
                    "message": expiry_message,
                    "document_type": doc_type,
                    "extracted_data": None,  # 🆕 NO DATA for expired docs
                    "is_valid": False,
                    "ai_reasoning": expiry_message,
                    "language": language,
                    "expiry_failed": True
                }

            # ✅ NORMALIZE extracted data BEFORE returning (so both endpoints get flat data)
            from app.services.data_normalizer import normalize_extracted_data

            # Don't normalize commercial licenses - they need nested structure for frontend
            if doc_type.lower() == "commercial":
                extracted_data_for_response = extracted_data
                logger.info(f"Preserving nested structure for commercial license")
            else:
                extracted_data_for_response = normalize_extracted_data(extracted_data, doc_type)
                logger.debug(f"Normalized {doc_type} data")

            logger.debug(f"Response data keys: {list(extracted_data_for_response.keys())}")

            # Get extracted message
            message = format_extraction_message(doc_type, extracted_data_for_response, clean_member_name)

            logger.info(f"Returning success response")

            return {
                "success": True,
                "message": message,
                "document_type": doc_type,
                "extracted_data": extracted_data_for_response,
                "is_valid": True,
                "ai_reasoning": None,
                "language": language
            }
                        
        except Exception as e:
            logger.error(f"Unexpected exception on attempt {attempt}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            if attempt < MAX_RETRIES:
                logger.info(f"Retrying after exception...")
                import time
                time.sleep(2)
                continue
            else:
                # ✅ GENERATE FRIENDLY ERROR MESSAGE
                ai_reasoning = MessageGenerator.friendly_error(
                    error_type="Processing Error",
                    context=str(e),
                    doc_type=doc_type if 'doc_type' in locals() else "document",
                    language=language
                )
                
                return {
                    "success": False,
                    "message": ai_reasoning,
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False,
                    "ai_reasoning": ai_reasoning,
                    "language": language
                }
    
    # Fallback at end of all retries (should never reach here)
    fallback_message = MessageGenerator.friendly_error(
        error_type="Processing Failed",
        context="All retry attempts exhausted",
        doc_type=None,
        language=language
    )

    return {
        "success": False,
        "message": fallback_message,
        "document_type": "unknown",
        "extracted_data": None,
        "is_valid": False,
        "language": language
    }
