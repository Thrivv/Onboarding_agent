"""
The document upload pipeline and the endpoints that read back what was
uploaded.

`upload_conversational` (2,391 lines) is the largest function in the codebase.
It is moved here **whole and unedited**. Decomposing it into the eight
collaborators the plan describes is Stage B5, which is gated on the B0
behavioural capture — there is no way to prove a split of a 2,391-line decision
tree preserves its behaviour without recorded real inputs.
"""

import logging
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import UploadFile, File, Form
from fastapi import APIRouter, HTTPException
from pydantic import EmailStr
from fastapi.responses import FileResponse, StreamingResponse
import io
import traceback
from app.i18n import localized
from app.i18n.messages import doc_name
from app.services.message_generator import MessageGenerator, ai_message_gen
from app.utils.language import normalize_language
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
from app.repositories.user_repository import UserRepository
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
from app.services.specialized_ocr.corporate_shareholder_detector import (
    detect_corporate_shareholders as _detect_corps,
    run_type2_analysis as _run_type2,
)
from app import config
from app.schemas.onboarding import ChatMessage, StartConversationRequest, ChatConversationalRequest, UploadConversationalResponse, OnboardingStatusResponse, ValidateRefRequest, CrossValidationRequest
from app.domain.onboarding.documents import _find_commercial_output, delete_invalid_document, extract_members_from_commercial
from app.domain.onboarding.emails import send_wrong_document_type_email_dynamic
from app.domain.onboarding.members import save_member_progress
from app.domain.onboarding.stages import get_onboarding_status, update_user_onboarding_status
from app.domain.onboarding.verification import process_uploaded_document
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)
from app.domain.exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Sub-router. The `/chatupload` prefix and tags are applied once in
# app/api/routes/onboarding/__init__.py, so every path below is unchanged.
router = APIRouter()

