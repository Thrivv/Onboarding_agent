"""
Document upload, preview, download and status endpoints.

Renamed from `documentpage.py` in Stage B3 — "page" was a frontend concept, and
this module is a resource, not a screen. Every route keeps its exact path,
method, request and response shape; only the module name and the location of
its helpers changed.

What lives here now
-------------------
Route handlers only: parse the request, call into `app.domain.documents.*`,
shape the response. The 16 helper functions that used to sit between the
handlers (1,100+ lines of discovery, preview, normalisation and status logic)
moved to `app/domain/documents/` and are imported below.

`upload_document` (930 lines) was deliberately NOT decomposed here. It is moved
as-is; breaking it up happens alongside its `chatupload` twin so the shared
upload pipeline gets designed once rather than twice.
"""

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

# Create router
router = APIRouter(prefix="/documentupload", tags=["Document Upload"])

# ============================================================================
# PYDANTIC MODELS
# ============================================================================


    
# ============================================================================
# PDF EXTRACTION HELPER
# ============================================================================

# ✅ FIX: Ensure UTF-8 encoding for all responses
import sys
import locale

# Set UTF-8 encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Set locale
try:
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
except:
    pass




# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

    









# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/get-document-requirements", response_model=dict)
async def get_document_requirements(request: GetDocumentRequirementsRequest):
    """
    Get required documents for user's account type.
    Always returns the FULL journey document list (not stage-specific) so that
    sidebar counts remain stable across all stages of the onboarding flow.
    """
    email = request.email

    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")

    account_type   = user.get("account_type")
    ownership_type = user.get("ownership_type")
    document_stage = user.get("document_stage", STAGE_IDENTIFICATION)

    try:
        from app.services.chatupload_helpers import get_full_journey_document_types

        # Full-journey list: sidebar counts stay stable as stages change
        allowed_info   = get_full_journey_document_types(account_type, ownership_type, email)
        doc_status     = check_documents_status(email)
        submitted_docs = get_submitted_documents(email)

        # Map display names → internal keys for sidebar matching
        display_to_internal = {
            "Emirates ID (EID)":                              "eid",
            "Emirates ID":                                    "eid",
            "Emirates ID (EID) or Passport":                  "identity",
            "Emirates ID (EID) or Passport for each member":  "identity",
            "Commercial License":                             "commercial",
            "Ejari (Tenancy Contract)":                       "ejari",
            "Ejari (Address Proof)":                          "ejari",
            "Ejari":                                          "ejari",
            "Tenancy Contract":                               "ejari",
            "Memorandum of Association (MOA)":                "moa",
            "Memorandum of Association":                      "moa",
            "MOA":                                            "moa",
            "Certificate of Incorporation":                   "certificate_of_incorporation",
        }

        required_internal_keys = [
            display_to_internal.get(d, d.lower())
            for d in allowed_info["required_docs"]
        ]

        logger.info(f"[DOC-REQ] Full-journey docs for {email} "
              f"({account_type}/{ownership_type}/stage={document_stage}): "
              f"{required_internal_keys}")

        document_status = {}
        for doc_type in allowed_info["allowed_types"]:
            document_status[doc_type] = {
                "submitted": doc_status.get(doc_type, False),
                "required":  doc_type in required_internal_keys,
            }

        return {
            "success":                    True,
            "account_type":               account_type,
            "ownership_type":             ownership_type,
            "stage":                      document_stage,
            "stage_description":          allowed_info["stage_description"],
            "required_documents":         required_internal_keys,
            "required_documents_display": allowed_info["required_docs"],
            "allowed_types":              allowed_info["allowed_types"],
            "document_status":            document_status,
            "submitted_documents":        submitted_docs,
            "is_complete": (
                len([d for d in document_status.values() if d["required"]]) ==
                len([d for d in document_status.values() if d["submitted"] and d["required"]])
            ),
        }

    except Exception as e:
        logger.error(f"get_document_requirements: {e}")
        raise DomainError(context=str(e))



@router.get("/debug-document/{email}/{doc_type}")
async def debug_document_data(email: str, doc_type: str):
    """
    Debug endpoint to check what data is stored in output.json
    """
    try:
        base_path = find_user_documents_directory(email)
        
        if not base_path:
            return {"error": "Document directory not found"}
        
        # Scan for matching document
        for item in base_path.iterdir():
            if not item.is_dir():
                continue
            
            output_file = item / "output.json"
            if not output_file.exists():
                continue
            
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            stored_doc_type = data.get("document_type", "").lower()
            if stored_doc_type != doc_type.lower():
                continue
            
            # Found matching document
            return {
                "success": True,
                "document_type": data.get("document_type"),
                "filename": data.get("filename"),
                "is_valid": data.get("is_valid"),
                "raw_data_keys": list(data.keys()),
                "extracted_fields": data.get("extracted_fields"),
                "extracted_data": data.get("extracted_data"),
                "validation": data.get("validation"),
                "full_output_json": data  # Complete data for inspection
            }
        
        return {"error": f"No document found for type: {doc_type}"}
        
    except Exception as e:
        return {"error": str(e)}


