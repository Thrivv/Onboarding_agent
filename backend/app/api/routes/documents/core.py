"""
backend/app/api/routes/documents/core.py

Split out of the former app/api/routes/documents.py (2,635 lines) as part of
the god-file decomposition pass. Document requirements, the (930-line, deliberately unsplit — see module docstring) upload pipeline, and health.

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
from app import config
from app.utils.pii_masker import mask_name
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

                    logger.info(f"[SUCCESS] Extracted {len(member_names)} members: {[mask_name(_n) for _n in member_names] if config.PII_LOG_MASKING_ENABLED else member_names}")
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
                logger.info(f"  - Members: {[mask_name(_n) for _n in (updated_member_progress.get('members') or [])] if config.PII_LOG_MASKING_ENABLED else updated_member_progress.get('members')}")
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
                    logger.info(f"  - Members: {[mask_name(_n) for _n in (updated_member_progress.get('members') or [])] if config.PII_LOG_MASKING_ENABLED else updated_member_progress.get('members')}")
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

    
    
@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "documentupload",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