@router.post("/upload-conversational")
async def upload_conversational(
    email: EmailStr = Form(...),
    language: str = Form("english"),
    member_name: Optional[str] = Form(None),
    is_ki_loop_add_eid: Optional[str] = Form(None),  # "true" when uploading for AI-added KI
    files: List[UploadFile] = File(...),
):
    # VALIDATE AND NORMALIZE LANGUAGE
    language = normalize_language(language)

    logger.debug(f"[upload_conversational] email={email} language={language.upper()} member={member_name!r}")

    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")

    if not files:
        raise ValidationError("No file provided")

    uploaded_file = files[0]
    user_name = user.get("name", "User")

    # ============================================================================
    # MEMBER NAME RESOLUTION
    # ============================================================================
    clean_member_name = None
    doc_stage = user.get("document_stage", STAGE_IDENTIFICATION)
    ownership = user.get("ownership_type")

    # When this is a KI-loop EID capture, skip ALL member auto-detection so the
    # file is stored at {email}/{doc_id}/ (no member sub-folder). /ki/add-ai will
    # move it to the correct member folder once the role is confirmed.
    _is_ki_loop_add = (is_ki_loop_add_eid or "").lower().strip() == "true"

    if _is_ki_loop_add:
        clean_member_name = None   # force root storage regardless of member_name
        logger.info(f"[KI-LOOP-EID] KI loop EID upload detected — skipping member routing")
    elif member_name is not None and member_name.strip():
        # Explicit member name provided by frontend
        clean_member_name = member_name.strip()
        logger.info(f"Explicit member name provided: '{clean_member_name}'")

    elif ((ownership in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and doc_stage == STAGE_MEMBER_EIDS) or
          (ownership == OWNERSHIP_SINGLE and doc_stage == STAGE_SO_MEMBER_EIDS)):
        logger.info(f"Auto-detecting member mode stage={doc_stage}...")

        mp = load_member_progress(email)
        if mp:
            members = mp.get("members", [])

            # Verified check — read member_progress.json's own "verified_members"
            # list, the SAME source get_onboarding_status trusts to build the
            # progress card and next_required_document.
            #
            # This previously scanned members/*/output.json for a "member_name"
            # field and collected whatever it found. That field is never written
            # — output.json only ever contains filename, document_type, raw_text,
            # extracted_fields, validation, expiry_validation, status_message,
            # is_valid, created_at, human_verified, document_id. (The one place
            # member_name IS written, further down this function, goes into the
            # conversation-log metadata blob, not into output.json.)
            #
            # So verified_on_disk was ALWAYS empty, pending_members was ALWAYS
            # the full member list, and pending_members[0] always resolved to the
            # first member. Every member EID after the first was re-attributed to
            # member #1 and the loop never advanced — while the UI, reading
            # verified_members, correctly showed "1/4" and named the next member.
            # Two sources of truth that disagreed; this is the broken one being
            # pointed at the good one. Same failure get_onboarding_status already
            # documents having fixed for its own copy of this logic.
            _verified_raw = mp.get("verified_members", []) or []
            verified_members_now = [m for m in members if m in _verified_raw]

            pending_members = [m for m in members if m not in verified_members_now]

            # The owner is tracked in member_progress as its first "member" to
            # drive the SO conversational loop, but their EID/Passport is saved
            # at the document ROOT rather than under members/, so they may never
            # appear in verified_members. Check doc_status directly for the owner
            # so an already-done owner isn't perpetually re-selected as pending.
            if pending_members and is_account_owner(email, pending_members[0]):
                _owner_doc_status = check_documents_status(email)
                if _owner_doc_status.get("eid") or _owner_doc_status.get("passport"):
                    pending_members = pending_members[1:]

            logger.info(
                f"[MEMBER-ROUTE] {email} members={len(members)} "
                f"verified={verified_members_now} pending={pending_members}"
            )

            if pending_members:
                clean_member_name = pending_members[0]
                logger.info(f"Auto-detected pending member: '{clean_member_name}'")
            else:
                logger.info(f"All members already verified — no pending member")
    else:
        logger.info(f"Processing as main user document")

    # ============================================================================
    # SAVE FILE
    # ============================================================================
    # NEW: Use ref_no as the root folder; temp document_id until OCR identifies type
    from app.services.document_helpers import (
        get_document_ref_no, get_user_documents_path_by_ref,
    )
    _ref_no_upload = user.get("ref_no") or get_document_ref_no(email)
    import uuid as _uuid_upload
    _temp_doc_id = f"tmp_{_uuid_upload.uuid4().hex[:8]}"
    document_id = _temp_doc_id  # will be updated to prefix-based name after OCR

    # This is only the TEMP save used for the pre-OCR tampering check —
    # process_uploaded_document() below saves the final, properly-named copy
    # and independently decides members/ vs root (it also special-cases the
    # account owner). clean_member_name itself is left untouched here on
    # purpose: it's read by ~50 downstream verification/messaging blocks in
    # this function, so only the physical path for this temp file changes.
    _save_temp_as_member = bool(clean_member_name) and not is_account_owner(email, clean_member_name)

    _base_upload_dir = get_user_documents_path_by_ref(_ref_no_upload)
    if _save_temp_as_member:
        _members_dir = _base_upload_dir / "members"
        _members_dir.mkdir(parents=True, exist_ok=True)
        file_path = _members_dir / _temp_doc_id / uploaded_file.filename
    else:
        file_path = _base_upload_dir / _temp_doc_id / uploaded_file.filename

    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "wb") as f:
        content = await uploaded_file.read()
        f.write(content)

    await uploaded_file.seek(0)
    logger.info(f"File saved: {file_path}")

    if not file_path.exists():
        raise DomainError("File save failed - file does not exist")

    file_size = file_path.stat().st_size
    if file_size == 0:
        raise DomainError("File save failed - file is empty")

    logger.info(f"File verified: {file_size} bytes")

    # ============================================================================
    # LOG INITIAL UPLOAD
    # ============================================================================
    upload_metadata_initial = {
        "message_type": "document_upload",
        "document_info": {
            "filename": uploaded_file.filename,
            "document_id": document_id,
            "member_name": clean_member_name,
            "file_type": uploaded_file.content_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "file_size": file_size,
            "file_path": str(file_path)
        }
    }

    try:
        insert_conversation_log(
            user_email=email,
            role="user",
            message=f"📎 Uploaded: {uploaded_file.filename}",
            channel="chat",
            metadata=upload_metadata_initial
        )
        logger.info(f"[SUCCESS] Upload message logged")
    except Exception as log_error:
        logger.warning(f"Failed to log upload message: {log_error}")

    # ============================================================================
    # TAMPERING DETECTION
    # ============================================================================
    from app.services.tampering_service import verify_document_authenticity, update_user_tampering_status
    from app.services.supabase_client import get_supabase_client

    # tampering_service already logs one line with the decision, score and
    # timing for this call — no need to repeat it here.
    tampering_result = verify_document_authenticity(
        file_path=str(file_path),
        user_email=email,
        doc_type="unknown",
        send_notifications=False
    )

    if tampering_result.test_report_id:
        supabase = get_supabase_client()
        update_user_tampering_status(
            user_email=email,
            test_report_id=tampering_result.test_report_id,
            decision=tampering_result.decision,
            tampering_score=tampering_result.overall_tampering_score,
            supabase_client=supabase
        )

    # ── REJECT ──────────────────────────────────────────────────────────────────
    if tampering_result.decision == "REJECT":
        import app.services.message_generator as msg_gen_module
        llm_reasoning_message = msg_gen_module.MessageGenerator.generate_tampering_rejection_message(
            tampering_result=tampering_result,
            language=language
        )
        logger.info(f"[SUCCESS] AI rejection message generated ({len(llm_reasoning_message)} chars)")

        tampering_metadata = {
            "message_type": "tampering_warning",
            "decision": "REJECT",
            "tampering_score": tampering_result.overall_tampering_score,
            "test_report_id": tampering_result.test_report_id,
            "failed_tests": getattr(tampering_result, 'failed_tests', []) or [],
            "display_config": {"format": "warning_banner", "severity": "high", "show_details": True},
            "language": language
        }

        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=llm_reasoning_message, channel="chat",
                metadata=tampering_metadata
            )
        except Exception as log_error:
            logger.warning(f"Failed to log rejection: {log_error}")

        try:
            send_tampering_rejection_email(
                user_email=email,
                reason=llm_reasoning_message,
                test_report_id=tampering_result.test_report_id,
                doc_type="document"
            )
        except Exception as email_error:
            logger.error(f"Failed to send rejection email: {email_error}")

        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Rejected file deleted")
        except Exception as e:
            logger.warning(f"Failed to delete rejected file: {e}")

        return {
            "success": False,
            "tampering_detected": True,
            "decision": "REJECT",
            "message": llm_reasoning_message,
            "llm_analysis": tampering_result.llm_analysis,
            "test_report_id": tampering_result.test_report_id,
            "tampering_score": tampering_result.overall_tampering_score,
            "document_type": "unknown",
            "is_valid": False,
            "is_complete": False,
            "language": language
        }

    # ── ESCALATE ─────────────────────────────────────────────────────────────────
    if tampering_result.decision == "ESCALATE":
        logger.warning(f"ESCALATE [TAMPERING] Generating AI explanation")

        import app.services.message_generator as msg_gen_module
        llm_reasoning_message = msg_gen_module.MessageGenerator.generate_tampering_escalation_message(
            tampering_result=tampering_result,
            language=language
        )
        logger.info(f"[SUCCESS] AI reasoning message generated ({len(llm_reasoning_message)} chars)")

        tampering_metadata = {
            "message_type": "tampering_warning",
            "decision": "ESCALATE",
            "tampering_score": tampering_result.overall_tampering_score,
            "test_report_id": tampering_result.test_report_id,
            "display_config": {"format": "warning_banner", "severity": "medium"},
            "language": language
        }

        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=llm_reasoning_message, channel="chat",
                metadata=tampering_metadata
            )
        except Exception as log_error:
            logger.warning(f"Failed to log escalation: {log_error}")

        try:
            send_manual_review_email_tampering(
                user_email=email,
                test_report_id=tampering_result.test_report_id,
                doc_type="document"
            )
        except Exception as email_error:
            logger.error(f"Failed to send manual review email: {email_error}")

        return {
            "success": True,
            "manual_review_required": True,
            "decision": "ESCALATE",
            "message": llm_reasoning_message,
            "test_report_id": tampering_result.test_report_id,
            "tampering_score": tampering_result.overall_tampering_score,
            "awaiting_verification": True,
            "language": language
        }

    logger.debug(f"[TAMPERING] {email} accepted — proceeding to extraction")

    # ── Capture the outer handler's temp folder path for cleanup after OCR ──────
    _outer_temp_folder = file_path.parent if file_path else None

    # ============================================================================
    # OCR PROCESSING
    # ============================================================================
    # Pass the tampering check we already ran above (tampering_result, ACCEPT —
    # REJECT/ESCALATE already returned early) so process_uploaded_document
    # doesn't re-run the whole forensics pass a second time on the same file.
    result = process_uploaded_document(
        email, uploaded_file, clean_member_name,
        precomputed_tampering_result=tampering_result,
    )

    # NEW: Clean up the outer handler's temp file/folder — process_uploaded_document
    # saves its own properly-named copy.  The tampering check file is now redundant.
    if _outer_temp_folder and _outer_temp_folder.exists():
        try:
            import shutil as _shutil_outer
            _shutil_outer.rmtree(_outer_temp_folder)
            logger.info(f"[CLEANUP] Removed outer temp folder: {_outer_temp_folder.name}")
        except Exception as _ce:
            logger.warning(f"Could not clean outer temp folder: {_ce}")

    # ── Handle failures ──────────────────────────────────────────────────────────
    if not result["success"] or result["document_type"] == "unknown":
        doc_type = result.get("document_type", "unknown")

        logger.info(f"\n{'='*80}")
        logger.warning(f"[PROCESSING] Document processing issue: {doc_type}")
        logger.info(f"{'='*80}\n")

        if doc_type == "unknown":
            try:
                raw_text = result.get("raw_text", "")
                if not raw_text and file_path.exists():
                    raw_text = extract_document_text_for_reasoning(
                        str(file_path), uploaded_file.content_type
                    )

                allowed_info = get_allowed_document_types(
                    user.get("account_type"),
                    user.get("ownership_type"),
                    user.get("document_stage", STAGE_IDENTIFICATION)
                )
                error_message = generate_unknown_document_reasoning(
                    raw_text=raw_text,
                    file_path=str(file_path),
                    user_data=user,
                    allowed_info=allowed_info,
                    member_name=clean_member_name,
                    language=language
                )
            except Exception as ai_error:
                logger.error(f"AI reasoning failed: {ai_error}")
                error_message = (
                    localized(language,
                        en=("I couldn't identify the document type."),
                        es=("No pude identificar el tipo de documento."),
                        ar=("لم أتمكن من تحديد نوع المستند."))
                )
        else:
            error_message = result.get("message", "Document could not be processed")
            try:
                error_message = ai_message_gen.generate_error_message(
                    error_type="processing",
                    doc_type=result.get("document_type", "document"),
                    user=user,
                    error_details={"issues": [error_message]},
                    language=language
                )
            except Exception:
                error_message = (
                    localized(language,
                        en=("I couldn't process your document."),
                        es=("No pude procesar tu documento."),
                        ar=("لم أتمكن من معالجة مستندك."))
                )

        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=f"❌ {error_message}", channel="chat",
                metadata={
                    "message_type": "validation_error",
                    "errors": [error_message],
                    "document_type": doc_type,
                    "is_unknown_document": (doc_type == "unknown"),
                    "language": language
                }
            )
        except Exception as e:
            logger.warning(f"Failed to log error: {e}")

        try:
            send_document_verification_email(
                to_email=email, user_name=user_name,
                document_type=doc_type, status="error",
                reason=error_message, extracted_data=None,
                is_complete=False,
                remaining_documents=get_remaining_required_documents(email, user),
                member_name=clean_member_name
            )
        except Exception as email_error:
            logger.warning(f"Failed to send error email: {email_error}")

        return {
            "success": False,
            "message": error_message,
            "document_type": doc_type,
            "is_valid": False,
            "is_complete": False,
            "language": language
        }

    # ============================================================================
    # DOCUMENT TYPE GATE — already validated / wrong type
    # ============================================================================
    doc_type = result["document_type"]
    logger.info(f"\n[VALIDATION CHECK] doc_type={doc_type}  member={clean_member_name or 'Main User'}\n")

    # ── KI loop EID capture: early return for role assignment ────────────────
    # When the user is adding a new AS/KI via the conversational loop (after
    # clicking "Yes, Add Another" in KiLoopCard), the frontend sets
    # is_ki_loop_add_eid=true.  Skip ALL member-routing, stage, and
    # FATCA logic — just return the OCR data so the frontend can show
    # KiRoleAssignCard for role assignment.  The file is already saved at
    # {email}/{document_id}/ and /ki/add-ai will move it once role is confirmed.
    if _is_ki_loop_add:
        _extracted_ki = result.get("extracted_data") or {}
        _id_label_ki  = "Passport" if doc_type.lower() == "passport" else "Emirates ID"
        # Pull the person's name from the extracted fields so the message is personalised
        # Try EID-style fields first, then passport-style (given_names + surname)
        _ki_person_name = (
            _extracted_ki.get("name_english") or
            _extracted_ki.get("full_name") or
            _extracted_ki.get("name") or
            ""
        ).strip()
        if not _ki_person_name:
            _ki_given   = (_extracted_ki.get("given_names") or "").strip()
            _ki_surname = (_extracted_ki.get("surname") or "").strip()
            if _ki_given or _ki_surname:
                _ki_person_name = f"{_ki_given} {_ki_surname}".strip()
        if _ki_person_name:
            _ki_cap_msg = localized(None,
                en=f"{_id_label_ki} for **{_ki_person_name}** has been successfully verified.\n\nPlease assign a role for this individual below.",
                es=f"El {('pasaporte' if doc_type.lower() == 'passport' else 'Emirates ID')} de **{_ki_person_name}** se ha verificado correctamente.\n\nAsigne un rol a esta persona a continuación.",
                ar=f"تم التحقق بنجاح من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الخاص بـ **{_ki_person_name}**.\n\nيُرجى تعيين دور لهذا الفرد أدناه.")
        else:
            _ki_cap_msg = localized(None,
                en=f"{_id_label_ki} captured successfully.\n\nPlease assign a role for this individual below.",
                es=f"El {('pasaporte' if doc_type.lower() == 'passport' else 'Emirates ID')} se ha registrado correctamente.\n\nAsigne un rol a esta persona a continuación.",
                ar=f"تم تسجيل {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} بنجاح.\n\nيُرجى تعيين دور لهذا الفرد أدناه.")
        logger.info(f"[KI-LOOP-EID] Capture complete — doc_type={doc_type}, doc_id={document_id}")

        # ── Breadcrumb for ki_role_assignment_pending (get_onboarding_status) ──
        # Without this, KiRoleAssignCard only ever appeared because this one
        # response happened to carry is_ai_ki_eid_capture — lost on refresh
        # exactly like the AS/KI and Product Package cards were before their
        # fix. Persist the data needed to rebuild the card; /ki/add-ai deletes
        # this file once the role is actually saved.
        try:
            _ki_role_breadcrumb_path = user_docs_path(email) / "pending_ki_role_assignment.json"
            with open(_ki_role_breadcrumb_path, "w", encoding="utf-8") as _brf:
                json.dump({
                    "extracted_fields": _extracted_ki,
                    "document_id": document_id,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }, _brf, indent=2, ensure_ascii=False)
        except Exception as _kb_write_err:
            logger.warning(f"[KI-LOOP-EID] Could not write pending_ki_role_assignment.json breadcrumb: {_kb_write_err}")

        return {
            "success":                  True,
            "message":                  _ki_cap_msg,
            "acknowledgment":           _ki_cap_msg,
            "is_ai_ki_eid_capture":     True,
            "extracted_fields":         _extracted_ki,
            "document_id":              document_id,
            "is_valid":                 True,
            "document_type":            doc_type,
            "ki_loop_prompt":           False,
            "fatca_trigger":            False,
            "pep_trigger":              False,
            "self_declaration_trigger": False,
            "so_as_trigger":            False,
            "remaining_documents":      [],
            "next_document":            None,
            "tampering_score":          tampering_result.overall_tampering_score,
        }
    # ── End KI loop EID capture ───────────────────────────────────────────────

    # Member documents (EID/passport uploaded for a specific member) must always
    # be accepted — skip the "already validated" gate which only tracks main-user
    # documents and would incorrectly block member uploads when the main user
    # already has a passport on file.
    if clean_member_name:
        should_accept, reason = True, None
        logger.info(f"Member document — skipping already-validated gate for: {clean_member_name}")
    else:
        should_accept, reason = should_request_document(email, doc_type, user)

    if not should_accept:
        logger.info(f"Document should NOT be accepted: {reason}")

        # ── Already validated ────────────────────────────────────────────────────
        if reason and reason.startswith("already_validated_and_verified"):
            remaining_docs = get_remaining_required_documents(email, user)

            try:
                onboarding_status = get_onboarding_status(email, user, skip_welcome=True)
                next_required = onboarding_status.get("next_required_document")
                is_complete = onboarding_status.get("is_complete", False)

                next_doc_type = next_required.get("type") if next_required else None
                next_doc_name = get_display_document_name(next_doc_type) if next_doc_type else None
                requires_member = next_required.get("requires_member_name", False) if next_required else False
                member_name_needed = next_required.get("member_name") if next_required else None

                from app.services.message_generator import MessageGenerator, PROFESSIONAL_BANKING_CONTEXT
                language_instruction = MessageGenerator._build_language_instruction(language)

                if is_complete:
                    completion_context = "All required documents have been submitted and verified."
                    next_step_context = "No additional documents are required. Final verification is in progress."
                elif next_required:
                    completion_context = f"{len(remaining_docs)} document(s) remaining"
                    next_step_context = (
                        f"Next required: Emirates ID or Passport for member {member_name_needed}"
                        if requires_member and member_name_needed
                        else f"Next required document: {next_doc_name or next_doc_type}"
                    )
                else:
                    completion_context = "Processing verification"
                    next_step_context = "Verification in progress"

                prompt = f"""{PROFESSIONAL_BANKING_CONTEXT}
{language_instruction}
TASK: Generate a professional message informing customer their document is already validated.
CONTEXT:
- Document Type: {doc_type.upper()}
- Status: Already successfully validated and verified
- Completion Status: {completion_context}
- Next Step: {next_step_context}
MESSAGE REQUIREMENTS:
1. State this document has already been successfully validated
2. If documents remain, direct them to upload next required document with specific name
3. If no documents remain, state submission is complete
4. Length: 2-3 sentences
5. Tone: Professional, clear, directive
6. NO celebratory language, NO emojis
Generate the message:"""

                already_validated_message = MessageGenerator._generate_with_retry(
                    prompt, "ALREADY_VALIDATED"
                )

            except Exception as ai_error:
                logger.error(f"AI message generation failed: {ai_error}")
                is_complete = False
                next_required = None
                next_doc_type = None
                next_doc_name = None
                requires_member = False
                member_name_needed = None
                already_validated_message = (
                    localized(language,
                        en=(f"Your {doc_type.upper()} has already been successfully validated. "
                    f"{'Please upload the next required document: ' + remaining_docs[0] + '.' if remaining_docs else 'All required documents have been submitted.'}"),
                        es=(f"Su {doc_type.upper()} ya ha sido validado exitosamente. "
                    f"{'Por favor, suba el siguiente documento requerido: ' + remaining_docs[0] + '.' if remaining_docs else 'Todos los documentos requeridos han sido enviados.'}"),
                        ar=(f"تم التحقق من {doc_type.upper()} الخاص بك بنجاح مسبقاً. "
                    f"{'يُرجى تحميل المستند المطلوب التالي: ' + doc_name(remaining_docs[0], 'arabic') + '.' if remaining_docs else 'تم تقديم جميع المستندات المطلوبة.'}"))
                )

            try:
                insert_conversation_log(
                    user_email=email, role="agent",
                    message=already_validated_message, channel="chat",
                    metadata={
                        "message_type": "already_validated",
                        "document_type": doc_type,
                        "remaining_documents": remaining_docs,
                        "language": language
                    }
                )
            except Exception as log_error:
                logger.warning(f"Failed to log: {log_error}")

            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Duplicate file deleted: {file_path}")
            except Exception as delete_error:
                logger.warning(f"Failed to delete duplicate: {delete_error}")

            return {
                "success": False,
                "message": already_validated_message,
                "document_type": doc_type,
                "already_validated": True,
                "is_complete": is_complete,
                "remaining_documents": remaining_docs,
                "next_document": {
                    "type": next_doc_type,
                    "display_name": next_doc_name,
                    "requires_member_name": requires_member,
                    "member_name": member_name_needed
                } if next_required else None,
                "language": language
            }

        # ── Wrong document type ──────────────────────────────────────────────────
        elif reason and reason.startswith("wrong_document_type"):
            logger.error(f"Wrong document type: {doc_type}")

            allowed_info = get_allowed_document_types(
                user.get("account_type"),
                user.get("ownership_type"),
                user.get("document_stage", STAGE_IDENTIFICATION)
            )

            deleted = delete_invalid_document(
                email=email, document_id=document_id,
                doc_type=doc_type, member_name=clean_member_name
            )

            try:
                required_docs = allowed_info.get("required_docs", [])
                dynamic_error_message = ai_message_gen.generate_error_message(
                    error_type="wrong_document",
                    doc_type=doc_type,
                    user=user,
                    error_details={
                        "issues": [f"Expected one of: {', '.join(required_docs)}"],
                        "uploaded_type": doc_type
                    },
                    language=language
                )
            except Exception:
                required_docs = allowed_info.get("required_docs", [])
                dynamic_error_message = (
                    localized(language,
                        en=(f"Wrong document type. I need: {', '.join(required_docs)}."),
                        es=(f"Tipo de documento incorrecto. Necesito: {', '.join(required_docs)}."),
                        ar=(f"نوع المستند غير صحيح. المطلوب: {'، '.join(doc_name(d, 'arabic') for d in required_docs)}."))
                )

            try:
                insert_conversation_log(
                    user_email=email, role="agent",
                    message=dynamic_error_message, channel="chat",
                    metadata={
                        "message_type": "validation_error",
                        "errors": [dynamic_error_message],
                        "uploaded_document_type": doc_type,
                        "expected_documents": allowed_info.get("required_docs", []),
                        "document_deleted": deleted,
                        "language": language
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to log: {e}")

            send_wrong_document_type_email_dynamic(
                to_email=email, user_name=user_name,
                uploaded_doc_type=doc_type, allowed_info=allowed_info,
                email=email, user_data=user, member_name=clean_member_name
            )

            return {
                "success": False,
                "message": dynamic_error_message,
                "document_type": doc_type,
                "is_valid": False,
                "is_complete": False,
                "wrong_document_type": True,
                "remaining_documents": get_remaining_required_documents(email, user),
                "language": language
            }

    # ============================================================================
    # DOCUMENT ACCEPTED — generate preview URL and success message
    # ============================================================================
    logger.info(f"[SUCCESS] Document acceptable: {doc_type}")

    # ── OWNERSHIP AUTO-CLASSIFICATION (fires once, at Commercial License upload) ──
    # Ownership Type is no longer asked upfront. As soon as a Corporate
    # account's Commercial License is verified and no ownership_type has been
    # set yet, classify it from the extracted partner list: 1 partner/owner →
    # Single Owner, 2+ → Multiple Owners/Partnership, none readable → ask the
    # user directly (ownership_ambiguous.json breadcrumb — see
    # ownership_selection_pending in get_onboarding_status()).
    #
    # Setting user["ownership_type"] here — before the Type-2 trigger,
    # mismatch detection, and message-generation blocks below — means all of
    # that existing ownership-aware logic sees the freshly-classified type
    # and behaves exactly as it would for an account that had ownership_type
    # set from the start. No other branch needs to change.
    _ownership_auto_classify_ambiguous = False
    _ownership_freshly_classified = None   # "Single Owner" | "Partnership" | None
    _ownership_partner_count = 0
    if (
        doc_type.lower() in ("commercial", "trade_license", "commercial_license")
        and result.get("is_valid", False)
        and not clean_member_name                       # main-user doc only
        and user.get("account_type") == ACCOUNT_CORPORATE
        and not user.get("ownership_type")
        and user.get("document_stage", STAGE_IDENTIFICATION) == STAGE_IDENTIFICATION
    ):
        try:
            _oc_comm_data = None
            _oc_partners = (result.get("extracted_data") or {}).get("partners", [])
            if not _oc_partners:
                _, _oc_comm_data = _find_commercial_output(email)
                _oc_partners = (
                    (_oc_comm_data or {}).get("extracted_fields", {}).get("partners", [])
                    or (_oc_comm_data or {}).get("partners", [])
                )
            _ownership_partner_count = len(_oc_partners) if isinstance(_oc_partners, list) else 0

            # ── Single Owner licences carry no `partners` array ──────────────
            # The extractor runs one of two paths. Multiple Owners produces
            # `partners[]`; Single Owner produces a single `owner` object and a
            # `legal_type` of "Limited Liability Company - Single Owner(LLC - SO)".
            #
            # Counting only `partners` therefore saw ZERO for every genuine
            # single-owner licence and fell through to "ambiguous", asking the
            # user a question the document had already answered — and which
            # `detect_ownership_type()` had already logged as "Detected: Single
            # Owner" moments earlier.
            #
            # So: before giving up, look at the two signals the extractor does
            # emit for that shape.
            if _ownership_partner_count == 0:
                _oc_extracted = (result.get("extracted_data") or {})
                _oc_fields = (
                    _oc_extracted.get("english")
                    or _oc_extracted
                    or {}
                )
                _oc_owner = (
                    _oc_extracted.get("owner")
                    or (_oc_comm_data or {}).get("owner")
                    or ((_oc_comm_data or {}).get("extracted_fields", {}) or {}).get("owner")
                    or {}
                )
                _oc_legal_type = str(
                    _oc_fields.get("legal_type", "")
                    or ((_oc_comm_data or {}).get("extracted_fields", {}) or {})
                        .get("english", {}).get("legal_type", "")
                    or ""
                )

                _is_single_owner_legal_type = bool(
                    re.search(r"single\s*owner|LLC\s*-\s*SO|L\.L\.C\s*-\s*S\.O",
                              _oc_legal_type, re.IGNORECASE)
                )
                _has_owner_record = bool(_oc_owner) and any(
                    (_oc_owner or {}).get(k) for k in ("name_english", "name", "person_number")
                )

                if _is_single_owner_legal_type or _has_owner_record:
                    _ownership_partner_count = 1
                    logger.info(
                        f"[OWNERSHIP-AUTO] Single Owner detected without a partners[] array "
                        f"(legal_type={_oc_legal_type!r}, owner_record={_has_owner_record}) — "
                        f"classifying from the licence rather than asking"
                    )

            if _ownership_partner_count == 0:
                _ownership_auto_classify_ambiguous = True
                try:
                    with open(user_docs_path(email) / "ownership_ambiguous.json", "w", encoding="utf-8") as _amb_f:
                        json.dump({
                            "reason": "no_partners_extracted",
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                        }, _amb_f, indent=2)
                except Exception as _amb_write_err:
                    logger.warning(f"[OWNERSHIP-AUTO] Could not write ownership_ambiguous.json: {_amb_write_err}")
                logger.warning(f"[OWNERSHIP-AUTO] No partners extracted from Commercial License for {email} — falling back to manual question")
            else:
                _ownership_freshly_classified = OWNERSHIP_SINGLE if _ownership_partner_count == 1 else OWNERSHIP_PARTNERSHIP
                try:
                    UserRepository.update_by_email_as_service(email, {"ownership_type": _ownership_freshly_classified})
                except Exception as _oc_save_err:
                    logger.warning(f"[OWNERSHIP-AUTO] Could not persist ownership_type: {_oc_save_err}")
                user["ownership_type"] = _ownership_freshly_classified
                logger.info(f"[OWNERSHIP-AUTO] Classified {email} as '{_ownership_freshly_classified}' from {_ownership_partner_count} partner(s) on Commercial License")
        except Exception as _oc_err:
            logger.warning(f"[OWNERSHIP-AUTO] Auto-classification failed (non-fatal, falling back to manual question): {_oc_err}")
            _ownership_auto_classify_ambiguous = True
            try:
                with open(user_docs_path(email) / "ownership_ambiguous.json", "w", encoding="utf-8") as _amb_f2:
                    json.dump({"reason": "classification_exception", "error": str(_oc_err)}, _amb_f2, indent=2)
            except Exception:
                pass
    # ── end OWNERSHIP AUTO-CLASSIFICATION ─────────────────────────────────────

    # ── TYPE-2 EARLY TRIGGER (fires at UPLOAD time, not at "okay" time) ──────
    # When a commercial license with corporate shareholders is uploaded for a
    # Corporate Multiple-Owner account, immediately transition the stage to
    # corporate_shareholder_docs so the next CoI upload is accepted without
    # the user having to type "okay" first.
    _up_pending_coi = None  # track any detected corporate shareholders for use in success message
    if (
        doc_type.lower() in ("commercial", "trade_license", "commercial_license")
        and result.get("is_valid", False)
        and not clean_member_name                       # main-user doc only
        and user.get("account_type") == ACCOUNT_CORPORATE
        and user.get("ownership_type") in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]
        and user.get("document_stage", STAGE_IDENTIFICATION) == STAGE_IDENTIFICATION
    ):
        try:
            # Partners live in extracted_data (nested structure preserved for commercial)
            _up_partners = (
                (result.get("extracted_data") or {}).get("partners", [])
            )
            # Fallback: re-read from saved output.json
            if not _up_partners:
                _, _up_comm_data = _find_commercial_output(email)
                _up_partners = (
                    _up_comm_data.get("extracted_fields", {}).get("partners", [])
                    or _up_comm_data.get("partners", [])
                )
            if _up_partners:
                _up_detection = _detect_corps(_up_partners)
                if _up_detection["has_corporate_shareholders"]:
                    _up_pending_coi = [
                        c["name"] for c in _up_detection["corporate_shareholders"]
                    ]
                    logger.info(f"[TYPE-2 UPLOAD] Corporate shareholders: {_up_pending_coi}")
                    save_member_progress(
                        email, members=[], current_index=0, pending_coi=_up_pending_coi
                    )
                    update_user_onboarding_status(email, False, STAGE_CORPORATE_SHAREHOLDER_DOCS)
                    # Update local user dict AND doc_stage so downstream helpers
                    # (including the stale-clear guard) see the new stage and do NOT
                    # delete the member_progress.json we just saved.
                    user["document_stage"] = STAGE_CORPORATE_SHAREHOLDER_DOCS
                    doc_stage = STAGE_CORPORATE_SHAREHOLDER_DOCS
                    logger.info("[TYPE-2 UPLOAD] Stage → corporate_shareholder_docs (immediate)")
        except Exception as _upe:
            logger.warning(f"Type-2 upload-time check failed (non-fatal): {_upe}")
    # ── end TYPE-2 EARLY TRIGGER ─────────────────────────────────────────────

    # ── v4: Commercial License Mismatch Detection ─────────────────────────────
    # After a valid commercial license is uploaded, compare:
    #   - Registered user name  vs OCR-extracted owner/manager name
    #   - Registered business name vs OCR-extracted business name
    # If either mismatches, flag it for the frontend to show the mismatch modal
    # (no rejection — user chooses to add as Authorized Signatory or Key Individual)
    _mismatch_detected = False
    _mismatch_extracted_name = None
    _mismatch_extracted_business = None
    if (
        doc_type.lower() in ("commercial", "trade_license", "commercial_license")
        and result.get("is_valid", False)
        and not clean_member_name
        and user.get("account_type") == ACCOUNT_CORPORATE
        and user.get("ownership_type") != OWNERSHIP_SINGLE   # Single Owner: no mismatch popup
    ):
        try:
            # Get registered info
            _reg_user_name     = (user.get("full_name") or user.get("name") or "").strip().lower()
            _reg_business_name = (user.get("business_name") or user.get("company_name") or "").strip().lower()

            # Get OCR-extracted info from result or saved output.json
            _ext_data = result.get("extracted_data") or {}
            _ext_fields = _ext_data.get("extracted_fields", _ext_data)
            _ext_owner  = _ext_fields.get("owner") or {}
            _ext_name   = (
                _ext_owner.get("name_english") or
                _ext_fields.get("owner_name") or
                _ext_fields.get("manager_name") or
                _ext_data.get("english", {}).get("owner_name", "")
            ).strip()
            _ext_biz    = (
                _ext_fields.get("business_name_english") or
                _ext_fields.get("trade_name_english") or
                _ext_fields.get("company_name") or
                _ext_data.get("english", {}).get("business_name", "")
            ).strip()

            # Compare names (fuzzy: shared word tokens)
            def _names_match(a: str, b: str) -> bool:
                if not a or not b:
                    return True   # can't compare → assume match
                a_words = set(a.lower().split())
                b_words = set(b.lower().split())
                shared  = a_words & b_words
                return len(shared) >= 1

            _name_ok = _names_match(_reg_user_name, _ext_name)
            _biz_ok  = _names_match(_reg_business_name, _ext_biz)

            _mismatch_found_name = None
            _mismatch_found_biz = None
            if _ext_name and not _name_ok:
                _mismatch_found_name = _ext_name
                _mismatch_found_biz  = _ext_biz or None
                logger.warning(f"[MISMATCH] Name mismatch — registered: '{_reg_user_name}' vs extracted: '{_ext_name}'")
            elif _ext_biz and not _biz_ok:
                _mismatch_found_name = _ext_name or None
                _mismatch_found_biz  = _ext_biz
                logger.warning(f"[MISMATCH] Business mismatch — registered: '{_reg_business_name}' vs extracted: '{_ext_biz}'")
            else:
                logger.info(f"[MISMATCH] Commercial license names match — no mismatch")

            # DEFERRED (not shown immediately): rather than popping the
            # "Document Details Mismatch" modal right here — before the
            # ownership question has even been asked — we just record the
            # finding to a breadcrumb. get_onboarding_status() surfaces it as
            # mismatch_role_pending only once we're actually right before
            # member verification (Ejari verified for Single Owner / MOA
            # verified for Multiple Owner), same gate as the AS/KI role card.
            # _mismatch_detected/_mismatch_extracted_name are intentionally
            # left False/None below so the old immediate-popup trigger in the
            # upload response no longer fires.
            if _mismatch_found_name or _mismatch_found_biz:
                try:
                    _mismatch_breadcrumb = user_docs_path(email) / "mismatch_pending.json"
                    with open(_mismatch_breadcrumb, "w", encoding="utf-8") as _mbf:
                        json.dump({
                            "extracted_name":     _mismatch_found_name,
                            "extracted_business": _mismatch_found_biz,
                            "detected_at":        datetime.now(timezone.utc).isoformat(),
                        }, _mbf, indent=2, ensure_ascii=False)
                except Exception as _mb_err:
                    logger.warning(f"[MISMATCH] Could not write mismatch_pending.json breadcrumb: {_mb_err}")
        except Exception as _me:
            logger.warning(f"[MISMATCH] Mismatch check failed (non-fatal): {_me}")
    # ── end v4 mismatch detection ─────────────────────────────────────────────

    from urllib.parse import quote
    _base = config.API_BASE_PATH
    preview_url = f"{_base}/chatupload/get-document/{email}/{doc_type}/{uploaded_file.filename}"
    if clean_member_name:
        preview_url += f"?member_name={quote(clean_member_name)}"
    logger.info(f"[PREVIEW] {preview_url}")

    remaining_docs = get_remaining_required_documents(email, user)

    # ── v4: trigger flags — initialised early so SO-Ejari blocks can set them ──
    # IMPORTANT: these MUST be initialised BEFORE the _so_ejari_id_stage /
    # _so_ejari_final blocks below, which set fatca_trigger = True.
    # Previously fatca_trigger = False was placed at line ~5499 (after those
    # blocks), which silently reset the True value before the final return dict.
    fatca_trigger     = False
    pep_trigger       = False
    self_decl_trigger = False
    ki_loop_prompt    = False   # KI loop gate: True → show KiLoopCard before FATCA/Ejari

    # ── Type-1 Multiple Owner upload-time trigger ─────────────────────────────
    # When a Multiple Owner / Partnership Commercial License is valid and no
    # corporate shareholders are detected, we auto-transition to member_eids
    # right from the upload response (no "type okay" needed).
    _mo_as_trigger     = False   # becomes moa_as_trigger in the return dict
    _mo_members_list   = []      # members for the AS card
    _mo_ubo_names_list = []      # UBO names
    _mo_stage_transition = False # set True when we advance the stage

    # ── v4: Single Owner message overrides (so_member_eids + identification) ─────
    # In so_member_eids stage the required_all is [] so remaining_docs is empty,
    # but the AI still generates confusing "X documents remain" messages.
    # Override with accurate stage-aware messages instead.
    _is_so_member_eids = (
        result.get("is_valid") and
        user.get("account_type") == ACCOUNT_CORPORATE and
        user.get("ownership_type") == OWNERSHIP_SINGLE and
        user.get("document_stage") == STAGE_SO_MEMBER_EIDS
    )
    # Single Owner Ejari upload in 'identification' stage (after all member EIDs verified)
    _is_so_identification = (
        result.get("is_valid") and
        user.get("account_type") == ACCOUNT_CORPORATE and
        user.get("ownership_type") == OWNERSHIP_SINGLE and
        user.get("document_stage") == STAGE_IDENTIFICATION
    )
    _so_eid_uploaded  = _is_so_member_eids and doc_type.lower() in ("eid", "emirates_id", "passport")
    _so_ejari_final   = _is_so_member_eids and doc_type.lower() in ("ejari", "tenancy")
    # Ejari uploaded in identification stage (the correct stage for Ejari collection)
    _so_ejari_id_stage = _is_so_identification and doc_type.lower() in ("ejari", "tenancy")
    # MOA uploaded in identification stage — new step 1.5, between Commercial
    # and Ejari (see stage_table.py's Single Owner required list).
    _so_moa_id_stage = _is_so_identification and doc_type.lower() in ("moa", "memorandum")

    if _so_moa_id_stage:
        # MOA uploaded for a Single Owner account. Cross-check the extracted
        # owner_name against the Commercial License owner (same pattern as the
        # Ejari company-name check and the EID owner-name check below), then
        # mark it human_verified so the next requested document is Ejari.
        _moa_cv_passed = True
        _moa_cv_commercial_owner = ""
        _moa_cv_moa_owner = ""
        try:
            _cv_moa_inline = CrossValidator()
            _, _comm_data_cv_moa = _find_commercial_output(email)
            if _comm_data_cv_moa:
                _c_ext_moa = _comm_data_cv_moa.get("extracted_fields") or _comm_data_cv_moa.get("extracted_data", {})
                _c_owner_moa = _c_ext_moa.get("owner") or {}
                _moa_cv_commercial_owner = (
                    _c_owner_moa.get("name_english") or
                    _c_ext_moa.get("english", {}).get("owner_name", "")
                ).strip()
                _moa_raw_ext = result.get("extracted_data", {})
                _moa_raw_eng = _moa_raw_ext.get("english", _moa_raw_ext)
                _moa_cv_moa_owner = (_moa_raw_eng.get("owner_name") or "").strip()
                if _moa_cv_commercial_owner and _moa_cv_moa_owner:
                    if not _cv_moa_inline._fuzzy_name_match(_moa_cv_commercial_owner, _moa_cv_moa_owner):
                        _moa_cv_passed = False
                        logger.error(f"[SO-MOA-CV] Owner name mismatch: '{_moa_cv_commercial_owner}' vs '{_moa_cv_moa_owner}'")
                    else:
                        logger.info(f"[SO-MOA-CV] Owner name match: '{_moa_cv_commercial_owner}' vs '{_moa_cv_moa_owner}'")
                else:
                    logger.warning(f"[SO-MOA-CV] Skipping check — missing name(s): commercial='{_moa_cv_commercial_owner}' moa='{_moa_cv_moa_owner}'")
            else:
                logger.warning(f"[SO-MOA-CV] No commercial data found — skipping inline check")
        except Exception as _moa_cv_err:
            logger.warning(f"[SO-MOA-CV] Inline check error (skipping): {_moa_cv_err}")

        if not _moa_cv_passed:
            # Owner mismatch — do NOT auto-verify, inform the user to re-upload
            remaining_docs = []
            dynamic_acknowledgment = (
                localized(language,
                    en=(f"⚠️ The owner name on the MOA does not match your Commercial License.\n\n"
                f"**Commercial License:** {_moa_cv_commercial_owner}\n"
                f"**MOA:** {_moa_cv_moa_owner}\n\n"
                "Please re-upload the correct MOA document that matches your Commercial License."),
                    es=(f"⚠️ El nombre del propietario en el documento MOA no coincide con su Licencia Comercial.\n\n"
                f"**Licencia Comercial:** {_moa_cv_commercial_owner}\n"
                f"**MOA:** {_moa_cv_moa_owner}\n\n"
                "Por favor, vuelva a cargar el documento MOA correcto que corresponda a su Licencia Comercial."),
                    ar=(f"⚠️ اسم المالك في عقد التأسيس لا يطابق الرخصة التجارية.\n\n"
                f"**الرخصة التجارية:** {_moa_cv_commercial_owner}\n"
                f"**عقد التأسيس:** {_moa_cv_moa_owner}\n\n"
                "يُرجى إعادة تحميل عقد التأسيس الصحيح المطابق لرخصتك التجارية."))
            )
            logger.error(f"[SO-MOA-CV] MOA rejected — skipping auto-verify and success flow")
        else:
            # Owner check passed (or no commercial data to check against) — proceed normally
            try:
                _moa_out_path = user_docs_path(email)
                _mp_names_moa = load_member_progress(email)
                _mp_skip_moa = set(_mp_names_moa.get("members", [])) if _mp_names_moa else set()
                for _moa_item in _moa_out_path.iterdir():
                    if not _moa_item.is_dir() or _moa_item.name in _mp_skip_moa or _moa_item.name == "members":
                        continue
                    _moa_out = _moa_item / "output.json"
                    if not _moa_out.exists():
                        continue
                    with open(_moa_out, "r", encoding="utf-8") as _moaf:
                        _moa_data = json.load(_moaf)
                    _moa_dt = _moa_data.get("document_type", "").lower()
                    if _moa_dt in ("moa", "memorandum") and _moa_data.get("is_valid") and not _moa_data.get("human_verified"):
                        _moa_data["human_verified"] = True
                        _moa_data["verified_at"] = datetime.now(timezone.utc).isoformat()
                        with open(_moa_out, "w", encoding="utf-8") as _moaf:
                            json.dump(_moa_data, _moaf, indent=2, ensure_ascii=False)
                        logger.info(f"[v4] MOA auto-marked human_verified for {email}")
            except Exception as _moave:
                logger.warning(f"[v4] Could not auto-verify MOA: {_moave}")

            remaining_docs = []
            _moa_ejari_done = check_documents_status(email).get("ejari", False)
            if _moa_ejari_done:
                # Out-of-order upload: Ejari was already done, MOA is the last
                # piece — the Step 2 trigger below will fire the role card.
                dynamic_acknowledgment = (
                    localized(language,
                        en=("Your MOA (Memorandum of Association) document has been successfully validated and accepted."),
                        es=("Su documento MOA (Memorando de Asociación) ha sido validado y aceptado exitosamente."),
                        ar=("تم التحقق من عقد التأسيس (MOA) وقبوله بنجاح."))
                )
            else:
                dynamic_acknowledgment = (
                    localized(language,
                        en=("Your MOA (Memorandum of Association) document has been successfully validated and accepted.\n\n"
                    "The next step is to upload your **Ejari (Tenancy Contract)**."),
                        es=("Su documento MOA (Memorando de Asociación) ha sido validado y aceptado exitosamente.\n\n"
                    "El siguiente paso es subir su **Contrato de Arrendamiento (Ejari)**."),
                        ar=("تم التحقق من عقد التأسيس (MOA) وقبوله بنجاح.\n\n"
                    "الخطوة التالية هي تحميل **إيجاري (عقد الإيجار)**."))
                )
            logger.info(f"[v4] SO MOA (id stage) verified — ejari_done={_moa_ejari_done}")
    elif _so_ejari_id_stage:
        # Ejari uploaded in identification stage.
        # NEW FLOW: Ejari is step 2 (before role assignment / EID collection).
        # Only fire FATCA if the KI loop is already done (legacy/re-upload path).
        # Otherwise: mark Ejari as human_verified and let the role card (_so_as_trigger)
        # take over — EID collection happens after role assignment.

        # ── [INLINE CV-1] Company name check: Commercial vs Ejari ─────────────
        # Run BEFORE auto-verification. If mismatch, reject the document and
        # ask the user to re-upload. Only applies to Single Owner flow.
        _ej_cv_passed = True
        _ej_cv_commercial_name = ""
        _ej_cv_ejari_name = ""
        try:
            _cv_ej_inline = CrossValidator()
            _, _comm_data_cv_ej = _find_commercial_output(email)
            if _comm_data_cv_ej:
                _c_ext_ej = _comm_data_cv_ej.get("extracted_fields") or _comm_data_cv_ej.get("extracted_data", {})
                _c_eng_ej = _c_ext_ej.get("english", _c_ext_ej)
                _ej_cv_commercial_name = _c_eng_ej.get("company_name_english", "").strip()
                _ej_raw_ext = result.get("extracted_data", {})
                _ej_raw_eng = _ej_raw_ext.get("english", _ej_raw_ext)
                _ej_cv_ejari_name = _ej_raw_eng.get("tenant_company", "").strip()
                if _ej_cv_commercial_name and _ej_cv_ejari_name:
                    if not _cv_ej_inline._fuzzy_name_match(_ej_cv_commercial_name, _ej_cv_ejari_name):
                        _ej_cv_passed = False
                        logger.error(f"[SO-EJ-CV] Company name mismatch: '{_ej_cv_commercial_name}' vs '{_ej_cv_ejari_name}'")
                    else:
                        logger.info(f"[SO-EJ-CV] Company name match: '{_ej_cv_commercial_name}' vs '{_ej_cv_ejari_name}'")
                else:
                    logger.warning(f"[SO-EJ-CV] Skipping check — missing name(s): commercial='{_ej_cv_commercial_name}' ejari='{_ej_cv_ejari_name}'")
        except Exception as _ej_cv_err:
            logger.warning(f"[SO-EJ-CV] Inline check error (skipping): {_ej_cv_err}")

        if not _ej_cv_passed:
            # Company name mismatch — do NOT auto-verify, inform the user to re-upload
            remaining_docs = []
            dynamic_acknowledgment = (
                localized(language,
                    en=(f"⚠️ The company name on the Ejari does not match your Commercial License.\n\n"
                f"**Commercial License:** {_ej_cv_commercial_name}\n"
                f"**Ejari (Tenant Company):** {_ej_cv_ejari_name}\n\n"
                "Please re-upload the correct Ejari document that matches your Commercial License."),
                    es=(f"⚠️ El nombre de la empresa en el documento Ejari no coincide con su Licencia Comercial.\n\n"
                f"**Licencia Comercial:** {_ej_cv_commercial_name}\n"
                f"**Ejari (Empresa Inquilina):** {_ej_cv_ejari_name}\n\n"
                "Por favor, vuelva a cargar el documento Ejari correcto que corresponda a su Licencia Comercial."),
                    ar=(f"⚠️ اسم الشركة في إيجاري لا يطابق الرخصة التجارية.\n\n"
                f"**الرخصة التجارية:** {_ej_cv_commercial_name}\n"
                f"**إيجاري (الشركة المستأجرة):** {_ej_cv_ejari_name}\n\n"
                "يُرجى إعادة تحميل مستند إيجاري الصحيح المطابق لرخصتك التجارية."))
            )
            logger.error(f"[SO-EJ-CV] Ejari rejected — skipping auto-verify and success flow")
        else:
            # Company name check passed (or no commercial data to check against) — proceed normally
            try:
                _ejari_out_path = user_docs_path(email)
                _mp_names_ejari = load_member_progress(email)
                _mp_skip = set(_mp_names_ejari.get("members", [])) if _mp_names_ejari else set()
                for _ej_item in _ejari_out_path.iterdir():
                    if not _ej_item.is_dir() or _ej_item.name in _mp_skip or _ej_item.name == "members":
                        continue
                    _ej_out = _ej_item / "output.json"
                    if not _ej_out.exists():
                        continue
                    with open(_ej_out, "r", encoding="utf-8") as _ejf:
                        _ej_data = json.load(_ejf)
                    _ej_dt = _ej_data.get("document_type", "").lower()
                    if _ej_dt in ("ejari", "tenancy") and _ej_data.get("is_valid") and not _ej_data.get("human_verified"):
                        _ej_data["human_verified"] = True
                        _ej_data["verified_at"] = datetime.now(timezone.utc).isoformat()
                        with open(_ej_out, "w", encoding="utf-8") as _ejf:
                            json.dump(_ej_data, _ejf, indent=2, ensure_ascii=False)
                        logger.info(f"[v4] Ejari auto-marked human_verified for {email}")
            except Exception as _ejve:
                logger.warning(f"[v4] Could not auto-verify Ejari: {_ejve}")

            # Determine if role assignment has already happened (member_progress exists)
            _ki_loop_done_flag = (user_docs_path(email) / "ki_loop_done.json").exists()
            _mp_exists = bool(_mp_names_ejari and _mp_names_ejari.get("members"))
            _so_ej_member_count = len(_mp_names_ejari.get("members", [])) if _mp_names_ejari else 0

            if _mp_exists and _ki_loop_done_flag:
                # Legacy / re-upload path: role assignment + KI loop already done.
                # Re-enabled: Single Owner now runs the same FATCA → PEP →
                # Product Package chain as Multiple Owner instead of skipping
                # straight to Product Package.
                remaining_docs = []
                _so_ej_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                _so_ej_pep_done   = get_pep_status_disk_only(email) == "completed"
                if not _so_ej_fatca_done:
                    fatca_trigger = True
                    dynamic_acknowledgment = (
                        localized(language,
                            en=(f"Your EJARI document has been successfully validated and accepted.\n\n"
                        f"All {_so_ej_member_count} member identity documents have been verified. "
                        "Please complete your **FATCA Declaration** below before proceeding."),
                            es=(f"Su documento EJARI ha sido validado y aceptado exitosamente.\n\n"
                        f"Todos los {_so_ej_member_count} documentos de identidad de los miembros han sido verificados exitosamente. "
                        "Complete su **Declaración FATCA** a continuación."),
                            ar=(f"تم التحقق من مستند إيجاري وقبوله بنجاح.\n\n"
                        f"تم التحقق من جميع مستندات هوية الأعضاء ({_so_ej_member_count}). "
                        "يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه قبل المتابعة."))
                    )
                elif not _so_ej_pep_done:
                    pep_trigger = True
                    dynamic_acknowledgment = (
                        localized(language,
                            en=("FATCA declaration saved. Please complete your **PEP Declaration** below."),
                            es=("Declaración FATCA guardada. Complete su **Declaración PEP** a continuación."),
                            ar=("تم حفظ إقرار فاتكا. يُرجى استكمال **إقرار الأشخاص المعرّضين سياسياً (PEP)** أدناه."))
                    )
                elif not is_package_done(email):
                    product_package_trigger = True
                    dynamic_acknowledgment = (
                        localized(language,
                            en=(f"Your EJARI document has been successfully validated and accepted.\n\n"
                        f"All {_so_ej_member_count} member identity documents have been verified. "
                        "Please complete your **Product Package** below before proceeding."),
                            es=(f"Su documento EJARI ha sido validado y aceptado exitosamente.\n\n"
                        f"Todos los {_so_ej_member_count} documentos de identidad de los miembros han sido verificados exitosamente. "
                        "Complete su **Paquete de Producto** a continuación."),
                            ar=(f"تم التحقق من مستند إيجاري وقبوله بنجاح.\n\n"
                        f"تم التحقق من جميع مستندات هوية الأعضاء ({_so_ej_member_count}). "
                        "يُرجى اختيار **باقة المنتجات** أدناه قبل المتابعة."))
                    )
                else:
                    dynamic_acknowledgment = (
                        localized(language,
                            en=("Your EJARI document has been successfully validated and accepted."),
                            es=("Su documento EJARI ha sido validado y aceptado exitosamente."),
                            ar=("تم التحقق من مستند إيجاري وقبوله بنجاح."))
                    )
                logger.info(f"[v4] SO Ejari (id stage, KI loop done) — fatca_trigger={fatca_trigger} pep_trigger={pep_trigger}")
            else:
                # Normal new flow: Ejari is step 2/3, role assignment not yet done.
                # Mark human_verified (done above) and let _so_as_trigger show the role card.
                remaining_docs = []
                _ejari_moa_done = check_documents_status(email).get("moa", False)
                if _ejari_moa_done:
                    dynamic_acknowledgment = (
                        localized(language,
                            en=("Your EJARI document has been successfully validated and accepted."),
                            es=("Su documento EJARI ha sido validado y aceptado exitosamente."),
                            ar=("تم التحقق من مستند إيجاري وقبوله بنجاح."))
                    )
                    logger.info(f"[v4] SO Ejari (id stage, pre-role-assignment) — role card will follow")
                else:
                    # Out-of-order upload: MOA hasn't been submitted yet — ask for it
                    # before the role card can fire (Step 2 below requires both).
                    dynamic_acknowledgment = (
                        localized(language,
                            en=("Your EJARI document has been successfully validated and accepted.\n\n"
                        "Please also upload your **MOA (Memorandum of Association)** to continue."),
                            es=("Su documento EJARI ha sido validado y aceptado exitosamente.\n\n"
                        "Por favor, suba también su **Memorando de Asociación (MOA)** para continuar."),
                            ar=("تم التحقق من مستند إيجاري وقبوله بنجاح.\n\n"
                        "يُرجى أيضاً تحميل **عقد التأسيس (MOA)** للمتابعة."))
                    )
                    logger.info(f"[v4] SO Ejari (id stage, pre-role-assignment) — waiting for MOA before role card")
    elif _so_ejari_final:
        # Auto-mark Ejari as human_verified (same as _so_ejari_id_stage)
        try:
            _ejari_out_path_f = user_docs_path(email)
            _mp_names_ejari_f = load_member_progress(email)
            _mp_skip_f = set(_mp_names_ejari_f.get("members", [])) if _mp_names_ejari_f else set()
            for _ej_item_f in _ejari_out_path_f.iterdir():
                if not _ej_item_f.is_dir() or _ej_item_f.name in _mp_skip_f or _ej_item_f.name == "members":
                    continue
                _ej_out_f = _ej_item_f / "output.json"
                if not _ej_out_f.exists():
                    continue
                with open(_ej_out_f, "r", encoding="utf-8") as _ejff:
                    _ej_data_f = json.load(_ejff)
                _ej_dt_f = _ej_data_f.get("document_type", "").lower()
                if _ej_dt_f in ("ejari", "tenancy") and _ej_data_f.get("is_valid") and not _ej_data_f.get("human_verified"):
                    _ej_data_f["human_verified"] = True
                    _ej_data_f["verified_at"] = datetime.now(timezone.utc).isoformat()
                    with open(_ej_out_f, "w", encoding="utf-8") as _ejff:
                        json.dump(_ej_data_f, _ejff, indent=2, ensure_ascii=False)
                    logger.info(f"[v4] Ejari (final stage) auto-marked human_verified for {email}")
        except Exception as _ejve_f:
            logger.warning(f"[v4] Could not auto-verify Ejari (final): {_ejve_f}")

        # Re-enabled: Single Owner now runs the same FATCA → PEP → Product
        # Package chain as Multiple Owner instead of skipping straight to
        # Product Package.
        _so_ejf_member_count = len(_mp_names_ejari_f.get("members", [])) if _mp_names_ejari_f else 0
        # FIX: Ejari verified via final path — progression widget must stop.
        remaining_docs = []
        _so_ejf_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
        _so_ejf_pep_done   = get_pep_status_disk_only(email) == "completed"
        if not _so_ejf_fatca_done:
            fatca_trigger = True
            dynamic_acknowledgment = (
                localized(language,
                    en=(f"Your EJARI document has been successfully validated and accepted.\n\n"
                f"All {_so_ejf_member_count} member identity documents have been successfully verified. "
                "Please complete your **FATCA Declaration** below before proceeding."),
                    es=(f"Su documento EJARI ha sido validado y aceptado exitosamente.\n\n"
                f"Todos los {_so_ejf_member_count} documentos de identidad de los miembros han sido verificados exitosamente. "
                "Complete su **Declaración FATCA** a continuación."),
                    ar=(f"تم التحقق من مستند إيجاري وقبوله بنجاح.\n\n"
                f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_so_ejf_member_count}). "
                "يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه قبل المتابعة."))
            )
        elif not _so_ejf_pep_done:
            pep_trigger = True
            dynamic_acknowledgment = (
                localized(language,
                    en=("FATCA declaration saved. Please complete your **PEP Declaration** below."),
                    es=("Declaración FATCA guardada. Complete su **Declaración PEP** a continuación."),
                    ar=("تم حفظ إقرار فاتكا. يُرجى استكمال **إقرار الأشخاص المعرّضين سياسياً (PEP)** أدناه."))
            )
        elif not is_package_done(email):
            product_package_trigger = True
            dynamic_acknowledgment = (
                localized(language,
                    en=(f"Your EJARI document has been successfully validated and accepted.\n\n"
                f"All {_so_ejf_member_count} member identity documents have been successfully verified. "
                "Please complete your **Product Package** below before proceeding."),
                    es=(f"Su documento EJARI ha sido validado y aceptado exitosamente.\n\n"
                f"Todos los {_so_ejf_member_count} documentos de identidad de los miembros han sido verificados exitosamente. "
                "Complete su **Paquete de Producto** a continuación."),
                    ar=(f"تم التحقق من مستند إيجاري وقبوله بنجاح.\n\n"
                f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_so_ejf_member_count}). "
                "يُرجى اختيار **باقة المنتجات** أدناه قبل المتابعة."))
            )
        else:
            dynamic_acknowledgment = (
                localized(language,
                    en=("Your EJARI document has been successfully validated and accepted."),
                    es=("Su documento EJARI ha sido validado y aceptado exitosamente."),
                    ar=("تم التحقق من مستند إيجاري وقبوله بنجاح."))
            )
        logger.info(f"[v4] Single Owner Ejari final stage — auto-advancing (fatca_trigger={fatca_trigger} pep_trigger={pep_trigger})")
    elif _so_eid_uploaded:
        _so_eid_name = clean_member_name or "member"
        # ── Auto-verify the document immediately — no "type okay" needed ─────
        # Previously this block just showed "Please type okay to confirm and proceed"
        # and relied on the chat handle_verification_response to do the actual
        # human_verified marking + member_progress advancement.
        # Problem: if the user uploaded two EIDs before typing "okay", the chat
        # scanner picked them up by timestamp in the wrong order, causing:
        #   - "50% progress, next: Srinivas M" (already verified)
        #   - Ejari being requested and uploaded twice
        # Fix: auto-verify here at upload time, advance member_progress, and
        # return the correct next-step message directly.

        # ── [INLINE CV-2] Owner name + nationality check: Commercial vs EID ──
        # Run BEFORE auto-verification. If mismatch, reject the document and
        # ask the user to re-upload. Only applies to Single Owner flow.
        _eid_cv_passed = True
        _eid_cv_mismatches = []
        _eid_cv_commercial_owner_name = ""
        _eid_cv_commercial_nationality = ""
        _eid_cv_eid_name = ""
        _eid_cv_eid_nationality = ""
        try:
            _cv_eid_inline = CrossValidator()
            _, _comm_data_cv_eid = _find_commercial_output(email)
            if _comm_data_cv_eid:
                _c_ext_eid = _comm_data_cv_eid.get("extracted_fields") or _comm_data_cv_eid.get("extracted_data", {})
                _c_owner_eid = _c_ext_eid.get("owner", {})
                _eid_cv_commercial_owner_name = _c_owner_eid.get("name_english", "").strip()
                _eid_cv_commercial_nationality = _c_owner_eid.get("nationality_english", "").strip()
                _eid_raw_ext = result.get("extracted_data", {})
                _eid_cv_eid_name = (_eid_raw_ext.get("Name") or _eid_raw_ext.get("name") or "").strip()
                _eid_cv_eid_nationality = (_eid_raw_ext.get("Nationality") or _eid_raw_ext.get("nationality") or "").strip()
                # Check owner name
                if _eid_cv_commercial_owner_name and _eid_cv_eid_name:
                    if not _cv_eid_inline._fuzzy_name_match(_eid_cv_commercial_owner_name, _eid_cv_eid_name):
                        _eid_cv_mismatches.append(
                            f"Owner name: Commercial ('{_eid_cv_commercial_owner_name}') vs EID ('{_eid_cv_eid_name}')"
                        )
                        logger.error(f"[SO-EID-CV] Owner name mismatch: '{_eid_cv_commercial_owner_name}' vs '{_eid_cv_eid_name}'")
                    else:
                        logger.info(f"[SO-EID-CV] Owner name match: '{_eid_cv_commercial_owner_name}' vs '{_eid_cv_eid_name}'")
                # Check nationality
                if _eid_cv_commercial_nationality and _eid_cv_eid_nationality:
                    if not _cv_eid_inline._fuzzy_name_match(_eid_cv_commercial_nationality, _eid_cv_eid_nationality):
                        _eid_cv_mismatches.append(
                            f"Nationality: Commercial ('{_eid_cv_commercial_nationality}') vs EID ('{_eid_cv_eid_nationality}')"
                        )
                        logger.error(f"[SO-EID-CV] Nationality mismatch: '{_eid_cv_commercial_nationality}' vs '{_eid_cv_eid_nationality}'")
                    else:
                        logger.info(f"[SO-EID-CV] Nationality match: '{_eid_cv_commercial_nationality}' vs '{_eid_cv_eid_nationality}'")
                if _eid_cv_mismatches:
                    _eid_cv_passed = False
            else:
                logger.warning(f"[SO-EID-CV] No commercial data found — skipping inline check")
        except Exception as _eid_cv_err:
            logger.warning(f"[SO-EID-CV] Inline check error (skipping): {_eid_cv_err}")

        if not _eid_cv_passed:
            # Mismatch detected — do NOT auto-verify, do NOT advance member_progress
            _eid_mismatch_lines = "\n".join([f"- {m}" for m in _eid_cv_mismatches])
            _so_id_label_cv = "Passport" if doc_type.lower() == "passport" else "Emirates ID"
            _so_id_label_cv_es = "Pasaporte" if doc_type.lower() == "passport" else "Emirates ID"
            dynamic_acknowledgment = (
                localized(language,
                    en=(f"⚠️ The information on the {_so_id_label_cv} does not match the Commercial License.\n\n"
                f"{_eid_mismatch_lines}\n\n"
                f"Please re-upload the correct {_so_id_label_cv} that matches the Commercial License."),
                    es=(f"⚠️ La información en el {_so_id_label_cv_es} no coincide con la Licencia Comercial.\n\n"
                f"{_eid_mismatch_lines}\n\n"
                f"Por favor, vuelva a cargar el {_so_id_label_cv_es} correcto que corresponda a la Licencia Comercial."),
                    ar=(f"⚠️ المعلومات الواردة في {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} لا تطابق الرخصة التجارية.\n\n"
                f"{_eid_mismatch_lines}\n\n"
                f"يُرجى إعادة تحميل {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الصحيح المطابق للرخصة التجارية."))
            )
            remaining_docs = []
            logger.error(f"[SO-EID-CV] EID rejected — mismatches: {_eid_cv_mismatches}")
        else:
            # Check passed (or no commercial data) — proceed with auto-verification

            # 1. Mark current document human_verified
            # output.json lives alongside the uploaded file in the same folder.
            # file_path is the uploaded document; file_path.parent is its directory.
            _so_eid_output_json = file_path.parent / "output.json"
            try:
                if _so_eid_output_json.exists():
                    with open(_so_eid_output_json, "r", encoding="utf-8") as _soef:
                        _so_out = json.load(_soef)
                    _so_out["human_verified"] = True
                    _so_out["verified_at"] = datetime.now(timezone.utc).isoformat()
                    with open(_so_eid_output_json, "w", encoding="utf-8") as _soef:
                        json.dump(_so_out, _soef, indent=2, ensure_ascii=False)
                    logger.info(f"[SO-EID] Auto-marked human_verified: {_so_eid_name}")
                else:
                    logger.warning(f"[SO-EID] output.json not found at {_so_eid_output_json}")
            except Exception as _soee:
                logger.warning(f"[SO-EID] Could not auto-verify document: {_soee}")

            # 2. Advance member_progress (add to verified_members, increment index)
            _so_next_member = None
            _so_all_done = False
            try:
                _so_mp = load_member_progress(email)
                if _so_mp:
                    _so_members  = _so_mp.get("members", [])
                    _so_verified = _so_mp.get("verified_members", [])
                    _so_cur_idx  = _so_mp.get("current_index", 0)

                    if _so_eid_name not in _so_verified:
                        _so_verified.append(_so_eid_name)
                        _so_mp["verified_members"] = _so_verified
                        _so_mp["current_index"]    = _so_cur_idx + 1

                    _so_done_count = len(_so_verified)
                    _so_total      = len(_so_members)

                    if _so_done_count < _so_total:
                        _so_new_idx    = _so_mp["current_index"]
                        _so_next_member = (
                            _so_members[_so_new_idx] if _so_new_idx < _so_total else None
                        )
                    else:
                        _so_all_done = True

                    _so_prog_path = member_progress_path(email)
                    with open(_so_prog_path, "w", encoding="utf-8") as _spf:
                        json.dump(_so_mp, _spf, indent=2, ensure_ascii=False)
                    logger.info(f"[SO-EID] member_progress advanced — verified={_so_done_count}/{_so_total}, next={_so_next_member}, all_done={_so_all_done}")
            except Exception as _spe:
                logger.warning(f"[SO-EID] Could not advance member_progress: {_spe}")

            # 3. Determine next step and set message
            _so_id_label = "Passport" if doc_type.lower() == "passport" else "Emirates ID"
            _so_id_label_es = "Pasaporte" if doc_type.lower() == "passport" else "Emirates ID"
            if _so_all_done:
                # ── KI Loop gate (upload path) ───────────────────────────────────
                # All member EIDs are verified.  Before asking for Ejari, check
                # whether the user has finalized the "add another AS/KI?" loop.
                # If ki_loop_done.json is absent, show the KiLoopCard instead.
                # The /ki/loop-finalize endpoint writes the file AND tells the user
                # to upload Ejari, so we only advance once the loop is done.
                _so_ki_loop_done_path = user_docs_path(email) / "ki_loop_done.json"
                if not _so_ki_loop_done_path.exists():
                    _so_loop_msg = localized(language,
                        en=(f"{_so_id_label} for {_so_eid_name} has been successfully validated and accepted.\n\n"
                            f"All identity documents have been verified.\n\n"
                            f"Would you like to add any additional Authorised Signatory "
                            f"or Key Individual to this account?"),
                        es=(f"El {('Pasaporte' if doc_type.lower() == 'passport' else 'Emirates ID')} de {_so_eid_name} ha sido validado y aceptado correctamente.\n\n"
                            f"Todos los documentos de identidad han sido verificados.\n\n"
                            f"¿Desea añadir algún Firmante Autorizado o Persona Clave adicional a esta cuenta?"),
                        ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الخاص بـ {_so_eid_name} وقبوله بنجاح.\n\n"
                            f"تم التحقق من جميع مستندات الهوية.\n\n"
                            f"هل ترغب في إضافة مفوّض بالتوقيع أو فرد رئيسي آخر إلى هذا الحساب؟"))
                    logger.info(f"[SO-EID] KI loop gate: ki_loop_done.json not found — returning ki_loop_prompt")
                    # ── Log extraction_result BEFORE early return so the Verification Hub
                    # sidebar can mark the identity step as VERIFIED ──────────────────────
                    if result.get("is_valid") and result.get("extracted_data"):
                        try:
                            insert_conversation_log(
                                user_email=email, role="agent",
                                message=_so_loop_msg, channel="chat",
                                metadata={
                                    "message_type": "extraction_result",
                                    "document_type": doc_type,
                                    "is_valid": True,
                                    "member_name": clean_member_name,
                                    "language": language,
                                }
                            )
                        except Exception as _ki_log_err:
                            logger.warning(f"[SO-EID] Failed to log extraction before ki_loop_prompt: {_ki_log_err}")
                    return {
                        "success":                  True,   # prevents frontend FIX-4 error guard from intercepting
                        "is_verification":          False,
                        "verified":                 True,
                        "message":                  _so_loop_msg,
                        "is_complete":              False,
                        "ki_loop_prompt":           True,
                        "fatca_trigger":            False,
                        "pep_trigger":              False,
                        "self_declaration_trigger": False,
                        "so_as_trigger":            False,
                        # ── Include doc metadata so the Unified Report labels this correctly ──
                        "document_type":            doc_type,
                        "extracted_fields":         result.get("extracted_data") or result.get("extracted_fields") or {},
                    }
                # ── ki_loop_done.json exists — safe to request Ejari ─────────────
                # All member EIDs done → transition stage back to identification for Ejari
                try:
                    update_user_onboarding_status(email, False, STAGE_IDENTIFICATION)
                    logger.info(f"[SO-EID] Stage: so_member_eids → identification (KI loop done, requesting Ejari)")
                except Exception as _ste2:
                    logger.warning(f"[SO-EID] Stage update failed: {_ste2}")
                # remaining_docs was computed using stale so_member_eids stage data and doesn't
                # include member-directory EIDs. Override with the correct next step.
                remaining_docs = ["Ejari (Tenancy Contract)"]
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"{_so_id_label} for {_so_eid_name} has been successfully validated and accepted.\n\n"
                    f"All identity documents have been verified. Please proceed by uploading the "
                    f"**Ejari (Tenancy Contract)** to complete your document submission."),
                        es=(f"El {_so_id_label_es} para {_so_eid_name} ha sido validado y aceptado exitosamente.\n\n"
                    f"Todos los documentos de identidad han sido verificados. Por favor proceda subiendo el "
                    f"**Ejari (Contrato de Arrendamiento)** para completar su envío de documentos."),
                        ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الخاص بـ {_so_eid_name} وقبوله بنجاح.\n\n"
                    f"تم التحقق من جميع مستندات الهوية. يُرجى المتابعة بتحميل "
                    f"**إيجاري (عقد الإيجار)** لاستكمال تقديم مستنداتك."))
                )
            elif _so_next_member:
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"{_so_id_label} for {_so_eid_name} has been successfully validated and accepted.\n\n"
                    f"Please proceed by uploading the **Emirates ID or Passport** for: **{_so_next_member}**."),
                        es=(f"El {_so_id_label_es} para {_so_eid_name} ha sido validado y aceptado exitosamente.\n\n"
                    f"Por favor proceda subiendo el **Emirates ID o Pasaporte** para: **{_so_next_member}**."),
                        ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الخاص بـ {_so_eid_name} وقبوله بنجاح.\n\n"
                    f"يُرجى المتابعة بتحميل **الهوية الإماراتية أو جواز السفر** لـ: **{_so_next_member}**."))
                )
            else:
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"{_so_id_label} for {_so_eid_name} has been successfully validated and accepted."),
                        es=(f"El {_so_id_label_es} para {_so_eid_name} ha sido validado y aceptado exitosamente."),
                        ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} الخاص بـ {_so_eid_name} وقبوله بنجاح."))
                )
            logger.info(f"[SO-EID] Auto-advanced — all_done={_so_all_done}, next_member={_so_next_member}")
    else:
        # ── FIX D: Guard premature Ejari in upload_conversational (identification stage) ──
        # Scenario: ki_so_as_selection was called (or even skipped) but stage stayed
        # "identification". The EID/passport was uploaded as a main-user identity doc.
        # At this point remaining_docs = ['ejari'], so the AI would say "Please upload
        # your Ejari" — but member_progress still has members whose IDs haven't been
        # collected. Intercept and redirect before the AI message is generated.
        _fixd_triggered = False
        _fixd_id_types = {"eid", "passport", "emirates id", "emirates_id", "emirates id card"}
        if (result.get("is_valid") and
                not clean_member_name and
                doc_type.lower() in _fixd_id_types and
                user.get("account_type") == ACCOUNT_CORPORATE and
                user.get("ownership_type") == OWNERSHIP_SINGLE and
                user.get("document_stage") == STAGE_IDENTIFICATION and
                remaining_docs == ["ejari"]):
            try:
                _fd_mp = load_member_progress(email)
                if _fd_mp:
                    _fd_members = _fd_mp.get("members", [])
                    _FD_IDTYPES = {"eid", "passport", "emirates id", "emirates_id"}
                    _fd_verified_disk = []
                    for _fdm in _fd_members:
                        _fdmdir = user_docs_path(email) / _fdm
                        if not _fdmdir.exists():
                            continue
                        for _fdi in _fdmdir.iterdir():
                            if not _fdi.is_dir():
                                continue
                            _fdo = _fdi / "output.json"
                            if not _fdo.exists():
                                continue
                            try:
                                with open(_fdo, "r", encoding="utf-8") as _fdof:
                                    _fdd = json.load(_fdof)
                                if (_fdd.get("is_valid") and
                                        _fdd.get("document_type", "").lower() in _FD_IDTYPES):
                                    _fd_verified_disk.append(_fdm)
                                    break
                            except Exception:
                                pass
                    _fd_pending = [m for m in _fd_members if m not in _fd_verified_disk]
                    if _fd_pending:
                        logger.warning(f"[FIX-D]  Ejari would be next but {len(_fd_pending)} member(s) still need IDs: {_fd_pending}")
                        # Self-heal: restore so_member_eids stage
                        try:
                            update_user_onboarding_status(email, False, STAGE_SO_MEMBER_EIDS)
                            logger.info(f"[FIX-D] Stage self-healed → so_member_eids for {email}")
                        except Exception as _fd_heal_err:
                            logger.warning(f"[FIX-D] Could not self-heal stage: {_fd_heal_err}")
                        _fd_next = _fd_pending[0]
                        dynamic_acknowledgment = (
                            localized(language,
                                en=(f"Identity document verified successfully.\n\n"
                            f"Please proceed by uploading the Emirates ID or Passport for: **{_fd_next}**."),
                                es=(f"Documento de identidad verificado exitosamente.\n\n"
                            f"Por favor, suba el Emirates ID o Pasaporte para: **{_fd_next}**."),
                                ar=(f"تم التحقق من مستند الهوية بنجاح.\n\n"
                            f"يُرجى المتابعة بتحميل الهوية الإماراتية أو جواز السفر لـ: **{_fd_next}**."))
                        )
                        _fixd_triggered = True
                        logger.info(f"[FIX-D]  Redirecting to next pending member: {_fd_next}")
            except Exception as _fd_err:
                logger.warning(f"[FIX-D] Guard check failed (non-fatal): {_fd_err}")
        # ── End Fix D ──

        # ── FIX: Member-aware remaining_docs for member_eids stage ──────────────
        # get_remaining_required_documents only scans the root user directory,
        # not member subdirectories. In member_eids stage it always returns
        # ["Emirates ID (EID) or Passport for each member"] regardless of how
        # many members have already been verified — so message_generator.py
        # never reaches the "last member" branch and always generates
        # "Please proceed with uploading the next member required document".
        # Fix: derive remaining_docs from member_progress.json directly,
        # including the current member in the verified set.
        _member_eids_remaining = None
        if (clean_member_name and
                user.get("document_stage") == STAGE_MEMBER_EIDS and
                result.get("is_valid")):
            try:
                _mp_msg = load_member_progress(email)
                if _mp_msg:
                    _mp_all      = _mp_msg.get("members", [])
                    _mp_verified = _mp_msg.get("verified_members", [])
                    # treat the member being confirmed right now as verified
                    _mp_verified_with_current = set(_mp_verified) | {clean_member_name}
                    _mp_pending  = [m for m in _mp_all
                                    if m not in _mp_verified_with_current]
                    _member_eids_remaining = [
                        f"Emirates ID for {m}" for m in _mp_pending
                    ]
                    logger.info(f"[MSG-FIX] Member remaining after '{clean_member_name}': "
                          f"{_member_eids_remaining} (pending={len(_mp_pending)}/{len(_mp_all)})")

                    # ── Auto-mark human_verified + sync KI status for Multiple Owner EIDs ──
                    # upload_conversational is the sole verification path for member_eids
                    # (the /verify endpoint is never called for these docs). We must
                    # mark human_verified=True here and update verified_members /
                    # key_individuals.json so the final summary shows "Verified".
                    if clean_member_name not in _mp_verified:
                        # 1. Mark the uploaded doc as human_verified on disk
                        try:
                            _eid_member_dir = user_docs_path(email) / clean_member_name
                            _ID_TYPES_AUTO = {"eid", "passport", "emirates id", "emirates_id"}
                            for _eid_item in _eid_member_dir.iterdir():
                                if not _eid_item.is_dir():
                                    continue
                                _eid_out = _eid_item / "output.json"
                                if not _eid_out.exists():
                                    continue
                                with open(_eid_out, "r", encoding="utf-8") as _ef:
                                    _eid_data = json.load(_ef)
                                if (_eid_data.get("is_valid") and
                                        _eid_data.get("document_type", "").lower() in _ID_TYPES_AUTO and
                                        not _eid_data.get("human_verified")):
                                    _eid_data["human_verified"] = True
                                    _eid_data["verified_at"] = datetime.now(timezone.utc).isoformat()
                                    with open(_eid_out, "w", encoding="utf-8") as _ef:
                                        json.dump(_eid_data, _ef, indent=2, ensure_ascii=False)
                                    logger.info(f"[MEMBER-EID] Auto-marked human_verified for '{clean_member_name}'")
                                    break
                        except Exception as _hve:
                            logger.warning(f"[MEMBER-EID] human_verified auto-mark failed: {_hve}")

                        # 2. Persist updated verified_members to member_progress.json
                        try:
                            _mp_msg["verified_members"] = list(_mp_verified_with_current)
                            _mp_prog_path = member_progress_path(email)
                            with open(_mp_prog_path, "w", encoding="utf-8") as _mpf:
                                json.dump(_mp_msg, _mpf, indent=2, ensure_ascii=False)
                            logger.info(f"[MEMBER-EID] verified_members persisted for '{clean_member_name}'")
                        except Exception as _mpe:
                            logger.warning(f"[MEMBER-EID] verified_members persist failed: {_mpe}")

                        # 3. Sync verification_status in key_individuals.json
                        try:
                            update_ki_verification_by_name(
                                email=email,
                                member_name=clean_member_name,
                                document_id=document_id,
                            )
                        except Exception as _kimo_err:
                            logger.warning(f"[MEMBER-EID] update_ki_verification_by_name failed: {_kimo_err}")

            except Exception as _mr_err:
                logger.warning(f"[MSG-FIX] Could not compute member remaining (non-fatal): {_mr_err}")
        # ── End member remaining fix ─────────────────────────────────────────────

        if not _fixd_triggered:
            try:
                dynamic_acknowledgment = ai_message_gen.generate_document_success_message(
                    doc_type=doc_type, user=user,
                    remaining_docs=_member_eids_remaining if _member_eids_remaining is not None else remaining_docs,
                    member_name=clean_member_name,
                    language=language,
                    pending_coi_names=_up_pending_coi  # pass detected corporate names for Type-2 commercial flow
                )
            except Exception:
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"Your {doc_type.upper()}{' for ' + clean_member_name if clean_member_name else ''} has been verified."),
                        es=(f"Tu {doc_type.upper()}{' para ' + clean_member_name if clean_member_name else ''} ha sido verificado."),
                        ar=(f"تم التحقق من {doc_type.upper()}{' الخاص بـ ' + clean_member_name if clean_member_name else ''}."))
                )

        # ── Single Owner: override post-commercial message to explicitly name Ejari ─
        # LLM may still say "Identity Document" if remaining_docs label is ambiguous.
        # Hardcode the next-step instruction for Single Owner after Commercial upload.
        _is_so_commercial = (
            result.get("is_valid") and
            not clean_member_name and
            doc_type.lower() in ("commercial", "trade_license", "commercial_license") and
            doc_stage == STAGE_IDENTIFICATION and
            user.get("account_type") == ACCOUNT_CORPORATE and
            user.get("ownership_type") not in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
        )
        if _is_so_commercial:
            _so_docs_after_commercial = check_documents_status(email)
            _moa_verified = _so_docs_after_commercial.get("moa", False)
            _ejari_verified = _so_docs_after_commercial.get("ejari", False)
            if not _moa_verified:
                dynamic_acknowledgment = localized(language,
                    en=("Your Commercial License has been successfully validated and accepted.\n\n"
                        "The next step is to upload your **MOA (Memorandum of Association)**. "
                        "Please upload your MOA document to continue the process."),
                    es=("Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                        "El siguiente paso es subir su **Memorando de Asociación (MOA)**. "
                        "Por favor, suba su documento MOA para continuar con el proceso."),
                    ar=("تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                        "الخطوة التالية هي تحميل **عقد التأسيس (MOA)**. "
                        "يُرجى تحميل عقد التأسيس لمتابعة الإجراءات."))
                logger.info(f"[v4] SO Commercial success → overriding acknowledgment to prompt for MOA")
            elif not _ejari_verified:
                dynamic_acknowledgment = localized(language,
                    en=("Your Commercial License has been successfully validated and accepted.\n\n"
                        "The next step is to upload your **Ejari (Tenancy Contract)**. "
                        "Please upload your Ejari document to continue the process."),
                    es=("Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                        "El siguiente paso es subir su **Contrato de Arrendamiento (Ejari)**. "
                        "Por favor, suba su documento Ejari para continuar con el proceso."),
                    ar=("تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                        "الخطوة التالية هي تحميل **إيجاري (عقد الإيجار)**. "
                        "يُرجى تحميل مستند إيجاري لمتابعة الإجراءات."))
                logger.info(f"[v4] SO Commercial success → overriding acknowledgment to prompt for Ejari")

        # ── Ownership auto-classification: announce result / ask fallback question ──
        # Runs last so it always wins over whatever generic/SO message was set
        # above, regardless of which branch fired.
        if _ownership_auto_classify_ambiguous:
            dynamic_acknowledgment = (
                localized(language,
                    en=("Your Commercial License has been successfully validated and accepted.\n\n"
                "I couldn't clearly determine the ownership details from it, though — quick question so "
                "I can set things up right: do you own this business by yourself, as a **Sole "
                "Proprietorship**, or do you share ownership with others, under **Joint Ownership**?"),
                    es=("Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                "No pude determinar con claridad los detalles de propiedad en el documento. "
                "Pregunta rápida para continuar correctamente: ¿posee este negocio usted solo, bajo "
                "**Propiedad Individual**, o comparte la propiedad con otras personas, bajo "
                "**Propiedad Conjunta**?"),
                    ar=("تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                "لكن لم أتمكن من تحديد تفاصيل الملكية بوضوح منها — سؤال سريع لإعداد الحساب بشكل صحيح: "
                "هل تملك هذا النشاط بمفردك، بصفة **ملكية فردية**، أم تتشارك الملكية مع آخرين، بصفة **ملكية مشتركة**؟"))
            )
            logger.info("[OWNERSHIP-AUTO] Ambiguous — overriding acknowledgment with manual ownership question")
        elif _ownership_freshly_classified == OWNERSHIP_PARTNERSHIP:
            # Partnership/Multiple Owners flow order per stage_table.py is
            # commercial -> ejari -> moa (Ejari before MOA — the reverse of
            # Single Owner). Read the actual verification state instead of
            # hardcoding a doc name here, so this text can't drift out of
            # sync with resolve_stage()/the "REQUIRED NEXT DOCUMENT" card again.
            _po_docs_after_commercial = check_documents_status(email)
            _po_ejari_verified = _po_docs_after_commercial.get("ejari", False)
            _po_next_doc_en = "MOA (Memorandum of Association)" if _po_ejari_verified else "Ejari (Tenancy Contract)"
            _po_next_doc_es = "Memorando de Asociación (MOA)" if _po_ejari_verified else "Contrato de Arrendamiento (Ejari)"

            # If the Type-2 early trigger above also detected a corporate
            # shareholder on this same license, a Certificate of
            # Incorporation is the more urgent next ask (that block already
            # transitioned document_stage → corporate_shareholder_docs).
            if _up_pending_coi:
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"Your Commercial License has been successfully validated and accepted.\n\n"
                    f"Based on the document, you share ownership of this business under **Joint "
                    f"Ownership** ({_ownership_partner_count} owners listed), and one of them is a "
                    f"corporate entity ({', '.join(_up_pending_coi)}). "
                    f"The next step is to upload a **Certificate of Incorporation** for that entity, "
                    f"along with your **{_po_next_doc_en}**."),
                        es=(f"Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                    f"Según el documento, usted comparte la propiedad de este negocio bajo "
                    f"**Propiedad Conjunta** ({_ownership_partner_count} propietarios listados), y uno "
                    f"de ellos es una entidad corporativa ({', '.join(_up_pending_coi)}). "
                    f"El siguiente paso es subir el **Certificado de Constitución** de esa entidad, "
                    f"junto con su **{_po_next_doc_es}**."),
                        ar=(f"تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                    f"وفقاً للمستند، تتشارك ملكية هذا النشاط بصفة **ملكية مشتركة** "
                    f"({_ownership_partner_count} ملاك مدرجون)، وأحدهم كيان اعتباري ({', '.join(_up_pending_coi)}). "
                    f"الخطوة التالية هي تحميل **شهادة التأسيس** لذلك الكيان، "
                    f"إلى جانب **{doc_name(_po_next_doc_en, 'arabic')}**."))
                )
            else:
                dynamic_acknowledgment = (
                    localized(language,
                        en=(f"Your Commercial License has been successfully validated and accepted.\n\n"
                    f"Based on the document, you share ownership of this business under **Joint "
                    f"Ownership** ({_ownership_partner_count} owners listed). "
                    f"The next step is to upload your **{_po_next_doc_en}**."),
                        es=(f"Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                    f"Según el documento, usted comparte la propiedad de este negocio bajo "
                    f"**Propiedad Conjunta** ({_ownership_partner_count} propietarios listados). "
                    f"El siguiente paso es subir su **{_po_next_doc_es}**."),
                        ar=(f"تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                    f"وفقاً للمستند، تتشارك ملكية هذا النشاط بصفة **ملكية مشتركة** "
                    f"({_ownership_partner_count} ملاك مدرجون). "
                    f"الخطوة التالية هي تحميل **{doc_name(_po_next_doc_en, 'arabic')}**."))
                )
            logger.info(f"[OWNERSHIP-AUTO] Announcing Joint Ownership classification ({_ownership_partner_count} partners, type2={bool(_up_pending_coi)}, next_doc={'moa' if _po_ejari_verified else 'ejari'})")
        elif _ownership_freshly_classified == OWNERSHIP_SINGLE:
            dynamic_acknowledgment = (
                localized(language,
                    en=("Your Commercial License has been successfully validated and accepted.\n\n"
                "Based on the document, you own this business by yourself, under **Sole "
                "Proprietorship**. The next step is to upload your **MOA (Memorandum of "
                "Association)**."),
                    es=("Su Licencia Comercial ha sido validada y aceptada exitosamente.\n\n"
                "Según el documento, usted posee este negocio bajo **Propiedad Individual**. "
                "El siguiente paso es subir su **Memorando de Asociación (MOA)**."),
                    ar=("تم التحقق من رخصتك التجارية وقبولها بنجاح.\n\n"
                "وفقاً للمستند، تملك هذا النشاط بمفردك بصفة **ملكية فردية**. "
                "الخطوة التالية هي تحميل **عقد التأسيس (MOA)**."))
            )
            logger.info("[OWNERSHIP-AUTO] Announcing Sole Proprietorship classification")

    # Log extraction result
    if result["success"] and result.get("extracted_data"):
        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=dynamic_acknowledgment, channel="chat",
                metadata={
                    "message_type": "extraction_result",
                    "document_type": doc_type,
                    "extracted_fields": result.get("extracted_data"),
                    "validation": result.get("validation", {}),
                    "display_config": {"format": "table", "style": "extracted-data-table", "collapsible": True},
                    "member_name": clean_member_name,
                    "is_valid": result.get("is_valid", False),
                    "tampering_score": tampering_result.overall_tampering_score,
                    "document_info": {
                        "filename": uploaded_file.filename,
                        "document_type": doc_type,
                        "member_name": clean_member_name,
                        "preview_url": preview_url
                    },
                    "language": language
                }
            )
        except Exception as log_error:
            logger.warning(f"Failed to log extraction: {log_error}")

    # Send validation-failed email if invalid
    if not result.get("is_valid"):
        try:
            send_document_verification_email(
                to_email=email, user_name=user_name,
                document_type=doc_type.upper(), status="invalid",
                filename=uploaded_file.filename,
                reason=result.get("ai_reasoning") or result.get("message") or "Document validation failed",
                extracted_data=result.get("extracted_data"),
                is_complete=False,
                remaining_documents=remaining_docs,
                member_name=clean_member_name
            )
        except Exception as email_error:
            logger.warning(f"Failed to send validation error email: {email_error}")

    status = get_onboarding_status(email, user, skip_welcome=True)
    is_complete = status.get("is_complete", False)

    # ── Single Owner flow: Commercial → MOA → Ejari → role card → EID loop ──────
    # Step 1: Commercial verified → clear stale data, prompt for MOA next.
    # Step 2: MOA + Ejari both verified (+ commercial already on disk) → fire so_as_trigger.
    # Multiple Owner flow is unchanged — role card fires after MOA via moa_as_trigger.
    _so_as_trigger = False
    _so_owner      = None

    # ── Step 1: Commercial verified ──────────────────────────────────────────
    if (result.get("is_valid") and
            not clean_member_name and
            doc_type.lower() in ("commercial", "trade_license", "commercial_license") and
            doc_stage == STAGE_IDENTIFICATION):
        # Clean ALL stale session data from a previous onboarding run so each
        # new Commercial upload starts completely fresh.
        for _stale_path, _label in [
            (fatca_json_path(email),                         "fatca.json"),
            (pep_json_path(email),                           "pep.json"),
            (user_docs_path(email) / "self_declaration.json","self_declaration.json"),
            (member_progress_path(email),                    "member_progress.json"),
            (ki_json_path(email),                            "key_individuals.json"),
            (user_docs_path(email) / "ki_loop_done.json",   "ki_loop_done.json"),
        ]:
            if _stale_path.exists():
                try:
                    _stale_path.unlink(missing_ok=True)
                    logger.info(f"[v4] Stale {_label} cleared for new session: {email}")
                except Exception as _fe:
                    logger.warning(f"[v4] Could not clear {_label}: {_fe}")

        _is_multiple_owner = user.get("ownership_type") in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
        if user.get("account_type") == ACCOUNT_CORPORATE and not _is_multiple_owner:
            # Single Owner: next required document is MOA, then Ejari — role
            # card fires once both are verified (see Step 2 below).
            logger.info(f"[v4] Commercial verified for Single Owner ({email}). Next step: MOA upload.")
        elif user.get("account_type") == ACCOUNT_CORPORATE and _is_multiple_owner:
            # ── Type-1 Multiple Owner: do NOT trigger on Commercial upload ────
            # The AS card and member extraction fire on MOA upload (once BOTH
            # Commercial + MOA are validated).  See _TYPE1_MOA_TRIGGER block below.
            logger.info(f"[TYPE-1-UPLOAD] Commercial verified for Multiple Owner — "
                  f"waiting for MOA before triggering member extraction")

    # ── Step 2: MOA + Ejari both verified → fire so_as_trigger for Single Owner ──
    # Fires ONLY for Single Owner Corporate in identification stage once BOTH
    # MOA and Ejari are accepted AND a commercial license is already on disk.
    # Order-independent: whichever of MOA/Ejari lands second sees both flags
    # true and fires; the first one just waits (mirrors the Multiple Owner
    # Type-1 MOA/Ejari auto-trigger pattern below).
    # Multiple Owner / Partnership: not affected (they don't reach this block).
    if (result.get("is_valid") and
            not clean_member_name and
            doc_type.lower() in ("ejari", "tenancy", "moa", "memorandum") and
            doc_stage == STAGE_IDENTIFICATION and
            user.get("account_type") == ACCOUNT_CORPORATE and
            user.get("ownership_type") not in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP) and
            check_documents_status(email).get("moa", False) and
            check_documents_status(email).get("ejari", False)):
        try:
            _comm_path, _comm_data = _find_commercial_output(email)
            if _comm_data:
                # Build so_owner from the already-extracted commercial data
                ef = _comm_data.get("extracted_fields", {})
                owner_block = (
                    ef.get("owner") or
                    ef.get("english", {}).get("owner") or
                    {"name_english": ef.get("english", {}).get("owner_name", ""),
                     "share_percentage": "100%", "role": "Owner"}
                )
                _ej_owner_name = (
                    owner_block.get("name_english") or
                    owner_block.get("name", "")
                ).strip()
                _so_as_trigger = True
                if _ej_owner_name:
                    _so_owner = {
                        "name":             _ej_owner_name,
                        "share_percentage": owner_block.get("share_percentage", "100%"),
                        "role":             owner_block.get("role", "Owner"),
                        "nationality":      owner_block.get("nationality_english", ""),
                    }
                    logger.info(f"[v4] Ejari verified → Owner role card trigger — owner: {_ej_owner_name}")
                else:
                    logger.info(f"[v4] Ejari verified → Owner role card trigger (no owner name extracted)")
            else:
                # Commercial not yet uploaded — don't trigger role card yet
                logger.info(f"[v4] Ejari verified but no commercial found for {email} — role card held")
        except Exception as _ej_oe:
            logger.warning(f"[v4] Could not build owner data on Ejari trigger: {_ej_oe}")
            _so_as_trigger = True  # still show the card so user can proceed

    # ── MULTIPLE OWNER (Type-1 and Type-2): auto-trigger member expansion ────
    # Fires after EVERY corporate/shareholder-stage document that could
    # plausibly be the last one a user uploads: Ejari, MOA, or (Type-2 only)
    # Certificate of Incorporation. One shared check
    # (member_expansion.check_and_expand_members) re-derives full readiness
    # from disk every time, so it doesn't matter which of these three the
    # user happens to upload last — Ejari-then-MOA, MOA-then-Ejari, or for
    # Type-2 any order including CoI-last, all land here and all fire the
    # same way. This replaces four near-identical trigger blocks (Type-1 on
    # MOA / Type-1 on Ejari / Type-2 on MOA / Type-2 on Ejari) that used to
    # live here — none of which had a CoI-upload copy, which was the actual
    # gap: a Type-2 account that uploaded CoI last had no trigger checking
    # "is everything ready now?" and stalled until the user typed "Okay" in
    # chat. See member_expansion.py's module docstring for the full history.
    if (result.get("is_valid") and
            not clean_member_name and
            doc_type.lower() in ("ejari", "tenancy", "moa", "memorandum",
                                  "certificate_of_incorporation", "coi") and
            doc_stage in (STAGE_IDENTIFICATION, STAGE_CORPORATE_SHAREHOLDER_DOCS) and
            user.get("account_type") == ACCOUNT_CORPORATE and
            user.get("ownership_type") in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)):
        try:
            from app.domain.onboarding.member_expansion import check_and_expand_members
            _expansion = check_and_expand_members(email, user, language)
            if _expansion:
                dynamic_acknowledgment = _expansion["message"]
                _mo_as_trigger        = True
                _mo_members_list      = _expansion["members"]
                _mo_ubo_names_list    = _expansion["ubo_names"]
                _mo_stage_transition  = True
                logger.info(
                    f"[MEMBER-EXPANSION] Auto-triggered on {doc_type} upload → "
                    f"{len(_expansion['members'])} members"
                )
        except Exception as _me_err:
            logger.warning(f"[MEMBER-EXPANSION] Trigger failed (non-fatal): {_me_err}")
    # ── End member-expansion trigger ─────────────────────────────────────────

    # ── FIX Issue 3 (AI Assistant): self_declaration_trigger on upload ────────
    # When the user uploads the LAST member EID via the file button (not "okay"),
    # upload-conversational never emitted self_declaration_trigger — so the
    # SelfDeclarationCard never appeared in the AI Assistant page.
    # Fix: after a valid member EID upload in the member_eids stage, check if
    # ALL member EIDs are now on disk; if so emit self_declaration_trigger: True.
    # Single Owner (so_member_eids): excluded — they need Ejari uploaded first.
    # NOTE: self_decl_trigger and pep_trigger are already initialised to False
    # near the top of the SO-override block — no re-init needed here.
    if (result.get("is_valid") and
            clean_member_name and
            doc_stage == STAGE_MEMBER_EIDS and
            ownership in (OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE)):
        try:
            _mp_up = load_member_progress(email)
            _decl_path_up = user_docs_path(email) / "self_declaration.json"
            if _mp_up and not _decl_path_up.exists():
                _all_members_up = _mp_up.get("members", [])
                IDENTITY_TYPES_UP = {"eid", "passport", "emirates id", "emirates_id"}
                _verified_on_disk = []
                for _m in _all_members_up:
                    _mdir = user_docs_path(email) / _m
                    if not _mdir.exists():
                        continue
                    for _item in _mdir.iterdir():
                        if not _item.is_dir():
                            continue
                        _out = _item / "output.json"
                        if not _out.exists():
                            continue
                        try:
                            with open(_out, "r", encoding="utf-8") as _f:
                                _a = json.load(_f)
                            if (_a.get("is_valid") and
                                    _a.get("document_type", "").lower() in IDENTITY_TYPES_UP):
                                _verified_on_disk.append(_m)
                                break
                        except Exception:
                            pass
                if (len(_all_members_up) > 0 and
                        len(_verified_on_disk) >= len(_all_members_up)):
                    # ── KI Loop gate (Multiple Owner upload path) ─────────────
                    # All member EIDs verified.  Before firing FATCA, ensure the
                    # user has finalized the "add another AS/KI?" loop.
                    # /ki/loop-finalize writes ki_loop_done.json; until it exists
                    # we return ki_loop_prompt so the frontend shows KiLoopCard.
                    _mo_ki_loop_done_path = user_docs_path(email) / "ki_loop_done.json"
                    if not _mo_ki_loop_done_path.exists():
                        _mo_id_label_loop = "Passport" if doc_type.lower() == "passport" else "Emirates ID"
                        _mo_loop_msg = localized(language,
                            en=(f"The {_mo_id_label_loop} for member {clean_member_name} has been "
                                f"successfully validated and accepted.\n\n"
                                f"All member identity documents have been verified.\n\n"
                                f"Would you like to add any additional Authorised Signatory "
                                f"or Key Individual to this account?"),
                            es=(f"El {('Pasaporte' if doc_type.lower() == 'passport' else 'Emirates ID')} del miembro {clean_member_name} ha sido validado y aceptado correctamente.\n\n"
                                f"Todos los documentos de identidad de los miembros han sido verificados.\n\n"
                                f"¿Desea añadir algún Firmante Autorizado o Persona Clave adicional a esta cuenta?"),
                            ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} للعضو {clean_member_name} وقبوله بنجاح.\n\n"
                                f"تم التحقق من جميع مستندات هوية الأعضاء.\n\n"
                                f"هل ترغب في إضافة مفوّض بالتوقيع أو فرد رئيسي آخر إلى هذا الحساب؟"))
                        logger.info(f"[SELF-DECL] KI loop gate: ki_loop_done.json not found — "
                              f"returning ki_loop_prompt for {email}")
                        dynamic_acknowledgment = _mo_loop_msg
                        ki_loop_prompt    = True
                        fatca_trigger     = False
                        pep_trigger       = False
                        self_decl_trigger = False
                    else:
                        # ── ki_loop_done.json exists — proceed with FATCA → PEP chain ──
                        _mo_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                        _mo_pep_done   = get_pep_status_disk_only(email) == "completed"
                        _mo_id_label    = "Passport" if doc_type.lower() == "passport" else "Emirates ID"
                        _mo_id_label_es = "Pasaporte" if doc_type.lower() == "passport" else "Emirates ID"
                        if not _mo_fatca_done:
                            fatca_trigger = True
                            # Override the AI-generated message — the last-member branch in
                            # generate_document_success_message still says "upload next EID".
                            # Replace it with a clear FATCA prompt.
                            dynamic_acknowledgment = (
                                localized(language,
                                    en=(f"The {_mo_id_label} for member {clean_member_name} has been "
                                f"successfully validated and accepted.\n\n"
                                f"All member identity documents have been verified. "
                                f"Please proceed with the FATCA Declaration below."),
                                    es=(f"El {_mo_id_label_es} del miembro {clean_member_name} ha sido "
                                f"validado y aceptado exitosamente.\n\n"
                                f"Todos los documentos de identidad de los miembros han sido "
                                f"verificados. Por favor, proceda con la Declaración FATCA a continuación."),
                                    ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} للعضو {clean_member_name} وقبوله بنجاح.\n\n"
                                f"تم التحقق من جميع مستندات هوية الأعضاء. "
                                f"يُرجى المتابعة بإقرار فاتكا (FATCA) أدناه."))
                            )
                            logger.info(f"[SELF-DECL] All {len(_all_members_up)} member EIDs on disk — "
                                  f"triggering FATCA for {email}")
                        elif not _mo_pep_done:
                            pep_trigger = True
                            dynamic_acknowledgment = (
                                localized(language,
                                    en=(f"The {_mo_id_label} for member {clean_member_name} has been "
                                f"successfully validated and accepted.\n\n"
                                f"All member identity documents have been verified. "
                                f"Please proceed with the PEP Declaration below."),
                                    es=(f"El {_mo_id_label_es} del miembro {clean_member_name} ha sido "
                                f"validado y aceptado exitosamente.\n\n"
                                f"Todos los documentos de identidad de los miembros han sido "
                                f"verificados. Por favor, proceda con la Declaración PEP a continuación."),
                                    ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} للعضو {clean_member_name} وقبوله بنجاح.\n\n"
                                f"تم التحقق من جميع مستندات هوية الأعضاء. "
                                f"يُرجى المتابعة بإقرار الأشخاص المعرّضين سياسياً (PEP) أدناه."))
                            )
                            logger.info(f"[SELF-DECL] FATCA done — triggering PEP for {email}")
                        else:
                            self_decl_trigger = True
                            dynamic_acknowledgment = (
                                localized(language,
                                    en=(f"The {_mo_id_label} for member {clean_member_name} has been "
                                f"successfully validated and accepted.\n\n"
                                f"All member identity documents have been verified. "
                                f"Please proceed with the Self-Declaration below."),
                                    es=(f"El {_mo_id_label_es} del miembro {clean_member_name} ha sido "
                                f"validado y aceptado exitosamente.\n\n"
                                f"Todos los documentos de identidad de los miembros han sido "
                                f"verificados. Por favor, proceda con la Auto-Declaración a continuación."),
                                    ar=(f"تم التحقق من {('جواز السفر' if doc_type.lower() == 'passport' else 'الهوية الإماراتية')} للعضو {clean_member_name} وقبوله بنجاح.\n\n"
                                f"تم التحقق من جميع مستندات هوية الأعضاء. "
                                f"يُرجى المتابعة بالإقرار الذاتي أدناه."))
                            )
                            logger.info(f"[SELF-DECL] All {len(_all_members_up)} member EIDs on disk — "
                                  f"triggering Self-Declaration card for {email}")
        except Exception as _sde:
            logger.warning(f"[SELF-DECL] Trigger check failed (non-fatal): {_sde}")

    # FIX Issue 1 & 2 — Safety net: when any completion-phase trigger is active
    # (FATCA, PEP, or Self-Declaration), the document collection phase is over.
    # Suppress next_document and remaining_documents so the Onboarding Progression
    # widget does not render a stale or incorrect "Required Next Document" card
    # alongside the compliance form.
    # ki_loop_prompt suppresses next-doc widgets just like completion triggers do.
    _any_completion_trigger = fatca_trigger or pep_trigger or self_decl_trigger or ki_loop_prompt
    _final_next_document = None if _any_completion_trigger else status.get("next_required_document")
    _final_remaining_docs = [] if _any_completion_trigger else remaining_docs

    return {
        "success": result["success"],
        "message": dynamic_acknowledgment,
        "acknowledgment": dynamic_acknowledgment,
        "document_type": result["document_type"],
        "extracted_data": result.get("extracted_data"),
        "is_valid": result.get("is_valid", False),
        "is_complete": is_complete,
        "awaiting_verification": result["is_valid"],
        "document_file_path": str(file_path),
        "next_document": _final_next_document,
        "remaining_documents": _final_remaining_docs,
        "wrong_document_type": False,
        "tampering_detected": False,
        "decision": "ACCEPT",
        "tampering_score": tampering_result.overall_tampering_score,
        "language": language,
        # ── v4 additions (FATCA now fires from verify path, not upload path) ──
        "fatca_trigger": fatca_trigger,
        "pep_trigger": pep_trigger,
        "self_declaration_trigger": self_decl_trigger,
        # ── KI loop gate: frontend shows KiLoopCard when True ────────────────
        "ki_loop_prompt": ki_loop_prompt,
        # ── v4: Owner ID card fires immediately after commercial extraction ──
        "so_as_trigger": _so_as_trigger,
        "so_owner":      _so_owner,
        # ── Type-1 Multiple Owner: AS card + stage transition from Commercial ─
        "moa_as_trigger":   _mo_as_trigger,
        "moa_members":      _mo_members_list,
        "ubo_names":        _mo_ubo_names_list,
        "stage_transition": _mo_stage_transition,
        "new_stage":        STAGE_MEMBER_EIDS if _mo_stage_transition else None,
        # ── v4: mismatch fields ──────────────────────────────────────────────
        "mismatch_detected":          _mismatch_detected,
        "mismatch_extracted_name":    _mismatch_extracted_name,
        "mismatch_extracted_business": _mismatch_extracted_business,
    }


