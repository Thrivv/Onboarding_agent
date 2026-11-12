"""
Document rules for onboarding: which types an account may upload, what has been
submitted, and removal of documents that failed validation.

Note that `get_submitted_documents` here is chatupload's version — the one that
does NOT take an `include_all` flag. `app/domain/documents/discovery.py` holds
the other implementation, from documentpage. The two have different signatures
and different callers; they were never interchangeable and are not merged.

Moved verbatim from `app/api/routes/chatupload.py` in Stage B4.
"""

from __future__ import annotations

import logging
import json
from typing import List, Optional
import shutil
import traceback
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
from app.utils.behaviour_capture import capture
from app.domain.onboarding.stage_table import STAGE_IDENTIFICATION

logger = logging.getLogger(__name__)

def _find_commercial_output(email: str):
    """Scan all subfolders for the commercial license output.json.
    Returns (path, data) for the MOST RECENTLY created commercial document
    (determined by the 'created_at' field inside output.json).
    This prevents stale documents from previous test runs being picked up."""
    base = user_docs_path(email)
    if not base.exists():
        return None, {}
    best_path, best_data, best_ts = None, {}, ""
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        out = folder / "output.json"
        if out.exists():
            try:
                with open(out, "r", encoding="utf-8") as _f:
                    data = json.load(_f)
                doc_type = data.get("document_type", "").lower()
                if doc_type in ("commercial", "trade_license", "commercial_license"):
                    ts = data.get("created_at", "")
                    if ts > best_ts:
                        best_ts, best_path, best_data = ts, out, data
            except Exception:
                pass
    if best_path is not None:
        logger.info(f"[COMMERCIAL] Most recent commercial found: {best_path} (created_at={best_ts})")
    return best_path, best_data


def validate_document_type_for_account(
    email: str,
    doc_type: str,
    user_data: dict,
    member_name: Optional[str] = None
) -> tuple:
    """Validate if uploaded document type is allowed for user's account configuration"""
    
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", STAGE_IDENTIFICATION)
    
    logger.info(f"\n[VALIDATION] Document Type Check: {doc_type} for {account_type}/{ownership_type}/{document_stage}")
    
    allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
    allowed_types = allowed_info["allowed_types"]
    
    doc_type_normalized = doc_type.lower().strip()
    is_allowed = doc_type_normalized in allowed_types
    
    if is_allowed:
        logger.info(f"[SUCCESS] Document type '{doc_type}' is ALLOWED")
        return True, "", allowed_info
    else:
        logger.error(f"Document type '{doc_type}' is NOT ALLOWED")
        
        member_context = f" for member {member_name}" if member_name else ""
        required_docs_formatted = "\n• ".join(allowed_info["required_docs"])
        
        error_message = f"""❌ **Wrong Document Type{member_context}**

I received a **{doc_type.upper()}** document, but this is not the correct document for your account type.

**Your Account:** {allowed_info['stage_description']}

**Required Documents:**
- {required_docs_formatted}

**What to do next:**
Please upload one of the required documents listed above. The {doc_type.upper()} document is not needed for your account type.

If you believe this is an error, please contact support."""
        
        return False, error_message, allowed_info


def delete_invalid_document(
    email: str,
    document_id: str,
    doc_type: str,
    member_name: Optional[str] = None
) -> bool:
    """Delete wrongly uploaded document and its folder"""
    
    try:
        if member_name:
            doc_folder = user_docs_path(email) / member_name / document_id
        else:
            doc_folder = user_docs_path(email) / document_id
        
        if not doc_folder.exists():
            logger.warning(f"Document folder does not exist: {doc_folder}")
            return False
        
        logger.info(f"Deleting invalid {doc_type.upper()} document: {doc_folder}")
        shutil.rmtree(doc_folder)
        logger.info(f"[SUCCESS] Successfully deleted invalid document folder")
        return True
        
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def extract_members_from_commercial(email: str) -> dict:
    """
    Extract members from Commercial License ONLY — MOA fields are excluded.
    Used by Type-1 Multiple Owner path (Commercial + MOA uploaded, but member
    names must come from Commercial partners/managers only, not MOA owner_name /
    manager_name fields).
    """
    from app.services.handle_reply import extract_members_from_documents

    return extract_members_from_documents(email, commercial_only=True)


