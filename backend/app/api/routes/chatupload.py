## # app/api/routes/chatupload.py

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, EmailStr

# Import from app services
from app.services.supabase_client import supabase, get_user_by_email
from app.services.ocr_service import process_document
from app.services.email_sender import send_email

# Import LLM runner
from llm_runner.run_model import call_local_llm

# Create router
router = APIRouter(prefix="/chatupload", tags=["Chat & Upload"])

# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class StartConversationRequest(BaseModel):
    email: EmailStr


class ChatConversationalRequest(BaseModel):
    email: EmailStr
    message: str
    chat_history: Optional[List[ChatMessage]] = []


class UploadConversationalResponse(BaseModel):
    success: bool
    message: str
    document_type: Optional[str] = None
    is_complete: bool
    awaiting_verification: bool
    next_document: Optional[str] = None


class OnboardingStatusResponse(BaseModel):
    stage: str
    required_documents: List[str]
    submitted_documents: List[dict]
    pending_documents: List[str]
    next_required_document: Optional[dict]
    members_info: Optional[dict]
    ai_message: str
    is_complete: bool
    
# ============================================================================
# HELPER FUNCTIONS - PATH MANAGEMENT
# ============================================================================


def user_docs_path(email: str) -> Path:
    """Get user's document directory path"""
    return Path("backend") / "documents" / "id" / email


def members_root_path(email: str) -> Path:
    """Get members root directory path"""
    return user_docs_path(email) / "members"


def member_progress_path(email: str) -> Path:
    """Get member progress JSON file path"""
    return user_docs_path(email) / "member_progress.json"

# ============================================================================
# MEMBER PROGRESS MANAGEMENT
# ============================================================================


def load_member_progress(email: str) -> Optional[dict]:
    """Load member progress from JSON file"""
    p = member_progress_path(email)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] load_member_progress: {e}")
        return None