@router.get("/get-document/{email}/{doc_type}/{filename}")
async def get_document_for_preview(
    email: EmailStr,
    doc_type: str,
    filename: str,
    member_name: Optional[str] = None
):
    """
    Get document file for preview in chat
    """
    try:
        logger.info(f"\n[PREVIEW] Fetching document:")
        logger.info(f"  Email: {email}")
        logger.info(f"  Doc Type: {doc_type}")
        logger.info(f"  Filename: {filename}")
        logger.info(f"  Member: {member_name or 'N/A'}")
        
        # Try multiple path strategies
        file_path = None

        # Resolve ref_no for this user (new naming convention)
        from app.services.document_helpers import (
            get_document_ref_no, get_user_documents_path_by_ref,
            build_document_id, get_member_index,
        )
        ref_no = get_document_ref_no(email)
        user_dir = get_user_documents_path_by_ref(ref_no)

        # Strategy 0: derive the actual saved document_id the same way
        # process_uploaded_document names it on disk (e.g. "MOA.pdf" as
        # uploaded is saved as "MOA-{ref_no}.pdf" under folder "MOA-{ref_no}/",
        # "Ejari.pdf" is saved with an entirely different POS- prefix — there
        # is no string relationship at all between the original filename this
        # route is called with and the renamed file, which is why every
        # strategy below that searches BY that original filename can never
        # find it, and why document preview was broken end-to-end (live and
        # after reload) for every non-legacy-saved document, not just bulk
        # ones. This mirrors the exact naming rule used at save time instead
        # of searching for a name that no longer exists on disk.
        try:
            if member_name:
                member_index = get_member_index(email, member_name)
                document_id = build_document_id(doc_type, ref_no, True, member_index)
                candidate_dir = user_dir / "members" / document_id
            else:
                document_id = build_document_id(doc_type, ref_no, False, None)
                candidate_dir = user_dir / document_id

            if candidate_dir.exists():
                candidates = [p for p in candidate_dir.iterdir() if p.is_file() and p.name != "output.json"]
                # Prefer a same-extension match if there's more than one
                # non-json file in the folder (shouldn't normally happen —
                # each document_id folder holds exactly one document — but
                # falling back to "first file found" rather than failing
                # outright keeps this robust against that edge case).
                requested_ext = Path(filename).suffix.lower()
                same_ext = [p for p in candidates if p.suffix.lower() == requested_ext]
                if same_ext:
                    file_path = same_ext[0]
                elif candidates:
                    file_path = candidates[0]
                if file_path:
                    logger.info(f"[PREVIEW] Found via Strategy 0 (document_id folder): {file_path}")
        except Exception as _s0_err:
            logger.warning(f"[PREVIEW] Strategy 0 lookup failed (non-fatal): {_s0_err}")

        # Strategy 1: doc_type subfolder (legacy name)
        test_path = user_dir / doc_type / filename
        if test_path.exists():
            file_path = test_path
            logger.info(f"[PREVIEW] Found via Strategy 1: {file_path}")

        # Strategy 2: members/ subfolder
        if not file_path and member_name:
            test_path = user_dir / "members" / member_name / filename
            if test_path.exists():
                file_path = test_path
                logger.info(f"[PREVIEW] Found via Strategy 2 (member): {file_path}")

        # Strategy 3: filename stem as subfolder name (new prefix-based naming)
        if not file_path:
            document_id = Path(filename).stem
            test_path = user_dir / document_id / filename
            if test_path.exists():
                file_path = test_path
                logger.info(f"[PREVIEW] Found via Strategy 3 (prefix folder): {file_path}")

        # Strategy 4: Recursive search under ref_no root
        if not file_path:
            if user_dir.exists():
                logger.info(f"[PREVIEW] Searching recursively under {user_dir}...")
                for found_file in user_dir.rglob(filename):
                    if found_file.is_file():
                        file_path = found_file
                        logger.info(f"[PREVIEW] Found via recursive search: {file_path}")
                        break
        
        if not file_path or not file_path.exists():
            logger.error(f"Document not found")
            raise NotFoundError("Document not found")
        
        logger.info(f"[PREVIEW] Serving: {file_path}")
        
        # Determine media type
        suffix = file_path.suffix.lower()
        media_type_map = {
            '.pdf': "application/pdf",
            '.jpg': "image/jpeg",
            '.jpeg': "image/jpeg",
            '.png': "image/png",
            '.webp': "image/webp"
        }
        media_type = media_type_map.get(suffix, "application/octet-stream")
        
        return FileResponse(
            str(file_path),
            media_type=media_type,
            filename=filename
        )
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Get document error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))   