@capture("get_submitted_documents")
def get_submitted_documents(email: str) -> List[dict]:
    """
    Get all submitted documents for a user
    ✅ FIXED: Properly reads extracted data from BOTH chat uploads AND email uploads
    ✅ FIXED: Correctly identifies and labels MOA documents
    """
    documents = []
    
    try:
        base_path = user_docs_path(email)
        
        if not base_path or not base_path.exists():
            logger.debug(f"[chatupload.get_submitted_documents] base path does not exist: {base_path}")
            return documents

        # ============================================================================
        # MAIN USER DOCUMENTS
        # ============================================================================
        for item in base_path.iterdir():
            if not item.is_dir():
                continue
            
            # ✅ Skip members folder (we'll process it separately)
            if item.name == "members":
                continue
            
            output_file = item / "output.json"
            
            if not output_file.exists():
                continue
            
            try:
                # Read the file
                with open(output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                doc_type = data.get("document_type", "unknown").lower().strip()
                is_valid = data.get("is_valid", False)
                
                # ✅ FIX: Normalize document type variations
                if doc_type in ["memorandum", "memorandum of association", "moa"]:
                    doc_type = "moa"
                elif doc_type in ["tenancy", "tenancy contract"]:
                    doc_type = "ejari"
                elif doc_type in ["trade license", "trade_license"]:
                    doc_type = "commercial"
                elif doc_type in ["emirates id", "emirates_id", "identity card"]:
                    doc_type = "eid"

                # ✅ CRITICAL: Check ALL possible locations for extracted data
                extracted = None
                
                # Location 1: Top-level extracted_fields (OCR service format)
                if "extracted_fields" in data:
                    extracted = data["extracted_fields"]
                
                # Location 2: Top-level extracted_data (alternative format)
                if not extracted and "extracted_data" in data:
                    extracted = data["extracted_data"]
                
                # Location 3: Nested in result object (email upload format)
                if not extracted and "result" in data:
                    result = data.get("result")
                    if isinstance(result, dict):
                        if "extracted_fields" in result:
                            extracted = result["extracted_fields"]
                        elif "extracted_data" in result:
                            extracted = result["extracted_data"]
                
                # Fallback to empty dict if nothing found
                if not extracted or not isinstance(extracted, dict):
                    extracted = {}
                
                validation = data.get("validation", {})
                
                doc_info = {
                    "document_type": doc_type,  # ✅ Normalized type (moa, commercial, eid, ejari)
                    "filename": data.get("filename", item.name),
                    "submitted": True,
                    "is_valid": is_valid,
                    "extracted_data": extracted,
                    "validation": validation,
                    "member_name": None  # Main user document
                }
                
                documents.append(doc_info)

            except Exception as e:
                logger.warning(f"[chatupload.get_submitted_documents] failed to read {output_file}: {e}")

        # ============================================================================
        # ✅ MEMBER DOCUMENTS
        # ============================================================================
        mp = load_member_progress(email)
        if mp:
            member_names = mp.get("members", [])

            for member_name in member_names:
                member_dir = base_path / member_name
                
                if not member_dir.exists():
                    continue
                
                # Scan for document folders
                for doc_folder in member_dir.iterdir():
                    if not doc_folder.is_dir():
                        continue
                    
                    output_file = doc_folder / "output.json"
                    
                    if not output_file.exists():
                        continue
                    
                    try:
                        with open(output_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        doc_type = data.get("document_type", "unknown").lower().strip()
                        is_valid = data.get("is_valid", False)
                        
                        # ✅ Normalize document type for member docs too
                        if doc_type in ["emirates id", "emirates_id", "identity card"]:
                            doc_type = "eid"
                        
                        # Same extraction logic for member documents
                        extracted = None
                        
                        if "extracted_fields" in data:
                            extracted = data["extracted_fields"]
                        if not extracted and "extracted_data" in data:
                            extracted = data["extracted_data"]
                        if not extracted and "result" in data:
                            result = data.get("result")
                            if isinstance(result, dict):
                                extracted = result.get("extracted_fields") or result.get("extracted_data")
                        
                        if not extracted or not isinstance(extracted, dict):
                            extracted = {}
                        
                        doc_info = {
                            "document_type": doc_type,  # ✅ Normalized type
                            "filename": data.get("filename", doc_folder.name),
                            "submitted": True,
                            "is_valid": is_valid,
                            "extracted_data": extracted,
                            "validation": data.get("validation", {}),
                            "member_name": member_name
                        }
                        
                        documents.append(doc_info)

                    except Exception as e:
                        logger.warning(f"[chatupload.get_submitted_documents] failed to read member document for {member_name}: {e}")

    except Exception as e:
        logger.error(f"[chatupload.get_submitted_documents] failed for {email}: {e}", exc_info=True)

    logger.debug(f"[chatupload.get_submitted_documents] {email} total={len(documents)}")

    return documents
