"""
backend/app/api/routes/documents/preview.py

Split out of the former app/api/routes/documents.py (2,635 lines) as part of
the god-file decomposition pass. Read-only document retrieval: preview, download, raw file, extracted-data readback, and version history.

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
from fastapi.responses import FileResponse
from pydantic import EmailStr
import mimetypes

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

# (FileResponse, mimetypes and the stage_table constants used below are
# imported once, at the top of this file — this used to be a second,
# mid-file copy of the same imports, left over from the original
# documents.py where it sat between two handlers. See the module docstring.)
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