@router.get("/preview/{email}/{filename}")
async def preview_document(email: EmailStr, filename: str):
    """
    Simple document preview endpoint - searches for file by name
    """
    try:
        from urllib.parse import unquote

        # Decode filename
        filename = unquote(filename)
        
        logger.info(f"\n[PREVIEW] Searching for document:")
        logger.info(f"  Email: {email}")
        logger.info(f"  Filename: {filename}")
        
        # Start from user's root directory (ref_no-based structure)
        from app.services.document_helpers import get_document_ref_no as _gdr_preview, get_user_documents_path_by_ref as _gudp_preview
        _preview_ref_no = _gdr_preview(email)
        user_dir = _gudp_preview(_preview_ref_no)

        if not user_dir.exists():
            logger.error(f"[PREVIEW] User directory not found: {user_dir}")
            raise NotFoundError("User directory not found")
        
        # Search recursively for the file
        file_path = None
        for found_file in user_dir.rglob(filename):
            if found_file.is_file():
                file_path = found_file
                logger.info(f"[PREVIEW] Found: {file_path}")
                break
        
        if not file_path or not file_path.exists():
            logger.error(f"[PREVIEW] File not found: {filename}")
            raise NotFoundError(f"Document not found: {filename}")
        
        # Determine media type
        suffix = file_path.suffix.lower()
        media_type_map = {
            '.pdf': "application/pdf",
            '.jpg': "image/jpeg",
            '.jpeg': "image/jpeg",
            '.png': "image/png",
            '.webp': "image/webp"
        }
        media_type = media_type_map.get(suffix, "application/octet-stream")
        
        logger.info(f"[PREVIEW] Serving: {file_path} ({media_type})")
        
        return FileResponse(
            str(file_path),
            media_type=media_type,
            filename=filename
        )
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Preview error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))    