@router.post("/upload-document", response_model=DocumentUploadResponse)
async def upload_document(
    email: EmailStr = Form(...),
    member_name: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    """
    ✅ FIXED: Complete upload endpoint - saves ALL uploads (including failures)

    Changes:
    - Always saves documents to disk (even failures)
    - No premature cleanup/deletion
    - Proper metadata for all rejection types
    - Consistent response structure
    - Member extraction and progress tracking
    - ✅ FIX: Uses all_names (flat list) instead of members (list of dicts)
    - ✅ FIX: Uses shared save_member_progress() + get_member_progress_path()
    """

    logger.info(f"\n{'='*80}")
    logger.info(f"[UPLOAD] Document upload started")
    logger.info(f"[INFO] Email: {email}")
    logger.info(f"[INFO] Member: '{member_name}'")
    logger.info(f"{'='*80}\n")

    # ========================================================================
    # STEP 0: VALIDATE USER AND FILES
    # ========================================================================
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")

    if not files:
        raise ValidationError("No file provided")

    uploaded_file = files[0]
    user_name = user.get("name", "User")
    account_type = user.get("account_type", "")

    clean_member_name = None
    if member_name is not None and member_name.strip():
        clean_member_name = member_name.strip()

    # Resolve ref_no for path construction (new naming convention)
    from app.services.document_helpers import get_document_ref_no as _get_ref_no
    _ref_no_for_path = user.get("ref_no") or _get_ref_no(email)

    # Temp fallback — will be replaced with the prefix-based doc_id from OCR result
    document_id = Path(uploaded_file.filename).stem
    logger.info(f"Document ID (initial fallback): {document_id}")

    # ========================================================================
    # STEP 1: SAVE TO TEMPORARY DIRECTORY
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 1] SAVING TO TEMPORARY DIRECTORY")
    logger.info(f"{'='*80}\n")

    temp_dir = None
    temp_file_path = None

    try:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"upload_{email}_"))
        temp_file_path = temp_dir / uploaded_file.filename

        file_content = await uploaded_file.read()
        with open(temp_file_path, "wb") as f:
            f.write(file_content)

        logger.info(f"[SUCCESS] File saved to temp: {temp_file_path}")
        logger.info(f"[INFO] File size: {len(file_content)} bytes\n")

    except Exception as e:
        logger.error(f"[ERROR] Failed to save to temp: {e}")
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise DomainError(context=f"Failed to save file: {str(e)}")

    # ========================================================================
    # STEP 2: PROCESS DOCUMENT (OCR + Extraction)
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 2] PROCESSING DOCUMENT")
    logger.info(f"{'='*80}\n")

    from io import BytesIO
    temp_upload_file = UploadFile(
        filename=uploaded_file.filename,
        file=BytesIO(file_content)
    )

    result = process_uploaded_document(email, temp_upload_file, clean_member_name)

    # Use the prefix-based document_id from process_uploaded_document (e.g. TL-{ref_no})
    document_id = result.get("document_id", document_id)
    logger.info(f"Document ID (after OCR): {document_id}")

    doc_type = result.get("document_type", "unknown")
    validation_result = result.get("validation", {})
    raw_extracted_data = result.get("extracted_data") or result.get("extracted_fields") or {}
    is_valid = result.get("is_valid", False)

    logger.info(f"[INFO] Document Type: {doc_type}")
    logger.info(f"[INFO] Validation Status: {is_valid}")
    logger.info(f"[INFO] Raw data keys: {list(raw_extracted_data.keys())[:5]}")

    # ========================================================================
    # STEP 2.5: NORMALIZE EXTRACTED DATA
    # ========================================================================
    logger.info(f"\n[DATA] Normalizing extracted data...")

    extracted_fields = {}
    normalization_failed = False
    normalization_error = None

    try:
        if raw_extracted_data and isinstance(raw_extracted_data, dict):
            extracted_fields = normalize_and_validate_extracted_data(
                raw_extracted_data,
                doc_type
            )
            logger.info(f"[DATA] Normalized {len(extracted_fields)} fields")
        else:
            logger.warning(f"[DATA] No raw data to normalize")
            normalization_failed = True
            normalization_error = "No data extracted from document"
    except ValueError as norm_error:
        logger.error(f"[DATA] Normalization failed: {norm_error}")
        normalization_failed = True
        normalization_error = str(norm_error)
        extracted_fields = {}

    # ========================================================================
    # ✅ HELPER FUNCTION TO SAVE FAILED UPLOAD
    # ========================================================================
    def save_and_respond_failure(
        failure_type: str,
        error_message: str,
        status_category: str = "rejected",
        additional_metadata: dict = None
    ):
        """Helper to save failed upload and return proper response."""
        logger.error(f"\n[FAILURE] {failure_type}: {error_message}")

        failure_metadata = {
            "status_category": status_category,
            "ai_reasoning": error_message,
            "failure_type": failure_type
        }

        if additional_metadata:
            failure_metadata.update(additional_metadata)

        version_info = {}

        try:
            success, message, version_info = save_document_with_version(
                user_email=email,
                document_type=doc_type,
                document_id=document_id,
                filename=uploaded_file.filename,
                file_content=file_content,
                extracted_data=extracted_fields,
                is_valid=False,
                validation_result=validation_result,
                member_name=clean_member_name,
                additional_data=failure_metadata
            )

            if success:
                logger.info(f"[SAVED] Failed upload saved as v{version_info.get('next_version', 1)}")
            else:
                logger.warning(f"[WARN] Could not save failed upload: {message}")

        except Exception as save_error:
            logger.error(f"[ERROR] Failed to save: {save_error}")

        finally:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info(f"[CLEANUP] Temp directory removed\n")

        if clean_member_name:
            file_path_str = str(get_documents_base_path() / _ref_no_for_path / "members" / document_id / uploaded_file.filename)
        else:
            file_path_str = str(get_documents_base_path() / _ref_no_for_path / document_id / uploaded_file.filename)

        remaining_docs = get_remaining_required_documents(email, user)

        return DocumentUploadResponse(
            success=False,
            message=error_message,
            document_type=doc_type,
            extracted_data=None,
            is_valid=False,
            is_complete=False,
            awaiting_verification=False,
            document_file_path=file_path_str,
            next_document=None,
            remaining_documents=remaining_docs,
            wrong_document_type=(failure_type == "wrong_document_type"),
            cross_validation_passed=None,
            cross_validation_errors=None,
            decision="REJECTED",
            tampering_detected=False,
            manual_review_required=False,
            filename=uploaded_file.filename,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            version=version_info.get("next_version", 1),
            status_category=status_category,
            ai_reasoning=error_message
        )

    # ========================================================================
    # ❌ HANDLE UNKNOWN DOCUMENT TYPE
    # ========================================================================
    if not result["success"] or doc_type == "unknown":
        logger.error(f"\n[ERROR] Unknown or failed document: {doc_type}")

        try:
            from app.services.handle_reply import generate_reasoning_for_wrong_document, send_reasoning_email

            raw_text = result.get("raw_text", "")

            if not raw_text:
                logger.info(f"Extracting text for reasoning...")
                ext = Path(temp_file_path).suffix.lower()

                try:
                    if ext == '.pdf':
                        import fitz
                        doc = fitz.open(str(temp_file_path))
                        raw_text = ""
                        for i in range(min(5, doc.page_count)):
                            page = doc.load_page(i)
                            raw_text += page.get_text()
                        doc.close()
                    elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
                        from app.services.ocr_service import run_ocr
                        raw_text = run_ocr(str(temp_file_path), VISION_FALLBACK)
                except Exception as e:
                    logger.warning(f"Failed to extract text: {e}")
                    raw_text = "[TEXT EXTRACTION FAILED]"

            reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)
            send_reasoning_email(
                to_email=email,
                filename=uploaded_file.filename,
                doc_type=doc_type if doc_type != "unknown" else "Unknown Document",
                reasoning=reasoning
            )
            logger.info(f"[SUCCESS] Reasoning email sent\n")

        except Exception as e:
            logger.error(f"Reasoning generation failed: {e}")
            reasoning = result.get("message", "Document type could not be identified")

        return save_and_respond_failure(
            failure_type="unknown_document",
            error_message=reasoning,
            status_category="rejected"
        )

    # ========================================================================
    # STEP 3: VALIDATE DOCUMENT TYPE AGAINST ACCOUNT
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 3] VALIDATING DOCUMENT TYPE AGAINST ACCOUNT")
    logger.info(f"{'='*80}\n")

    is_valid_type, error_message, allowed_info = validate_document_type_for_account(
        email=email,
        doc_type=doc_type,
        user_data=user,
        member_name=clean_member_name
    )

    logger.info(f"[INFO] Document type valid for account: {is_valid_type}\n")

    # ========================================================================
    # ❌ HANDLE WRONG DOCUMENT TYPE
    # ========================================================================
    if not is_valid_type:
        logger.error(f"[ERROR] Wrong document type detected: {doc_type}")

        dynamic_error_message = generate_dynamic_invalid_document_response(
            uploaded_doc_type=doc_type,
            allowed_info=allowed_info,
            email=email,
            user_data=user,
            member_name=clean_member_name
        )

        try:
            send_wrong_document_type_email_dynamic(
                to_email=email,
                user_name=user_name,
                uploaded_doc_type=doc_type,
                allowed_info=allowed_info,
                email=email,
                user_data=user,
                member_name=clean_member_name
            )
            logger.info(f"[SUCCESS] Wrong document type email sent\n")
        except Exception as e:
            logger.warning(f"[WARN] Failed to send email: {e}\n")

        return save_and_respond_failure(
            failure_type="wrong_document_type",
            error_message=dynamic_error_message,
            status_category="rejected",
            additional_metadata={
                "expected_types": allowed_info.get("required_docs", []),
                "received_type": doc_type
            }
        )

    # ========================================================================
    # ❌ HANDLE INVALID DOCUMENT (extraction/validation failed)
    # ========================================================================
    if not result["success"] or not is_valid or normalization_failed:
        logger.error(f"[ERROR] Document validation or normalization failed")

        failure_reason = normalization_error or result.get("message", "Document validation failed")

        try:
            from app.services.handle_reply import generate_reasoning_for_wrong_document, send_reasoning_email

            raw_text = result.get("raw_text", "")

            if not raw_text:
                logger.info(f"Extracting text for reasoning...")
                ext = Path(temp_file_path).suffix.lower()

                try:
                    if ext == '.pdf':
                        import fitz
                        doc = fitz.open(str(temp_file_path))
                        raw_text = ""
                        for i in range(min(5, doc.page_count)):
                            page = doc.load_page(i)
                            raw_text += page.get_text()
                        doc.close()
                    elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
                        from app.services.ocr_service import run_ocr
                        raw_text = run_ocr(str(temp_file_path), VISION_FALLBACK)
                except Exception as e:
                    logger.warning(f"Failed to extract text: {e}")
                    raw_text = "[TEXT EXTRACTION FAILED]"

            reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)
            send_reasoning_email(
                to_email=email,
                filename=uploaded_file.filename,
                doc_type=doc_type,
                reasoning=reasoning
            )
            logger.info(f"[SUCCESS] Validation error email sent\n")

        except Exception as e:
            logger.error(f"Reasoning generation/email failed: {e}")
            reasoning = failure_reason

        return save_and_respond_failure(
            failure_type="validation_failed",
            error_message=reasoning,
            status_category="rejected"
        )

    # ========================================================================
    # STEP 4: TAMPERING CHECK (Only for valid documents)
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 4] SECURITY VERIFICATION (TAMPERING CHECK)")
    logger.info(f"{'='*80}\n")

    tampering_result = None
    try:
        tampering_result = verify_document_authenticity(
            file_path=str(temp_file_path),
            user_email=email,
            doc_type=doc_type,
            send_notifications=True
        )

        logger.info(f"[INFO] Tampering Decision: {tampering_result.decision}")
        logger.info(f"[INFO] Tampering Score: {tampering_result.overall_tampering_score}/100")

        if tampering_result.decision == "REJECT":
            logger.error(f"\n[TAMPERING] DOCUMENT REJECTED\n")

            return save_and_respond_failure(
                failure_type="tampering_rejected",
                error_message=f"Security verification failed: {tampering_result.llm_analysis or tampering_result.reason}",
                status_category="rejected",
                additional_metadata={
                    "tampering": {
                        "decision": "REJECT",
                        "score": tampering_result.overall_tampering_score,
                        "test_report_id": tampering_result.test_report_id,
                        "llm_analysis": tampering_result.llm_analysis
                    }
                }
            )

        elif tampering_result.decision == "ESCALATE":
            logger.warning(f"\n[TAMPERING] MANUAL REVIEW REQUIRED\n")

        else:
            logger.info(f"[TAMPERING] DOCUMENT ACCEPTED\n")

    except Exception as e:
        logger.warning(f"[WARN] Tampering check failed: {e}\n")
        import traceback
        logger.error(traceback.format_exc())

    # ========================================================================
    # STEP 5: SAVE WITH ATOMIC VERSION TRACKING
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 5] SAVING WITH ATOMIC VERSION TRACKING")
    logger.info(f"{'='*80}\n")

    try:
        additional_data = {}

        if tampering_result:
            additional_data["tampering"] = {
                "decision": tampering_result.decision,
                "score": tampering_result.overall_tampering_score,
                "test_report_id": tampering_result.test_report_id,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "llm_analysis": tampering_result.llm_analysis
            }

        success, message, version_info = save_document_with_version(
            user_email=email,
            document_type=doc_type,
            document_id=document_id,
            filename=uploaded_file.filename,
            file_content=file_content,
            extracted_data=extracted_fields,
            is_valid=is_valid,
            validation_result=validation_result,
            member_name=clean_member_name,
            additional_data=additional_data
        )

        if not success:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)

            logger.error(f"[ERROR] Save failed: {message}")

            return DocumentUploadResponse(
                success=False,
                message=f"Upload failed: {message}",
                document_type=doc_type,
                extracted_data=None,
                is_valid=False,
                is_complete=False,
                awaiting_verification=False,
                document_file_path=None,
                wrong_document_type=False,
                cross_validation_passed=None,
                cross_validation_errors=None,
                version=None
            )

        logger.info(f"[SUCCESS] Document saved with version {version_info['next_version']}")

        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
            logger.info(f"[CLEANUP] Temp directory removed\n")

    except Exception as e:
        logger.error(f"[ERROR] Failed to save document: {e}")

        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)

        raise DomainError(context=f"Failed to save document: {str(e)}")

    # ========================================================================
    # STEP 6: CHECK EXPIRY VALIDATION
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[EXPIRY CHECK] Checking for expired document")
    logger.info(f"{'='*80}\n")

    if clean_member_name:
        doc_path = get_member_documents_path(email, clean_member_name) / document_id / "output.json"
    else:
        doc_path = get_user_documents_path(email) / document_id / "output.json"

    expiry_failed = False
    expiry_message = None
    expiry_val = None

    if doc_path.exists():
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)

            expiry_val = saved_data.get("expiry_validation")

            if expiry_val and expiry_val.get("document_status") == "EXPIRED":
                expiry_failed = True
                logger.error(f"[EXPIRY] Document expired: {expiry_val.get('expiry_reason')}")

                doc_type_mapping = {
                    "eid": "eid",
                    "ejari": "ejari",
                    "commercial": "commercial_license"
                }
                validator_doc_type = doc_type_mapping.get(doc_type, doc_type)

                try:
                    expiry_message = generate_expiry_failure_message(
                        doc_type=validator_doc_type,
                        expiry_date_found=expiry_val.get("expiry_date_found"),
                        current_date=expiry_val.get("current_date"),
                        reason=expiry_val.get("expiry_reason")
                    )
                    logger.info(f"[EXPIRY] AI message generated")
                except Exception as e:
                    logger.warning(f"[EXPIRY] Failed to generate message: {e}")
                    expiry_message = (
                        saved_data.get("status_message")
                        or saved_data.get("ai_reasoning")
                        or "Document has expired. Please upload a valid document."
                    )
            else:
                logger.info(f"[EXPIRY] Document is valid (not expired)")

        except Exception as e:
            logger.warning(f"Could not check expiry: {e}")

    if expiry_failed:
        logger.error(f"\n[EXPIRY] Returning expiry error response\n")

        remaining_docs = get_remaining_required_documents(email, user)

        if clean_member_name:
            file_path_str = str(get_documents_base_path() / _ref_no_for_path / "members" / document_id / uploaded_file.filename)
        else:
            file_path_str = str(get_documents_base_path() / _ref_no_for_path / document_id / uploaded_file.filename)

        return DocumentUploadResponse(
            success=False,
            message=expiry_message or "Document has expired. Please upload a valid document.",
            document_type=doc_type,
            extracted_data=None,
            is_valid=False,
            is_complete=False,
            awaiting_verification=False,
            document_file_path=file_path_str,
            next_document=None,
            remaining_documents=remaining_docs,
            wrong_document_type=False,
            cross_validation_passed=None,
            cross_validation_errors=None,
            decision="EXPIRED",
            tampering_detected=False,
            manual_review_required=False,
            filename=uploaded_file.filename,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            version=version_info.get("next_version", 1),
            status_category="rejected",
            ai_reasoning=expiry_message,
            expiry_failed=True,
            expiry_validation=expiry_val
        )

    # ============================================================================
    # STEP 6.5 - MEMBER HANDLING (For Corporate Multiple Owners)
    # ============================================================================
    logger.info(f"\n{'='*80}")
    logger.info(f"[MEMBER_CHECK] Checking if member extraction/update needed")
    logger.info(f"{'='*80}\n")

    ownership_type = user.get("ownership_type", "")
    document_stage = user.get("document_stage", STAGE_IDENTIFICATION)

    logger.info(f"Account Type: {account_type}")
    logger.info(f"Ownership Type: {ownership_type}")
    logger.info(f"Document Stage: {document_stage}")
    logger.info(f"Uploaded Doc Type: {doc_type}")
    logger.info(f"Member Name: {clean_member_name}")

    # ✅ CASE 1: MOA Upload - Extract Members (Stage 1 → Stage 2 transition)
    if (account_type == ACCOUNT_CORPORATE and
        ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
        doc_type == "moa" and
        is_valid):

        logger.info(f"\n[INFO] MOA uploaded for Multiple Owners — checking if member extraction needed")

        # ✅ FIX: Use shared helper for consistent path (works in Docker + local)
        progress_file = get_member_progress_path(email)
        logger.info(f"Checking member progress at: {progress_file}")

        if not progress_file.exists():
            logger.info(f"No member progress found — extracting members from documents...")

            try:
                member_data = extract_members_from_commercial(email)

                if member_data and member_data.get("all_names"):
                    # ✅ FIX: Use all_names — flat list of strings (UBOs + members + agents)
                    member_names = member_data["all_names"]
                    includes_user = member_data.get("includes_user", False)

                    logger.info(f"[SUCCESS] Extracted {len(member_names)} members: {member_names}")
                    logger.info(f"Registered user in documents: {includes_user}")

                    # ✅ Create member directories
                    for member in member_names:
                        member_dir = user_docs_path(email) / member
                        member_dir.mkdir(parents=True, exist_ok=True)
                        logger.info(f"Created member folder: {member_dir}")

                    # ── TYPE-2 CHECK: detect corporate shareholders before transitioning ──
                    _dp_comm_path, comm_data = _find_commercial_output(email)
                    corporate_detected = False
                    pending_coi_list = []

                    if _dp_comm_path is not None:
                        try:
                            partners_list = (
                                comm_data.get("extracted_fields", {}).get("partners", [])
                                or comm_data.get("partners", [])
                            )
                            if partners_list:
                                corp_detection = _detect_corps(partners_list)
                                if corp_detection["has_corporate_shareholders"]:
                                    corporate_detected = True
                                    pending_coi_list = [
                                        c["name"] for c in corp_detection["corporate_shareholders"]
                                    ]
                                    logger.info(f"[TYPE-2] Corporate shareholders found: {pending_coi_list}")
                        except Exception as _e:
                            logger.warning(f"Type-2 detection skipped (non-fatal): {_e}")

                    if corporate_detected and pending_coi_list:
                        # ── TYPE-2 PATH ──
                        logger.info("[TYPE-2] documentpage: Transitioning → corporate_shareholder_docs")
                        save_member_progress(email, members=[], current_index=0, pending_coi=pending_coi_list)
                        from app.services.supabase_client import supabase
                        UserRepository.update_by_email(email, {
                            "document_stage": STAGE_CORPORATE_SHAREHOLDER_DOCS,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        })
                        logger.info("[TYPE-2] DB updated: identification → corporate_shareholder_docs")
                        try:
                            send_corporate_shareholder_request_email(
                                to_email=email,
                                corp_name=pending_coi_list[0],
                                corp_index=1,
                                total_corps=len(pending_coi_list),
                            )
                        except Exception as _ee:
                            logger.warning(f"CoI request email failed (non-fatal): {_ee}")
                    else:
                        # ── STANDARD PATH ──
                        save_member_progress(email, member_names, 0)
                        logger.info(f"[SUCCESS] Member progress saved via shared function: {progress_file}")

                        # Update database stage
                        from app.services.supabase_client import supabase
                        UserRepository.update_by_email(email, {
                            "document_stage": STAGE_MEMBER_EIDS,
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        })

                        logger.info("[SUCCESS] User stage updated to 'member_eids'")
                        logger.info(f"System will now require EID for: {member_names}")

                else:
                    logger.warning(f"No members extracted from documents")

            except Exception as e:
                logger.error(f"Member extraction failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.info(f"Member progress already exists — skipping extraction")

    # ✅ CASE 2: Member EID Upload - Update Progress (Auto-advance)
    elif (account_type == ACCOUNT_CORPORATE and
          ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
          document_stage == STAGE_MEMBER_EIDS and
          doc_type == "eid" and
          clean_member_name and
          is_valid):

        logger.info(f"\n[INFO] Member EID uploaded — updating progress...")
        logger.info(f"Member: {clean_member_name}")

        status_category = "approved"
        if tampering_result and tampering_result.decision == "ESCALATE":
            status_category = "tampered"
        elif not is_valid:
            status_category = "rejected"

        logger.info(f"Status Category: {status_category}")

        try:
            progress_updated = update_member_progress_after_upload(
                email=email,
                member_name=clean_member_name,
                status_category=status_category
            )

            if progress_updated:
                logger.info(f"[SUCCESS] Member progress updated successfully")
            else:
                logger.info(f"Member progress not updated (see logs above)")

        except Exception as progress_error:
            logger.error(f"Failed to update member progress: {progress_error}")
            import traceback
            logger.error(traceback.format_exc())

    logger.info(f"\n{'='*80}\n")

    # ========================================================================
    # STEP 7: SUCCESS RESPONSE
    # ========================================================================
    logger.info(f"{'='*80}")
    logger.info(f"[STEP 7] DOCUMENT ACCEPTED AND SAVED")
    logger.info(f"{'='*80}\n")

    logger.info(f"Valid document processed - waiting for user confirmation")

    # Safely retrieve pending_coi_list if it was set during Type-2 detection above
    try:
        _pending_coi_for_msg = pending_coi_list if pending_coi_list else None
    except NameError:
        _pending_coi_for_msg = None

    dynamic_acknowledgment = generate_dynamic_valid_document_response(
        doc_type=doc_type,
        email=email,
        user_data=user,
        member_name=clean_member_name,
        pending_coi_names=_pending_coi_for_msg
    )

    # Refresh status after potential member extraction
    status = get_onboarding_status(email, user)
    is_complete = status.get("is_complete", False)
    remaining_docs = get_remaining_required_documents(email, user)

    # Format preview data (only non-empty fields)
    preview_data_formatted = None
    if extracted_fields and isinstance(extracted_fields, dict):
        preview_data_formatted = {
            key: value for key, value in extracted_fields.items()
            if value and value != "Not found" and value != "N/A"
        }

    # Construct file path (ref_no-based structure)
    if clean_member_name:
        file_path_str = f"backend/documents/id/{_ref_no_for_path}/members/{document_id}/{uploaded_file.filename}"
    else:
        file_path_str = f"backend/documents/id/{_ref_no_for_path}/{document_id}/{uploaded_file.filename}"

    logger.info(f"[INFO] Final Status:")
    logger.info(f"   - Document Type: {doc_type}")
    logger.info(f"   - Document ID (folder): {document_id}")
    logger.info(f"   - Version: {version_info['next_version']}")
    logger.info(f"   - Is Valid: {is_valid}")
    logger.info(f"   - Is Complete: {is_complete}")
    logger.info(f"   - File Path: {file_path_str}\n")

    # Determine status category
    status_category = "approved"
    if tampering_result and tampering_result.decision == "ESCALATE":
        status_category = "tampered"
    elif not is_valid:
        status_category = "rejected"

    # ============================================================================
    # ✅ Get updated member progress if this was a member EID or MOA upload
    # ============================================================================
    updated_member_progress = None

    # Case 1: Member EID upload
    if (account_type == ACCOUNT_CORPORATE and
        ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
        clean_member_name and
        doc_type == "eid"):

        logger.info(f"Fetching updated member progress after EID upload...")

        try:
            updated_member_progress = get_member_progress_with_status(email)

            if updated_member_progress:
                logger.info(f"[SUCCESS] Updated member progress retrieved:")
                logger.info(f"  - Current Index: {updated_member_progress.get('current_index')}")
                logger.info(f"  - All Complete: {updated_member_progress.get('all_members_completed')}")
                logger.info(f"  - Members: {updated_member_progress.get('members')}")
            else:
                logger.warning(f"Could not retrieve member progress")

        except Exception as mp_error:
            logger.error(f"Failed to get member progress: {mp_error}")
            import traceback
            logger.error(traceback.format_exc())

    # Case 2: MOA/Commercial upload that triggered member extraction
    elif (account_type == ACCOUNT_CORPORATE and
          ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
          doc_type in ["moa", "commercial"] and
          is_valid):

        logger.info(f"Fetching member progress after {doc_type.upper()} upload...")

        try:
            # ✅ FIX: Use shared helper for correct path
            progress_file = get_member_progress_path(email)

            if progress_file.exists():
                logger.info(f"Member progress file found at: {progress_file}")
                updated_member_progress = get_member_progress_with_status(email)

                if updated_member_progress:
                    logger.info(f"[SUCCESS] Member progress retrieved after {doc_type.upper()} upload:")
                    logger.info(f"  - Total Members: {len(updated_member_progress.get('members', []))}")
                    logger.info(f"  - Current Index: {updated_member_progress.get('current_index')}")
                    logger.info(f"  - Members: {updated_member_progress.get('members')}")
                else:
                    logger.warning(f"Member progress file exists but couldn't load status")
            else:
                logger.info(f"No member progress file found at: {progress_file}")
                logger.info(f"Member extraction may not have been triggered yet")

        except Exception as mp_error:
            logger.error(f"Failed to get member progress: {mp_error}")
            import traceback
            logger.error(traceback.format_exc())

        logger.info(f"\n{'='*80}\n")

    # ── v4: Commercial License Mismatch Detection (Document Upload page) ─────
    _dp_mismatch_detected        = False
    _dp_mismatch_extracted_name  = None
    _dp_mismatch_extracted_biz   = None
    if (
        doc_type.lower() in ("commercial", "trade_license", "commercial_license")
        and is_valid
        and not clean_member_name
        and account_type == ACCOUNT_CORPORATE
    ):
        try:
            _dp_reg_name = (user.get("full_name") or user.get("name") or "").strip().lower()
            _dp_reg_biz  = (user.get("business_name") or user.get("company_name") or "").strip().lower()
            _dp_ext_data = extracted_fields or {}
            _dp_ext_owner = _dp_ext_data.get("owner") or {}
            _dp_ext_name  = (
                _dp_ext_owner.get("name_english") or
                _dp_ext_data.get("owner_name") or
                _dp_ext_data.get("manager_name") or ""
            ).strip()
            _dp_ext_biz   = (
                _dp_ext_data.get("business_name_english") or
                _dp_ext_data.get("trade_name_english") or
                _dp_ext_data.get("company_name") or ""
            ).strip()

            def _dp_names_match(a: str, b: str) -> bool:
                if not a or not b:
                    return True
                return bool(set(a.lower().split()) & set(b.lower().split()))

            if _dp_ext_name and not _dp_names_match(_dp_reg_name, _dp_ext_name):
                _dp_mismatch_detected       = True
                _dp_mismatch_extracted_name = _dp_ext_name
                _dp_mismatch_extracted_biz  = _dp_ext_biz or None
            elif _dp_ext_biz and not _dp_names_match(_dp_reg_biz, _dp_ext_biz):
                _dp_mismatch_detected       = True
                _dp_mismatch_extracted_name = _dp_ext_name or None
                _dp_mismatch_extracted_biz  = _dp_ext_biz
        except Exception as _dp_me:
            logger.warning(f"[MISMATCH-DP] Check failed (non-fatal): {_dp_me}")
    # ── v4: FATCA/PEP stale-file cleanup on new commercial license ────────────
    if (
        doc_type.lower() in ("commercial", "trade_license", "commercial_license")
        and is_valid
        and not clean_member_name
    ):
        for _sp, _sl in [(fatca_json_path(email), "fatca.json"), (pep_json_path(email), "pep.json")]:
            if _sp.exists():
                try:
                    _sp.unlink(missing_ok=True)
                    logger.info(f"[v4-DP] Stale {_sl} cleared: {email}")
                except Exception:
                    pass

    return DocumentUploadResponse(
        success=True,
        message=f"{dynamic_acknowledgment}\n\nDocument saved successfully (Version {version_info['next_version']}). You can review it before confirmation.",
        document_type=doc_type,
        extracted_data=preview_data_formatted,
        is_valid=is_valid,
        is_complete=is_complete,
        awaiting_verification=is_valid,
        document_file_path=file_path_str,
        next_document=status.get("next_required_document"),
        remaining_documents=remaining_docs,
        wrong_document_type=False,
        cross_validation_passed=None,
        cross_validation_errors=None,
        decision="ACCEPT" if not tampering_result or tampering_result.decision == "ACCEPT" else tampering_result.decision,
        tampering_detected=False,
        manual_review_required=tampering_result and tampering_result.decision == "ESCALATE",
        filename=uploaded_file.filename,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        version=version_info.get("next_version", 1),
        status_category=status_category,
        ai_reasoning=tampering_result.llm_analysis if tampering_result and tampering_result.decision == "ESCALATE" else None,
        updated_member_progress=updated_member_progress,
        # ── v4 ────────────────────────────────────────────────────────────────
        fatca_trigger=False,
        pep_trigger=False,
        mismatch_detected=_dp_mismatch_detected,
        mismatch_extracted_name=_dp_mismatch_extracted_name,
        mismatch_extracted_business=_dp_mismatch_extracted_biz,
    )

    
    




@router.get("/get-document-preview/{email}/{doc_type}")
async def get_document_preview(email: str, doc_type: str, member_name: Optional[str] = None):
    """
    Fetch preview data for a document
    ✅ Handles both chat uploads (with files) and email uploads (data only)
    """
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        logger.info(f"Fetching preview for {doc_type}...")
        
        preview_data = get_document_preview_data(email, doc_type, member_name)
        
        if not preview_data.get("success"):
            logger.warning(f"Preview not available: {preview_data.get('error')}")
            return {
                "success": False,
                "error": preview_data.get("error", "Document not found"),
                "can_display": False
            }
        
        has_file = preview_data.get("file_path") is not None
        
        # ✅ CRITICAL: Apply transformation pipeline
        raw_extracted_data = preview_data.get("extracted_data", {})
        document_type = preview_data.get("document_type", doc_type)
        
        logger.info(f"\n[DEBUG] TRANSFORMATION PIPELINE:")
        logger.debug(f"Step 1: Raw data keys: {list(raw_extracted_data.keys())[:5]}")
        
        # Step 1: Normalize (flatten nested structures)
        normalized_data = normalize_extracted_data(raw_extracted_data, document_type)
        logger.debug(f"Step 2: Normalized data keys: {list(normalized_data.keys())[:5]}")
        logger.debug(f"Step 2: Normalized count: {len(normalized_data)}")
        
        # Step 2: Map to display names
        display_extracted_data = map_fields_to_display_names(normalized_data, document_type)
        logger.debug(f"Step 3: Display data keys: {list(display_extracted_data.keys())[:5]}")
        logger.debug(f"Step 3: Display count: {len(display_extracted_data)}")
        
        if display_extracted_data:
            # Show sample for verification
            sample = dict(list(display_extracted_data.items())[:3])
            logger.debug(f"Sample display data: {sample}")
        else:
            logger.error(f"Display data is EMPTY after transformation!")
        
        if not has_file:
            logger.info(f"Email upload - no file available")
            
            return {
                "success": True,
                "filename": preview_data.get("filename", "Document"),
                "mime_type": None,
                "file_ext": None,
                "pdf_metadata": None,
                "preview_html": None,
                "file_path": None,
                "can_display": False,
                "extracted_data": display_extracted_data,  # ✅ Transformed data
                "is_email_upload": True
            }
        
        preview_html = get_document_preview_html(preview_data)
        
        response = {
            "success": True,
            "filename": preview_data.get("filename"),
            "mime_type": preview_data.get("mime_type"),
            "file_ext": preview_data.get("file_ext"),
            "pdf_metadata": preview_data.get("pdf_metadata"),
            "preview_html": preview_html,
            "file_path": preview_data.get("file_path"),
            "can_display": True,
            "extracted_data": display_extracted_data,  # ✅ Transformed data
            "is_email_upload": False
        }
        
        logger.info(f"[SUCCESS] Returning {len(display_extracted_data)} display fields\n")
        return response
        
    except Exception as e:
        logger.error(f"get_document_preview: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))

@router.get("/download-document/{email}/{doc_type}")
async def download_document(email: str, doc_type: str, member_name: Optional[str] = None):
    """
    Download document file
    ✅ Handles file bytes for download
    """
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        logger.info(f"Preparing download for {doc_type}...")
        
        preview_data = get_document_preview_data(email, doc_type, member_name)
        
        if not preview_data.get("success"):
            raise NotFoundError("Document not found")
        
        file_bytes = preview_data.get("file_bytes")
        filename = preview_data.get("filename")
        mime_type = preview_data.get("mime_type")
        
        from fastapi.responses import StreamingResponse
        from io import BytesIO
        
        return StreamingResponse(
            BytesIO(file_bytes),
            media_type=mime_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"download_document: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


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

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "documentupload",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


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

@router.get("/get-extracted-data/{user_email}/{doc_type}")
def get_extracted_data(user_email: str, doc_type: str):
    """Get extracted data for a specific document"""
    try:
        user = get_user_by_email(user_email)
        if not user:
            raise NotFoundError("User not found")

        # Map document types to validation fields
        field_map = {
            "emirates_id": "user_doc_validation",
            "ejari": "user_doc_validation",
            "trade_license": "user_doc_validation",
            "moa": "user_doc_validation"
        }
        
        field = field_map.get(doc_type)
        if not field or not user.get(field):
            return {}
        
        data = user[field]
        if isinstance(data, str):
            import json
            data = json.loads(data)
        
        return data.get(doc_type, {})

    # Without this, the broad handler below catches the NotFoundError raised
    # for a missing user and reports it as a 500. Every `except Exception`
    # that sits outside a raise needs this guard.
    except DomainError:
        raise
    except Exception as e:
        logger.error(f"Get extracted data error: {e}")
        raise DomainError(context=str(e))

from fastapi.responses import FileResponse
import mimetypes
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
)



@router.get("/get-document/{email}/{doc_type}")
async def get_document_file(
    email: str,
    doc_type: str,
    member_name: Optional[str] = None,
    version: Optional[int] = None  # ✅ NEW: Support version parameter
):
    """
    ✅ UPDATED: Get document file for preview with version support
    - Scans all directories under user folder
    - Matches doc_type from output.json files
    - Returns file from correct {document_id} folder
    - Works with nested structure: {email}/{document_id}/file.pdf
    - ✅ NEW: Supports ?version=N to view historical versions
    - ✅ NEW: Only returns current documents by default (is_current=true)
    """
    try:
        logger.info(f"\n[DEBUG] get_document_file called")
        logger.debug(f"Email: {email}")
        logger.debug(f"Doc Type: {doc_type}")
        logger.debug(f"Member Name: {member_name}")
        logger.debug(f"Version: {version if version else 'current'}")
        
        # ✅ Use helper function to get user documents path
        if member_name:
            base_path = get_member_documents_path(email, member_name)
        else:
            base_path = get_user_documents_path(email)
        
        if not base_path or not base_path.exists():
            logger.error(f"Document directory not found for {email}")
            raise NotFoundError("Document directory not found")
        
        logger.debug(f"Base path: {base_path}")
        
        # ============================================================================
        # ✅ NEW: If version specified, get that specific version
        # ============================================================================
        if version:
            logger.info(f"Looking for specific version: {version}")
            
            # Use helper function to get document history
            history = get_document_history(email, doc_type, member_name)
            
            target_doc_id = None
            for v in history:
                if v["version"] == version:
                    target_doc_id = v["document_id"]
                    logger.info(f"Found version {version} with ID: {target_doc_id}")
                    break
            
            if not target_doc_id:
                logger.error(f"Version {version} not found")
                raise NotFoundError(f"Version {version} not found for {doc_type}")
            
            # Get the document folder
            target_folder = base_path / target_doc_id
            
            if not target_folder.exists():
                logger.error(f"Document folder not found: {target_folder}")
                raise NotFoundError(f"Document folder not found")
            
            # Find the actual file in this folder
            document_files = [
                f for f in target_folder.iterdir() 
                if f.is_file() 
                and f.name != "output.json"
                and f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']
            ]
            
            if not document_files:
                logger.error(f"No document file found in {target_folder}")
                raise NotFoundError("Document file not found")
            
            document_file = document_files[0]
            
            logger.debug(f"Found version {version} document: {document_file.name}")
            
            # Determine MIME type
            mime_type, _ = mimetypes.guess_type(str(document_file))
            if not mime_type:
                if document_file.suffix.lower() == '.pdf':
                    mime_type = 'application/pdf'
                elif document_file.suffix.lower() in ['.jpg', '.jpeg']:
                    mime_type = 'image/jpeg'
                elif document_file.suffix.lower() == '.png':
                    mime_type = 'image/png'
                elif document_file.suffix.lower() == '.webp':
                    mime_type = 'image/webp'
                else:
                    mime_type = 'application/octet-stream'
            
            logger.debug(f"MIME type: {mime_type}")
            logger.info(f"[SUCCESS] Serving version {version} for preview: {document_file.name}")
            
            # Return file for inline display
            return FileResponse(
                path=str(document_file),
                media_type=mime_type,
                filename=document_file.name,
                headers={
                    "Content-Disposition": f'inline; filename="{document_file.name}"',
                    "Cache-Control": "public, max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                    "X-Document-Version": str(version)  # ✅ Include version in header
                }
            )
        
        # ============================================================================
        # ✅ DEFAULT: Find CURRENT version only (is_current=true)
        # ============================================================================
        logger.info(f"Looking for current version (is_current=true)")
        
        # Scan all directories
        for item in base_path.iterdir():
            if not item.is_dir():
                continue
            
            # Skip members folder
            if item.name == "members":
                continue
            
            # Check for output.json
            output_json = item / "output.json"
            
            if not output_json.exists():
                logger.debug(f"⏭Skipping {item.name} - no output.json")
                continue
            
            try:
                logger.debug(f"Checking: {output_json}")
                
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_doc_type = data.get("document_type", "").lower().strip()
                search_doc_type = doc_type.lower().strip()
                
                # ✅ CRITICAL: Check if document is current
                is_current = data.get("is_current", True)  # Default True for backward compatibility
                version_num = data.get("version", 1)
                
                logger.debug(f"Document: type='{stored_doc_type}', version={version_num}, is_current={is_current}")
                
                # ✅ FILTER: Skip superseded documents
                if not is_current:
                    logger.debug(f"⏭Skipping - superseded version (is_current=false)")
                    continue
                
                # Check match with aliases
                match = False
                if stored_doc_type == search_doc_type:
                    match = True
                    logger.debug(f"Exact match!")
                elif stored_doc_type in ["tenancy", "ejari"] and search_doc_type in ["tenancy", "ejari"]:
                    match = True
                    logger.debug(f"Alias match (tenancy/ejari)!")
                elif stored_doc_type in ["moa", "memorandum"] and search_doc_type in ["moa", "memorandum"]:
                    match = True
                    logger.debug(f"Alias match (moa/memorandum)!")
                elif stored_doc_type in ["commercial", "commercial_license", "trade_license"] and search_doc_type in ["commercial", "commercial_license", "trade_license"]:
                    match = True
                    logger.debug(f"Alias match (commercial)!")
                
                if not match:
                    logger.debug(f"⏭Skipping - type mismatch")
                    continue
                
                logger.debug(f"MATCH FOUND for {doc_type} (current version {version_num})!")
                
                # Find the actual document file in this folder
                document_files = [
                    f for f in item.iterdir() 
                    if f.is_file() 
                    and f.name != "output.json"
                    and f.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']
                ]
                
                if not document_files:
                    logger.error(f"No document file found in {item}")
                    continue
                
                document_file = document_files[0]
                
                logger.debug(f"Found document: {document_file.name}")
                logger.debug(f"Full path: {document_file}")
                
                # Determine MIME type
                mime_type, _ = mimetypes.guess_type(str(document_file))
                if not mime_type:
                    if document_file.suffix.lower() == '.pdf':
                        mime_type = 'application/pdf'
                    elif document_file.suffix.lower() in ['.jpg', '.jpeg']:
                        mime_type = 'image/jpeg'
                    elif document_file.suffix.lower() == '.png':
                        mime_type = 'image/png'
                    elif document_file.suffix.lower() == '.webp':
                        mime_type = 'image/webp'
                    else:
                        mime_type = 'application/octet-stream'
                
                logger.debug(f"MIME type: {mime_type}")
                logger.info(f"[SUCCESS] Serving current version (v{version_num}) for preview: {document_file.name}")
                
                # ✅ Return for inline display (not download)
                return FileResponse(
                    path=str(document_file),
                    media_type=mime_type,
                    filename=document_file.name,
                    headers={
                        "Content-Disposition": f'inline; filename="{document_file.name}"',
                        "Cache-Control": "public, max-age=3600",
                        "Access-Control-Allow-Origin": "*",
                        "X-Document-Version": str(version_num),  # ✅ Include version in header
                        "X-Is-Current": "true"  # ✅ Indicate this is current version
                    }
                )
                
            except Exception as e:
                logger.error(f"Error processing {output_json}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue
        
        # No matching document found
        logger.error(f"No matching CURRENT document found for type: {doc_type}")
        logger.info(f"Tip: There might be superseded versions. Use ?version=N to view them.")
        raise NotFoundError(f"No current document found for type: {doc_type}")
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Failed to serve document: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=f"Failed to serve document: {str(e)}")


@router.get("/document-history/{email}/{document_type}")
async def get_document_history_endpoint(
    email: str,
    document_type: str,
    member_name: Optional[str] = None
):
    """
    ✅ NEW ENDPOINT: Get complete version history for a document type
    """
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    try:
        # Use helper function
        history = get_document_history(email, document_type, member_name)
        
        return {
            "success": True,
            "email": email,
            "document_type": document_type,
            "member_name": member_name,
            "versions": history,
            "total_versions": len(history)
        }
        
    except Exception as e:
        logger.error(f"get_document_history: {e}")
        raise DomainError(context=str(e))

# NOTE: get_document_requirements endpoint is defined at the top of this file (line ~649).
# The duplicate definition that was here has been removed to avoid dead code.

# ============================================================================
# ✅ NEW ENDPOINT: Pre-confirmation validation
# ============================================================================

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
__all__ = ["router"]