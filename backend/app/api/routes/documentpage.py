
# app/api/routes/documentpage.py

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import shutil

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, EmailStr

# Import from app services
from app.services.supabase_client import supabase, get_user_by_email

# Import functions from chatupload
from app.api.routes.chatupload import (
    validate_document_type_for_account,
    delete_invalid_document,
    process_uploaded_document,
    user_docs_path,
    load_member_progress,
    generate_dynamic_valid_document_response,
    generate_dynamic_invalid_document_response,
    send_wrong_document_type_email_dynamic,
    get_remaining_required_documents,
    check_documents_status,
    get_submitted_documents,
    update_user_onboarding_status,
    extract_members_from_commercial,
    save_member_progress,
    insert_conversation_log,
    get_onboarding_status,
)

from app.services.email_sender import (
    send_document_verification_email,
    send_onboarding_completion_email
)

from app.services.eid_validation import validate_eid_before_confirmation

# Create router
router = APIRouter(prefix="/documentupload", tags=["Document Upload"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class GetDocumentRequirementsRequest(BaseModel):
    email: EmailStr


class DocumentUploadRequest(BaseModel):
    email: EmailStr
    member_name: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    success: bool
    message: str
    document_type: Optional[str] = None
    extracted_data: Optional[dict] = None
    is_valid: bool
    is_complete: bool
    awaiting_verification: bool
    next_document: Optional[dict] = None
    remaining_documents: Optional[List[str]] = None
    wrong_document_type: bool = False
    document_file_path: Optional[str] = None
    cross_validation_passed: Optional[bool] = None
    cross_validation_errors: Optional[List[str]] = None

    class Config:
        extra = "ignore"


class DocumentStatusResponse(BaseModel):
    email: str
    documents: List[dict]
    remaining_documents: List[str]
    is_complete: bool
    stage: str
    members_info: Optional[dict] = None


class MemberListResponse(BaseModel):
    email: str
    members: List[dict]
    total: int
    verified: int


# ============================================================================
# PDF EXTRACTION HELPER
# ============================================================================

def ensure_user_directory(email: str, member_name: Optional[str] = None) -> Path:
    """
    Simple function to get and create user directory
    Works in Docker and local environments
    """
    base = Path(__file__).resolve().parent.parent.parent.parent / "documents" / "id" / email
    
    if member_name:
        base = base / member_name
    
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_display_document_name(doc_type: str) -> str:
    """Convert internal document type to user-friendly display name"""
    display_names = {
        "eid": "Emirates ID (EID)",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)"
    }
    return display_names.get(doc_type.lower(), doc_type.upper())


def extract_pdf_metadata(file_path: str) -> dict:
    """Extract text and metadata from PDF file"""
    try:
        import PyPDF2
        
        pdf_metadata = {
            "num_pages": 0,
            "text_preview": "",
            "title": ""
        }
        
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            pdf_metadata["num_pages"] = len(pdf_reader.pages)
            
            try:
                first_page = pdf_reader.pages[0]
                text = first_page.extract_text()
                pdf_metadata["text_preview"] = text[:500] if text else ""
            except:
                pdf_metadata["text_preview"] = "Preview not available"
            
            if pdf_reader.metadata:
                pdf_metadata["title"] = pdf_reader.metadata.get("/Title", "").strip() or Path(file_path).stem
        
        print(f"[INFO] ✅ PDF metadata extracted: {pdf_metadata['num_pages']} pages")
        return pdf_metadata
        
    except ImportError:
        print(f"[WARN] ⚠️ PyPDF2 not installed, returning basic metadata")
        return {
            "num_pages": 1,
            "text_preview": "PDF document - view full content by downloading",
            "title": Path(file_path).stem
        }
    except Exception as e:
        print(f"[ERROR] ❌ Error extracting PDF: {e}")
        return {
            "num_pages": 0,
            "text_preview": "Could not extract preview",
            "title": Path(file_path).stem
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def find_user_documents_directory(email: str) -> Optional[Path]:
    """Find where user documents are actually stored"""
    
    possible_paths = [
        Path(f"backend/documents/id/{email}"),
        Path(f"documents/id/{email}"),
        Path(f"app/backend/documents/id/{email}"),
        Path(f"./backend/documents/id/{email}"),
        Path(f"../backend/documents/id/{email}"),
        Path(f"uploads/{email}"),
        Path(f"backend/uploads/{email}"),
        Path(f"app/documents/{email}"),
    ]
    
    cwd = Path.cwd()
    
    for possible_path in possible_paths:
        abs_path = possible_path.resolve() if possible_path.is_absolute() else (cwd / possible_path).resolve()
        
        if abs_path.exists():
            print(f"[SUCCESS] ✅ Found directory: {abs_path}")
            return abs_path
    
    print(f"[ERROR] ❌ Document directory NOT FOUND for {email}")
    return None


def get_document_file_path(email: str, doc_type: str, member_name: Optional[str] = None):
    """Helper to get document file path with PDF metadata extraction"""
    try:
        base_path = find_user_documents_directory(email)
        if not base_path:
            print(f"[ERROR] ❌ Could not locate documents directory for {email}")
            return None
        
        search_path = base_path / member_name if member_name else base_path
        
        if not search_path.exists():
            print(f"[WARN] ⚠️ Search path does not exist: {search_path}")
            return None
        
        for item in search_path.rglob("*"):
            if not item.is_file():
                continue
            
            if item.name == "output.json":
                continue
            
            if not item.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']:
                continue
            
            output_json = item.parent / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_doc_type = data.get("document_type", "").lower().strip()
                search_doc_type = doc_type.lower().strip()
                
                match = False
                if stored_doc_type == search_doc_type:
                    match = True
                elif stored_doc_type in ["tenancy", "ejari"] and search_doc_type in ["tenancy", "ejari"]:
                    match = True
                elif stored_doc_type in ["moa", "memorandum"] and search_doc_type in ["moa", "memorandum"]:
                    match = True
                
                if match:
                    if item.suffix.lower() == '.pdf':
                        pdf_metadata = extract_pdf_metadata(str(item))
                        data["pdf_metadata"] = pdf_metadata
                        
                        with open(output_json, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    print(f"[SUCCESS] ✅ Found document file: {item}")
                    return str(item)
                    
            except Exception as e:
                print(f"[WARN] ⚠️ Error reading {output_json}: {e}")
                continue
        
        print(f"[WARN] ⚠️ No matching document found for '{doc_type}'")
        return None
        
    except Exception as e:
        print(f"[ERROR] ❌ get_document_file_path: {e}")
        import traceback
        traceback.print_exc()
        return None


def format_document_preview(doc_type: str, extracted_data: dict, member_name: Optional[str] = None, pdf_metadata: Optional[dict] = None) -> dict:
    """
    Format extracted document data for frontend preview
    ✅ FIXED: Properly handles nested structures for all document types
    """
    
    preview = {
        "document_type": doc_type,
        "member_name": member_name,
        "is_valid": True,
        "extracted_data": extracted_data,
        "pdf_metadata": pdf_metadata
    }
    
    print(f"\n[DEBUG] 🎨 Formatting preview for: {doc_type}")
    print(f"[DEBUG] 📊 Extracted data keys: {list(extracted_data.keys())}")
    
    # ============================================================================
    # ✅ EID - Flat structure
    # ============================================================================
    if doc_type.lower() == "eid":
        preview["key_fields"] = {
            "Name": extracted_data.get("Name") or extracted_data.get("name", "N/A"),
            "ID Number": extracted_data.get("ID Number") or extracted_data.get("id_number", "N/A"),
            "Nationality": extracted_data.get("Nationality") or extracted_data.get("nationality", "N/A"),
            "Expiry Date": extracted_data.get("Expiry Date") or extracted_data.get("expiry_date", "N/A"),
        }
    
    # ============================================================================
    # ✅ COMMERCIAL LICENSE - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() == "commercial":
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            print(f"[DEBUG] ✅ Using nested 'english' structure")
        else:
            eng = extracted_data
            print(f"[DEBUG] ⚠️ Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Company Name": eng.get("company_name_english") or eng.get("Company Name", "N/A"),
            "License Number": eng.get("license_number") or eng.get("License Number", "N/A"),
            "Status": eng.get("status") or eng.get("Status", "N/A"),
            "Expiry Date": eng.get("expiry_date") or eng.get("Expiry Date", "N/A"),
        }
        print(f"[DEBUG] 📋 Commercial key_fields: {preview['key_fields']}")
    
    # ============================================================================
    # ✅ EJARI - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() in ["ejari", "tenancy"]:
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            print(f"[DEBUG] ✅ Using nested 'english' structure")
        else:
            eng = extracted_data
            print(f"[DEBUG] ⚠️ Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Contract Number": eng.get("contract_number", "N/A"),
            "Owner Name": eng.get("owner_name", "N/A"),
            "Tenant Company": eng.get("tenant_company", "N/A"),
            "Start Date": eng.get("start_date", "N/A"),
            "End Date": eng.get("end_date", "N/A"),
            "Property Type": eng.get("property_type", "N/A"),
            "Area": eng.get("area", "N/A"),
        }
        print(f"[DEBUG] 📋 Ejari key_fields: {preview['key_fields']}")
    
    # ============================================================================
    # ✅ MOA - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() in ["moa", "memorandum"]:
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            print(f"[DEBUG] ✅ Using nested 'english' structure")
        else:
            eng = extracted_data
            print(f"[DEBUG] ⚠️ Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Company Name": eng.get("company_name") or eng.get("Company Name (EN)", "N/A"),
            "Owner Name": eng.get("owner_name", "N/A"),
            "Date of Execution": eng.get("date_of_execution", "N/A"),
            "Number of Shares": eng.get("number_of_shares", "N/A"),
        }
        print(f"[DEBUG] 📋 MOA key_fields: {preview['key_fields']}")
    
    return preview


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/get-document-requirements", response_model=dict)
async def get_document_requirements(request: GetDocumentRequirementsRequest):
    """Get required documents for user's account type"""
    email = request.email
    
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    account_type = user.get("account_type")
    ownership_type = user.get("ownership_type")
    document_stage = user.get("document_stage", "identification")
    
    try:
        from app.api.routes.chatupload import get_allowed_document_types
        
        allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
        doc_status = check_documents_status(email)
        submitted_docs = get_submitted_documents(email)
        
        document_status = {}
        for doc_type in allowed_info["allowed_types"]:
            document_status[doc_type] = {
                "submitted": doc_status.get(doc_type, False),
                "required": doc_type in [dt.lower() for dt in allowed_info["required_docs"]]
            }
        
        return {
            "success": True,
            "account_type": account_type,
            "ownership_type": ownership_type,
            "stage": document_stage,
            "stage_description": allowed_info["stage_description"],
            "required_documents": allowed_info["required_docs"],
            "allowed_types": allowed_info["allowed_types"],
            "document_status": document_status,
            "submitted_documents": submitted_docs,
            "is_complete": len([d for d in document_status.values() if d["required"]]) == len([d for d in document_status.values() if d["submitted"] and d["required"]]),
        }
        
    except Exception as e:
        print(f"[ERROR] ❌ get_document_requirements: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload-document", response_model=DocumentUploadResponse)
async def upload_document(
    email: EmailStr = Form(...),
    member_name: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    """
    Upload and process a single document with proper stage transitions
    ✅ Handles Corporate Partnership Stage 1 -> Stage 2 transitions
    ✅ NO validation here - validation happens ONLY when user clicks "Confirm Documents"
    """
    
    print(f"\n{'='*80}")
    print(f"🚀 [DEBUG] upload_document endpoint called")
    print(f"📧 [DEBUG] email: {email}")
    print(f"👤 [DEBUG] member_name: '{member_name}'")
    print(f"{'='*80}\n")
    
    # ============================================================================
    # ✅ VALIDATE USER AND FILES
    # ============================================================================
    print(f"🔍 [INFO] Validating user and files...")
    user = get_user_by_email(email)
    if not user:
        print(f"❌ [ERROR] User not found: {email}")
        raise HTTPException(status_code=404, detail="User not found")
    
    if not files:
        print(f"❌ [ERROR] No files provided")
        raise HTTPException(status_code=400, detail="No file provided")
    
    uploaded_file = files[0]
    user_name = user.get("name", "User")
    account_type = user.get("account_type", "")
    ownership = user.get("ownership_type", "")
    doc_stage = user.get("document_stage", "identification")
    
    print(f"✅ [INFO] User found: {user_name}")
    print(f"📊 [DEBUG] Account: {account_type} | Ownership: {ownership} | Stage: {doc_stage}")
    
    # ============================================================================
    # ✅ CLEAN AND VALIDATE MEMBER NAME
    # ============================================================================
    print(f"\n🔍 [INFO] Processing member name...")
    clean_member_name = None
    
    if member_name is not None and member_name.strip():
        clean_member_name = member_name.strip()
        print(f"✅ [INFO] Explicit member name provided: '{clean_member_name}'")
    
    elif (ownership in ["Partnership", "Multiple Owners"] and 
          doc_stage == "member_eids" and
          uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf'))):
        print(f"🔄 [INFO] Auto-detecting member mode...")
        mp = load_member_progress(email)
        if mp:
            members = mp.get("members", [])
            current_idx = mp.get("current_index", 0)
            if current_idx < len(members):
                clean_member_name = members[current_idx]
                print(f"✅ [INFO] Auto-detected member: '{clean_member_name}'")
    
    # ============================================================================
    # ✅ PROCESS DOCUMENT
    # ============================================================================
    print(f"\n📤 [INFO] Processing uploaded document: {uploaded_file.filename}")
    result = process_uploaded_document(email, uploaded_file, clean_member_name)
    
    # ============================================================================
    # ❌ HANDLE UNKNOWN DOCUMENT TYPE
    # ============================================================================
    if not result["success"] or result["document_type"] == "unknown":
        print(f"\n❌ [ERROR] Unknown or failed document: {result.get('document_type', 'unknown')}")
        
        try:
            send_document_verification_email(
                to_email=email,
                user_name=user_name,
                document_type="Unknown",
                status="invalid",
                filename=uploaded_file.filename,
                reason=result.get("ai_reasoning") or "Could not identify document type. Please ensure the document is clear and readable.",
                extracted_data=None
            )
            print(f"📧 [INFO] Error email sent for unknown document")
        except Exception as e:
            print(f"⚠️ [WARN] Failed to send email: {e}")
        
        return DocumentUploadResponse(
            success=False,
            message=result["message"],
            document_type=result.get("document_type", "unknown"),
            extracted_data=None,
            is_valid=False,
            is_complete=False,
            awaiting_verification=False,
            document_file_path=None,
            wrong_document_type=False,
            cross_validation_passed=None,
            cross_validation_errors=None
        )
    
    # ============================================================================
    # ✅ VALIDATE DOCUMENT TYPE
    # ============================================================================
    doc_type = result["document_type"]
    document_id = Path(uploaded_file.filename).stem
    
    print(f"\n📋 [INFO] Validating document type: {doc_type}")
    
    is_valid_type, error_message, allowed_info = validate_document_type_for_account(
        email=email,
        doc_type=doc_type,
        user_data=user,
        member_name=clean_member_name
    )
    
    # ============================================================================
    # ❌ HANDLE WRONG DOCUMENT TYPE
    # ============================================================================
    if not is_valid_type:
        print(f"❌ [ERROR] Wrong document type detected: {doc_type}")
        
        delete_invalid_document(
            email=email,
            document_id=document_id,
            doc_type=doc_type,
            member_name=clean_member_name
        )
        print(f"🗑️ [INFO] Invalid document deleted")
        
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
            print(f"📧 [INFO] Error email sent for wrong document type")
        except Exception as e:
            print(f"⚠️ [WARN] Failed to send email: {e}")
        
        remaining_docs = get_remaining_required_documents(email, user)
        
        return DocumentUploadResponse(
            success=False,
            message=dynamic_error_message,
            document_type=doc_type,
            extracted_data=None,
            is_valid=False,
            is_complete=False,
            awaiting_verification=False,
            wrong_document_type=True,
            remaining_documents=remaining_docs,
            document_file_path=None,
            cross_validation_passed=None,
            cross_validation_errors=None
        )
    
    # ============================================================================
    # ✅ VALID DOCUMENT TYPE - PROCESS FURTHER
    # ============================================================================
    print(f"✅ [SUCCESS] Correct document type: {doc_type}")
    
    if clean_member_name:
        file_path = f"backend/documents/id/{email}/{clean_member_name}/{document_id}/{uploaded_file.filename}"
    else:
        file_path = f"backend/documents/id/{email}/{document_id}/{uploaded_file.filename}"
    
    print(f"📁 [DEBUG] File path: {file_path}")
    
    dynamic_acknowledgment = generate_dynamic_valid_document_response(
        doc_type=doc_type,
        email=email,
        user_data=user,
        member_name=clean_member_name
    )
    
    # ============================================================================
    # 🔄 REFRESH USER DATA AND GET CURRENT STATUS
    # ============================================================================
    print(f"\n🔄 [DEBUG] Refreshing user data from database...")
    user_fresh = get_user_by_email(email)
    current_doc_stage = user_fresh.get("document_stage", "identification")
    current_account_type = user_fresh.get("account_type", "")
    current_ownership = user_fresh.get("ownership_type", "")
    
    print(f"📊 [DEBUG] Refreshed - Account: {current_account_type} | Ownership: {current_ownership} | Stage: {current_doc_stage}")
    
    status = get_onboarding_status(email, user_fresh, skip_welcome=True)
    print(f"📋 [DEBUG] Current stage from status: {status.get('stage')}")
    
    # ============================================================================
    # 🚀 CORPORATE PARTNERSHIP STAGE 1 -> STAGE 2 TRANSITION
    # ============================================================================
    print(f"\n🔍 [DEBUG] Checking for Stage 1->Stage 2 transition...")
    
    if (current_account_type == "Corporate" and 
        current_ownership in ["Partnership", "Multiple Owners"] and 
        current_doc_stage == "identification"):
        
        print(f"\n🎯 [INFO] Corporate Partnership in Stage 1 - Checking for transition conditions...")
        
        doc_status = check_documents_status(email)
        has_commercial = doc_status.get("commercial", False)
        has_moa = doc_status.get("moa", False)
        
        print(f"📄 [DEBUG] Commercial License valid: {has_commercial}")
        print(f"📜 [DEBUG] MOA valid: {has_moa}")
        
        if has_commercial and has_moa:
            print(f"\n✅ [SUCCESS] Both Commercial License and MOA are valid!")
            print(f"🚀 [INFO] Triggering Stage 1 -> Stage 2 transition...")
            
            try:
                print(f"👥 [INFO] Extracting members from Commercial License...")
                member_data = extract_members_from_commercial(email)
                members = member_data.get("members", [])
                
                if members and len(members) > 0:
                    print(f"✅ [SUCCESS] Extracted {len(members)} member(s)")
                    for idx, m in enumerate(members, 1):
                        print(f"   {idx}. {m}")
                    
                    print(f"💾 [INFO] Saving member progress...")
                    save_member_progress(email, members, 0)
                    print(f"✅ [SUCCESS] Member progress saved")
                    
                    print(f"📁 [INFO] Creating member directories...")
                    for member in members:
                        member_dir = user_docs_path(email) / member
                        member_dir.mkdir(parents=True, exist_ok=True)
                        print(f"   ✅ Created folder: {member}")
                    
                    print(f"🔧 [INFO] Updating database to member_eids stage...")
                    update_user_onboarding_status(email, False, "member_eids")
                    print(f"✅ [SUCCESS] Database updated to member_eids!")
                    
                    print(f"🔄 [DEBUG] Refreshing user data after database update...")
                    user_fresh = get_user_by_email(email)
                    status = get_onboarding_status(email, user_fresh, skip_welcome=True)
                    print(f"📋 [DEBUG] New stage: {status.get('stage')}")
                    print(f"🎉 [SUCCESS] Transition complete! Stage is now: {status.get('stage')}")
                
                else:
                    print(f"⚠️ [WARN] No members extracted from Commercial License")
            
            except Exception as e:
                print(f"❌ [ERROR] Failed during Stage 1->Stage 2 transition: {e}")
                import traceback
                traceback.print_exc()
        
        else:
            print(f"⏳ [DEBUG] Not ready for transition yet")
    
    else:
        print(f"⭐️ [DEBUG] Not a Corporate Partnership Stage 1, skipping transition logic")
    
    # ============================================================================
    # END OF STAGE TRANSITION
    # ============================================================================
    
    is_complete = status.get("is_complete", False)
    remaining_docs = get_remaining_required_documents(email, user_fresh)
    
    print(f"\n📊 [DEBUG] Upload Status:")
    print(f"   - Is complete: {is_complete}")
    print(f"   - Remaining docs: {len(remaining_docs)}")
    
    # ============================================================================
    # 📧 SEND ERROR EMAIL IF DOCUMENT INVALID
    # ============================================================================
    if not result["success"] or not result["is_valid"]:
        print(f"📧 [INFO] Sending error email for invalid document...")
        try:
            from app.services.email_sender import send_document_verification_email
            
            ai_reasoning = result.get("ai_reasoning") or result.get("message") or "Document validation failed"
            
            send_document_verification_email(
                to_email=email,
                user_name=user_name,
                document_type=doc_type.upper(),
                status="invalid",
                filename=uploaded_file.filename,
                reason=ai_reasoning,
                extracted_data=None,
                is_complete=False,
                remaining_documents=remaining_docs,
                member_name=clean_member_name
            )
            print(f"[SUCCESS] ✅ Error email sent for {doc_type}")
        except Exception as e:
            print(f"[WARN] ⚠️ Failed to send error email: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"✅ [INFO] Valid document processed - waiting for user confirmation (no email sent yet)")
    
    # ============================================================================
    # 📝 LOG CONVERSATION
    # ============================================================================
    print(f"📝 [INFO] Logging conversation...")
    try:
        ts = datetime.now(timezone.utc)
        insert_conversation_log({
            "user_email": email,
            "role": "agent",
            "message": dynamic_acknowledgment,
            "timestamp": ts
        }, channel="document_upload")
        print(f"✅ [SUCCESS] Conversation logged")
    except Exception as e:
        print(f"⚠️ [WARN] Failed to log conversation: {e}")
    
    # ============================================================================
    # 🖼️ GET PREVIEW DATA FOR FRONTEND DISPLAY
    # ============================================================================
    print(f"\n🖼️ [INFO] Generating preview data for {doc_type}...")
    
    preview_data = get_document_preview_data(
        email=email,
        doc_type=doc_type,
        member_name=clean_member_name
    )
    
    preview_html = None
    can_display_preview = False
    
    if preview_data.get("success"):
        preview_html = get_document_preview_html(preview_data)
        can_display_preview = True
        print(f"✅ [SUCCESS] Preview data generated for {doc_type}")
        print(f"📄 [DEBUG] Preview filename: {preview_data.get('filename')}")
        print(f"📤 [DEBUG] Preview MIME type: {preview_data.get('mime_type')}")
    else:
        error_msg = preview_data.get("error", "Unknown error")
        print(f"⚠️ [WARN] No preview data available: {error_msg}")
    
    # ============================================================================
    # 📋 FORMAT DOCUMENT PREVIEW FOR RESPONSE
    # ============================================================================
    preview_data_formatted = format_document_preview(
        doc_type=doc_type,
        extracted_data=result.get("extracted_data", {}),
        member_name=clean_member_name,
        pdf_metadata=preview_data.get("pdf_metadata") if preview_data.get("success") else None
    )
    
    # ============================================================================
    # ✅ VALIDATION REMOVED - WILL HAPPEN ONLY AT CONFIRMATION
    # ============================================================================
    # NOTE: Cross-validation and SurePass validation now run ONLY when user clicks
    # "Confirm Documents" button in /send-completion-email endpoint
    
    print(f"[INFO] ⏳ All documents uploaded. Waiting for user to click 'Confirm Documents'")
    print(f"[INFO] 🔍 Validation will run when user confirms (not now)")
    
    # ============================================================================
    # ✅ RETURN SUCCESSFUL RESPONSE
    # ============================================================================
    print(f"\n✅ [SUCCESS] Document upload completed successfully!")
    print(f"📊 [DEBUG] Final Status:")
    print(f"   - Document type: {result['document_type']}")
    print(f"   - Is valid: {result.get('is_valid', False)}")
    print(f"   - Is complete: {is_complete}")
    print(f"   - Current stage: {status.get('stage')}")
    print(f"{'='*80}\n")
    
    return DocumentUploadResponse(
        success=result["success"],
        message=f"{dynamic_acknowledgment}\n\n{result['message']}",
        document_type=result["document_type"],
        extracted_data=preview_data_formatted,
        is_valid=result.get("is_valid", False),
        is_complete=is_complete,
        awaiting_verification=result["is_valid"],
        document_file_path=file_path,
        next_document=status.get("next_required_document"),
        remaining_documents=remaining_docs,
        wrong_document_type=False,
        cross_validation_passed=None,  # Not validated yet
        cross_validation_errors=None
    )

def get_document_preview_data(email: str, doc_type: str, member_name: Optional[str] = None) -> dict:
    """
    Get complete preview data for a document including bytes for frontend display
    ✅ FIXED: Properly extracts nested extracted_fields from output.json
    """
    try:
        base_path = find_user_documents_directory(email)
        
        if not base_path:
            print(f"[ERROR] ❌ Document directory not found for {email}")
            return {"success": False, "error": "Document directory not found"}
        
        search_path = base_path / member_name if member_name else base_path
        
        if not search_path.exists():
            print(f"[ERROR] ❌ Search path does not exist: {search_path}")
            return {"success": False, "error": "Search path not found"}
        
        print(f"\n[DEBUG] 🔍 Searching for '{doc_type}' in: {search_path}")
        
        # ✅ Scan folders directly (same pattern as get_submitted_documents())
        for item in search_path.iterdir():
            if not item.is_dir():
                continue
            
            # Skip members folder
            if item.name == "members":
                continue
            
            output_file = item / "output.json"
            
            if not output_file.exists():
                print(f"[DEBUG] ⏭️ Skipping {item.name} - no output.json")
                continue
            
            try:
                print(f"[DEBUG] 📖 Checking: {output_file}")
                
                with open(output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_doc_type = data.get("document_type", "").lower().strip()
                search_doc_type = doc_type.lower().strip()
                
                print(f"[DEBUG] 📋 Comparing: stored='{stored_doc_type}' vs search='{search_doc_type}'")
                
                # Check match
                match = False
                if stored_doc_type == search_doc_type:
                    match = True
                elif stored_doc_type in ["tenancy", "ejari"] and search_doc_type in ["tenancy", "ejari"]:
                    match = True
                elif stored_doc_type in ["moa", "memorandum"] and search_doc_type in ["moa", "memorandum"]:
                    match = True
                
                if not match:
                    print(f"[DEBUG] ⏭️ Skipping - type mismatch")
                    continue
                
                print(f"[DEBUG] ✅ MATCH FOUND for {doc_type}!")
                
                # ✅ Find the actual document file in this folder
                document_file = None
                for file_item in item.iterdir():
                    if file_item.is_file() and file_item.name != "output.json":
                        if file_item.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']:
                            document_file = file_item
                            print(f"[DEBUG] 📄 Found document file: {document_file.name}")
                            break
                
                # ============================================================================
                # ✅ CRITICAL FIX: Extract data from correct location in output.json
                # ============================================================================
                
                # Try multiple possible locations for extracted data
                extracted_data = None
                
                # Location 1: extracted_fields (most common for chat uploads)
                if "extracted_fields" in data:
                    extracted_data = data["extracted_fields"]
                    print(f"[DEBUG] ✅ Found extracted_fields (chat upload format)")
                
                # Location 2: extracted_data (alternative format)
                elif "extracted_data" in data:
                    extracted_data = data["extracted_data"]
                    print(f"[DEBUG] ✅ Found extracted_data")
                
                # Location 3: result.extracted_fields (email upload format)
                elif "result" in data and isinstance(data["result"], dict):
                    result = data["result"]
                    if "extracted_fields" in result:
                        extracted_data = result["extracted_fields"]
                        print(f"[DEBUG] ✅ Found result.extracted_fields (email upload format)")
                    elif "extracted_data" in result:
                        extracted_data = result["extracted_data"]
                        print(f"[DEBUG] ✅ Found result.extracted_data")
                
                # Validate that we have meaningful data
                if not extracted_data or not isinstance(extracted_data, dict):
                    print(f"[WARN] ⚠️ No valid extracted data found in output.json")
                    extracted_data = {}
                else:
                    field_count = len(extracted_data) if not any(isinstance(v, dict) for v in extracted_data.values()) else sum(len(v) if isinstance(v, dict) else 1 for v in extracted_data.values())
                    print(f"[DEBUG] 📊 Extracted {field_count} field(s)")
                    
                    # Log sample fields for debugging
                    if extracted_data:
                        sample_keys = list(extracted_data.keys())[:3]
                        print(f"[DEBUG] 🔑 Sample keys: {sample_keys}")
                
                # ============================================================================
                # ✅ HANDLE FILE DATA
                # ============================================================================
                
                file_bytes = None
                mime_type = None
                file_ext = None
                pdf_metadata = None
                
                if document_file:
                    # Read file bytes
                    print(f"[DEBUG] 📖 Reading file bytes from: {document_file}")
                    with open(document_file, 'rb') as f:
                        file_bytes = f.read()
                    
                    print(f"[DEBUG] ✅ Read {len(file_bytes)} bytes")
                    
                    # Extract metadata
                    file_ext = document_file.suffix.lower()
                    mime_type = "application/pdf" if file_ext == ".pdf" else f"image/{file_ext.lstrip('.')}"
                    
                    # Get PDF metadata if applicable
                    if file_ext == ".pdf":
                        pdf_metadata = extract_pdf_metadata(str(document_file))
                        print(f"[DEBUG] 📄 PDF metadata: {pdf_metadata.get('num_pages', 0)} pages")
                
                # ============================================================================
                # ✅ RETURN COMPLETE DATA
                # ============================================================================
                
                return {
                    "success": True,
                    "filename": document_file.name if document_file else data.get("filename", "Document"),
                    "file_path": str(document_file) if document_file else None,
                    "file_bytes": file_bytes,
                    "mime_type": mime_type,
                    "file_ext": file_ext,
                    "pdf_metadata": pdf_metadata,
                    "extracted_data": extracted_data,  # ✅ This now contains the actual fields
                    "document_type": data.get("document_type", ""),
                    "is_valid": data.get("is_valid", False),
                    "human_verified": data.get("human_verified", False)
                }
            
            except Exception as e:
                print(f"[ERROR] ❌ Error processing {output_file}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"[ERROR] ❌ No matching document found for type: {doc_type}")
        return {"success": False, "error": f"No document found for type: {doc_type}"}
    
    except Exception as e:
        print(f"[ERROR] ❌ get_document_preview_data failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    
def get_document_preview_html(preview_data: dict) -> str:
    """
    Generate clean HTML preview for document display
    ✅ FIXED: Shows proper preview cards instead of raw metadata
    """
    if not preview_data.get("success"):
        return f"<p>❌ Error: {preview_data.get('error', 'Unknown error')}</p>"
    
    filename = preview_data.get("filename", "Document")
    mime_type = preview_data.get("mime_type")
    file_ext = preview_data.get("file_ext")
    pdf_metadata = preview_data.get("pdf_metadata")
    extracted_data = preview_data.get("extracted_data", {})
    
    # ============================================================================
    # ✅ EMAIL UPLOADS (No file available)
    # ============================================================================
    if not mime_type:
        return """
        <div style='
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border: 2px dashed #2196f3;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            margin: 15px 0;
        '>
            <div style='font-size: 48px; margin-bottom: 10px;'>📧</div>
            <div style='
                font-size: 16px;
                font-weight: 700;
                color: #1565c0;
            '>Document Verified via Email</div>
            <div style='
                font-size: 12px;
                color: #1976d2;
                margin: 8px 0;
            '>Extracted data available below</div>
        </div>
        """
    
    # ============================================================================
    # ✅ IMAGE FILES - Display actual image
    # ============================================================================
    if mime_type.startswith("image/"):
        file_bytes = preview_data.get("file_bytes")
        if file_bytes:
            import base64
            base64_data = base64.b64encode(file_bytes).decode('utf-8')
            return f'''
            <div style="
                text-align: center; 
                padding: 10px;
                background: #f8f9fa;
                border-radius: 8px;
                border: 1px solid #dee2e6;
            ">
                <img src="data:{mime_type};base64,{base64_data}" 
                     alt="{filename}" 
                     style="
                         max-width: 100%; 
                         max-height: 600px; 
                         border: 1px solid #ddd; 
                         border-radius: 8px;
                         box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                     " />
                <p style="
                    margin-top: 10px; 
                    font-size: 12px; 
                    color: #6c757d;
                ">{filename}</p>
            </div>
            '''
    
    # ============================================================================
    # ✅ PDF FILES - Show clean metadata card
    # ============================================================================
    elif mime_type == "application/pdf":
        num_pages = pdf_metadata.get('num_pages', 'N/A') if pdf_metadata else 'N/A'
        
        html = f"""
        <div style='
            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
            border: 2px solid #ffc107;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            margin: 15px 0;
            box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
        '>
            <div style='font-size: 64px; margin-bottom: 15px; opacity: 0.9;'>📄</div>
            <div style='
                font-size: 18px;
                font-weight: 700;
                color: #856404;
                margin-bottom: 10px;
            '>{filename}</div>
            <div style='
                font-size: 14px;
                color: #856404;
                margin: 8px 0;
            '>📊 {num_pages} page(s) • PDF Document</div>
            <div style='
                background: white;
                padding: 12px;
                border-radius: 8px;
                margin-top: 15px;
                border-left: 4px solid #ffc107;
            '>
                <p style='
                    margin: 0;
                    color: #856404;
                    font-size: 13px;
                '>💡 <strong>Tip:</strong> Use the download button below to view the full PDF document</p>
            </div>
        </div>
        """
        return html
    
    return f"<p>📄 Document: {filename} ({mime_type})</p>"

@router.get("/get-document-preview/{email}/{doc_type}")
async def get_document_preview(email: str, doc_type: str, member_name: Optional[str] = None):
    """
    Fetch preview data for a document
    ✅ Handles both chat uploads (with files) and email uploads (data only)
    """
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        print(f"[INFO] 🖼️ Fetching preview for {doc_type}...")
        
        preview_data = get_document_preview_data(email, doc_type, member_name)
        
        if not preview_data.get("success"):
            print(f"[WARN] ⚠️ Preview not available: {preview_data.get('error')}")
            return {
                "success": False,
                "error": preview_data.get("error", "Document not found"),
                "can_display": False
            }
        
        has_file = preview_data.get("file_path") is not None
        
        if not has_file:
            print(f"[INFO] ℹ️ Email upload - no file available")
            
            return {
                "success": True,
                "filename": preview_data.get("filename", "Document"),
                "mime_type": None,
                "file_ext": None,
                "pdf_metadata": None,
                "preview_html": None,
                "file_path": None,
                "can_display": False,
                "extracted_data": preview_data.get("extracted_data"),
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
            "extracted_data": preview_data.get("extracted_data"),
            "is_email_upload": False
        }
        
        print(f"[SUCCESS] ✅ Preview data prepared")
        return response
        
    except Exception as e:
        print(f"[ERROR] ❌ get_document_preview: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-document/{email}/{doc_type}")
async def download_document(email: str, doc_type: str, member_name: Optional[str] = None):
    """
    Download document file
    ✅ Handles file bytes for download
    """
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        print(f"[INFO] 📥 Preparing download for {doc_type}...")
        
        preview_data = get_document_preview_data(email, doc_type, member_name)
        
        if not preview_data.get("success"):
            raise HTTPException(status_code=404, detail="Document not found")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] ❌ download_document: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-confirmation-status/{email}")
async def check_confirmation_status(email: str):
    """Check if user already confirmed documents"""
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        response = supabase.table("users").select(
            "document_confirmation_sent"
        ).eq("email", email).single().execute()
        
        if response.data:
            return {
                "confirmation_sent": response.data.get("document_confirmation_sent", False)
            }
        return {"confirmation_sent": False}
    except Exception as e:
        print(f"[ERROR] ❌ check_confirmation_status: {e}")
        return {"confirmation_sent": False}

@router.post("/send-completion-email")
async def send_completion_email_endpoint(request: dict):
    """
    Send final completion email when user confirms all documents
    ✅ Runs cross-validation + SurePass API validation ONCE (the only validation)
    ✅ This is the ONLY place where validation happens
    """
    email = request.get("email")
    
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_name = user.get("name", "User")
    account_type = user.get("account_type", "")
    
    try:
        print(f"\n{'='*80}")
        print(f"[INFO] 🎉 PROCESSING DOCUMENT CONFIRMATION")
        print(f"[INFO] Email: {email}")
        print(f"[INFO] User: {user_name}")
        print(f"[INFO] Account Type: {account_type}")
        print(f"{'='*80}\n")
        
        # ============================================================================
        # 🔍 STEP 1: RUN CROSS-VALIDATION (ONLY VALIDATION IN ENTIRE FLOW)
        # ============================================================================
        print(f"\n🔍 [INFO] Running cross-validation (THIS IS THE ONLY VALIDATION)...")
        
        try:
            from app.services.cross_validator import CrossValidator
            from app.services.email_sender import (
                send_validation_pending_email,
                send_validation_failed_email,
                send_validation_passed_email
            )
            
            validator = CrossValidator()
            
            # Check if already completed via other channel
            onboarding_step = user.get("onboarding_step", "")
            document_confirmation_sent = user.get("document_confirmation_sent", False)
            
            if document_confirmation_sent and onboarding_step == "verification_complete":
                print("[INFO] ⚠️ User already completed onboarding via another channel")
                return {
                    "success": True,
                    "message": "Completion email already sent",
                    "already_completed": True,
                    "onboarding_step": "verification_complete"
                }
            
            # ✅ STEP 1A: Send "Validation Pending" notification
            print("[INFO] 📧 Sending validation pending notification...")
            send_validation_pending_email(email, user_name)
            print("[SUCCESS] ✅ Validation pending email sent")
            
            # ✅ STEP 1B: Run cross-validation
            print("[INFO] 🔍 Running cross-validation...")
            validation_result = validator.validate_documents(email, user)
            
            # ✅ STEP 1C: Save validation result as JSON
            print("[INFO] 💾 Saving validation result...")
            validator.save_validation_result(email, validation_result)
            print("[SUCCESS] ✅ Validation result saved to JSON")
            
            # ============================================================================
            # 🔍 STEP 2: HANDLE CROSS-VALIDATION RESULT
            # ============================================================================
            if not validation_result["passed"]:
                # ❌ CROSS-VALIDATION FAILED
                print(f"❌ [ERROR] Cross-validation failed: {validation_result['mismatches']}")
                
                # Send failure notification with details
                send_validation_failed_email(
                    to_email=email,
                    user_name=user_name,
                    mismatches=validation_result["mismatches"],
                    attempt_count=validation_result.get("attempt_count", 1)
                )
                print("[INFO] ✅ Validation failure email sent with detailed mismatches")
                
                # Build error response
                mismatch_list = '\n'.join([f"• {m}" for m in validation_result["mismatches"]])
                
                return {
                    "success": False,
                    "message": f"Cross-validation failed. Please review and fix the following issues:\n\n{mismatch_list}",
                    "validation_passed": False,
                    "mismatches": validation_result["mismatches"],
                    "onboarding_step": "documents_pending",
                    "email_sent": True  # Failure email was sent
                }
            
            # ✅ CROSS-VALIDATION PASSED
            print("✅ [SUCCESS] Cross-validation passed!")
            
            # ============================================================================
            # ✅ STEP 2A: SUREPASS API VALIDATION (Savings & Single Owner only)
            # ============================================================================
            print(f"\n{'='*80}")
            print(f"🔍 [SUREPASS] Running government verification for Emirates ID...")
            print(f"{'='*80}")
            
            surepass_valid, surepass_message = validate_eid_before_confirmation(email)
            
            if not surepass_valid:
                print(f"❌ ERROR: SurePass validation failed")
                print(f"❌ Reason: {surepass_message}")
                # Failure email already sent by validate_eid_before_confirmation
                return {
                    "success": False,
                    "message": f"Government verification failed: {surepass_message}",
                    "validation_passed": False,
                    "surepass_failed": True,
                    "onboarding_step": "documents_pending",
                    "email_sent": True  # Failure email was sent
                }
            else:
                print(f"✅ SUCCESS: SurePass validation passed!")
                
                # Send success notification
                send_validation_passed_email(email, user_name)
                print("[INFO] ✅ Validation success email sent")
            
        except Exception as validation_error:
            print(f"[ERROR] ❌ Validation system error: {validation_error}")
            import traceback
            traceback.print_exc()
            
            # Return error - DO NOT proceed to completion
            raise HTTPException(
                status_code=500, 
                detail=f"Validation system error: {str(validation_error)}"
            )
        
        # ============================================================================
        # ✅ STEP 3: UPDATE DATABASE (Only if both validations passed)
        # ============================================================================
        print(f"\n🔍 [INFO] Updating database to completion status...")
        
        try:
            update_payload = {
                "document_confirmation_sent": True,
                "confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
                # ✅ CRITICAL: Update onboarding_step for Admin Dashboard
                "onboarding_step": "verification_complete",
                # ✅ Mark document stage as complete
                "document_stage": "complete"
            }
            
            print(f"[DEBUG] 🔧 Updating database with payload: {update_payload}")
            
            result = supabase.table("users").update(update_payload).eq("email", email).execute()
            
            print(f"[SUCCESS] ✅ Database updated successfully")
            print(f"[DEBUG] Updated record: {result.data}")
            
            # ✅ Verify the update
            verify = supabase.table("users").select(
                "onboarding_step, document_stage, document_confirmation_sent"
            ).eq("email", email).single().execute()
            
            print(f"[DEBUG] ✅ Verified update in database:")
            print(f"  - onboarding_step: {verify.data.get('onboarding_step')}")
            print(f"  - document_stage: {verify.data.get('document_stage')}")
            print(f"  - document_confirmation_sent: {verify.data.get('document_confirmation_sent')}")
            
        except Exception as db_error:
            print(f"[ERROR] ❌ Failed to update database: {db_error}")
            import traceback
            traceback.print_exc()
            raise
        
        # ============================================================================
        # ✅ STEP 4: GENERATE PDF AND SEND COMPLETION EMAIL
        # ============================================================================
        print(f"\n📧 [INFO] Generating PDF and sending completion email...")
        
        try:
            from llm_pipeline.handle_reply import send_completion_email
            print(f"[INFO] 📄 Generating PDF summary and sending completion email...")
            send_completion_email(email, account_type)
            print(f"[SUCCESS] ✅ Completion email with PDF sent to {email}")
        except Exception as email_error:
            print(f"[ERROR] ❌ Failed to send completion email: {email_error}")
            import traceback
            traceback.print_exc()
            raise
        
        # ✅ Log the confirmation action
        ts = datetime.now(timezone.utc)
        insert_conversation_log({
            "user_email": email,
            "role": "agent",
            "message": "🎉 Document Verification Complete! User confirmed all documents. PDF summary generated and sent.",
            "timestamp": ts
        }, channel="document_upload")
        print(f"[SUCCESS] ✅ Conversation logged")
        
        return {
            "success": True,
            "message": "Completion email with PDF sent successfully and database updated",
            "validation_passed": True,
            "surepass_passed": True,
            "onboarding_step": "verification_complete",
            "document_stage": "complete",
            "pdf_generated": True,
            "email_sent": True
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] ❌ send_completion_email failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/document-status/{email}", response_model=DocumentStatusResponse)
async def get_document_status(email: str):
    """Get current document submission status with file paths and extracted data"""
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        onboarding_step = user.get("onboarding_step", "")
        document_confirmation_sent = user.get("document_confirmation_sent", False)
        
        print(f"[INFO] 🔍 Checking confirmation status for: {email}")
        print(f"[INFO] 📊 Onboarding Step: {onboarding_step}")
        print(f"[INFO] 📧 Confirmation Sent: {document_confirmation_sent}")
        
        is_already_complete = (
            onboarding_step == "verification_complete" or
            document_confirmation_sent == True
        )
        
        if is_already_complete:
            print(f"[INFO] ✅ User already completed verification via other channel")
        
        submitted_docs = get_submitted_documents(email)
        
        for doc in submitted_docs:
            doc["display_name"] = get_display_document_name(doc["document_type"])
            doc_type = doc.get("document_type", "").lower()
            member_name = doc.get("member_name")
            
            preview_data = get_document_preview_data(email, doc_type, member_name)
            
            if preview_data.get("success"):
                doc["extracted_data"] = preview_data.get("extracted_data", {})
                doc["file_path"] = preview_data.get("file_path")
                doc["has_preview"] = True
                
                if preview_data.get("pdf_metadata"):
                    doc["pdf_metadata"] = preview_data["pdf_metadata"]
            else:
                if not doc.get("extracted_data"):
                    doc["extracted_data"] = {}
                doc["file_path"] = None
                doc["has_preview"] = False
        
        account_type = user.get("account_type")
        ownership_type = user.get("ownership_type")
        document_stage = user.get("document_stage", "identification")
        
        from app.api.routes.chatupload import get_allowed_document_types
        allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
        
        valid_submitted_types = set()
        for doc in submitted_docs:
            if doc.get("is_valid"):
                doc_type = doc.get("document_type", "").lower()
                valid_submitted_types.add(doc_type)
                
                if doc_type in ["tenancy", "ejari"]:
                    valid_submitted_types.add("ejari")
                    valid_submitted_types.add("tenancy")
                elif doc_type in ["moa", "memorandum"]:
                    valid_submitted_types.add("moa")
                    valid_submitted_types.add("memorandum")
        
        remaining_docs = []
        
        if (account_type == "Corporate" and
            ownership_type in ["Partnership", "Multiple Owners"] and
            document_stage == "member_eids"):
            
            mp = load_member_progress(email)
            if mp:
                members = mp.get("members", [])
                total_members = len(members)
                
                member_eids_submitted = sum(
                    1 for doc in submitted_docs
                    if doc.get("document_type", "").lower() == "eid" and
                       doc.get("member_name") and
                       doc.get("is_valid")
                )
                
                remaining_member_count = total_members - member_eids_submitted
                
                if remaining_member_count > 0:
                    remaining_docs.append(f"Emirates ID (EID) for {remaining_member_count} member(s)")
        else:
            for required_doc in allowed_info["required_docs"]:
                doc_type_lower = required_doc.lower()
                is_submitted = False
                
                if "eid" in doc_type_lower and "eid" in valid_submitted_types:
                    is_submitted = True
                elif "commercial" in doc_type_lower and "commercial" in valid_submitted_types:
                    is_submitted = True
                elif "ejari" in doc_type_lower or "tenancy" in doc_type_lower:
                    if "ejari" in valid_submitted_types or "tenancy" in valid_submitted_types:
                        is_submitted = True
                elif "moa" in doc_type_lower or "memorandum" in doc_type_lower:
                    if "moa" in valid_submitted_types or "memorandum" in valid_submitted_types:
                        is_submitted = True
                
                if not is_submitted:
                    remaining_docs.append(required_doc)
        
        status = get_onboarding_status(email, user, skip_welcome=True)
        
        final_is_complete = is_already_complete or status["is_complete"]
        
        print(f"[INFO] 📊 Final Status:")
        print(f"  - Stage: {status['stage']}")
        print(f"  - Already Complete: {is_already_complete}")
        print(f"  - Current Complete: {status['is_complete']}")
        print(f"  - Final Is Complete: {final_is_complete}")
        print(f"  - Remaining Docs: {remaining_docs}")
        
        return DocumentStatusResponse(
            email=email,
            documents=submitted_docs,
            remaining_documents=remaining_docs,
            is_complete=final_is_complete,
            stage=status["stage"],
            members_info=status.get("members_info")
        )
        
    except Exception as e:
        print(f"[ERROR] ❌ get_document_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/member-list/{email}")
async def get_member_list(email: str):
    """Get list of members for Corporate Partnership/Multiple Owners"""
    try:
        member_progress_path = f"backend/documents/id/{email}/member_progress.json"
        
        if not os.path.exists(member_progress_path):
            raise HTTPException(status_code=404, detail="Member list not found")
        
        with open(member_progress_path, 'r') as f:
            member_data = json.load(f)
        
        return {
            "success": True,
            "members": member_data.get("members", []),
            "current_index": member_data.get("current_index", 0)
        }
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Member progress file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        print(f"[ERROR] ❌ get_validation_status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Export router
__all__ = ["router"]