@router.get("/member-progress/{email}")
async def get_member_progress(email: str):
    """Get member progress information"""
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    mp = load_member_progress(email)
    if not mp:
        return {
            "email": email,
            "members": [],
            "message": "No member progress found"
        }
    
    # FIX: Members are now simple strings
    members_list = mp.get("members", [])  # Simple list of strings
    current_index = mp.get("current_index", 0)
    
    # Build enhanced member info with verification status
    members_with_status = []
    
    for member_name in members_list:
        member_info = {
            "name": member_name,
            "eid_verified": False,
            "eid_uploaded": False
        }
        
        # Check if this member has uploaded/verified EID or Passport
        IDENTITY_TYPES_STATUS = {"eid", "passport", "emirates id", "emirates_id"}
        member_dir = user_docs_path(email) / member_name  # FIXED PATH
        if member_dir.exists():
            for item in member_dir.iterdir():
                if not item.is_dir():
                    continue

                out = item / "output.json"
                if out.exists():
                    try:
                        with open(out, "r", encoding="utf-8") as f:
                            analysis = json.load(f)

                        if analysis.get("document_type", "").lower() in IDENTITY_TYPES_STATUS:
                            member_info["eid_uploaded"] = True
                            member_info["eid_verified"] = analysis.get("human_verified", False)
                            break
                    except:
                        pass
        
        members_with_status.append(member_info)
    
    verified_count = sum(1 for m in members_with_status if m["eid_verified"])
    
    return {
        "email": email,
        "members": members_with_status,
        "total": len(members_list),
        "verified": verified_count,
        "current_index": current_index,
        "current_member": members_list[current_index] if current_index < len(members_list) else None
    }


