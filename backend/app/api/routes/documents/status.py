"""
backend/app/api/routes/documents/status.py

Split out of the former app/api/routes/documents.py (2,635 lines) as part of
the god-file decomposition pass. Status, validation, member-list, confirmation-email and pre-confirmation validation endpoints.

Pure code motion: every handler below is moved verbatim (same decorator,
same path, same method, same body) from the original file — no logic was
changed. Verified with backend/tests/contract_check.py, which diffs the
declared route surface against baseline/routes.json and fails on any path,
method, handler-name or signature drift.

`router` here is created bare (no prefix) and mounted by
app/api/routes/documents/__init__.py under the shared "/documentupload"
prefix — the same pattern already used for app/api/routes/onboarding/*.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import EmailStr

# app/api/routes/documents.py

import json
import shutil
import tempfile
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import EmailStr

from app.domain.exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
)
from app.schemas.documents import GetDocumentRequirementsRequest, DocumentUploadRequest, DocumentUploadResponse, DocumentStatusResponse, MemberListResponse

# Import from app services
from app.services.supabase_client import supabase, get_user_by_email
from app.repositories.user_repository import UserRepository
from app.repositories.tampering_repository import TamperingRepository
from app.services.tampering_service import verify_document_authenticity
from app.services.llm_client import VISION_FALLBACK
# Stage B4 note: this block used to import all of the below from
# `app.api.routes.chatupload`. Seven of the fourteen names were never defined
# there — chatupload had imported them from services and this module was
# reading them back out, so a route module was acting as a re-export hub. Each
# name now comes from where it is actually defined.
from app.domain.onboarding.documents import (
    extract_members_from_commercial,
    validate_document_type_for_account,
)
from app.domain.onboarding.emails import send_wrong_document_type_email_dynamic
from app.domain.onboarding.members import save_member_progress
from app.domain.onboarding.stages import get_onboarding_status
from app.domain.onboarding.verification import process_uploaded_document
from app.services.chatupload_helpers import (
    check_documents_status,
    get_remaining_required_documents,
    insert_conversation_log,
    load_member_progress,
    user_docs_path,
)
from app.services.document_messaging import (
    generate_dynamic_invalid_document_response,
    generate_dynamic_valid_document_response,
)

from app.services.document_helpers import (
    get_user_documents_path,
    get_member_documents_path,
    save_document_with_version,
    normalize_and_validate_extracted_data,
    calculate_document_status,
    get_document_history,
    get_documents_base_path,  # ✅ config-driven base path (YAML / env var)
)

from app.services.chatupload_helpers import member_progress_path as get_member_progress_path
from app.services.email_sender import (
    send_corporate_shareholder_request_email,   # TYPE-2
)
# TYPE-2: Corporate shareholder detection
from app.services.specialized_ocr.corporate_shareholder_detector import (
    detect_corporate_shareholders as _detect_corps,
)
from app.services.eid_validation import validate_eid_before_confirmation
from app.services.document_expiry_validator import generate_expiry_failure_message
# ── v4: FATCA + PEP (paths only — the PEP endpoints live in chatupload.py) ────
from app.services.fatca_service import fatca_json_path
from app.services.pep_service import pep_json_path
# Create router
# ── Document domain logic (extracted from this file in Stage B3) ─────────────
# These were defined further down this module. They are unchanged; they simply
# have a home now. Note that `get_submitted_documents` and
# `get_display_document_name` were ALSO imported at the top of this file from
# chatupload / document_helpers — those imports were dead, because the local
# definitions below them shadowed the names. The imports have been removed and
# the real (local) implementations are imported here instead, so the behaviour
# is identical to what actually ran.
from app.domain.documents.discovery import (
    _find_commercial_output,
    delete_document_completely,
    find_user_documents_directory,
    get_document_file_path,
    get_submitted_documents,
)
from app.domain.documents.member_progress import (
    get_member_progress_with_status,
    update_member_progress_after_upload,
)
from app.domain.documents.normalizer import (
    get_display_document_name,
    map_fields_to_display_names,
    normalize_extracted_data,
)
from app.domain.documents.preview import (
    format_document_preview,
    get_document_preview_data,
    get_document_preview_html,
)
from app.domain.documents.status import (
    determine_status_category,
    extract_pdf_metadata,
    get_tampering_data_for_document,
)

# NOTE: this import used to sit at module level in the middle of the
# original documents.py (right before get_document_file), where Python's
# module-level execution order made it available to every function in the
# file regardless of where they were defined relative to it. Splitting the
# file into separate modules means each one now needs its own copy.
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
)

router = APIRouter()

@router.get("/check-confirmation-status/{email}")
async def check_confirmation_status(email: str):
    """Check if user already confirmed documents"""
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        response = UserRepository.get_confirmation_flag(email)
        
        if response.data:
            return {
                "confirmation_sent": response.data.get("document_confirmation_sent", False)
            }
        return {"confirmation_sent": False}
    except Exception as e:
        logger.error(f"check_confirmation_status: {e}")
        return {"confirmation_sent": False}

from datetime import datetime, timezone
@router.post("/send-completion-email")
async def send_completion_email_endpoint(request: dict):
    """
    Send final completion email when user confirms all documents
    ✅ UPDATED: Now runs pre-confirmation validation first
    ✅ Runs cross-validation + SurePass API validation ONCE
    ✅ Generates PDF summary using handle_reply.py function
    ✅ This is the ONLY place where validation happens
    """
    email = request.get("email")
    
    if not email:
        raise ValidationError("Email is required")
    
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    user_name = user.get("name", "User")
    account_type = user.get("account_type", "")
    
    try:
        logger.info(f"\n{'='*80}")
        logger.info(f"PROCESSING DOCUMENT CONFIRMATION")
        logger.info(f"Email: {email}")
        logger.info(f"User: {user_name}")
        logger.info(f"Account Type: {account_type}")
        logger.info(f"{'='*80}\n")
        
        # ============================================================================
        # ✅ NEW STEP 0: PRE-CONFIRMATION VALIDATION (VERSION CONFLICT CHECK)
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 0] PRE-CONFIRMATION VALIDATION")
        logger.info(f"{'='*80}\n")
        
        try:
            logger.info(f"Checking for document version conflicts...")
            
            # Import the validation function
            from app.services.document_helpers import detect_and_repair_version_conflicts
            
            # Run conflict detection and auto-repair
            conflict_check = detect_and_repair_version_conflicts(
                user_email=email,
                member_name=None,
                auto_repair=True
            )
            
            conflicts_found = conflict_check.get("conflicts_found", 0)
            conflicts_repaired = conflict_check.get("conflicts_repaired", 0)
            
            if conflicts_found > 0:
                logger.warning(f"Found {conflicts_found} version conflicts")
                
                if conflicts_repaired == conflicts_found:
                    # All conflicts successfully repaired
                    logger.info(f"[SUCCESS] All {conflicts_repaired} conflicts repaired automatically")
                    logger.info(f"Proceeding with confirmation after repair")
                else:
                    # Some conflicts could not be repaired
                    logger.error(f"Could only repair {conflicts_repaired}/{conflicts_found} conflicts")
                    
                    return {
                        "success": False,
                        "message": (
                            f"❌ Found {conflicts_found} version conflicts but could only repair {conflicts_repaired}. "
                            f"Please refresh the page and try again. If the issue persists, contact support."
                        ),
                        "validation_passed": False,
                        "conflicts_found": conflicts_found,
                        "conflicts_repaired": conflicts_repaired,
                        "pre_validation_failed": True
                    }
            else:
                logger.info(f"No version conflicts detected")
            
        except Exception as pre_validation_error:
            logger.error(f"Pre-confirmation validation failed: {pre_validation_error}")
            import traceback
            logger.error(traceback.format_exc())
            
            return {
                "success": False,
                "message": f"Pre-confirmation validation failed: {str(pre_validation_error)}",
                "validation_passed": False,
                "pre_validation_failed": True
            }
        
        logger.info(f"\n[SUCCESS] Pre-confirmation validation passed\n")
        
        # ============================================================================
        # 🔍 STEP 1: CHECK IF ALREADY COMPLETED
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 1] CHECKING COMPLETION STATUS")
        logger.info(f"{'='*80}\n")
        
        onboarding_step = user.get("onboarding_step", "")
        document_confirmation_sent = user.get("document_confirmation_sent", False)
        
        if document_confirmation_sent and onboarding_step == "verification_complete":
            logger.warning("User already completed onboarding")
            return {
                "success": True,
                "message": "Verification already completed",
                "validation_passed": True,
                "already_completed": True,
                "onboarding_step": "verification_complete"
            }
        
        logger.info(f"[INFO] User has not completed verification yet - proceeding\n")
        
        # ============================================================================
        # 🔍 STEP 2: RUN CROSS-VALIDATION
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 2] CROSS-VALIDATION")
        logger.info(f"{'='*80}\n")
        
        try:
            from app.services.cross_validator import CrossValidator
            from app.services.email_sender import send_email
            
            validator = CrossValidator()
            
            # ✅ STEP 2A: Send "Validation Pending" notification
            logger.info("Sending validation pending notification...")
            try:
                pending_subject = "⏳ Document Verification in Progress"
                pending_body = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <style>
                        body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                        .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                        .header {{ background: #3b82f6; color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
                        .content {{ padding: 30px; }}
                        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2 style="margin: 0;">⏳ Verification in Progress</h2>
                        </div>
                        <div class="content">
                            <p>Dear {user_name},</p>
                            <p>We are currently validating your submitted documents. This process typically takes 30-60 seconds.</p>
                            <p>You will receive another email shortly with the validation results.</p>
                        </div>
                        <div class="footer">
                            <p style="margin: 0;">Best regards,</p>
                            <p style="margin: 5px 0 0 0; font-weight: 600;">DigiOB Onboarding Team</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                send_email(email, pending_subject, pending_body, html=True)
                logger.info("[SUCCESS] Validation pending email sent")
            except Exception as pending_error:
                logger.warning(f"Could not send pending email: {pending_error}")
            
            # ✅ STEP 2B: Run cross-validation
            logger.info("Running cross-validation...")
            validation_result = validator.validate_documents(email, user)
            
            # ✅ STEP 2C: Save validation result as JSON
            logger.info("Saving validation result...")
            validator.save_validation_result(email, validation_result)
            logger.info("[SUCCESS] Validation result saved to JSON")
            
            # ============================================================================
            # 🔍 STEP 3: HANDLE CROSS-VALIDATION RESULT
            # ============================================================================
            if not validation_result["passed"]:
                # ❌ CROSS-VALIDATION FAILED
                logger.error(f"[ERROR] Cross-validation failed: {validation_result['mismatches']}")
                
                # Send failure notification
                mismatch_list = '<br>'.join([f"• {m}" for m in validation_result["mismatches"]])
                failure_subject = "❌ Document Validation Failed"
                failure_body = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="UTF-8">
                    <style>
                        body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                        .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
                        .header {{ background: #dc3545; color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
                        .content {{ padding: 30px; }}
                        .error-box {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                        .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2 style="margin: 0;">❌ Validation Failed</h2>
                        </div>
                        <div class="content">
                            <p>Dear {user_name},</p>
                            <div class="error-box">
                                <h3 style="color: #721c24; margin-top: 0;">Issues Found:</h3>
                                <p style="color: #721c24;">{mismatch_list}</p>
                            </div>
                            <p>Please review your documents and re-upload corrected versions.</p>
                        </div>
                        <div class="footer">
                            <p style="margin: 0;">Best regards,</p>
                            <p style="margin: 5px 0 0 0; font-weight: 600;">DigiOB Onboarding Team</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                try:
                    send_email(email, failure_subject, failure_body, html=True)
                    logger.info("Validation failure email sent")
                except Exception as fail_email_error:
                    logger.warning(f"Could not send failure email: {fail_email_error}")
                
                # Build error response
                error_list = '\n'.join([f"• {m}" for m in validation_result["mismatches"]])
                
                return {
                    "success": False,
                    "message": f"Cross-validation failed. Please review:\n\n{error_list}",
                    "validation_passed": False,
                    "validation_errors": validation_result["mismatches"],
                    "onboarding_step": "documents_pending"
                }
            
            # ✅ CROSS-VALIDATION PASSED
            logger.info("[SUCCESS] Cross-validation passed!\n")
            
        except Exception as validation_error:
            logger.error(f"Validation error: {validation_error}")
            import traceback
            logger.error(traceback.format_exc())
            raise DomainError(f"Validation error: {str(validation_error)}")
        
        # ============================================================================
        # ✅ STEP 4: SUREPASS API VALIDATION (if enabled)
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 4] SUREPASS GOVERNMENT VERIFICATION")
        logger.info(f"{'='*80}\n")
        
        try:
            surepass_valid, surepass_message = validate_eid_before_confirmation(email)
            
            if not surepass_valid:
                logger.error(f"[ERROR] SurePass validation failed: {surepass_message}")
                return {
                    "success": False,
                    "message": f"Government verification failed: {surepass_message}",
                    "validation_passed": False,
                    "surepass_failed": True
                }
            
            logger.info(f"[SUCCESS] SurePass validation passed!\n")
            
        except Exception as surepass_error:
            logger.error(f"SurePass error: {surepass_error}")
            return {
                "success": False,
                "message": f"Government verification error: {str(surepass_error)}",
                "validation_passed": False
            }
        
        # ============================================================================
        # ✅ STEP 5: UPDATE DATABASE
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 5] UPDATING DATABASE")
        logger.info(f"{'='*80}\n")
        
        try:
            update_payload = {
                "document_confirmation_sent": True,
                "confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
                "onboarding_step": "verification_complete",
                "document_stage": "complete"
            }
            
            logger.info(f"Updating database...")
            result = UserRepository.update_by_email(email, update_payload)
            logger.info(f"[SUCCESS] Database updated successfully\n")
            
        except Exception as db_error:
            logger.error(f"Failed to update database: {db_error}")
            import traceback
            logger.error(traceback.format_exc())
            # Continue to send email even if DB update fails
        
        # ============================================================================
        # ✅ STEP 6: GENERATE PDF AND SEND COMPLETION EMAIL
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 6] GENERATING PDF & SENDING EMAIL")
        logger.info(f"{'='*80}\n")
        
        try:
            # ✅ Call the function from handle_reply.py to generate PDF and send email
            from app.services.handle_reply import send_completion_email
            
            logger.info(f"Calling send_completion_email from handle_reply.py...")
            send_completion_email(email, account_type)
            logger.info(f"[SUCCESS] Completion email with PDF sent to {email}\n")
            
        except Exception as email_error:
            logger.error(f"Failed to send completion email: {email_error}")
            import traceback
            logger.error(traceback.format_exc())
            # Return error but mark as partially successful
            return {
                "success": True,
                "message": "Validation passed but email sending failed. User record updated.",
                "validation_passed": True,
                "email_failed": True,
                "email_error": str(email_error)
            }
        
        # ============================================================================
        # ✅ STEP 7: LOG CONVERSATION
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[STEP 7] LOGGING CONVERSATION")
        logger.info(f"{'='*80}\n")
        
        try:
            insert_conversation_log(
                user_email=email,
                role="agent",
                message=f"🎉 Document Verification Complete!\n\nUser confirmed all documents on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}.\n\n✅ Cross-validation: PASSED\n✅ Government verification: PASSED\n📧 Completion email with PDF sent",
                channel="document_upload"
            )
            logger.info(f"[SUCCESS] Conversation logged\n")
        except Exception as log_error:
            logger.warning(f"Could not log conversation: {log_error}")
        
        # ============================================================================
        # ✅ STEP 8: RETURN SUCCESS
        # ============================================================================
        logger.info(f"{'='*80}")
        logger.info(f"[SUCCESS] DOCUMENT CONFIRMATION COMPLETED SUCCESSFULLY")
        logger.info(f"{'='*80}\n")
        
        return {
            "success": True,
            "message": "Document verification complete! Check your email for PDF summary.",
            "validation_passed": True,
            "surepass_passed": True,
            "onboarding_step": "verification_complete",
            "document_stage": "complete",
            "pdf_generated": True,
            "email_sent": True,
            "conflicts_repaired": conflict_check.get("conflicts_repaired", 0) if 'conflict_check' in locals() else 0
        }
    
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"send_completion_email failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))

# Tracks the last logged (approved, required, missing, can_confirm, verified)
# tuple per email so get_document_status only emits a fresh INFO summary
# line when the outcome actually changes between polls, instead of once per
# poll (the frontend polls this endpoint every few seconds).
_last_document_status_log: dict = {}
@router.get("/document-status/{email}")
async def get_document_status(email: str):
    """
    Get current document submission status with complete tampering data
    
    ✅ UPDATED LOGIC: 
    - Smart confirmation that ignores old rejected/tampered docs if approved replacements exist
    - Only checks current documents (is_current=True)
    - ✅ ISSUE #3 FIX: Includes member EID counts for accurate Action Required display
    """
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        logger.debug(f"[document-status] request start for {email}")

        # ============================================================================
        # STEP 1: Get user status and check if already complete
        # ============================================================================
        onboarding_step = user.get("onboarding_step", "")
        document_confirmation_sent = user.get("document_confirmation_sent", False)
        account_type = user.get("account_type", "")
        ownership_type = user.get("ownership_type", "")
        document_stage = user.get("document_stage", STAGE_IDENTIFICATION)

        # Check if verification is complete
        is_already_complete = (
            onboarding_step == "verification_complete" or
            document_confirmation_sent == True
        )

        logger.debug(
            f"[document-status] user status: step={onboarding_step} "
            f"confirmation_sent={document_confirmation_sent} already_complete={is_already_complete} "
            f"account={account_type}/{ownership_type} stage={document_stage}"
        )
        
        # ============================================================================
        # STEP 2: Get ALL documents (will be categorized)
        # ============================================================================
        all_documents = get_submitted_documents(email, include_all=True)
        
        # Map field names to display names for frontend
        for doc in all_documents:
            doc_type = doc.get("document_type", "")
            raw_extracted = doc.get("extracted_data", {})
            if raw_extracted:
                doc["extracted_data"] = map_fields_to_display_names(raw_extracted, doc_type)

        # Categorize documents
        approved_docs = [d for d in all_documents if d["status_category"] == "approved"]
        tampered_docs = [d for d in all_documents if d["status_category"] == "tampered"]
        rejected_docs = [d for d in all_documents if d["status_category"] == "rejected"]

        # Filter to only CURRENT documents for status calculation
        current_approved = [d for d in approved_docs if d.get("is_current") == True]
        current_tampered = [d for d in tampered_docs if d.get("is_current") == True]
        current_rejected = [d for d in rejected_docs if d.get("is_current") == True]

        logger.debug(
            f"[document-status] breakdown approved={len(approved_docs)}(cur={len(current_approved)}) "
            f"tampered={len(tampered_docs)}(cur={len(current_tampered)}) "
            f"rejected={len(rejected_docs)}(cur={len(current_rejected)})"
        )
        
        # ============================================================================
        # STEP 3: Determine required documents based on account type
        # ============================================================================
        required_doc_types = []

        if account_type == ACCOUNT_CORPORATE:
            if ownership_type == OWNERSHIP_SINGLE:
                required_doc_types = ["commercial", "eid", "ejari"]
            elif ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
                if document_stage == STAGE_IDENTIFICATION:
                    required_doc_types = ["commercial", "moa"]
                elif document_stage == STAGE_MEMBER_EIDS:
                    required_doc_types = ["commercial", "moa"]
                else:
                    required_doc_types = ["commercial", "moa"]
        
        logger.debug(f"[document-status] required_doc_types={required_doc_types}")

        # ============================================================================
        # STEP 4: Use helper function to calculate status
        # ============================================================================
        status_calc = calculate_document_status(
            user_email=email,
            required_doc_types=required_doc_types,
            documents=all_documents,
            member_name=None
        )

        is_complete = status_calc["can_confirm"]
        remaining_docs = status_calc["missing_documents"]

        logger.debug(
            f"[document-status] status_calc can_confirm={status_calc['can_confirm']} "
            f"all_submitted={status_calc['all_submitted']} all_approved={status_calc['all_approved']} "
            f"missing={status_calc['missing_documents']} pending={status_calc['pending_approval']} "
            f"approved={status_calc['total_approved']}/{status_calc['total_required']}"
        )
        
        # ============================================================================
        # STEP 5: SMART CONFIRMATION LOGIC
        # ============================================================================
        approved_doc_types = set()
        for doc in current_approved:
            doc_type_normalized = doc["document_type"].lower()
            approved_doc_types.add(doc_type_normalized)
            
            if doc_type_normalized in ["tenancy", "ejari"]:
                approved_doc_types.update(["ejari", "tenancy"])
            elif doc_type_normalized in ["moa", "memorandum"]:
                approved_doc_types.update(["moa", "memorandum"])
            elif doc_type_normalized in ["commercial", "commercial_license", "trade_license"]:
                approved_doc_types.update(["commercial", "commercial_license", "trade_license"])
        
        blocking_rejected = []
        for doc in current_rejected:
            doc_type_normalized = doc["document_type"].lower()
            
            is_required = False
            for req_type in required_doc_types:
                if doc_type_normalized == req_type.lower():
                    is_required = True
                    break
                if doc_type_normalized in ["tenancy", "ejari"] and req_type.lower() in ["tenancy", "ejari"]:
                    is_required = True
                    break
                if doc_type_normalized in ["moa", "memorandum"] and req_type.lower() in ["moa", "memorandum"]:
                    is_required = True
                    break
            
            if is_required and doc_type_normalized not in approved_doc_types:
                blocking_rejected.append(doc_type_normalized)

        blocking_tampered = []
        for doc in current_tampered:
            doc_type_normalized = doc["document_type"].lower()
            
            is_required = False
            for req_type in required_doc_types:
                if doc_type_normalized == req_type.lower():
                    is_required = True
                    break
                if doc_type_normalized in ["tenancy", "ejari"] and req_type.lower() in ["tenancy", "ejari"]:
                    is_required = True
                    break
                if doc_type_normalized in ["moa", "memorandum"] and req_type.lower() in ["moa", "memorandum"]:
                    is_required = True
                    break
            
            if is_required and doc_type_normalized not in approved_doc_types:
                blocking_tampered.append(doc_type_normalized)

        logger.debug(
            f"[document-status] smart-confirmation approved_types={approved_doc_types} "
            f"blocking_rejected={blocking_rejected} blocking_tampered={blocking_tampered}"
        )

        can_confirm = (
            is_complete and
            len(blocking_tampered) == 0 and
            len(blocking_rejected) == 0 and
            not is_already_complete
        )
        
        # ============================================================================
        # STEP 5B: ENHANCED MEMBER EID VALIDATION
        # ============================================================================
        member_eid_status = None
        
        if can_confirm and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            # Load member progress
            member_progress = load_member_progress(email)

            if member_progress and member_progress.get("members"):
                members = member_progress["members"]
                current_index = member_progress.get("current_index", 0)
                all_members_completed = member_progress.get("all_members_completed", False)

                # Normalize member names for comparison
                normalized_member_names = [name.strip().lower() for name in members]

                # Find all member EID documents
                approved_member_eids = []
                for doc in current_approved:
                    doc_type = doc.get("document_type", "").lower()
                    member_name = doc.get("member_name", "").strip()

                    if doc_type in ["eid", "emirates_id"] and member_name:
                        normalized_doc_member = member_name.lower()
                        if normalized_doc_member in normalized_member_names:
                            approved_member_eids.append(doc)

                total_members = len(members)
                approved_eids = len(approved_member_eids)

                # Check which members are missing
                members_with_eids = set(doc.get("member_name", "").strip().lower() for doc in approved_member_eids)
                missing_members = [m for m in members if m.strip().lower() not in members_with_eids]

                logger.debug(
                    f"[document-status] member-eid-validation total={total_members} approved={approved_eids} "
                    f"missing={missing_members}"
                )

                # Determine if all members have approved EIDs
                if approved_eids < total_members:
                    can_confirm = False

                    member_eid_status = {
                        "required": True,
                        "total_members": total_members,
                        "submitted_eids": approved_eids,
                        "pending_eids": total_members - approved_eids,
                        "members": members,
                        "current_member_index": current_index,
                        "missing_members": missing_members
                    }
                else:
                    # Update member_progress.json with completion flag if not already set
                    if not all_members_completed:
                        try:
                            member_progress["all_members_completed"] = True
                            member_progress["completed_at"] = datetime.now(timezone.utc).isoformat()

                            from app.services.document_helpers import get_document_ref_no as _gdr, get_documents_base_path as _gdbp
                            _rno = user.get("ref_no") or _gdr(email)
                            member_progress_path = _gdbp() / _rno / "member_progress.json"
                            with open(member_progress_path, 'w') as f:
                                json.dump(member_progress, f, indent=2)
                        except Exception as flag_error:
                            logger.warning(f"[document-status] could not set all_members_completed flag for {email}: {flag_error}")

                    member_eid_status = {
                        "required": True,
                        "total_members": total_members,
                        "submitted_eids": approved_eids,
                        "pending_eids": 0,
                        "all_complete": True
                    }

            else:
                # No member progress found
                can_confirm = False
                member_eid_status = {
                    "required": True,
                    "error": "Member list not initialized"
                }
        
        # ============================================================================
        # ✅ ISSUE #3 FIX: Calculate member EID counts for Action Required display
        # ============================================================================
        member_eid_pending = 0
        member_eid_rejected = 0
        member_eid_under_review = 0
        total_members = 0
        
        if ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            member_progress = load_member_progress(email)
            
            if member_progress and member_progress.get("members"):
                total_members = len(member_progress["members"])
                member_names_set = set(m.strip().lower() for m in member_progress["members"])
                
                # Count member EIDs by status
                approved_member_eids = []
                rejected_member_eids = []
                tampered_member_eids = []
                
                for doc in all_documents:
                    doc_type = doc.get("document_type", "").lower()
                    member_name = doc.get("member_name", "")
                    is_current = doc.get("is_current", True)
                    
                    # Only count current EID documents for members
                    if doc_type in ["eid", "emirates_id"] and member_name and is_current:
                        # Check if this member is in the expected list
                        if member_name.strip().lower() in member_names_set:
                            status_cat = doc.get("status_category", "")
                            
                            if status_cat == "approved":
                                approved_member_eids.append(member_name)
                            elif status_cat == "rejected":
                                rejected_member_eids.append(member_name)
                            elif status_cat == "tampered":
                                tampered_member_eids.append(member_name)
                
                # Calculate pending count
                member_eid_pending = total_members - len(approved_member_eids)
                member_eid_rejected = len(rejected_member_eids)
                member_eid_under_review = len(tampered_member_eids)

        # ============================================================================
        # STEP 6: Get current stage and member info
        # ============================================================================
        status = get_onboarding_status(email, user, skip_welcome=True)

        # One INFO line carries the whole outcome of this request, tagged
        # with the request id automatically (see main.py RequestIdFilter).
        # Repeated polls from the frontend that return the *same* result are
        # skipped so the log only grows when something actually changes —
        # see _last_document_status_log below.
        status_key = (
            status_calc['total_approved'], status_calc['total_required'],
            tuple(status_calc['missing_documents']), can_confirm, is_already_complete,
        )
        if _last_document_status_log.get(email) != status_key:
            _last_document_status_log[email] = status_key
            logger.info(
                f"[document-status] {email} approved={status_calc['total_approved']}/{status_calc['total_required']} "
                f"missing={status_calc['missing_documents']} can_confirm={can_confirm} "
                f"already_verified={is_already_complete}"
            )
        else:
            logger.debug(f"[document-status] {email} unchanged since last poll — skipping repeat INFO log")

        response = {
            "email": email,
            "account_type": account_type,
            "ownership_type": ownership_type,
            
            # Categorized documents
            "approved_documents": current_approved,
            "tampered_documents": current_tampered,
            "rejected_documents": current_rejected,
            
            # Counts
            "approved_count": len(current_approved),
            "tampered_count": len(current_tampered),
            "rejected_count": len(current_rejected),
            "total_count": len(current_approved) + len(current_tampered) + len(current_rejected),
            
            # Legacy field
            "documents": current_approved,
            
            # Status
            "remaining_documents": remaining_docs,
            "is_complete": is_complete or is_already_complete,
            "stage": status.get("stage"),
            "members_info": status.get("members_info"),
            
            # Verification status
            "verification_complete": is_already_complete,
            "onboarding_step": onboarding_step,
            "can_confirm": can_confirm,
            
            # Additional context
            "document_stage": document_stage,
            "required_document_types": required_doc_types,
            
            # Status details
            "status_details": {
                "total_required": status_calc['total_required'],
                "total_submitted": status_calc['total_submitted'],
                "total_approved": status_calc['total_approved'],
                "missing_documents": status_calc['missing_documents'],
                "pending_approval": status_calc['pending_approval']
            },
            
            # Smart confirmation details
            "confirmation_blockers": {
                "blocking_rejected": blocking_rejected,
                "blocking_tampered": blocking_tampered,
                "approved_doc_types": list(approved_doc_types)
            },
            
            # ✅ ISSUE #3 FIX: Member EID specific counts
            "member_eid_counts": {
                "pending": member_eid_pending,
                "rejected": member_eid_rejected,
                "under_review": member_eid_under_review,
                "total_required": total_members
            }
        }
        
        # Add member EID status if applicable
        if member_eid_status:
            response["member_eid_status"] = member_eid_status
        
        return response
        
    except Exception as e:
        logger.error(f"[document-status] failed for {email}: {e}", exc_info=True)
        raise DomainError(context=str(e))
@router.get("/member-list/{email}")
async def get_member_list(email: str):
    """Get list of members with document status for Corporate Partnership/Multiple Owners"""
    try:
        logger.info(f"\n{'='*80}")
        logger.info(f"[ENDPOINT] GET /member-list/{email}")
        logger.info(f"{'='*80}\n")
        
        # ✅ Use new function that includes status
        progress_with_status = get_member_progress_with_status(email)
        
        if not progress_with_status:
            logger.error(f"get_member_list: No member progress found for {email}")
            raise NotFoundError("Member list not found")
        
        logger.info(f"[SUCCESS] Member list retrieved:")
        logger.info(f"  - Total Members: {progress_with_status.get('total_members', 0)}")
        logger.info(f"  - Current Index: {progress_with_status.get('current_index', 0)}")
        logger.info(f"  - All Complete: {progress_with_status.get('all_members_completed', False)}")
        
        return {
            "success": True,
            "members": progress_with_status.get("members", []),
            "current_index": progress_with_status.get("current_index", 0),
            "total_members": progress_with_status.get("total_members", 0),
            "member_statuses": progress_with_status.get("member_statuses", {}),
            "all_members_completed": progress_with_status.get("all_members_completed", False)
        }
        
    except FileNotFoundError:
        logger.error(f"get_member_list: File not found for {email}")
        raise NotFoundError("Member progress file not found")
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"get_member_list: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))
@router.get("/validation-status/{email}")
async def get_validation_status(email: str):
    """Get current validation status"""
    try:
        from app.services.cross_validator import CrossValidator
        
        validator = CrossValidator()
        result = validator.load_validation_result(email)
        
        if not result:
            return {
                "status": "not_started",
                "message": "No validation run yet"
            }
        
        status_map = {
            True: "passed",
            False: "failed"
        }
        
        return {
            "status": status_map.get(result.get("passed"), "unknown"),
            "timestamp": result.get("timestamp"),
            "attempt_count": result.get("attempt_count", 0),
            "mismatches": result.get("mismatches", []),
            "validation_details": result.get("validation_details", {}),
            "message": result.get("message", "")
        }
        
    except Exception as e:
        logger.error(f"get_validation_status: {e}")
        raise DomainError(context=str(e))
@router.post("/validate-before-confirmation")
async def validate_before_confirmation(request: dict):
    """
    Validate system state before allowing confirmation
    Checks for version conflicts and other inconsistencies
    """
    email = request.get("email")
    
    if not email:
        raise ValidationError("Email is required")
    
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        # Run conflict detection and repair
        from app.services.document_helpers import detect_and_repair_version_conflicts
        
        logger.info(f"[VALIDATION] Pre-confirmation checks for {email}...")
        
        conflict_check = detect_and_repair_version_conflicts(
            email,
            member_name=None,
            auto_repair=True
        )
        
        if conflict_check["conflicts_found"] > 0:
            if conflict_check["conflicts_repaired"] == (conflict_check["conflicts_found"]):
                return {
                    "success": True,
                    "can_proceed": True,
                    "message": f"✅ Found and repaired {conflict_check['conflicts_repaired']} version conflicts. You can now proceed.",
                    "conflicts_repaired": conflict_check["conflicts_repaired"]
                }
            else:
                return {
                    "success": False,
                    "can_proceed": False,
                    "message": f"❌ Found {conflict_check['conflicts_found']} version conflicts but could only repair {conflict_check['conflicts_repaired']}. Please contact support.",
                    "conflicts_found": conflict_check["conflicts_found"],
                    "conflicts_repaired": conflict_check["conflicts_repaired"]
                }
        
        return {
            "success": True,
            "can_proceed": True,
            "message": "✅ All validations passed. Ready for confirmation.",
            "conflicts_found": 0
        }
        
    except Exception as e:
        logger.error(f"Pre-confirmation validation failed: {e}")
        raise DomainError(context=str(e))





# Export router