def save_member_progress(email: str, members: list, current_index: int = 0) -> bool:
    """Save member progress to JSON file - STANDARDIZED FORMAT"""
    try:
        p = member_progress_path(email)
        p.parent.mkdir(parents=True, exist_ok=True)
        
        # ✅ USE SIMPLE LIST FORMAT (matching handle_reply.py)
        data = {
            "members": members,  # Simple list of strings
            "current_index": current_index,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[INFO] Member progress saved with {len(members)} members")
        return True
    except Exception as e:
        print(f"[ERROR] save_member_progress: {e}")
        return False

# ============================================================================
# CONVERSATION LOG HELPER
# ============================================================================


def insert_conversation_log(log_data: dict) -> bool:
    """Insert conversation log into conversations table"""
    try:
        supabase.table("conversations").insert(
            {
                "user_email": log_data["user_email"],
                "role": log_data["role"],
                "message": log_data["message"],
                "timestamp": (
                    log_data["timestamp"].isoformat()
                    if isinstance(log_data["timestamp"], datetime)
                    else log_data["timestamp"]
                ),
            }
        ).execute()
        return True
    except Exception as e:
        print(f"[ERROR] insert_conversation_log: {e}")
        return False
    
# ============================================================================
# EMAIL NOTIFICATION FUNCTIONS
# ============================================================================


def send_document_verification_email(to_email: str, user_name: str, doc_type: str, extracted_data: dict, member_name: Optional[str] = None):
    """Send email notification after document verification with extracted data"""
    
    subject = f"Document Verified - {doc_type.upper()}"
    
    # Format extracted data for email
    if doc_type.lower() == "eid":
        name = extracted_data.get("Name") or extracted_data.get("name") or "N/A"
        id_number = extracted_data.get("ID Number") or extracted_data.get("id_number") or "N/A"
        nationality = extracted_data.get("Nationality") or extracted_data.get("nationality") or "N/A"
        
        member_info = f"<p><strong>Member:</strong> {member_name}</p>" if member_name else ""
        
        data_html = f"""
        {member_info}
        <p><strong>Name:</strong> {name}</p>
        <p><strong>ID Number:</strong> {id_number}</p>
        <p><strong>Nationality:</strong> {nationality}</p>
        """
    
    elif doc_type.lower() == "commercial":
        eng = extracted_data.get("english", {})
        company = eng.get("company_name_english", "N/A")
        license_num = eng.get("license_number", "N/A")
        
        data_html = f"""
        <p><strong>Company Name:</strong> {company}</p>
        <p><strong>License Number:</strong> {license_num}</p>
        """
    
    elif doc_type.lower() in ("ejari", "tenancy"):
        eng = extracted_data.get("english", {})
        contract_num = eng.get("contract_number", "N/A")
        property_type = eng.get("property_type", "N/A")
        
        data_html = f"""
        <p><strong>Contract Number:</strong> {contract_num}</p>
        <p><strong>Property Type:</strong> {property_type}</p>
        """
    
    else:
        data_html = "<p>Document verified successfully</p>"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            .header {{ background: #28a745; color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
            .content {{ padding: 30px; }}
            .success-box {{ background: #d4edda; border-left: 4px solid #28a745; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">✅ Document Verified</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                <p>Your <strong>{doc_type.upper()}</strong> has been successfully verified!</p>
                
                <div class="success-box">
                    <h3 style="margin: 0 0 15px 0; color: #28a745;">Extracted Information</h3>
                    {data_html}
                </div>
                
                <p>Continue uploading any remaining documents to complete your onboarding.</p>
            </div>
            <div class="footer">
                <p style="margin: 0;">Best regards,</p>
                <p style="margin: 5px 0 0 0; font-weight: 600;">Thrivv Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[INFO] Verification email sent for {doc_type}")
    except Exception as e:
        print(f"[ERROR] Failed to send verification email: {e}")


def send_onboarding_complete_email(to_email: str, user_name: str):
    """Send final onboarding completion email"""
    subject = "🎉 Onboarding Complete - Account Activation Pending"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 40px; text-align: center; border-radius: 12px 12px 0 0; }}
            .content {{ padding: 40px; }}
            .success-box {{ background: #d4edda; border: 2px solid #4CAF50; padding: 25px; margin: 20px 0; border-radius: 10px; text-align: center; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">🎉 Congratulations!</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <div class="success-box">
                    <h2 style="margin: 0 0 15px 0; color: #4CAF50;">Onboarding Complete!</h2>
                    <p style="margin: 0; font-size: 16px;">All your documents have been successfully verified.</p>
                </div>
                
                <p><strong>Next Steps:</strong></p>
                <ul style="line-height: 1.8;">
                    <li>Your account will be activated within <strong>3-4 business days</strong></li>
                    <li>You will receive your account details via email</li>
                    <li>You can start using Thrivv services once activated</li>
                </ul>
                
                <p style="margin-top: 30px;">Thank you for choosing Thrivv Bank!</p>
            </div>
            <div class="footer">
                <p style="margin: 0;">Best regards,</p>
                <p style="margin: 5px 0 0 0; font-weight: 600;">Thrivv Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[INFO] Onboarding completion email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] Failed to send completion email: {e}")


def send_error_notification_email(to_email: str, user_name: str, doc_type: str, error_message: str):
    """Send email notification for document processing errors"""
    subject = f"Document Processing Issue - {doc_type.upper()}"
    
    body = f"""
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
                <h2 style="margin: 0;">⚠️ Document Processing Issue</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                <p>We encountered an issue processing your <strong>{doc_type.upper()}</strong> document.</p>
                
                <div class="error-box">
                    <h3 style="margin: 0 0 10px 0; color: #dc3545;">Issue Details</h3>
                    <p style="margin: 0;">{error_message}</p>
                </div>
                
                <p><strong>What to do next:</strong></p>
                <ul>
                    <li>Ensure the document is clear and readable</li>
                    <li>Upload a high-quality photo or scan</li>
                    <li>Make sure all text is visible</li>
                </ul>
                
                <p>Please upload the document again or contact support if you need assistance.</p>
            </div>
            <div class="footer">
                <p style="margin: 0;">Best regards,</p>
                <p style="margin: 5px 0 0 0; font-weight: 600;">Thrivv Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[INFO] Error notification email sent")
    except Exception as e:
        print(f"[ERROR] Failed to send error email: {e}")

# ============================================================================
# DATABASE STATUS UPDATE
# ============================================================================


def update_user_onboarding_status(email: str, is_complete: bool, stage: str):
    """Update user's onboarding status in database"""
    try:
        if is_complete:
            update_data = {
                "onboarding_step": "verification_complete",
                "document_stage": "onboarding_complete"
            }
            print(f"[INFO] Updating user status to COMPLETE")
        else:
            update_data = {
                "onboarding_step": "documents_pending",
                "document_stage": stage
            }
            print(f"[INFO] Updating user status to stage: {stage}")
        
        supabase.table("users").update(update_data).eq("email", email).execute()
        print(f"[SUCCESS] Database updated for {email}")
        
    except Exception as e:
        print(f"[ERROR] Failed to update user status: {e}")
        import traceback
        traceback.print_exc()

# ============================================================================
# MEMBER EXTRACTION LOGIC
# ============================================================================

def extract_members_from_commercial(email: str) -> dict:
    """
    Extract members from Commercial License ONLY (managers with role == 'Manager')
    - Extract managers with role == 'Manager' from Commercial License
    - Include registered user if not already in list
    """
    root = user_docs_path(email)
    names = []
    seen = set()

    # Get registered user's name
    try:
        user_response = supabase.table("users").select("name").eq("email", email).execute()
        registered_user_name = user_response.data[0].get("name") if user_response.data else None
    except Exception as e:
        print(f"[ERROR] Failed to get user name: {e}")
        registered_user_name = None

    # Extract from Commercial License ONLY
    try:
        for item in root.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            outp = item / "output.json"
            if not outp.exists():
                continue
            
            with open(outp, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            doc_type = (data.get("document_type") or "").lower()
            
            # From Commercial License - managers only
            if doc_type == "commercial" and data.get("is_valid"):
                extracted = data.get("extracted_data") or data.get("extracted_fields") or {}
                managers = extracted.get("managers") or []

                for mgr in managers:
                    name = mgr.get("name_english") or mgr.get("name", "")
                    name = name.strip()
                    role = mgr.get("role", "").strip()

                    if name and role.lower() == "manager":
                        normalized = name.upper()
                        if normalized not in seen:
                            names.append(name)
                            seen.add(normalized)
                            print(f"[INFO] Added manager from Commercial License: {name}")
            
            # REMOVED MOA extraction logic - no longer processing MOA documents here
                        
    except Exception as e:
        print(f"[ERROR] extract_members: {e}")

    # Remove duplicates, preserve order
    unique_names = []
    seen_unique = set()
    for name in names:
        name_upper = name.upper()
        if name_upper not in seen_unique:
            unique_names.append(name)
            seen_unique.add(name_upper)
    
    # Check if user already in list
    user_in_list = False
    if registered_user_name:
        for member in unique_names:
            if registered_user_name.lower() in member.lower() or member.lower() in registered_user_name.lower():
                user_in_list = True
                break
        
        # Add user at beginning if not found
        if not user_in_list and registered_user_name:
            unique_names.insert(0, registered_user_name)
            print(f"[INFO] Added registered user to beginning: {registered_user_name}")

    return {
        "members": unique_names,  # Simple list of strings
        "includes_user": user_in_list or (registered_user_name in unique_names if registered_user_name else False)
    }
    
# ============================================================================
# DOCUMENT STATUS CHECKING
# ============================================================================

def check_documents_status(email: str) -> dict:
    """Check which documents have been submitted and are valid"""
    root = user_docs_path(email)
    status = {
        "commercial": False,
        "eid": False,
        "tenancy": False,
        "ejari": False,
        "moa": False,
    }

    if not root.exists():
        return status

    # ✅ FIX: Members are now simple strings, not dicts
    mp = load_member_progress(email)
    member_names = (mp or {}).get("members", []) if mp else []
    # No more .get("name") - members is already a list of strings!

    try:
        # Get main user documents
        for item in root.iterdir():
            if not item.is_dir() or item.name in member_names or item.name == "members":
                continue

            out = item / "output.json"
            if not out.exists():
                continue

            try:
                with open(out, "r", encoding="utf-8") as f:
                    analysis = json.load(f)

                doc_type = (analysis.get("document_type") or "").lower()
                is_valid = analysis.get("is_valid", False)

                if is_valid:
                    if doc_type in status:
                        status[doc_type] = True
            except Exception as e:
                print(f"[ERROR] Reading {out}: {e}")

    except Exception as e:
        print(f"[ERROR] check_documents_status: {e}")

    return status


def get_submitted_documents(email: str) -> list:
    """Get list of submitted documents with their details"""
    root = user_docs_path(email)
    documents = []

    if not root.exists():
        return documents

    mp = load_member_progress(email)
    # ✅ FIX HERE:
    member_names = (mp or {}).get("members", []) if mp else []

    try:
        # Get main user documents
        for item in root.iterdir():
            if not item.is_dir() or item.name in member_names or item.name == "members":
                continue

            out = item / "output.json"
            if not out.exists():
                continue

            try:
                with open(out, "r", encoding="utf-8") as f:
                    analysis = json.load(f)

                # Find the original filename
                filename = None
                for file in item.iterdir():
                    if file.is_file() and file.name != "output.json":
                        filename = file.name
                        break

                doc_info = {
                    "document_type": analysis.get("document_type", "unknown"),
                    "filename": filename or item.name,
                    "is_valid": analysis.get("is_valid", False),
                    "extracted_data": analysis.get("extracted_data") or analysis.get("extracted_fields", {}),
                    "validation": analysis.get("validation", {}),
                    "status_message": analysis.get("status_message", ""),
                    "member_name": None,
                }
                documents.append(doc_info)
            except Exception as e:
                print(f"[ERROR] Reading {out}: {e}")

        # Get member documents
        for member_name in member_names:  # ✅ Already strings, no .get() needed
            member_dir = root / member_name
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

                    filename = None
                    for file in item.iterdir():
                        if file.is_file() and file.name != "output.json":
                            filename = file.name
                            break

                    doc_info = {
                        "document_type": analysis.get("document_type", "unknown"),
                        "filename": filename or item.name,
                        "is_valid": analysis.get("is_valid", False),
                        "extracted_data": analysis.get("extracted_data") or analysis.get("extracted_fields", {}),
                        "validation": analysis.get("validation", {}),
                        "status_message": analysis.get("status_message", ""),
                        "member_name": member_name,  # ✅ Simple string
                    }
                    documents.append(doc_info)
                except Exception as e:
                    print(f"[ERROR] Reading member {member_name} document: {e}")

    except Exception as e:
        print(f"[ERROR] get_submitted_documents: {e}")

    return documents

# ============================================================================
# ONBOARDING STATUS LOGIC - FIXED
# ============================================================================


def get_onboarding_status(email: str, user_data: dict, skip_welcome: bool = False) -> dict:
    """
    Get comprehensive onboarding status with next required document
    skip_welcome: If True, don't generate welcome message (prevents duplicate completion messages)
    """
    account_type = user_data.get("account_type")
    ownership = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", "identification")

    doc_status = check_documents_status(email)
    submitted_docs = get_submitted_documents(email)

    # ✅ CRITICAL FIX: Initialize members_info to None at the start
    members_info = None

    # Determine required documents based on account type
    if account_type == "Savings":
        required_all = ["eid", "ejari"]
        stage = "identification"
        
    elif account_type == "Corporate" and ownership == "Single Owner":
        required_all = ["commercial", "eid", "ejari"]
        stage = "identification"
        
    elif account_type == "Corporate" and ownership in ["Partnership", "Multiple Owners"]:
        if document_stage == "identification":
            required_all = ["commercial", "moa"]
            stage = "identification"
        else:
            required_all = []
            stage = "member_eids"
    else:
        required_all = []
        stage = "identification"

    # Check what's missing
    pending = []
    for req in required_all:
        if not doc_status.get(req, False):
            pending.append(req)

    # Determine next required document
    next_required = None
    if stage == "identification" and pending:
        next_doc_type = pending[0]
        next_required = {
            "type": next_doc_type,
            "requires_member_name": False,
            "member_name": None
        }
    elif stage == "member_eids":
        # ✅ Get member info for multiple owners - BUILD members_info HERE
        mp = load_member_progress(email)
        if mp:
            # ✅ Members are now simple strings
            all_members = mp.get("members", [])  # Already a list of strings
            current_idx = mp.get("current_index", 0)
            
            # Check which members have verified EIDs
            verified_members = []
            for member_name in all_members:
                # Check if this member has a valid EID
                member_dir = user_docs_path(email) / member_name  # ✅ FIXED PATH
                if member_dir.exists():
                    for item in member_dir.iterdir():
                        if item.is_dir():
                            out = item / "output.json"
                            if out.exists():
                                try:
                                    with open(out, "r", encoding="utf-8") as f:
                                        analysis = json.load(f)
                                    if analysis.get("is_valid") and analysis.get("document_type", "").lower() == "eid":
                                        verified_members.append(member_name)
                                        break
                                except:
                                    pass
            
            # ✅ BUILD members_info
            members_info = {
                "total": len(all_members),
                "verified": len(verified_members),
                "current_member": all_members[current_idx] if current_idx < len(all_members) else None,
                "all_members": all_members,
                "verified_members": verified_members,
                "pending_members": [m for m in all_members if m not in verified_members]
            }
            
            # Determine next required member EID
            pending_members = members_info["pending_members"]
            if pending_members:
                next_required = {
                    "type": "eid",
                    "requires_member_name": True,
                    "member_name": pending_members[0]
                }

    # Check if complete
    is_complete = False
    if stage == "identification" and not pending:
        if account_type == "Corporate" and ownership in ["Partnership", "Multiple Owners"]:
            is_complete = False
        else:
            is_complete = True
    elif stage == "member_eids":
        if members_info:  # ✅ Safe to access now
            is_complete = members_info["verified"] >= members_info["total"] and members_info["total"] > 0

    # Generate AI message ONLY if not skipping
    if skip_welcome:
        ai_message = ""
    else:
        ai_message = generate_welcome_message(
            email, user_data, doc_status, stage, pending, 
            next_required, is_complete, members_info  # ✅ Now always initialized
        )

    return {
        "stage": stage,
        "required_documents": required_all,
        "submitted_documents": submitted_docs,
        "pending_documents": pending,
        "next_required_document": next_required,
        "members_info": members_info,  # ✅ Can be None for non-partnership accounts
        "ai_message": ai_message,
        "is_complete": is_complete
    }


def generate_welcome_message(email: str, user_data: dict, doc_status: dict, stage: str, 
                            pending: list, next_required: dict, is_complete: bool, 
                            members_info: Optional[dict]) -> str:
    """Generate AI welcome/status message"""
    name = user_data.get("name", "there")
    account_type = user_data.get("account_type")
    ownership = user_data.get("ownership_type")

    if is_complete:
        return f"Welcome back, {name}! 🎉 All your documents have been verified. Your account will be activated within 3-4 business days."

    if stage == "identification":
        if not doc_status.get("commercial") and not doc_status.get("moa"):
            if account_type == "Savings":
                return f"Hi {name}! Welcome to Thrivv Bank. Let's get started with your Savings account onboarding.\n\nI'll need two documents from you:\n1. Emirates ID (EID)\n2. Ejari (Tenancy Contract)\n\nLet's start with your Emirates ID. Please upload it below."
            elif ownership == "Single Owner":
                return f"Hi {name}! Welcome to Thrivv Bank. Let's get started with your Corporate account onboarding.\n\nI'll need three documents:\n1. Emirates ID (EID)\n2. Commercial License\n3. Ejari (Tenancy Contract)\n\nLet's start with your Emirates ID. Please upload it below."
            else:
                return f"Hi {name}! Welcome to Thrivv Bank. Let's get started with your Corporate Partnership account onboarding.\n\nFirst, I'll need:\n1. Commercial License\n2. Memorandum of Association (MOA)\n\nAfter that, I'll identify all members and collect their Emirates IDs.\n\nLet's start with your Commercial License. Please upload it below."
        else:
            if next_required:
                doc_name = next_required["type"].upper()
                return f"Great progress, {name}! Next, please upload your {doc_name}."
            else:
                return f"Thanks {name}! Processing your documents..."

    elif stage == "member_eids":
        # ✅ SAFE: Check if members_info exists before accessing
        if members_info:
            total = members_info.get("total", 0)
            verified = members_info.get("verified", 0)
            pending_members = members_info.get("pending_members", [])
            
            if verified == 0:
                return f"Excellent, {name}! I've identified {total} members from your documents.\n\nNow I need Emirates IDs for each member. Let's start with {pending_members[0] if pending_members else 'the first member'}.\n\nPlease upload their Emirates ID."
            elif verified < total:
                return f"Great progress! {verified}/{total} member EIDs collected.\n\nNext, I need the Emirates ID for {pending_members[0] if pending_members else 'the next member'}.\n\nPlease upload their Emirates ID."
            else:
                return f"Perfect! All {total} member EIDs collected. Processing final verification..."
        else:
            return f"Hi {name}! Setting up member EID collection..."

    return f"Hi {name}! Continue uploading your documents."

# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

def process_uploaded_document(email: str, uploaded_file: UploadFile, member_name: Optional[str]) -> dict:
    """Process uploaded document and return conversational response - FULLY CORRECTED WITH RETRY"""
    
    MAX_RETRIES = 3
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 🔍 COMPREHENSIVE DEBUG LOGGING
            print(f"\n{'='*80}")
            print(f"[DEBUG] process_uploaded_document called (Attempt {attempt}/{MAX_RETRIES}):")
            print(f"  - email: {email}")
            print(f"  - uploaded_file.filename: {uploaded_file.filename}")
            print(f"  - member_name param: '{member_name}'")
            print(f"  - member_name type: {type(member_name)}")
            print(f"  - member_name is None: {member_name is None}")
            print(f"  - member_name == '': {member_name == ''}")
            if member_name:
                print(f"  - member_name stripped: '{member_name.strip()}'")
                print(f"  - member_name bool: {bool(member_name)}")
                print(f"  - member_name.strip() bool: {bool(member_name.strip())}")
            print(f"{'='*80}\n")
            
            document_id = Path(uploaded_file.filename).stem
            
            # 🔧 CRITICAL FIX: More robust member check
            is_member = bool(member_name and member_name.strip())
            
            print(f"[DEBUG] ✨ is_member calculated as: {is_member}")
            print(f"[DEBUG] Logic breakdown:")
            print(f"  - member_name exists: {member_name is not None}")
            print(f"  - member_name bool: {bool(member_name)}")
            if member_name:
                print(f"  - member_name.strip() bool: {bool(member_name.strip())}")
            print(f"  - Final is_member: {is_member}")

            # ✅ CRITICAL FIX: Match handle_reply.py path structure EXACTLY
            if is_member:
                member_name_clean = member_name.strip()
                save_dir = user_docs_path(email) / member_name_clean / document_id
                user_email_for_processing = f"{email}/{member_name_clean}"
                print(f"[INFO] ✅ MEMBER DOCUMENT MODE")
                print(f"[INFO] Uploading member document for: '{member_name_clean}'")
                print(f"[INFO] Save directory: {save_dir}")
                print(f"[INFO] Processing path: {user_email_for_processing}")
            else:
                # Main user documents
                save_dir = user_docs_path(email) / document_id
                user_email_for_processing = email
                print(f"[INFO] ℹ️  MAIN USER DOCUMENT MODE")
                print(f"[INFO] Save directory: {save_dir}")
                print(f"[INFO] Processing path: {user_email_for_processing}")

            # Only create directory on first attempt
            if attempt == 1:
                save_dir.mkdir(parents=True, exist_ok=True)
                file_path = save_dir / uploaded_file.filename

                content = uploaded_file.file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                print(f"[INFO] ✅ File saved successfully: {file_path}")
            else:
                file_path = save_dir / uploaded_file.filename
                print(f"[INFO] 🔄 Retry attempt {attempt}, using existing file: {file_path}")

            print(f"[DEBUG] About to call process_document with:")
            print(f"  - user_email: {user_email_for_processing}")
            print(f"  - document_id: {document_id}")
            print(f"  - file_path: {file_path}")
            print(f"  - is_member: {is_member}")

            # Select model based on file type
            ext = file_path.suffix.lower()
            if ext == '.pdf':
                model_name = "meta-llama/llama-3.2-11b-vision-instruct"
            else:
                model_name = "qwen/qwen-2.5-vl-7b-instruct"
            
            print(f"[INFO] Using model: {model_name}")

            result = process_document(
                user_email=user_email_for_processing,
                document_id=document_id,
                file_path=str(file_path),
                model_name=model_name,
                is_member=is_member,
            )

            is_valid = result.get("is_valid", False)
            doc_type = result.get("document_type", "unknown")
            extracted_data = result.get("extracted_data") or result.get("extracted_fields", {})
            raw_text = result.get("raw_text", "")
            
            print(f"[INFO] OCR processing complete (Attempt {attempt}):")
            print(f"  - Document type: {doc_type}")
            print(f"  - Is valid: {is_valid}")
            print(f"  - Is member doc: {is_member}")

            # 🔧 IMPROVED EID VALIDATION: Check for placeholder/dummy data
            if doc_type.lower() == "eid" and is_valid:
                # Extract name and ID fields
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
                
                print(f"[DEBUG] EID Field Check (Attempt {attempt}):")
                print(f"  - Name: '{name}' (empty: {not name})")
                print(f"  - ID Number: '{id_number}' (empty: {not id_number})")
                print(f"  - Nationality: '{nationality}' (empty: {not nationality})")
                print(f"  - DOB: '{dob}' (empty: {not dob})")
                print(f"  - Raw text: '{raw_text[:100]}'")
                
                # Check if data looks like placeholder or extraction failed
                is_placeholder = (
                    # Common placeholder names
                    "john doe" in name.lower() or
                    "jane doe" in name.lower() or
                    # ID contains placeholder patterns
                    "xxxx" in id_number.lower() or
                    "0000" in id_number or
                    # All fields are empty or N/A
                    name in ["", "N/A", "null", "none"] or
                    id_number in ["", "N/A", "null", "none"] or
                    # Model refused to process (privacy message)
                    "can't identify people" in raw_text.lower() or
                    "unable to provide" in raw_text.lower() or
                    # Raw text indicates failure
                    raw_text.strip() in ["unsafe", "unsafe\nS1", ""]
                )
                
                print(f"[DEBUG] Placeholder check result: {is_placeholder}")
                
                if is_placeholder:
                    print(f"[WARNING] ⚠️  Detected placeholder/invalid EID data on attempt {attempt}")
                    
                    # If not last attempt, retry
                    if attempt < MAX_RETRIES:
                        print(f"[INFO] 🔄 Retrying with different model...")
                        continue
                    else:
                        # Last attempt failed
                        print(f"[ERROR] ❌ All {MAX_RETRIES} attempts failed - EID unreadable")
                        is_valid = False
                        message = f"I had trouble reading your Emirates ID clearly after {MAX_RETRIES} attempts.\n\nThe document appears blurred or the text couldn't be extracted properly.\n\nPlease upload a clear, high-quality photo or scan of your Emirates ID."
                        return {
                            "success": False,
                            "message": message,
                            "document_type": doc_type,
                            "extracted_data": extracted_data,
                            "is_valid": False
                        }
                else:
                    # Data looks valid
                    print(f"[SUCCESS] ✅ EID data appears valid on attempt {attempt}")

            # Generate conversational message with extracted data
            if is_valid:
                # Pass member_name to format function (already cleaned if exists)
                message = format_extraction_message(doc_type, extracted_data, member_name.strip() if member_name else None)
                
                return {
                    "success": True,
                    "message": message,
                    "document_type": doc_type,
                    "extracted_data": extracted_data,
                    "is_valid": True
                }
            else:
                # Not valid, but might retry
                if attempt < MAX_RETRIES:
                    print(f"[INFO] 🔄 Validation failed on attempt {attempt}, retrying...")
                    continue
                else:
                    # All retries exhausted
                    validation = result.get("validation", {})
                    reason = validation.get("validation_reason", "Document could not be validated")
                    message = f"I had trouble processing your {doc_type.upper()} after {MAX_RETRIES} attempts.\n\nIssue: {reason}\n\nPlease upload a clear, readable copy of the document."
                    
                    return {
                        "success": False,
                        "message": message,
                        "document_type": doc_type,
                        "extracted_data": extracted_data,
                        "is_valid": False
                    }

        except Exception as e:
            print(f"[ERROR] process_uploaded_document (Attempt {attempt}): {e}")
            import traceback
            traceback.print_exc()
            
            if attempt < MAX_RETRIES:
                print(f"[INFO] 🔄 Exception occurred, retrying...")
                continue
            else:
                return {
                    "success": False,
                    "message": f"Sorry, I encountered an error processing your document after {MAX_RETRIES} attempts: {str(e)[:100]}\n\nPlease try again.",
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False
                }
    
    # Should never reach here, but just in case
    return {
        "success": False,
        "message": "Processing failed after all retry attempts.",
        "document_type": "unknown",
        "extracted_data": None,
        "is_valid": False
    }

def format_extraction_message(doc_type: str, extracted_data: dict, member_name: Optional[str]) -> str:
    """Format extracted data into structured conversational message for verification"""

    # 🪪 EMIRATES ID DETAILS
    if doc_type.lower() == "eid":
        msg = f"✅ Emirates ID processed successfully"
        if member_name:
            msg += f" for {member_name}"
        msg += ".\n\n"

        msg += "### 📋 Personal Information\n"
        msg += f"- **Name:** {extracted_data.get('Name') or extracted_data.get('name', 'N/A')}\n"
        msg += f"- **ID Number:** {extracted_data.get('ID Number') or extracted_data.get('id_number', 'N/A')}\n"
        msg += f"- **Nationality:** {extracted_data.get('Nationality') or extracted_data.get('nationality', 'N/A')}\n"
        msg += f"- **Sex:** {extracted_data.get('Sex') or extracted_data.get('sex', 'N/A')}\n\n"

        msg += "### 🗓️ Date Information\n"
        msg += f"- **Date of Birth:** {extracted_data.get('Date of Birth') or extracted_data.get('date_of_birth', 'N/A')}\n"
        msg += f"- **Issuing Date:** {extracted_data.get('Issuing Date') or extracted_data.get('issuing_date', 'N/A')}\n"
        msg += f"- **Expiry Date:** {extracted_data.get('Expiry Date') or extracted_data.get('expiry_date', 'N/A')}\n\n"

        msg += "Please review and type **'verified'** to confirm or let me know if something is incorrect."
        return msg

    # 🏢 COMMERCIAL LICENSE DETAILS
    elif doc_type.lower() == "commercial":
        eng = extracted_data.get("english", extracted_data)
        msg = "✅ Commercial License processed successfully.\n\n"

        msg += "### 🏭 Company Information\n"
        msg += f"- **Company Name:** {eng.get('company_name_english') or eng.get('Company Name', 'N/A')}\n"
        msg += f"- **Trade Name:** {eng.get('trade_name_english') or eng.get('Trade Name', 'N/A')}\n"
        msg += f"- **License Number:** {eng.get('license_number') or eng.get('License Number', 'N/A')}\n"
        msg += f"- **Legal Type:** {eng.get('legal_type') or eng.get('Legal Type', 'N/A')}\n"
        msg += f"- **Phone:** {eng.get('phone') or eng.get('Phone', 'N/A')}\n"
        msg += f"- **Issue Date:** {eng.get('issue_date') or eng.get('Issue Date', 'N/A')}\n"
        msg += f"- **Expiry Date:** {eng.get('expiry_date') or eng.get('Expiry Date', 'N/A')}\n"
        msg += f"- **Status:** {eng.get('status') or eng.get('Status', 'N/A')}\n\n"

        msg += "### 📍 Address\n"
        msg += f"- **License Address:** {eng.get('license_address_english') or eng.get('License Address', 'N/A')}\n\n"

        # Business Activities
        activities = extracted_data.get("activities", [])
        msg += "### 💼 Business Activities\n"
        if activities:
            for i, act in enumerate(activities, 1):
                msg += f"{i}. {act}\n"
        else:
            msg += "No activities found.\n\n"

        # Managers
        managers = extracted_data.get("managers", [])
        msg += "\n### 💼 Managers\n"
        for i, mgr in enumerate(managers, 1):
            name = mgr.get('name_english') or mgr.get('Name (EN)', 'N/A')
            role = mgr.get('role') or mgr.get('Role', 'N/A')
            nationality = mgr.get('nationality_english') or mgr.get('Nationality (EN)', 'N/A')
            msg += f"{i}. {name} ({role}) - {nationality}\n"

        # Partners / Shareholders
        partners = extracted_data.get("partners", [])
        if partners:
            msg += "\n### 🤝 Partners / Shareholders\n"
            for i, p in enumerate(partners, 1):
                name = p.get('name_english') or p.get('Name (EN)', 'N/A')
                share = p.get('share') or p.get('Share', 'N/A')
                share_pct = p.get('share_percentage') or p.get('Share Percentage', 'N/A')
                msg += f"{i}. {name} - Share: {share} ({share_pct}%)\n"

        # Owner
        owner = extracted_data.get("owner", {})
        if owner:
            msg += "\n### 👤 Owner\n"
            msg += f"- **Name (EN):** {owner.get('name_english') or owner.get('Name (EN)', 'N/A')}\n"
            msg += f"- **Nationality (EN):** {owner.get('nationality_english') or owner.get('Nationality (EN)', 'N/A')}\n"
            msg += f"- **Share:** {owner.get('share') or owner.get('Share', 'N/A')}\n\n"

        msg += "Please type **'verified'** to confirm the information."
        return msg

    # 📋 MOA DETAILS
    elif doc_type.lower() == "moa":
        eng = extracted_data.get("english", extracted_data)
        msg = "✅ Memorandum of Association processed successfully.\n\n"

        msg += "### 🏭 Company Information\n"
        msg += f"- **Company Name (EN):** {eng.get('company_name') or eng.get('Company Name (EN)', 'N/A')}\n"
        msg += f"- **Company Name (AR):** {eng.get('company_name_ar') or eng.get('Company Name (AR)', 'N/A')}\n"
        msg += f"- **Owner Name (EN):** {eng.get('owner_name') or eng.get('Owner Name (EN)', 'N/A')}\n"
        msg += f"- **Manager Name (EN):** {eng.get('manager_name') or eng.get('Manager Name (EN)', 'N/A')}\n"
        msg += f"- **Execution Date:** {eng.get('execution_date') or eng.get('Execution Date', 'N/A')}\n\n"

        msg += "### 💰 Share Information\n"
        msg += f"- **Number of Shares:** {eng.get('number_of_shares') or eng.get('Number of Shares', 'N/A')}\n"
        msg += f"- **Value per Share:** {eng.get('value_per_share') or eng.get('Value per Share', 'N/A')}\n"
        msg += f"- **Share Type:** {eng.get('share_type') or eng.get('Share Type', 'N/A')}\n\n"

        msg += "### 📄 Additional Information\n"
        msg += f"- **Company Duration:** {eng.get('company_duration') or eng.get('Company Duration', 'N/A')}\n"
        msg += f"- **Capital:** {eng.get('capital') or eng.get('Capital', 'N/A')}\n\n"

        msg += "Please review and type **'verified'** to confirm."
        return msg

    # 🏠 EJARI / TENANCY CONTRACT - FIXED FIELD NAMES
    elif doc_type.lower() in ("ejari", "tenancy"):
        eng = extracted_data.get("english", extracted_data)
        msg = "✅ Ejari / Tenancy Contract processed successfully.\n\n"

        msg += "### 📜 Contract Information\n"
        msg += f"- **Contract Number:** {eng.get('contract_number', 'N/A')}\n"
        msg += f"- **Registration Date:** {eng.get('registration_date', 'N/A')}\n"
        msg += f"- **Start Date:** {eng.get('start_date', 'N/A')}\n"
        msg += f"- **End Date:** {eng.get('end_date', 'N/A')}\n"
        msg += f"- **Contract Type:** {eng.get('contract_type', 'N/A')}\n"
        msg += f"- **Contract Value:** {eng.get('contract_value', 'N/A')}\n"
        msg += f"- **Payment Method:** {eng.get('payment_method', 'N/A')}\n"
        msg += f"- **Number of Payments:** {eng.get('number_of_payments', 'N/A')}\n\n"

        msg += "### 🏢 Property Information\n"
        msg += f"- **Property Type:** {eng.get('property_type', 'N/A')}\n"
        msg += f"- **Property Subtype:** {eng.get('property_subtype', 'N/A')}\n"
        msg += f"- **Usage:** {eng.get('usage', 'N/A')}\n"
        msg += f"- **Size:** {eng.get('size', 'N/A')}\n"
        msg += f"- **Property Number:** {eng.get('property_number', 'N/A')}\n"
        msg += f"- **Makani Number:** {eng.get('makani_number', 'N/A')}\n"
        msg += f"- **Plot Number:** {eng.get('plot_number', 'N/A')}\n"
        msg += f"- **Building Number:** {eng.get('building_number', 'N/A')}\n\n"

        msg += "### 📍 Property Location\n"
        msg += f"- **Building Name:** {eng.get('building_name', 'N/A')}\n"
        msg += f"- **Area / Community:** {eng.get('area') or eng.get('community', 'N/A')}\n"
        msg += f"- **Emirates:** {eng.get('emirates', 'N/A')}\n\n"

        msg += "### 👥 Parties\n"
        msg += "**Lessor (Owner):**\n"
        msg += f"- Name: {eng.get('owner_name') or eng.get('lessor_name', 'N/A')}\n"
        msg += f"- Company: {eng.get('lessor_company', 'N/A')}\n"
        msg += f"- License: {eng.get('lessor_license_number', 'N/A')}\n"
        msg += f"- Phone: {eng.get('lessor_phone', 'N/A')}\n"
        msg += f"- Email: {eng.get('lessor_email', 'N/A')}\n\n"

        msg += "**Tenant:**\n"
        msg += f"- Company: {eng.get('tenant_company', 'N/A')}\n"
        msg += f"- License: {eng.get('tenant_license', 'N/A')}\n"
        msg += f"- Tenant Number: {eng.get('tenant_number', 'N/A')}\n\n"

        msg += "Please type **'verified'** to confirm the above details."
        return msg

    # Default
    else:
        return f"I've processed your {doc_type.upper()} document.\n\nPlease type 'verified' to confirm the extracted data."
   
# ============================================================================
# VERIFICATION HANDLING
# ============================================================================

def handle_verification_response(email: str, user_message: str, user_data: dict) -> dict:
    """
    Check if user is verifying a document
    Returns: {is_verification: bool, verified: bool, next_message: str, is_complete: bool}
    """
    verification_keywords = ["verified", "confirm", "correct", "yes", "approve", "looks good"]
    user_lower = user_message.lower().strip()
    
    is_verification = any(keyword in user_lower for keyword in verification_keywords)
    
    if not is_verification:
        return {
            "is_verification": False,
            "verified": False,
            "next_message": None,
            "is_complete": False
        }

    print(f"[DEBUG] ✅ Verification detected from user: '{user_message}'")

    # Find the most recently uploaded unverified document
    root = user_docs_path(email)
    latest_doc = None
    latest_time = None
    latest_doc_type = None
    latest_member_name = None
    latest_extracted_data = None
    
    # Check main documents
    for item in root.iterdir():
        if not item.is_dir() or item.name == "members":
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
                    latest_member_name = None
                    latest_extracted_data = analysis.get("extracted_data") or analysis.get("extracted_fields", {})
        except:
            pass

    # ✅ Check member documents - FIXED PATH
    mp = load_member_progress(email)
    if mp:
        member_names = mp.get("members", [])
        for member_name in member_names:
            member_dir = user_docs_path(email) / member_name  # ✅ FIXED: No "members" folder
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
                except:
                    pass

    if not latest_doc:
        return {
            "is_verification": True,
            "verified": False,
            "next_message": "I couldn't find a document to verify. Please upload a document first.",
            "is_complete": False
        }

    # Mark document as verified
    try:
        with open(latest_doc, "r", encoding="utf-8") as f:
            analysis = json.load(f)
        
        analysis["human_verified"] = True
        analysis["verified_at"] = datetime.now(timezone.utc).isoformat()
        
        with open(latest_doc, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        
        doc_type = latest_doc_type or "document"
        
        print(f"[DEBUG] ✅ Document marked as verified:")
        print(f"  - Type: {doc_type}")
        print(f"  - Member: {latest_member_name or 'N/A (main user)'}")
        
        # ✅ SEND EMAIL NOTIFICATION FOR VERIFICATION
        user_name = user_data.get("name", "User")
        send_document_verification_email(
            to_email=email,
            user_name=user_name,
            doc_type=doc_type,
            extracted_data=latest_extracted_data,
            member_name=latest_member_name
        )
        
        # ✅ CRITICAL FIX: If member EID, update progress and check completion
        if latest_member_name and doc_type.lower() == "eid":
            print(f"[INFO] 👤 Member EID verified for: {latest_member_name}")
            
            progress_file = member_progress_path(email)
            if progress_file.exists():
                try:
                    with open(progress_file, "r", encoding="utf-8") as f:
                        progress_data = json.load(f)
                    
                    members = progress_data.get("members", [])
                    current_index = progress_data.get("current_index", 0)
                    
                    print(f"[DEBUG] Member progress before update:")
                    print(f"  - Total members: {len(members)}")
                    print(f"  - Current index: {current_index}")
                    print(f"  - Current member: {members[current_index] if current_index < len(members) else 'N/A'}")
                    
                    # 🔧 CRITICAL FIX: Move to next member ONLY after verification
                    current_index += 1
                    progress_data["current_index"] = current_index
                    progress_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    
                    with open(progress_file, "w", encoding="utf-8") as f:
                        json.dump(progress_data, f, indent=2, ensure_ascii=False)
                    
                    print(f"[DEBUG] Member progress after update:")
                    print(f"  - New current_index: {current_index}")
                    print(f"  - Next member: {members[current_index] if current_index < len(members) else 'ALL COMPLETE'}")
                    
                    # Count verified members
                    verified_count = current_index  # This member was just verified
                    total_members = len(members)
                    
                    print(f"[DEBUG] Verification status:")
                    print(f"  - Verified: {verified_count}/{total_members}")
                    print(f"  - Is complete: {verified_count >= total_members}")
                    
                    # 🔧 CRITICAL FIX: Check if ALL members verified BEFORE declaring complete
                    if verified_count >= total_members:
                        print(f"[SUCCESS] 🎉 ALL MEMBERS VERIFIED! Completing onboarding...")
                        
                        # ✅ ALL MEMBERS VERIFIED - ONBOARDING COMPLETE!
                        next_message = f"✅ {latest_member_name}'s EID verified!\n\n🎉 Congratulations! All {total_members} member EIDs have been verified.\n\nYour partnership onboarding is complete! Your account will be activated within 3-4 business days."
                        
                        # ✅ UPDATE DATABASE TO COMPLETE
                        update_user_onboarding_status(email, True, "onboarding_complete")
                        
                        # ✅ SEND COMPLETION EMAIL
                        send_onboarding_complete_email(email, user_name)
                        
                        return {
                            "is_verification": True,
                            "verified": True,
                            "next_message": next_message,
                            "is_complete": True
                        }
                    else:
                        # More members to verify
                        next_member = members[current_index] if current_index < len(members) else None
                        
                        if next_member:
                            next_message = f"✅ {latest_member_name}'s EID verified!\n\nProgress: {verified_count}/{total_members} members completed\n\nNext, I need the Emirates ID for {next_member}.\n\nPlease upload {next_member}'s Emirates ID."
                            
                            print(f"[INFO] 📤 Requesting next member EID: {next_member}")
                            
                            # ✅ UPDATE DATABASE STATUS (NOT complete yet)
                            update_user_onboarding_status(email, False, "member_eids")
                            
                            return {
                                "is_verification": True,
                                "verified": True,
                                "next_message": next_message,
                                "is_complete": False  # ← NOT complete yet!
                            }
                    
                except Exception as e:
                    print(f"[ERROR] Failed to update member progress: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Check if MOA verification triggers Stage 2
        ownership = user_data.get("ownership_type")
        account_type = user_data.get("account_type")
        document_stage = user_data.get("document_stage", "identification")
        
        if (account_type == "Corporate" and 
            ownership in ["Partnership", "Multiple Owners"] and 
            document_stage == "identification" and
            doc_type.lower() == "moa"):
            
            doc_status = check_documents_status(email)
            
            if doc_status.get("commercial") and doc_status.get("moa"):
                print("[INFO] Both Commercial and MOA verified - Extracting members!")
                
                member_data = extract_members_from_commercial(email)
                members = member_data["members"]
                
                if members and len(members) > 0:
                    save_member_progress(email, members, 0)
                    
                    # ✅ Create member folders with FIXED PATH
                    for member in members:
                        member_dir = user_docs_path(email) / member
                        member_dir.mkdir(parents=True, exist_ok=True)
                        print(f"[INFO] Created folder: {member_dir}")
                    
                    # ✅ UPDATE DATABASE TO STAGE 2
                    update_user_onboarding_status(email, False, "member_eids")
                    
                    member_list = ", ".join(members[:3])
                    if len(members) > 3:
                        member_list += f", and {len(members) - 3} more"
                    
                    next_message = f"✅ MOA verified!\n\n🎉 Stage 1 Complete!\n\nI've identified {len(members)} members from your documents:\n{member_list}\n\nNow I need Emirates IDs for each member. Let's start with {members[0]}.\n\nPlease upload {members[0]}'s Emirates ID."
                    
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": next_message,
                        "is_complete": False  # ← NOT complete, just stage transition!
                    }
        
        # Regular flow - check completion
        status = get_onboarding_status(email, user_data, skip_welcome=True)
        
        if status["is_complete"]:
            # ✅ ONBOARDING COMPLETE!
            next_message = f"✅ {doc_type.upper()} verified!\n\n🎉 Congratulations! All your documents have been verified. Your account will be activated within 3-4 business days."
            
            # ✅ UPDATE DATABASE TO COMPLETE
            update_user_onboarding_status(email, True, "onboarding_complete")
            
            # ✅ SEND COMPLETION EMAIL
            send_onboarding_complete_email(email, user_name)
            
        elif status["next_required_document"]:
            next_doc = status["next_required_document"]
            doc_name = next_doc["type"].upper()
            if next_doc.get("requires_member_name"):
                member = next_doc.get("member_name")
                next_message = f"✅ {doc_type.upper()} verified!\n\nNext, I need the Emirates ID for {member}. Please upload it below."
            else:
                next_message = f"✅ {doc_type.upper()} verified!\n\nNext, please upload your {doc_name}."
            
            # ✅ UPDATE DATABASE STATUS
            update_user_onboarding_status(email, False, status["stage"])
        else:
            next_message = f"✅ {doc_type.upper()} verified! Processing..."
        
        return {
            "is_verification": True,
            "verified": True,
            "next_message": next_message,
            "is_complete": status.get("is_complete", False)
        }
        
    except Exception as e:
        print(f"[ERROR] handle_verification_response: {e}")
        import traceback
        traceback.print_exc()
        return {
            "is_verification": True,
            "verified": False,
            "next_message": f"Sorry, I encountered an error during verification: {str(e)}\n\nPlease try again.",
            "is_complete": False
        }

        
# ============================================================================
# AI CHAT PROMPT BUILDING
# ============================================================================


def build_conversational_prompt(user_message: str, user_data: dict, status: dict, chat_history: list) -> str:
    """Build AI prompt for conversational chat"""
    name = user_data.get("name", "there")
    account_type = user_data.get("account_type")
    ownership = user_data.get("ownership_type")
    stage = status.get("stage")
    is_complete = status.get("is_complete")

    context = f"""You are a friendly, helpful onboarding assistant at Thrivv Bank.

User Information:
- Name: {name}
- Account Type: {account_type}
- Ownership: {ownership}
- Stage: {stage}
- Status: {'Complete' if is_complete else 'In Progress'}

"""

    if chat_history:
        context += "Recent conversation:\n"
        for msg in chat_history[-5:]:
            if isinstance(msg, dict):
                role = "User" if msg.get("role") == "user" else "You"
                content = msg.get("content", "")
            else:
                role = "User" if msg.role == "user" else "You"
                content = msg.content
            context += f"{role}: {content}\n"

    prompt = f"""{context}

User's message: {user_message}

Instructions:
- Be friendly, warm, and conversational
- Keep responses concise (2-3 sentences unless detailed explanation requested)
- Use plain text only - NO HTML tags
- Answer questions about onboarding process naturally
- If asked about requirements, explain what's needed for their specific account type

Your response (plain text only):"""

    return prompt.strip()

# ============================================================================
# API ENDPOINTS
# ============================================================================


@router.post("/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """Start conversational onboarding session"""
    email = request.email
    
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    status = get_onboarding_status(email, user)
    
    # Log initial message
    try:
        insert_conversation_log({
            "user_email": email,
            "role": "agent",
            "message": status["ai_message"],
            "timestamp": datetime.now(timezone.utc)
        })
    except:
        pass
    
    return {
        "success": True,
        "welcome_message": status["ai_message"],
        "status": status
    }


@router.get("/get-onboarding-status/{email}")
async def get_onboarding_status_endpoint(email: str):
    """Get current onboarding status"""
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    status = get_onboarding_status(email, user)
    return status

@router.post("/upload-conversational")
async def upload_conversational(
    email: EmailStr = Form(...),
    member_name: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
):
    """
    Upload document with conversational response + EMAIL NOTIFICATION
    FULLY CORRECTED - No premature completion
    """
    
    # 🔍 DEBUG LOGGING - Critical for troubleshooting
    print(f"\n{'='*80}")
    print(f"[DEBUG] upload_conversational endpoint called")
    print(f"[DEBUG] email: {email}")
    print(f"[DEBUG] member_name received: '{member_name}'")
    print(f"[DEBUG] member_name type: {type(member_name)}")
    print(f"[DEBUG] member_name is None: {member_name is None}")
    print(f"[DEBUG] member_name == '': {member_name == ''}")
    if member_name:
        print(f"[DEBUG] member_name stripped: '{member_name.strip()}'")
        print(f"[DEBUG] member_name length: {len(member_name)}")
    print(f"{'='*80}\n")
    
    # Get user data
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not files:
        raise HTTPException(status_code=400, detail="No file provided")
    
    uploaded_file = files[0]
    
    # 🔧 CRITICAL FIX: Clean and validate member_name
    # Handle empty strings, whitespace-only strings, and None
    clean_member_name = None
    
    # Check if user is in member_eids stage for auto-detection
    doc_stage = user.get("document_stage", "identification")
    ownership = user.get("ownership_type")
    
    if member_name is not None and member_name.strip():
        # Member name explicitly provided by user
        clean_member_name = member_name.strip()
        print(f"[INFO] ✅ Explicit member name provided: '{clean_member_name}'")
        
    elif (ownership in ["Partnership", "Multiple Owners"] and 
          doc_stage == "member_eids" and
          uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg'))):
        # Auto-detect mode - get current member from progress
        print(f"[INFO] 🔍 Auto-detecting member mode (no member_name provided)...")
        mp = load_member_progress(email)
        if mp:
            members = mp.get("members", [])
            current_idx = mp.get("current_index", 0)
            if current_idx < len(members):
                clean_member_name = members[current_idx]
                print(f"[INFO] ✅ Auto-detected member: '{clean_member_name}' (index {current_idx}/{len(members)})")
            else:
                print(f"[WARN] ⚠️  All members already processed (index {current_idx}/{len(members)})")
        else:
            print(f"[WARN] ⚠️  No member progress found")
    else:
        print(f"[INFO] ℹ️  Processing as main user document (no member context)")
    
    # Process document with cleaned/detected member_name
    result = process_uploaded_document(email, uploaded_file, clean_member_name)
    
    # ✅ SEND EMAIL NOTIFICATION BASED ON RESULT
    user_name = user.get("name", "User")
    
    if result["success"] and result["is_valid"]:
        # Document processed successfully - send verification email
        send_document_verification_email(
            to_email=email,
            user_name=user_name,
            doc_type=result["document_type"],
            extracted_data=result["extracted_data"],
            member_name=clean_member_name  # Use cleaned/detected version
        )
        print(f"[INFO] Verification email sent for {result['document_type']}")
    else:
        # Document failed - send error notification
        send_error_notification_email(
            to_email=email,
            user_name=user_name,
            doc_type=result["document_type"],
            error_message=result["message"]
        )
        print(f"[INFO] Error notification email sent for {result['document_type']}")
    
    # Get updated status (skip welcome to prevent duplicate messages)
    status = get_onboarding_status(email, user, skip_welcome=True)
    
    # ✅ Check if stage transition happened (Partnership Stage 1 -> Stage 2)
    # This happens when both Commercial + MOA are uploaded and verified
    if status["stage"] == "member_eids" and user.get("document_stage") == "identification":
        print(f"[INFO] 🔄 Stage transition detected: identification → member_eids")
        
        member_data = extract_members_from_commercial(email)
        members = member_data["members"]
        
        if members:
            save_member_progress(email, members, 0)
            
            # ✅ Create member folders with FIXED PATH
            for member in members:
                member_dir = user_docs_path(email) / member  # ✅ No "members" folder
                member_dir.mkdir(parents=True, exist_ok=True)
                print(f"[INFO] Created member folder: {member_dir}")
            
            # ✅ UPDATE DATABASE TO MEMBER_EIDS STAGE
            update_user_onboarding_status(email, False, "member_eids")
            print(f"[INFO] Database updated to member_eids stage")
            
            # Refresh status after stage transition
            status = get_onboarding_status(email, user, skip_welcome=True)
    
    # Log conversation
    try:
        ts = datetime.now(timezone.utc)
        insert_conversation_log({
            "user_email": email,
            "role": "agent",
            "message": result["message"],
            "timestamp": ts
        })
    except Exception as e:
        print(f"[WARN] Failed to log conversation: {e}")
    
    # 🔧 CRITICAL FIX: is_complete should ONLY be True after VERIFICATION, not after upload
    # Documents need user confirmation before marking complete
    return {
        "success": result["success"],
        "message": result["message"],
        "document_type": result["document_type"],
        "is_complete": False,  # ← ALWAYS False after upload, completion happens in verification
        "awaiting_verification": result["is_valid"],
        "next_document": status.get("next_required_document")
    }

@router.post("/chat-conversational")
async def chat_conversational(request: ChatConversationalRequest):
    """Handle conversational chat with verification detection"""
    email = request.email
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if this is a verification response
    verification = handle_verification_response(email, request.message, user)
    
    if verification["is_verification"]:
        # User is verifying a document
        response = verification["next_message"]
        
        # Log conversation
        try:
            ts = datetime.now(timezone.utc)
            insert_conversation_log({
                "user_email": email,
                "role": "user",
                "message": request.message,
                "timestamp": ts
            })
            insert_conversation_log({
                "user_email": email,
                "role": "agent",
                "message": response,
                "timestamp": ts
            })
        except:
            pass
        
        return {
            "response": response,
            "verification_accepted": verification["verified"],
            "is_complete": verification.get("is_complete", False)
        }
    
    # Regular chat query - use skip_welcome=True to prevent duplicate completion messages
    status = get_onboarding_status(email, user, skip_welcome=True)
    
    # Build chat history
    chat_history_dicts = []
    if request.chat_history:
        for msg in request.chat_history:
            chat_history_dicts.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp
            })
    
    # Build prompt and get AI response
    prompt = build_conversational_prompt(
        request.message,
        user,
        status,
        chat_history_dicts
    )
    
    try:
        answer = call_local_llm(prompt)
    except Exception as e:
        print(f"[ERROR] LLM: {e}")
        answer = "Sorry, I'm having trouble answering right now. Please try uploading your documents or ask me again."
    
    # Log conversation
    try:
        ts = datetime.now(timezone.utc)
        insert_conversation_log({
            "user_email": email,
            "role": "user",
            "message": request.message,
            "timestamp": ts
        })
        insert_conversation_log({
            "user_email": email,
            "role": "agent",
            "message": answer,
            "timestamp": ts
        })
    except:
        pass
    
    return {
        "response": answer,
        "verification_accepted": False,
        "is_complete": status["is_complete"]
    }
    
@router.get("/conversation-logs/{email}")
async def get_conversation_logs(email: str, limit: int = 20):
    """Get conversation history"""
    try:
        response = (
            supabase.table("conversations")
            .select("*")
            .eq("user_email", email)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        
        logs = response.data if response.data else []
        
        return {
            "email": email,
            "logs": logs,
            "count": len(logs)
        }
    except Exception as e:
        print(f"[ERROR] get_conversation_logs: {e}")
        return {
            "email": email,
            "logs": [],
            "count": 0
        }


@router.get("/member-progress/{email}")
async def get_member_progress(email: str):
    """Get member progress information"""
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    mp = load_member_progress(email)
    if not mp:
        return {
            "email": email,
            "members": [],
            "message": "No member progress found"
        }
    
    # ✅ FIX: Members are now simple strings
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
        
        # Check if this member has uploaded/verified EID
        member_dir = user_docs_path(email) / member_name  # ✅ FIXED PATH
        if member_dir.exists():
            for item in member_dir.iterdir():
                if not item.is_dir():
                    continue
                
                out = item / "output.json"
                if out.exists():
                    try:
                        with open(out, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
                        
                        if analysis.get("document_type", "").lower() == "eid":
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


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "chatupload-conversational",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# Export router
__all__ = ["router"]