@router.post("/cross-validation/run")
async def run_cross_validation(req: CrossValidationRequest):
    """
    Run cross-validation after self-declaration is confirmed.
    Checks all uploaded documents for consistency.
    Returns: passed (bool), mismatches (list), message (str)
    """
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        user_data = dict(user) if not isinstance(user, dict) else user

        logger.info(f"[CROSS-VALID] Running cross-validation for {req.email}")

        cross_validator = CrossValidator()
        result = cross_validator.validate_documents(req.email, user_data)

        passed = result.get("passed", False)
        mismatches = result.get("mismatches", [])

        logger.info(f"[CROSS-VALID] {'PASSED' if passed else 'FAILED'} — {len(mismatches)} mismatch(es)")

        if passed:
            try:
                msg = MessageGenerator.cross_validation_success(
                    user_name=user_data.get("first_name", ""),
                    language=req.language
                )
            except Exception:
                msg = localized(None,
                    en="Cross-validation completed successfully. All documents are consistent. Your application is now complete and will proceed to review.",
                    es="La validación cruzada se completó correctamente. Todos los documentos son coherentes. Su solicitud está completa y pasará a revisión.",
                    ar="اكتمل التحقق المتقاطع بنجاح. جميع المستندات متّسقة. اكتمل طلبك وسينتقل إلى المراجعة.")

            # Mark onboarding complete
            #
            # BUGFIX: this called `update_onboarding_status(...)`, which does
            # not exist anywhere — the real function is
            # `update_user_onboarding_status(email, is_complete, stage)`,
            # defined at the top of this module. The call sat inside
            # `except Exception`, so it failed silently on every invocation and
            # only logged "Could not mark complete: name ... is not defined".
            #
            # Impact was limited: the frontend never calls this endpoint. The
            # live path is /chatupload/self-declaration/confirm, which runs
            # cross-validation itself and already marks completion correctly.
            # Fixed for correctness, matching the argument form used by the
            # other 18 call sites.
            try:
                update_user_onboarding_status(req.email, True, "onboarding_complete")
            except Exception as e:
                logger.warning(f"[CROSS-VALID] Could not mark complete: {e}")

        else:
            mismatch_summary = "; ".join(str(m) for m in mismatches[:5])
            try:
                msg = MessageGenerator.cross_validation_failure(
                    mismatches=mismatches,
                    user_name=user_data.get("first_name", ""),
                    language=req.language
                )
            except Exception:
                msg = localized(None,
                    en=f"Cross-validation found inconsistencies in your documents: {mismatch_summary}. Please review and re-upload the affected documents.",
                    es=f"La validación cruzada encontró incoherencias en sus documentos: {mismatch_summary}. Revise y vuelva a cargar los documentos afectados.",
                    ar=f"رصد التحقق المتقاطع عدم تطابق في مستنداتك: {mismatch_summary}. يُرجى المراجعة وإعادة تحميل المستندات المعنية.")

        insert_conversation_log(
            user_email=req.email,
            role="agent",
            message=msg,
            channel="chat",
            metadata={
                "message_type": "cross_validation_result",
                "passed": passed,
                "mismatch_count": len(mismatches),
            }
        )

        return {
            "success": True,
            "passed": passed,
            "mismatches": mismatches,
            "message": msg,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[CROSS-VALID] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.get("/summary/pdf/{user_email}")
async def download_summary_pdf(user_email: str):
    """
    Generate and stream the full onboarding summary PDF for a given user.
    Includes: applicant info, FATCA, key individuals (with roles), uploaded docs,
    self-declaration status.
    """
    try:
        from app.services.pdf_summary_service import generate_onboarding_summary_pdf
        from app.services.fatca_service import load_fatca, get_fatca_status
        from app.services.key_individual_service import load_key_individuals

        user = get_user_by_email(user_email)
        if not user:
            raise NotFoundError("User not found")

        user_data = dict(user) if not isinstance(user, dict) else user

        # FATCA
        fatca_status = get_fatca_status(user_email)
        fatca_data = load_fatca(user_email)

        # Key individuals
        ki_list = load_key_individuals(user_email)

        # Uploaded documents — load from conversation logs or doc-status
        uploaded_docs = []
        try:
            docs_status = check_documents_status(user_email)
            # docs_status returns a list of dicts with document_type and status
            for doc_type, info in (docs_status.get("documents", {}) or {}).items():
                uploaded_docs.append({
                    "document_type": doc_type,
                    "status": info.get("status", "unknown") if isinstance(info, dict) else str(info),
                    "uploaded_at": info.get("uploaded_at") if isinstance(info, dict) else None,
                })
        except Exception as doc_err:
            logger.warning(f"[PDF-SUMMARY] Could not load docs: {doc_err}")

        # Product Package
        package_data = get_package_selection(user_email)

        logger.info(f"[PDF-SUMMARY] Generating for {user_email}: "
              f"FATCA={fatca_status}, KIs={len(ki_list)}, Docs={len(uploaded_docs)}, "
              f"Package={package_data.get('selected_package') if package_data else 'none'}")

        pdf_bytes = generate_onboarding_summary_pdf(
            email=user_email,
            user_data=user_data,
            fatca_data=fatca_data,
            fatca_status=fatca_status,
            ki_list=ki_list,
            uploaded_docs=uploaded_docs,
            package_data=package_data,
        )

        safe_name = user_email.replace("@", "_at_").replace(".", "_")
        filename = f"onboarding_summary_{safe_name}.pdf"

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[PDF-SUMMARY] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


# ============================================================================
# BULK UPLOAD — several files in one request
# ============================================================================
# Additive and separate from upload_conversational above, which is left
# untouched on purpose (see its module docstring: a 2,391-line decision
# tree with no behavioural-capture coverage for a rewrite). This handles
# exactly two batch shapes, matched off document_stage:
#   - corporate documents (commercial / ejari / moa), whichever
#     combination stage_table.resolve_stage currently requires
#   - member identity documents (EID / passport), one per pending member
#
# Parallel vs. sequential
# ------------------------
# Per-file tamper check + OCR/extraction (process_uploaded_document) runs
# concurrently via bulk_upload_service.run_parallel — each file is
# independent I/O with no cross-file dependency. Everything that reads or
# writes state SHARED across files in the same batch — member_progress.json,
# ownership auto-classification, the Type-2 corporate-shareholder trigger —
# runs once, after every worker has finished, never inside a worker. Two
# concrete bugs that split avoids:
#   1. The MOA-vs-commercial owner-name cross-check reads commercial's
#      already-saved output.json from disk. If MOA and commercial were
#      both mid-flight in the same parallel phase, MOA could read before
#      commercial had written. Cross-file checks for the corporate batch
#      therefore happen after collection, from the in-memory results —
#      see the ownership/Type-2 block below.
#   2. Two member EID uploads both appending to member_progress.json's
#      verified_members list at the same instant is a lost-update race —
#      whichever write lands last silently erases the other. So
#      member_progress.json is written exactly once per batch, after
#      every worker finishes, from the full set of results.
#
# Trigger cards (KI-loop, FATCA, PEP, self-declaration) are deliberately
# NOT computed or returned by this endpoint. get_onboarding_status()'s
# pending-actions block already re-derives every one of them from disk
# state (member_progress.json, ki_loop_done.json, fatca/pep status) on
# every call, and the frontend's syncPendingActions() — called after this
# endpoint returns — already back-fills whichever card is due from that
# same ground truth. Duplicating that cascade here would be a second copy
# of logic that only has to agree with the first, for a bulk request that
# already ends with a call to the function that computes it correctly.
#
# Still single-file only, for now: the KI-loop-gate message copy variants
# (the acknowledgement text shown alongside the card) aren't reproduced
# here — the card itself still appears correctly via the ground-truth
# path above, this endpoint just doesn't also write custom prose for it.
@router.post("/upload-conversational-bulk")
async def upload_conversational_bulk(
    email: EmailStr = Form(...),
    language: str = Form("english"),
    files: List[UploadFile] = File(...),
):
    language = normalize_language(language)

    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    if not files or len(files) < 2:
        raise ValidationError(
            "Bulk upload needs at least 2 files — use /upload-conversational for a single file"
        )

    account_type = user.get("account_type")
    ownership = user.get("ownership_type")
    doc_stage = user.get("document_stage", STAGE_IDENTIFICATION)

    is_member_stage = (
        (ownership in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and doc_stage == STAGE_MEMBER_EIDS) or
        (ownership == OWNERSHIP_SINGLE and doc_stage == STAGE_SO_MEMBER_EIDS)
    )

    # STAGE_CORPORATE_SHAREHOLDER_DOCS is the Type-2 CoI/ejari/moa batch —
    # same save mechanics as STAGE_IDENTIFICATION (main-user-level
    # documents, member_name=None), just a different stage's required-doc
    # list, which process_uploaded_document/should_request_document
    # already read from `user` fresh rather than from anything this
    # router branches on. Routed to the same handler for that reason.
    if is_member_stage:
        return await _bulk_member_documents(email, user, language, files)
    elif account_type == ACCOUNT_CORPORATE and doc_stage in (STAGE_IDENTIFICATION, STAGE_CORPORATE_SHAREHOLDER_DOCS):
        return await _bulk_corporate_documents(email, user, language, files)
    else:
        raise ValidationError(
            "Bulk upload isn't available at this step — upload one document at a time here."
        )


async def _bulk_corporate_documents(
    email: str, user: dict, language: str, files: List[UploadFile]
) -> dict:
    """
    Batch handler for commercial licence / ejari / MOA / certificate of
    incorporation. Each file's type is discovered by OCR, not by which
    slot it was dropped in — so files can be selected in any order.
    """
    from app.services.bulk_upload_service import run_parallel, dedupe_by_document_type
    from app.services.document_helpers import (
        get_document_ref_no as _get_ref_no, get_user_documents_path_by_ref as _get_docs_path,
        build_document_id as _build_doc_id,
    )

    stage_before = user.get("document_stage")

    def _process_one(f: UploadFile) -> dict:
        result = process_uploaded_document(email, f, member_name=None, language=language)
        result["_filename"] = f.filename
        return result

    raw_results = await run_parallel(list(files), _process_one)
    deduped = dedupe_by_document_type(raw_results)

    # ── close the same-type race window ──────────────────────────────────
    # process_uploaded_document renames its temp folder to a name derived
    # purely from doc_type for non-member documents (build_document_id has
    # no per-file uniqueness when is_member=False) — see get_document_prefix.
    # If two files in this batch happen to OCR to the same type (a
    # duplicate/misfiled upload — dedupe_by_document_type above already
    # decided which one is authoritative), both workers' renames targeted
    # the identical folder while running in parallel, and whichever
    # finished last physically wins on disk regardless of which one this
    # endpoint reports as accepted. Re-write the accepted file's own bytes
    # to its final path from the original upload so disk state can't end
    # up holding the other file's content under the accepted one's
    # extracted data. A no-op whenever every file in the batch OCR'd to a
    # distinct type, which is the normal case this exists to not slow down.
    ref_no_corp = user.get("ref_no") or _get_ref_no(email)
    for i, r in enumerate(deduped):
        if not r.get("is_valid") or r.get("duplicate_in_batch"):
            continue
        doc_type_i = (r.get("document_type") or "").lower()
        try:
            doc_id = _build_doc_id(doc_type_i, ref_no_corp, False, None)
            save_dir = _get_docs_path(ref_no_corp) / doc_id
            if not save_dir.exists():
                continue
            target_files = [p for p in save_dir.iterdir() if p.is_file() and p.name != "output.json"]
            if not target_files:
                continue
            matching_file = files[i]
            await matching_file.seek(0)
            content = await matching_file.read()
            with open(target_files[0], "wb") as fdisk:
                fdisk.write(content)
        except Exception as e:
            logger.warning(f"[BULK-CORP] disk-state re-save failed for {r.get('_filename')}: {e}")

    # ── sequential merge: ownership auto-classification ──────────────────
    # Mirrors the inline "OWNERSHIP AUTO-CLASSIFICATION" block in
    # upload_conversational above. Kept as its own copy rather than
    # extracted into a shared function — unlike the member-expansion
    # trigger below (now shared via member_expansion.check_and_expand_members),
    # this block only runs once per account (right after Commercial is first
    # classified), so the duplication cost is much lower. If this logic
    # changes in upload_conversational, mirror the change here.
    commercial_result = next(
        (r for r in deduped if (r.get("document_type") or "").lower() == "commercial" and r.get("is_valid")),
        None,
    )
    if (
        commercial_result
        and user.get("account_type") == ACCOUNT_CORPORATE
        and not user.get("ownership_type")
    ):
        try:
            extracted = commercial_result.get("extracted_data") or {}
            partners = extracted.get("partners", [])
            partner_count = len(partners) if isinstance(partners, list) else 0

            if partner_count == 0:
                owner = extracted.get("owner") or {}
                if owner and any(owner.get(k) for k in ("name_english", "name", "person_number")):
                    partner_count = 1

            if partner_count >= 1:
                classified = OWNERSHIP_SINGLE if partner_count == 1 else OWNERSHIP_PARTNERSHIP
                try:
                    UserRepository.update_by_email_as_service(email, {"ownership_type": classified})
                    user["ownership_type"] = classified
                    logger.info(
                        f"[BULK-OWNERSHIP] {email} classified as {classified} from {partner_count} partner(s)"
                    )
                except Exception as e:
                    logger.warning(f"[BULK-OWNERSHIP] persist failed: {e}")

                if classified == OWNERSHIP_PARTNERSHIP and partners:
                    try:
                        detection = _detect_corps(partners)
                        if detection["has_corporate_shareholders"]:
                            pending_coi = [c["name"] for c in detection["corporate_shareholders"]]
                            save_member_progress(email, members=[], current_index=0, pending_coi=pending_coi)
                            update_user_onboarding_status(email, False, STAGE_CORPORATE_SHAREHOLDER_DOCS)
                            user["document_stage"] = STAGE_CORPORATE_SHAREHOLDER_DOCS
                            logger.info(f"[BULK-TYPE2] {email} corporate shareholders: {pending_coi}")
                    except Exception as e:
                        logger.warning(f"[BULK-TYPE2] detection failed: {e}")
        except Exception as e:
            logger.warning(f"[BULK-OWNERSHIP] classification block failed: {e}")

    # ── Member-expansion trigger (Type-1 and Type-2, shared) ─────────────────
    # A bulk batch can deliver Ejari + MOA (Type-1) or CoI + Ejari + MOA
    # (Type-2) all together in one call, in any order — so a single readiness
    # check against final disk state, run once after every file in this batch
    # is already saved, covers both shapes. Uses the same
    # member_expansion.check_and_expand_members() the single-file upload path
    # calls, so a bulk batch and a sequence of single-file uploads that reach
    # the same end state produce the same result and the same message.
    # Without this the batch verifies fine (all docs show valid) but
    # document_stage never leaves identification/corporate_shareholder_docs,
    # member_progress.json's members list stays empty, and the Authorised
    # Signatory / KI loop card never appears.
    if (
        user.get("account_type") == ACCOUNT_CORPORATE
        and user.get("ownership_type") in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
    ):
        try:
            from app.domain.onboarding.member_expansion import check_and_expand_members
            _expansion = check_and_expand_members(email, user, language)
            if _expansion:
                user["document_stage"] = _expansion["new_stage"]
                try:
                    insert_conversation_log(
                        user_email=email, role="agent",
                        message=_expansion["message"],
                        channel="chat",
                        metadata={
                            "message_type": "document_upload_bulk_member_expansion_trigger",
                            "language": language,
                        },
                    )
                except Exception as e:
                    logger.warning(f"[BULK-MEMBER-EXPANSION] ack log failed: {e}")
                logger.info(
                    f"[BULK-MEMBER-EXPANSION] Auto-triggered → "
                    f"{len(_expansion['members'])} members"
                )
        except Exception as e:
            logger.warning(f"[BULK-MEMBER-EXPANSION] trigger failed (non-fatal): {e}")
    # ── End member-expansion trigger ──────────────────────────────────────────

    from urllib.parse import quote as _quote_corp
    from app.services.bulk_upload_service import build_bulk_success_message
    _base_corp = config.API_BASE_PATH

    # Computed once, after every file in this batch is already saved to disk —
    # not per file — so "Next, please upload X" reflects the true state after
    # the whole batch, and this stays a single cheap call instead of N of them.
    remaining_docs_for_msg = get_remaining_required_documents(email, user)

    # Only the LAST valid file's ack message gets the "Next, please upload X"
    # sentence. Every valid entry used to get it, since they all shared the
    # same remaining_docs_for_msg — so a 2-file batch (e.g. Ejari + EID
    # together) produced two back-to-back messages both ending in "Next,
    # please upload your MOA", which reads as the assistant repeating itself.
    # The instruction only needs to be said once per batch.
    _last_valid_idx = next(
        (i for i in range(len(deduped) - 1, -1, -1) if deduped[i].get("is_valid")),
        None,
    )

    results = []
    for _idx, r in enumerate(deduped):
        doc_type_r = (r.get("document_type") or "unknown").lower()
        filename_r = r.get("_filename")
        is_valid_r = bool(r.get("is_valid"))
        extracted_r = r.get("extracted_data")

        # Same preview_url shape the single-file path builds (upload_conversational,
        # ~line 1056) — the sidebar/report reads this field, not a client-side blob
        # URL, once the message comes back from a request instead of a local File.
        preview_url_r = None
        if is_valid_r and filename_r:
            preview_url_r = f"{_base_corp}/chatupload/get-document/{email}/{doc_type_r}/{_quote_corp(filename_r)}"

        # display_message is a deterministic acknowledgment worded to match
        # the single-file flow's LLM-generated text (see
        # generate_dynamic_valid_document_response — imported into this module
        # for re-export only, never called here). No LLM call per file: that
        # used to run in this exact loop, sequentially, one blocking OpenRouter
        # round trip per file, on top of the parallel OCR phase above — the
        # actual source of bulk-upload slowness. build_bulk_success_message now
        # produces the same phrasing from fixed strings instead.
        display_message_r = None
        if is_valid_r:
            display_message_r = build_bulk_success_message(
                doc_type_r, extracted_r,
                remaining_docs=remaining_docs_for_msg,
                suppress_next_step=(_idx != _last_valid_idx),
            )

        entry = {
            "filename": filename_r,
            "document_type": doc_type_r,
            "success": bool(r.get("success")),
            "is_valid": is_valid_r,
            "message": r.get("message"),
            "display_message": display_message_r,
            "duplicate_in_batch": bool(r.get("duplicate_in_batch")),
            # Feeds the frontend's report/vault views directly (extractedData /
            # documentMetadata on the chat message) instead of relying on the
            # client's healing/backfill matcher to find it after the fact.
            "extracted_data": extracted_r,
            "preview_url": preview_url_r,
        }
        results.append(entry)

        # Persisted log line uses display_message, NOT r.get("message") (see
        # above) — that stays out of chat history entirely now rather than
        # coming back verbatim, dump and all, the next time conversation
        # history is fetched and re-rendered.
        if is_valid_r:
            log_message = display_message_r
        else:
            log_message = f"❌ {filename_r}: {entry['message'] or 'could not be verified'}"

        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=log_message,
                channel="chat",
                metadata={
                    "message_type": "document_upload_bulk",
                    "filename": filename_r,
                    "document_type": doc_type_r,
                    "is_valid": is_valid_r,
                    "language": language,
                    # Restores extractedData/documentMetadata/previewUrl on a
                    # relogin/page-reload history replay, mirroring the
                    # single-file "extraction_result" log entry — without
                    # these, a reload after a bulk upload lost the Unified
                    # Report data and the document preview entirely, even
                    # though the live/in-session message had both.
                    "extracted_fields": extracted_r,
                    "document_info": {
                        "filename": filename_r,
                        "document_type": doc_type_r,
                        "preview_url": preview_url_r,
                    },
                },
            )
        except Exception as e:
            logger.warning(f"[BULK] log failed for {filename_r}: {e}")

    status = get_onboarding_status(email, user, skip_welcome=True)
    return {
        "success": True,
        "results": results,
        "remaining_documents": get_remaining_required_documents(email, user),
        "next_document": status.get("next_required_document"),
        "is_complete": status.get("is_complete", False),
        "stage_advanced": user.get("document_stage") != stage_before,
        "language": language,
    }


async def _bulk_member_documents(
    email: str, user: dict, language: str, files: List[UploadFile]
) -> dict:
    """
    Batch handler for member/AS/KI identity documents (Emirates ID or
    passport), one file per pending member.

    Assignment starts as submission order (file 1 -> first pending
    member, file 2 -> second, ...) — a distinct member has to be assigned
    before OCR even runs so process_uploaded_document gives each file a
    collision-free save path; two parallel non-member EID uploads would
    otherwise resolve to the identical folder name and clobber each
    other. Once OCR has run, the order-based guess is corrected against
    the extracted name (fuzzy_assign_members) and, if a better match
    exists elsewhere in the same batch, the saved file is physically
    moved to that member's folder (reassign_member_document) — so
    picking files in a different order than the member list still lands
    correctly, rather than only being flagged.

    Single Owner batches additionally get the same owner-name/nationality
    cross-check against the Commercial License that the single-file path
    runs (see upload_conversational's `_so_eid_uploaded` block above) — a
    mismatch here fails the file exactly as it would one at a time,
    instead of silently skipping a check the single-file path enforces.
    """
    import shutil
    from app.services.bulk_upload_service import (
        run_parallel, extract_person_name, name_matches_expected,
        fuzzy_assign_members, reassign_member_document,
    )
    from app.services.document_helpers import (
        get_document_ref_no, get_user_documents_path_by_ref, build_document_id, get_member_index,
    )
    from app.services.key_individual_service import update_ki_verification_by_name

    stage_before = user.get("document_stage")
    is_so_stage = stage_before == STAGE_SO_MEMBER_EIDS

    mp = load_member_progress(email) or {}
    members = mp.get("members", [])
    verified_raw = mp.get("verified_members", []) or []
    verified_now = [m for m in members if m in verified_raw]
    pending = [m for m in members if m not in verified_now]

    # Owner is tracked as the first "member" but their EID/passport is
    # saved at the document root rather than under members/, so they may
    # never show up in verified_members — same adjustment
    # upload_conversational makes for the single-file path.
    if pending and is_account_owner(email, pending[0]):
        owner_status = check_documents_status(email)
        if owner_status.get("eid") or owner_status.get("passport"):
            pending = pending[1:]

    if not pending:
        raise ValidationError("No pending members to assign documents to right now")

    assigned_members = pending[: len(files)]
    unassigned_files = files[len(assigned_members):]

    # Single Owner: fetch the Commercial License owner once, up front —
    # every file in this batch cross-checks against the same document, no
    # need to re-read it per file. Mirrors upload_conversational's
    # `_so_eid_uploaded` block, which does this same lookup per upload.
    so_commercial_owner_name = ""
    so_commercial_nationality = ""
    if is_so_stage:
        try:
            _, so_comm_data = _find_commercial_output(email)
            if so_comm_data:
                so_ext = so_comm_data.get("extracted_fields") or so_comm_data.get("extracted_data", {})
                so_owner = so_ext.get("owner", {})
                so_commercial_owner_name = (so_owner.get("name_english") or "").strip()
                so_commercial_nationality = (so_owner.get("nationality_english") or "").strip()
        except Exception as e:
            logger.warning(f"[BULK-MEMBERS] SO commercial lookup failed: {e}")

    def _process_one(pair):
        f, member_name = pair
        result = process_uploaded_document(email, f, member_name=member_name, language=language)
        result["_filename"] = f.filename
        result["_assigned_member"] = member_name
        return result

    raw_results = await run_parallel(list(zip(files[: len(assigned_members)], assigned_members)), _process_one)

    ref_no = user.get("ref_no") or get_document_ref_no(email)

    # ── correct the order-based guess using the extracted name ────────────
    extracted_names = [
        extract_person_name(r.get("extracted_data")) if r.get("is_valid") else None
        for r in raw_results
    ]
    correction = fuzzy_assign_members(assigned_members, extracted_names)
    final_members = []
    for i, r in enumerate(raw_results):
        original = r["_assigned_member"]
        corrected = correction.get(i)
        final_members.append(corrected if (corrected and corrected != original) else original)

    # ── physically move any file whose corrected member differs ───────────
    # Two-phase (vacate to a temp name, then move to the final name) rather
    # than a direct move, so a genuine swap between two files in the same
    # batch can't have one move overwrite the other's still-occupied slot.
    needs_move = [
        i for i, r in enumerate(raw_results)
        if r.get("is_valid") and final_members[i] != r["_assigned_member"]
    ]
    if needs_move:
        temp_dirs = {}
        for i in needs_move:
            r = raw_results[i]
            doc_type_i = (r.get("document_type") or "unknown").lower()
            orig_member = r["_assigned_member"]
            try:
                orig_index = get_member_index(email, orig_member)
                orig_doc_id = build_document_id(doc_type_i, ref_no, True, orig_index)
                orig_dir = get_user_documents_path_by_ref(ref_no) / "members" / orig_doc_id
                if not orig_dir.exists():
                    continue
                tmp_dir = orig_dir.parent / f"{orig_doc_id}__reassign_tmp{i}"
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir)
                orig_dir.rename(tmp_dir)
                temp_dirs[i] = tmp_dir
            except Exception as e:
                logger.warning(f"[BULK-REASSIGN] could not vacate slot for {orig_member}: {e}")

        for i, tmp_dir in temp_dirs.items():
            r = raw_results[i]
            doc_type_i = (r.get("document_type") or "unknown").lower()
            new_member = final_members[i]
            try:
                new_index = get_member_index(email, new_member)
                moved = reassign_member_document(tmp_dir, doc_type_i, ref_no, new_index)
                if not moved:
                    final_members[i] = r["_assigned_member"]
                    logger.warning(f"[BULK-REASSIGN] move incomplete for file {i}, keeping original label")
            except Exception as e:
                final_members[i] = r["_assigned_member"]
                logger.warning(f"[BULK-REASSIGN] move failed for file {i}: {e}")

    newly_verified: List[str] = []
    results = []

    from urllib.parse import quote as _quote_mem
    from app.services.bulk_upload_service import build_bulk_success_message
    _base_mem = config.API_BASE_PATH

    # Computed once, not per file/member — see the matching comment in
    # _bulk_corporate_documents above.
    remaining_docs_for_msg = get_remaining_required_documents(email, user)

    # Only the LAST valid result in this batch gets the "Next, please upload
    # X" sentence — see the matching comment on build_bulk_success_message's
    # suppress_next_step parameter. Validity here has to account for the SO
    # name/nationality cross-check below (a result that starts out
    # is_valid=True can still be rejected there), so this is a quick
    # pre-pass using the same check, rather than raw_results' own is_valid.
    def _survives_so_cross_check(_r) -> bool:
        if not bool(_r.get("is_valid")):
            return False
        if not (is_so_stage and so_commercial_owner_name):
            return True
        _ext = _r.get("extracted_data") or {}
        cv = CrossValidator()
        _eid_name = (_ext.get("Name") or _ext.get("name") or "").strip()
        _eid_nat = (_ext.get("Nationality") or _ext.get("nationality") or "").strip()
        if _eid_name and not cv._fuzzy_name_match(so_commercial_owner_name, _eid_name):
            return False
        if so_commercial_nationality and _eid_nat and not cv._fuzzy_name_match(so_commercial_nationality, _eid_nat):
            return False
        return True

    _last_valid_idx = next(
        (i for i in range(len(raw_results) - 1, -1, -1) if _survives_so_cross_check(raw_results[i])),
        None,
    )

    for i, r in enumerate(raw_results):
        member_name = final_members[i]
        extracted = r.get("extracted_data") or {}
        extracted_name = extracted_names[i]
        doc_type = (r.get("document_type") or "unknown").lower()
        filename_i = r.get("_filename")
        is_valid_i = bool(r.get("is_valid"))

        preview_url_i = None
        if is_valid_i and filename_i:
            preview_url_i = (
                f"{_base_mem}/chatupload/get-document/{email}/{doc_type}/{_quote_mem(filename_i)}"
                f"?member_name={_quote_mem(member_name)}"
            )

        entry = {
            "filename": filename_i,
            "member_name": member_name,
            "document_type": doc_type,
            "success": bool(r.get("success")),
            "is_valid": is_valid_i,
            "message": r.get("message"),
            "name_matches_expected": name_matches_expected(member_name, extracted_name),
            # Feeds the frontend's report/vault views directly, same reason
            # as the corporate-batch entries above.
            "extracted_data": r.get("extracted_data"),
            "preview_url": preview_url_i,
        }

        # Single Owner: reject on a name/nationality mismatch against the
        # Commercial License, same as the single-file `_so_eid_uploaded`
        # check — this only downgrades an already-valid OCR result, it
        # doesn't touch documents that failed OCR/tampering for other
        # reasons.
        if entry["is_valid"] and is_so_stage and so_commercial_owner_name:
            cv = CrossValidator()
            eid_name = (extracted.get("Name") or extracted.get("name") or "").strip()
            eid_nationality = (extracted.get("Nationality") or extracted.get("nationality") or "").strip()
            mismatches = []
            if eid_name and not cv._fuzzy_name_match(so_commercial_owner_name, eid_name):
                mismatches.append(f"name (licence: '{so_commercial_owner_name}', document: '{eid_name}')")
            if so_commercial_nationality and eid_nationality and not cv._fuzzy_name_match(so_commercial_nationality, eid_nationality):
                mismatches.append(f"nationality (licence: '{so_commercial_nationality}', document: '{eid_nationality}')")
            if mismatches:
                entry["is_valid"] = False
                entry["success"] = False
                entry["message"] = "Does not match the Commercial License — " + "; ".join(mismatches)
                logger.error(f"[BULK-SO-EID-CV] {entry['filename']} rejected — {mismatches}")

        # Computed after the SO cross-validation check above (not at entry
        # creation) so a mismatch-rejected file doesn't get a positive-sounding
        # display_message for a result that ends up marked invalid. Deterministic,
        # worded to match the single-file flow's LLM text — see the matching
        # comment in _bulk_corporate_documents above for why this is no longer
        # an LLM call.
        entry["display_message"] = None
        if entry["is_valid"]:
            entry["display_message"] = build_bulk_success_message(
                doc_type, entry.get("extracted_data"), member_name,
                remaining_docs=remaining_docs_for_msg,
                suppress_next_step=(i != _last_valid_idx),
            )

        results.append(entry)

        if not entry["is_valid"]:
            continue

        newly_verified.append(member_name)

        # Mark the saved document human_verified, same as the single-file
        # SO-EID path. The save location is deterministic from doc_type +
        # ref_no + this member's index, so it's reconstructed here rather
        # than needing process_uploaded_document to return it.
        try:
            member_index = get_member_index(email, member_name)
            doc_id = build_document_id(doc_type, ref_no, True, member_index)
            save_dir = get_user_documents_path_by_ref(ref_no) / "members" / doc_id
            output_json = save_dir / "output.json"
            if output_json.exists():
                with open(output_json, "r", encoding="utf-8") as fjson:
                    out_data = json.load(fjson)
                out_data["human_verified"] = True
                out_data["verified_at"] = datetime.now(timezone.utc).isoformat()
                with open(output_json, "w", encoding="utf-8") as fjson:
                    json.dump(out_data, fjson, indent=2, ensure_ascii=False)
            try:
                update_ki_verification_by_name(email=email, member_name=member_name, document_id=doc_id)
            except Exception as e:
                logger.warning(f"[BULK-MEMBERS] KI sync failed for {member_name}: {e}")
        except Exception as e:
            logger.warning(f"[BULK-MEMBERS] could not mark human_verified for {member_name}: {e}")

        try:
            insert_conversation_log(
                user_email=email, role="agent",
                message=entry["display_message"] or f"✅ {doc_type.upper()} for {member_name} verified.",
                channel="chat",
                metadata={
                    "message_type": "document_upload_bulk",
                    "filename": entry["filename"],
                    "member_name": member_name,
                    "document_type": doc_type,
                    "is_valid": True,
                    "language": language,
                    # Restores extractedData/documentMetadata/previewUrl on a
                    # relogin/page-reload history replay — same reasoning as
                    # the corporate-batch log entries above.
                    "extracted_fields": entry.get("extracted_data"),
                    "document_info": {
                        "filename": entry["filename"],
                        "document_type": doc_type,
                        "member_name": member_name,
                        "preview_url": entry.get("preview_url"),
                    },
                },
            )
        except Exception as e:
            logger.warning(f"[BULK-MEMBERS] log failed for {entry['filename']}: {e}")

    for f in unassigned_files:
        results.append({
            "filename": f.filename,
            "member_name": None,
            "document_type": None,
            "success": False,
            "is_valid": False,
            "message": localized(None,
                en="No pending member left for this file in this batch — upload it separately once a member is available.",
                es="No queda ningún miembro pendiente para este archivo en este lote. Cárguelo por separado cuando haya un miembro disponible.",
                ar="لا يوجد عضو معلّق متبقٍ لهذا الملف في هذه الدفعة — حمّله بشكل منفصل عند توفر عضو."),
            "name_matches_expected": None,
        })

    # ── single sequential write ──────────────────────────────────────────
    # Safe even though every worker above ran in parallel, because nothing
    # above touched member_progress.json — this is the only write, and it
    # happens once, after every worker has finished. Re-read fresh rather
    # than reusing `mp` in case anything else changed it while the batch
    # was processing.
    if newly_verified:
        try:
            progress_path = member_progress_path(email)
            if progress_path.exists():
                with open(progress_path, "r", encoding="utf-8") as f:
                    progress = json.load(f)
                current_verified = progress.get("verified_members", [])
                added = 0
                for name in newly_verified:
                    if name not in current_verified:
                        current_verified.append(name)
                        added += 1
                progress["verified_members"] = current_verified
                if is_so_stage:
                    progress["current_index"] = progress.get("current_index", 0) + added
                with open(progress_path, "w", encoding="utf-8") as f:
                    json.dump(progress, f, indent=2, ensure_ascii=False)
                logger.info(
                    f"[BULK-MEMBERS] {email} verified_members now "
                    f"{len(current_verified)}/{len(members)} after this batch"
                )
        except Exception as e:
            logger.warning(f"[BULK-MEMBERS] member_progress write failed: {e}")

    status = get_onboarding_status(email, user, skip_welcome=True)
    return {
        "success": True,
        "results": results,
        "remaining_documents": get_remaining_required_documents(email, user),
        "next_document": status.get("next_required_document"),
        "is_complete": status.get("is_complete", False),
        "stage_advanced": user.get("document_stage") != stage_before,
        "language": language,
    }
