## # app/api/routes/chatupload.py

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from app.services.cross_validator import CrossValidator
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, EmailStr
import os
from pathlib import Path

# Import from app services
from app.services.supabase_client import supabase, get_user_by_email
from app.services.ocr_service import process_document
from app.services.email_sender import send_email
from app.services.eid_validation import validate_eid_before_confirmation
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
CURRENT_FILE = Path(__file__).resolve()  # Full path to chatupload.py
ROUTES_DIR = CURRENT_FILE.parent  # backend/app/api/routes/
API_DIR = ROUTES_DIR.parent  # backend/app/api/
APP_DIR = API_DIR.parent  # backend/app/
BACKEND_DIR = APP_DIR.parent  # backend/

def ensure_user_directory(email: str, member_name: Optional[str] = None) -> Path:
    """
    Simple function to get and create user directory
    Works in Docker and local environments
    """
    # Get base path
    base = Path(__file__).resolve().parent.parent.parent.parent / "documents" / "id" / email
    
    # Add member folder if needed
    if member_name:
        base = base / member_name
    
    # Create directory
    base.mkdir(parents=True, exist_ok=True)
    
    return base

def user_docs_path(email: str) -> Path:
    """Get user's document directory path using absolute path"""
    return Path("/app/backend/documents/id") / email


def members_root_path(email: str) -> Path:
    """Get members root directory path"""
    return user_docs_path(email) / "members"


def member_progress_path(email: str) -> Path:
    """Get member progress JSON file path"""
    return user_docs_path(email) / "member_progress.json"


def members_root_path(email: str) -> Path:
    """Get members root directory path"""
    return user_docs_path(email) / "members"


def member_progress_path(email: str) -> Path:
    """Get member progress JSON file path"""
    return user_docs_path(email) / "member_progress.json"

def get_display_document_name(doc_type: str) -> str:
    """Convert internal document type to user-friendly display name"""
    display_names = {
        "eid": "Emirates ID (EID)",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)"
    }
    return display_names.get(doc_type.lower(), doc_type.upper())

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
        print(f"[ERROR] ❌ load_member_progress: {e}")
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
        print(f"[INFO] 📋 Member progress saved with {len(members)} members")
        return True
    except Exception as e:
        print(f"[ERROR] ❌ save_member_progress: {e}")
        return False

# ============================================================================
# CONVERSATION LOG HELPER
# ============================================================================

def insert_conversation_log(user_email: str, role: str, message: str, channel: str = "chat") -> bool:
    """
    Insert conversation log with channel parameter.
    
    Args:
        user_email: User's email address
        role: 'user' or 'agent'
        message: Conversation message
        channel: Communication channel (default: 'chat')
                 Options: 'web', 'chat', 'email', 'api', 'document_upload', 'ai_assistant'
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Validate channel value
        valid_channels = ['web', 'chat', 'email', 'api', 'document_upload', 'ai_assistant']
        if channel not in valid_channels:
            print(f"[WARNING] ⚠️ Invalid channel '{channel}', defaulting to 'chat'")
            channel = 'chat'
        
        # Prepare conversation data
        conversation_data = {
            "user_email": user_email,
            "role": role,
            "message": message,
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Insert into database
        result = supabase.table("conversations").insert(conversation_data).execute()
        
        if result.data:
            print(f"[SUCCESS] ✅ Conversation logged (channel: {channel})")
            return True
        else:
            print(f"[WARNING] ⚠️ Conversation log returned no data")
            return False
            
    except Exception as e:
        print(f"[ERROR] ❌ insert_conversation_log: {e}")
        import traceback
        traceback.print_exc()
        return False
    
# ============================================================================
# EMAIL NOTIFICATION FUNCTIONS
# ============================================================================


def get_remaining_required_documents(email: str, user_data: dict) -> List[str]:
    """
    Get list of remaining documents that user still needs to upload
    
    Returns:
        List of document names that are still required
    """
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", "identification")
    
    # Get allowed document types for this configuration
    allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
    required_doc_names = allowed_info["required_docs"]
    
    # Check which documents have been submitted and are valid
    doc_status = check_documents_status(email)
    
    remaining = []
    
    # Map document types to readable names
    doc_type_map = {
        "eid": "Emirates ID (EID)",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "tenancy": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)",
        "memorandum": "Memorandum of Association (MOA)"
    }
    
    # Check each allowed type
    for doc_type_key in allowed_info["allowed_types"]:
        if not doc_status.get(doc_type_key, False):
            doc_name = doc_type_map.get(doc_type_key, doc_type_key.upper())
            if doc_name not in remaining:
                remaining.append(doc_name)
    
    return remaining


def generate_dynamic_valid_document_response(
    doc_type: str,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None
) -> str:
    """
    Generate dynamic AI response for VALID document uploads
    Uses LLM to create contextual, natural responses
    
    Args:
        doc_type: Type of document uploaded (eid, commercial, etc.)
        email: User email
        user_data: User data dictionary
        member_name: Optional member name if member document
    
    Returns:
        str: AI-generated contextual response
    """
    
    account_type = user_data.get("account_type", "N/A")
    ownership_type = user_data.get("ownership_type", "N/A")
    user_name = user_data.get("name", "there")
    
    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user_data)
    
    member_context = f" for member {member_name}" if member_name else ""
    
    # Build context for LLM
    context = f"""User: {user_name}
Account Type: {account_type}
Ownership: {ownership_type}
Document Uploaded: {doc_type.upper()}{member_context}
Document Status: Valid and accepted
Remaining Documents Needed: {', '.join(remaining_docs) if remaining_docs else 'None - all documents submitted'}
"""
    
    # Build prompt for LLM
    prompt = f"""You are a friendly AI onboarding assistant at Thrivv Bank. A user just uploaded a document and it has been successfully validated.

{context}

Generate a brief, conversational acknowledgment message (2-3 sentences) that:
1. Confirms you received the {doc_type.upper()} document{member_context}
2. Mentions that you're extracting/processing the details
3. If there are remaining documents, naturally mention what's needed next
4. Keep it warm, professional, and encouraging

DO NOT use bullet points or lists. Write in natural conversational sentences.

Your response:"""
    
    try:
        response = call_local_llm(prompt)
        return response.strip()
    except Exception as e:
        print(f"[ERROR] ❌ LLM generation failed: {e}")
        # Fallback to template-based response
        if doc_type.lower() == "eid":
            ack = f"Got it âœ“ - I've received your Emirates ID{member_context}. Let me extract the details."
        elif doc_type.lower() == "commercial":
            ack = f"Perfect! I've received your Commercial License. Processing the details now."
        elif doc_type.lower() in ["ejari", "tenancy"]:
            ack = f"Thanks! I can now process your Tenancy Contract for verification."
        elif doc_type.lower() in ["moa", "memorandum"]:
            ack = f"Excellent! I've received your Memorandum of Association. Processing now."
        else:
            ack = f"Thanks! I've received your {doc_type.upper()} document. Processing now."
        
        if remaining_docs:
            ack += f"\n\nNext, I'll need: {', '.join(remaining_docs[:2])}"
        
        return ack


def generate_dynamic_invalid_document_response(
    uploaded_doc_type: str,
    allowed_info: dict,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None
) -> str:
    """
    Generate dynamic AI response for INVALID/WRONG document uploads
    
    Args:
        uploaded_doc_type: Type of document that was uploaded (wrong type)
        allowed_info: Dictionary with allowed_types, required_docs, etc.
        email: User email
        user_data: User data dictionary
        member_name: Optional member name if member document
    
    Returns:
        str: Structured error message with required documents
    """
    
    member_context = f" for member {member_name}" if member_name else ""
    
    # Get remaining documents (all required docs since wrong type was uploaded)
    remaining_docs = get_remaining_required_documents(email, user_data)
    
    # Build the structured message
    required_docs_formatted = "\nâ€¢ ".join(allowed_info["required_docs"])
    remaining_docs_formatted = "\nâ€¢ ".join(remaining_docs) if remaining_docs else "None"
    
    message = f"""❌ **Wrong Document Type{member_context}**

I received a **{uploaded_doc_type.upper()}** document, but this is not the correct document for your account type.

**Your Account:** {allowed_info['stage_description']}

**Required Documents:**
â€¢ {required_docs_formatted}

**What to do next:**
Please upload one of the required documents listed above. The {uploaded_doc_type.upper()} document is not needed for your account type.

If you believe this is an error, please contact support.

**📋 Remaining Documents to Upload:**
â€¢ {remaining_docs_formatted}

Please upload the remaining documents listed above."""
    
    return message

def generate_dynamic_email_for_invalid_document(
    to_email: str,
    user_name: str,
    uploaded_doc_type: str,
    allowed_info: dict,
    remaining_docs: List[str],
    member_name: Optional[str] = None
) -> tuple:
    """
    Generate dynamic email for invalid/wrong document type
    
    Returns:
        tuple: (subject, html_body)
    """
    
    member_context = f" for member {member_name}" if member_name else ""
    subject = f"❌ Wrong Document Uploaded{member_context} - Action Required"
    
    required_docs_html = "".join([f"<li>{doc}</li>" for doc in allowed_info["required_docs"]])
    remaining_docs_html = "".join([f"<li>{doc}</li>" for doc in remaining_docs]) if remaining_docs else "<li>None - please upload required documents</li>"
    
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
            .required-box {{ background: #d1ecf1; border-left: 4px solid #0c5460; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .remaining-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
            ul {{ margin: 10px 0; padding-left: 25px; }}
            li {{ margin: 8px 0; font-size: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">❌ Wrong Document Type</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                
                <div class="error-box">
                    <h3 style="margin: 0 0 15px 0; color: #721c24;">Document Type Mismatch</h3>
                    <p style="margin: 0; color: #721c24;">
                        You uploaded a <strong>{uploaded_doc_type.upper()}</strong> document{member_context}, 
                        but this is not the correct document type for your account.
                    </p>
                </div>
                
                <p><strong>Your Account Type:</strong> {allowed_info['stage_description']}</p>
                
                <div class="required-box">
                    <h3 style="margin: 0 0 15px 0; color: #0c5460;">✅ Required Documents for Your Account:</h3>
                    <ul>
                        {required_docs_html}
                    </ul>
                </div>
                
                <div class="remaining-box">
                    <h3 style="margin: 0 0 15px 0; color: #856404;">📋 Remaining Documents to Upload:</h3>
                    <ul>
                        {remaining_docs_html}
                    </ul>
                    <p style="margin: 15px 0 0 0; color: #856404;">
                        <strong>Next Step:</strong> Please upload the remaining documents listed above.
                    </p>
                </div>
                
                <p><strong>👤 Action Required:</strong></p>
                <p>The uploaded {uploaded_doc_type.upper()} document has been automatically removed from your account. 
                Please upload one of the required document types as listed above to continue your onboarding.</p>
                
                <p style="margin-top: 25px;">You can upload the correct document through the chat interface or by replying to this email.</p>
                
                <p style="margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
                    <strong>Need Help?</strong><br>
                    If you believe this is an error or need assistance, please contact our support team.
                </p>
            </div>
            <div class="footer">
                <p style="margin: 0;">Best regards,</p>
                <p style="margin: 5px 0 0 0; font-weight: 600;">Thrivv Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return subject, body


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
        print(f"[INFO] 📋 Verification email sent for {doc_type}")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send verification email: {e}")


def send_onboarding_complete_email(to_email: str, user_name: str):
    """Send final onboarding completion email"""
    subject = "Onboarding Complete - Account Activation Pending"
    
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
                <h1 style="margin: 0; font-size: 32px;"> Congratulations!</h1>
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
        print(f"[INFO] 📋 Onboarding completion email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send completion email: {e}")


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
                <h2 style="margin: 0;">âš™ï¸ Document Processing Issue</h2>
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
        print(f"[INFO] 📋 Error notification email sent")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send error email: {e}")

def send_wrong_document_type_email_dynamic(
    to_email: str,
    user_name: str,
    uploaded_doc_type: str,
    allowed_info: dict,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None
):
    """
    UPDATED: Send email for wrong document with dynamic remaining docs
    """
    
    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user_data)
    
    # Generate dynamic email
    subject, body = generate_dynamic_email_for_invalid_document(
        to_email=to_email,
        user_name=user_name,
        uploaded_doc_type=uploaded_doc_type,
        allowed_info=allowed_info,
        remaining_docs=remaining_docs,
        member_name=member_name
    )
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[INFO] 📋 ✅ Dynamic wrong document email sent")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send wrong document email: {e}")

# ============================================================================
# DATABASE STATUS UPDATE
# ============================================================================

def update_user_onboarding_status(email: str, is_complete: bool, stage: str):
    """Update user's onboarding status in database"""
    try:
        if is_complete:
            update_data = {
                "onboarding_step": "verification_complete",
                "document_stage": "onboarding_complete",
                "document_confirmation_sent": True,  # ✅ ADD THIS
                "confirmation_timestamp": datetime.now(timezone.utc).isoformat()  # ✅ ADD THIS
            }
            print(f"[INFO] 📋 Updating user status to COMPLETE")
        else:
            update_data = {
                "onboarding_step": "documents_pending",
                "document_stage": stage
            }
            print(f"[INFO] 📋 Updating user status to stage: {stage}")
        
        supabase.table("users").update(update_data).eq("email", email).execute()
        print(f"[SUCCESS] ✅ Database updated for {email}")
        
    except Exception as e:
        print(f"[ERROR] ❌ Failed to update user status: {e}")
        import traceback
        traceback.print_exc()

def get_allowed_document_types(account_type: str, ownership_type: str, document_stage: str) -> Dict[str, List[str]]:
    """Get allowed document types for specific account configuration and stage"""
    
    if account_type == "Savings":
        return {
            "allowed_types": ["eid", "ejari", "tenancy"],
            "stage_description": "Savings Account",
            "required_docs": ["Emirates ID (EID)", "Ejari (Tenancy Contract)"]
        }
    
    elif account_type == "Corporate" and ownership_type == "Single Owner":
        return {
            "allowed_types": ["commercial", "eid", "ejari", "tenancy"],
            "stage_description": "Corporate Single Owner Account",
            "required_docs": ["Commercial License", "Emirates ID (EID)", "Ejari (Tenancy Contract)"]
        }
    
    elif account_type == "Corporate" and ownership_type in ["Partnership", "Multiple Owners"]:
        
        if document_stage == "identification":
            return {
                "allowed_types": ["commercial", "moa", "memorandum"],
                "stage_description": "Partnership Identification Stage",
                "required_docs": ["Commercial License", "Memorandum of Association (MOA)"]
            }
        
        elif document_stage == "member_eids":
            return {
                "allowed_types": ["eid"],
                "stage_description": "Partnership Member EID Collection",
                "required_docs": ["Emirates ID (EID) for each member"]
            }
    
    return {
        "allowed_types": ["eid", "commercial", "ejari", "tenancy", "moa"],
        "stage_description": "General Account",
        "required_docs": ["Required documents"]
    }


def validate_document_type_for_account(
    email: str,
    doc_type: str,
    user_data: dict,
    member_name: Optional[str] = None
) -> Tuple[bool, str, dict]:
    """Validate if uploaded document type is allowed for user's account configuration"""
    
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", "identification")
    
    print(f"\n[VALIDATION] Document Type Check: {doc_type} for {account_type}/{ownership_type}/{document_stage}")
    
    allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
    allowed_types = allowed_info["allowed_types"]
    
    doc_type_normalized = doc_type.lower().strip()
    is_allowed = doc_type_normalized in allowed_types
    
    if is_allowed:
        print(f"[SUCCESS] ✅ Document type '{doc_type}' is ALLOWED")
        return True, "", allowed_info
    else:
        print(f"[ERROR] ❌ ❌ Document type '{doc_type}' is NOT ALLOWED")
        
        member_context = f" for member {member_name}" if member_name else ""
        required_docs_formatted = "\nâ€¢ ".join(allowed_info["required_docs"])
        
        error_message = f"""❌ **Wrong Document Type{member_context}**

I received a **{doc_type.upper()}** document, but this is not the correct document for your account type.

**Your Account:** {allowed_info['stage_description']}

**Required Documents:**
â€¢ {required_docs_formatted}

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
            print(f"[WARN] ⚠️ Document folder does not exist: {doc_folder}")
            return False
        
        print(f"[INFO] 📋 ðŸ—‘ï¸ Deleting invalid {doc_type.upper()} document: {doc_folder}")
        shutil.rmtree(doc_folder)
        print(f"[SUCCESS] ✅ Successfully deleted invalid document folder")
        return True
        
    except Exception as e:
        print(f"[ERROR] ❌ Failed to delete document: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_wrong_document_type_email(
    to_email: str,
    user_name: str,
    uploaded_doc_type: str,
    allowed_info: dict,
    member_name: Optional[str] = None
):
    """Send email notification when wrong document type is uploaded"""
    
    member_context = f" for member {member_name}" if member_name else ""
    subject = f"❌ Wrong Document Uploaded{member_context} - Action Required"
    
    required_docs_html = "".join([f"<li>{doc}</li>" for doc in allowed_info["required_docs"]])
    
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
            .required-box {{ background: #d1ecf1; border-left: 4px solid #0c5460; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
            ul {{ margin: 10px 0; padding-left: 25px; }}
            li {{ margin: 8px 0; font-size: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">❌ Wrong Document Type</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                
                <div class="error-box">
                    <h3 style="margin: 0 0 15px 0; color: #721c24;">Document Type Mismatch</h3>
                    <p style="margin: 0; color: #721c24;">
                        You uploaded a <strong>{uploaded_doc_type.upper()}</strong> document{member_context}, 
                        but this is not the correct document type for your account.
                    </p>
                </div>
                
                <p><strong>Your Account Type:</strong> {allowed_info['stage_description']}</p>
                
                <div class="required-box">
                    <h3 style="margin: 0 0 15px 0; color: #0c5460;">✅ Required Documents:</h3>
                    <ul>
                        {required_docs_html}
                    </ul>
                </div>
                
                <p><strong>👤 Action Required:</strong></p>
                <p>The uploaded {uploaded_doc_type.upper()} document has been automatically removed from your account. 
                Please upload the correct document type as listed above to continue your onboarding.</p>
                
                <p style="margin-top: 25px;">You can upload the correct document through the chat interface or by replying to this email.</p>
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
        print(f"[INFO] 📋 ✅ Wrong document type email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send wrong document type email: {e}")


# ============================================================================
# MEMBER EXTRACTION LOGIC
# ============================================================================

def extract_members_from_commercial(email: str) -> dict:
    """
    ✅ USE CENTRALIZED FUNCTION FROM handle_reply.py
    This ensures consistent logic across all channels
    """
    from llm_pipeline.handle_reply import extract_members_from_documents
    
    return extract_members_from_documents(email)
    
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
                print(f"[ERROR] ❌ Reading {out}: {e}")

    except Exception as e:
        print(f"[ERROR] ❌ check_documents_status: {e}")

    return status

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
            print(f"[WARN] ⚠️ Base path does not exist: {base_path}")
            return documents
        
        print(f"\n[INFO] ðŸ“‚ Scanning documents for: {email}")
        
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
                
                print(f"[INFO] 📋 ✅ Found document: {doc_type.upper()} (valid={is_valid})")
                
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
                print(f"[ERROR] ❌ Reading {output_file}: {e}")
        
        # ============================================================================
        # ✅ MEMBER DOCUMENTS
        # ============================================================================
        mp = load_member_progress(email)
        if mp:
            member_names = mp.get("members", [])
            print(f"[INFO] 📋 Processing {len(member_names)} member(s)")
            
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
                        print(f"[INFO] 📋 ✅ Member doc: {member_name} - {doc_type.upper()}")
                        
                    except Exception as e:
                        print(f"[ERROR] ❌ Reading member document: {e}")
    
    except Exception as e:
        print(f"[ERROR] ❌ get_submitted_documents: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"[INFO] 📋 ðŸ“Š Total documents found: {len(documents)}\n")
    
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
        return f"Welcome back, {name}! All your documents have been verified. Your account will be activated within 3-4 business days."

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
    """
    Process uploaded document with EID-specific validation logic + AI reasoning for failures.
    
    CORRECTED:
    - Removed generate_document_preview calls
    - Fixed return statement to use correct variables
    - Document image display happens on frontend, not backend
    - ✅ FIXED: Simple directory creation
    """
    
    MAX_RETRIES = 3
    file_path = None  # Track file path across retries
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"\n{'='*80}")
            print(f"[DEBUG] 🔍 process_uploaded_document (Attempt {attempt}/{MAX_RETRIES}):")
            print(f"  - email: {email}")
            print(f"  - filename: {uploaded_file.filename}")
            print(f"  - member_name: '{member_name}'")
            print(f"{'='*80}\n")
            
            document_id = Path(uploaded_file.filename).stem
            
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
            
            # Determine if member document
            is_member = bool(member_name and member_name.strip())
            
            print(f"[DEBUG] 🔍 is_member: {is_member}")
            
            if is_member:
                member_name_clean = member_name.strip()
                # Create base user directory first
                base_user_dir = user_docs_path(email)
                base_user_dir.mkdir(parents=True, exist_ok=True)
                
                # Then create member directory
                save_dir = base_user_dir / member_name_clean / document_id
                user_email_for_processing = f"{email}/{member_name_clean}"
                print(f"[INFO] 📋 MEMBER DOCUMENT MODE: {member_name_clean}")
            else:
                # Create base user directory
                base_user_dir = user_docs_path(email)
                base_user_dir.mkdir(parents=True, exist_ok=True)
                
                save_dir = base_user_dir / document_id
                user_email_for_processing = email
                print(f"[INFO] 📋 MAIN USER DOCUMENT MODE")
            
            # Save file only on first attempt
            if attempt == 1:
                # ✅ SIMPLE FIX: Create all parent directories
                save_dir.mkdir(parents=True, exist_ok=True)
                file_path = save_dir / uploaded_file.filename
                
                content = uploaded_file.file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                print(f"[SUCCESS] ✅ File saved: {file_path}")
                
                # ✅ VERIFY: Check file was actually saved
                if not file_path.exists():
                    raise RuntimeError(f"File not saved: {file_path}")
                if file_path.stat().st_size == 0:
                    raise RuntimeError(f"File saved but empty: {file_path}")
                    
            else:
                # File already saved, just use existing path
                if file_path and file_path.exists():
                    print(f"[INFO] 📋 Retry {attempt}, reusing file: {file_path}")
                else:
                    print(f"[ERROR] ❌ File path not found on retry attempt {attempt}")
                    raise RuntimeError("File path lost during retry")
            
            # Select model
            ext = file_path.suffix.lower()
            model_name = "meta-llama/llama-3.2-11b-vision-instruct" if ext == '.pdf' else "qwen/qwen-2.5-vl-7b-instruct"
            
            print(f"[INFO] 📋 Using model: {model_name}")
            print(f"[DEBUG] 🔍 File exists before process_document: {file_path.exists()}")
            print(f"[DEBUG] 🔍 File size: {file_path.stat().st_size if file_path.exists() else 'N/A'} bytes")
            
            # === CALL PROCESS_DOCUMENT ===
            try:
                result = process_document(
                    user_email=user_email_for_processing,
                    document_id=document_id,
                    file_path=str(file_path),
                    model_name=model_name,
                    is_member=is_member,
                )
            except RuntimeError as api_error:
                error_str = str(api_error).lower()
                is_retryable = any(code in error_str for code in ['400', '429', '502', '503', '504', 'timeout', 'connection'])
                
                print(f"[ERROR] ❌ process_document failed: {api_error}")
                print(f"[DEBUG] 🔍 Error string: {error_str}")
                print(f"[DEBUG] 🔍 Is retryable: {is_retryable}")
                
                if is_retryable and attempt < MAX_RETRIES:
                    print(f"[INFO] 📋 Retrying after API error (attempt {attempt}/{MAX_RETRIES})...")
                    import time
                    time.sleep(2)
                    continue
                else:
                    ai_reasoning = (
                        f"I encountered a technical issue while processing your document. "
                        f"Please try uploading your document again, or try a different file format (JPEG, PNG, or PDF). "
                        f"If the problem persists, contact support."
                    )
                    
                    return {
                        "success": False,
                        "message": f"Technical Error: {ai_reasoning}",
                        "document_type": "unknown",
                        "extracted_data": None,
                        "is_valid": False,
                        "ai_reasoning": ai_reasoning
                    }
            
            is_valid = result.get("is_valid", False)
            doc_type = result.get("document_type", "unknown")
            extracted_data = result.get("extracted_data") or result.get("extracted_fields", {})
            raw_text = result.get("raw_text", "")
            validation_result = result.get("validation", {})
            
            print(f"[INFO] 📋 Document processed: type={doc_type}, valid={is_valid}")
            
            # === HANDLE UNKNOWN DOCUMENT TYPE ===
            if doc_type == "unknown":
                print(f"[WARN] ⚠️ Unknown document type detected")
                
                ai_reasoning = generate_ai_reasoning_for_invalid_document(
                    raw_text=raw_text,
                    doc_type="unknown",
                    validation_result={"is_valid": False, "issues": ["Document type not recognized"]},
                    extracted_fields={},
                    expected_fields=["EID", "Commercial License", "Ejari", "MOA"],
                    member_name=member_name
                )
                
                return {
                    "success": False,
                    "message": f"Document Not Recognized\n\n{ai_reasoning}",
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False,
                    "ai_reasoning": ai_reasoning
                }
            
            # === HANDLE MEMBER DOCUMENT VALIDATION ===
            if is_member and doc_type != "eid":
                print(f"[WARN] ⚠️ Wrong document type for member (expected EID, got {doc_type})")
                
                ai_reasoning = (
                    f"I see you uploaded a {doc_type.upper()} document for {member_name}, but I need their Emirates ID (EID) instead. "
                    f"For partnership accounts, each member needs to provide their Emirates ID. "
                    f"Please upload {member_name}'s Emirates ID to continue."
                )
                
                return {
                    "success": False,
                    "message": f"Wrong Document Type\n\n{ai_reasoning}",
                    "document_type": doc_type,
                    "extracted_data": None,
                    "is_valid": False,
                    "ai_reasoning": ai_reasoning
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
                
                print(f"[DEBUG] 🔍 EID Field Check (Attempt {attempt}):")
                print(f"  - Name: '{name}' (empty: {not name})")
                print(f"  - ID Number: '{id_number}' (empty: {not id_number})")
                print(f"  - Nationality: '{nationality}' (empty: {not nationality})")
                print(f"  - DOB: '{dob}' (empty: {not dob})")
                
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
                
                print(f"[DEBUG] 🔍 Placeholder check: {is_placeholder}")
                
                if is_placeholder:
                    print(f"[WARNING] Detected placeholder/invalid EID data on attempt {attempt}")
                    
                    if attempt < MAX_RETRIES:
                        print(f"[INFO] 📋 Retrying with different model...")
                        continue
                    else:
                        print(f"[ERROR] ❌ All {MAX_RETRIES} attempts failed - EID unreadable")
                        
                        ai_reasoning = generate_ai_reasoning_for_invalid_document(
                            raw_text=raw_text,
                            doc_type="eid",
                            validation_result={"is_valid": False, "issues": ["Could not extract EID fields"]},
                            extracted_fields=extracted_data,
                            expected_fields=["Name", "ID Number", "Nationality", "DOB"],
                            member_name=member_name
                        )
                        
                        return {
                            "success": False,
                            "message": f"EID Unreadable\n\n{ai_reasoning}",
                            "document_type": doc_type,
                            "extracted_data": extracted_data,
                            "is_valid": False,
                            "ai_reasoning": ai_reasoning
                        }
                else:
                    print(f"[SUCCESS] ✅ EID data appears valid on attempt {attempt}")
                    
                    # === NAME VALIDATION ===
                    if not is_member:
                        should_validate_name = (
                            account_type == "Savings" or 
                            (account_type == "Corporate" and ownership_type == "Single Owner")
                        )
                        
                        if should_validate_name:
                            extracted_name = name.lower()
                            
                            print(f"[DEBUG] 🔍 Name Validation Check:")
                            print(f"  - Account Type: {account_type}")
                            print(f"  - Ownership: {ownership_type}")
                            print(f"  - Registered: '{user_name}'")
                            print(f"  - Extracted: '{extracted_name}'")
                            
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
                                print(f"[WARNING] Name mismatch detected")
                                
                                output_json_path = save_dir / "output.json"
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
                                        print(f"[ERROR] ❌ Failed to update output.json: {e}")
                                
                                ai_reasoning = (
                                    f"The name on your Emirates ID ({extracted_name}) doesn't match your registered name ({user_name}). "
                                    f"For security, these must match exactly. "
                                    f"Please upload the correct Emirates ID or contact support to update your registration."
                                )
                                
                                return {
                                    "success": False,
                                    "message": f"Name Mismatch\n\n{ai_reasoning}",
                                    "document_type": doc_type,
                                    "extracted_data": extracted_data,
                                    "is_valid": False,
                                    "ai_reasoning": ai_reasoning
                                }
                            else:
                                print(f"[SUCCESS] ✅ Name validation passed for EID")
            
            # === HANDLE VALIDATION FAILURE ===
            if not is_valid:
                if attempt < MAX_RETRIES:
                    print(f"[INFO] 📋 Validation failed on attempt {attempt}, retrying...")
                    continue
                else:
                    print(f"[ERROR] ❌ All {MAX_RETRIES} validation attempts exhausted")
                    
                    ai_reasoning = generate_ai_reasoning_for_invalid_document(
                        raw_text=raw_text,
                        doc_type=doc_type,
                        validation_result=validation_result,
                        extracted_fields=extracted_data,
                        expected_fields=validation_result.get('required_fields', []),
                        member_name=member_name
                    )
                    
                    return {
                        "success": False,
                        "message": f"Validation Failed\n\n{ai_reasoning}",
                        "document_type": doc_type,
                        "extracted_data": extracted_data,
                        "is_valid": False,
                        "ai_reasoning": ai_reasoning
                    }
            
            # === SUCCESS PATH ===
            print(f"[SUCCESS] ✅ Document validated successfully on attempt {attempt}")
            
            # Get extracted message with updated prompt
            message = format_extraction_message(doc_type, extracted_data, member_name.strip() if member_name else None)
            
            # NOTE: Document preview/image display happens on FRONTEND (Streamlit)
            # Backend returns file path, frontend displays the image using st.image()
            
            print(f"[INFO] 📋 Returning success response with message")
            
            # ✅ CORRECTED RETURN
            return {
                "success": True,
                "message": message,
                "document_type": doc_type,
                "extracted_data": extracted_data,
                "is_valid": True,
                "ai_reasoning": None
            }
            
        except Exception as e:
            print(f"[ERROR] ❌ Unexpected exception on attempt {attempt}: {e}")
            import traceback
            traceback.print_exc()
            
            if attempt < MAX_RETRIES:
                print(f"[INFO] 📋 Retrying after exception...")
                import time
                time.sleep(2)
                continue
            else:
                ai_reasoning = (
                    f"I encountered an unexpected error while processing your document. "
                    f"Please try uploading again, or try a different file format (JPEG, PNG, or PDF). "
                    f"If the problem persists, contact support."
                )
                
                return {
                    "success": False,
                    "message": f"Processing Error: {ai_reasoning}",
                    "document_type": "unknown",
                    "extracted_data": None,
                    "is_valid": False,
                    "ai_reasoning": ai_reasoning
                }
    
    # Fallback
    return {
        "success": False,
        "message": "Processing failed after all attempts.",
        "document_type": "unknown",
        "extracted_data": None,
        "is_valid": False
    }

def format_extraction_message(doc_type: str, extracted_data: dict, member_name: Optional[str]) -> str:
    """Format extracted data into structured conversational message for verification"""

    # ðŸ†” EMIRATES ID DETAILS
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

        msg += "### 📝 Date Information\n"
        msg += f"- **Date of Birth:** {extracted_data.get('Date of Birth') or extracted_data.get('date_of_birth', 'N/A')}\n"
        msg += f"- **Issuing Date:** {extracted_data.get('Issuing Date') or extracted_data.get('issuing_date', 'N/A')}\n"
        msg += f"- **Expiry Date:** {extracted_data.get('Expiry Date') or extracted_data.get('expiry_date', 'N/A')}\n\n"

        msg += "Please respond with a confirmation word to verify the above details."
        return msg

    # 📄¢ COMMERCIAL LICENSE DETAILS
    elif doc_type.lower() == "commercial":
        msg = "✅ Commercial License processed successfully.\n\n"
        msg += "### 📝 Company Information\n"
        
        eng = extracted_data.get("english", {})
        msg += "### 🏢­ Company Information\n"
        msg += f"- **Company Name:** {eng.get('company_name_english') or eng.get('Company Name', 'N/A')}\n"
        msg += f"- **Trade Name:** {eng.get('trade_name_english') or eng.get('Trade Name', 'N/A')}\n"
        msg += f"- **License Number:** {eng.get('license_number') or eng.get('License Number', 'N/A')}\n"
        msg += f"- **Legal Type:** {eng.get('legal_type') or eng.get('Legal Type', 'N/A')}\n"
        msg += f"- **Phone:** {eng.get('phone') or eng.get('Phone', 'N/A')}\n"
        msg += f"- **Issue Date:** {eng.get('issue_date') or eng.get('Issue Date', 'N/A')}\n"
        msg += f"- **Expiry Date:** {eng.get('expiry_date') or eng.get('Expiry Date', 'N/A')}\n"
        msg += f"- **Status:** {eng.get('status') or eng.get('Status', 'N/A')}\n\n"

        # Business Activities
        activities = extracted_data.get("activities", [])
        msg += "### Business Activities\n"
        if activities:
            for i, act in enumerate(activities, 1):
                msg += f"{i}. {act}\n"
        else:
            msg += "No activities found.\n\n"

        # Managers
        managers = extracted_data.get("managers", [])
        msg += "\n### Managers\n"
        for i, mgr in enumerate(managers, 1):
            name = mgr.get('name_english') or mgr.get('Name (EN)', 'N/A')
            role = mgr.get('role') or mgr.get('Role', 'N/A')
            nationality = mgr.get('nationality_english') or mgr.get('Nationality (EN)', 'N/A')
            msg += f"{i}. {name} ({role}) - {nationality}\n"

        # Partners / Shareholders
        partners = extracted_data.get("partners", [])
        if partners:
            msg += "\n### Partners / Shareholders\n"
            for i, p in enumerate(partners, 1):
                name = p.get('name_english') or p.get('Name (EN)', 'N/A')
                share = p.get('share') or p.get('Share', 'N/A')
                share_pct = p.get('share_percentage') or p.get('Share Percentage', 'N/A')
                msg += f"{i}. {name} - Share: {share} ({share_pct}%)\n"

        # Owner
        owner = extracted_data.get("owner", {})
        if owner:
            msg += "\n### Owner\n"
            msg += f"- **Name (EN):** {owner.get('name_english') or owner.get('Name (EN)', 'N/A')}\n"
            msg += f"- **Nationality (EN):** {owner.get('nationality_english') or owner.get('Nationality (EN)', 'N/A')}\n"
            msg += f"- **Share:** {owner.get('share') or owner.get('Share', 'N/A')}\n\n"
        
        msg += "Please respond with a confirmation word to verify the above details."
        return msg

    # 📄˜ï¸ EJARI / TENANCY DETAILS
    elif doc_type.lower() in ("ejari", "tenancy"):
        msg = f"✅ {doc_type.upper()} processed successfully.\n\n"
        msg += "### 📄  Tenancy Information\n"
        
        eng = extracted_data.get("english", {})
        msg += "### 👤 Contract Information\n"
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

        msg += "### 📌 Property Location\n"
        msg += f"- **Building Name:** {eng.get('building_name', 'N/A')}\n"
        msg += f"- **Area / Community:** {eng.get('area') or eng.get('community', 'N/A')}\n"
        msg += f"- **Emirates:** {eng.get('emirates', 'N/A')}\n\n"

        msg += "### Parties\n"
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

        
        msg += "Please respond with a confirmation word to verify the above details."
        return msg

    # 👤 MEMORANDUM OF ASSOCIATION
    elif doc_type.lower() in ("moa", "memorandum"):
        msg = "✅ Memorandum of Association processed successfully.\n\n"
        msg += "### 📋 Company Details\n"
        
        eng = extracted_data.get("english", {})
        msg += "### 🏢­ Company Information\n"
        msg += f"- **Company Name (EN):** {eng.get('company_name') or eng.get('Company Name (EN)', 'N/A')}\n"
        msg += f"- **Company Name (AR):** {eng.get('company_name_ar') or eng.get('Company Name (AR)', 'N/A')}\n"
        msg += f"- **Owner Name (EN):** {eng.get('owner_name') or eng.get('Owner Name (EN)', 'N/A')}\n"
        msg += f"- **Manager Name (EN):** {eng.get('manager_name') or eng.get('Manager Name (EN)', 'N/A')}\n"
        msg += f"- **Execution Date:** {eng.get('execution_date') or eng.get('Execution Date', 'N/A')}\n\n"

        msg += "### Share Information\n"
        msg += f"- **Number of Shares:** {eng.get('number_of_shares') or eng.get('Number of Shares', 'N/A')}\n"
        msg += f"- **Value per Share:** {eng.get('value_per_share') or eng.get('Value per Share', 'N/A')}\n"
        msg += f"- **Share Type:** {eng.get('share_type') or eng.get('Share Type', 'N/A')}\n\n"

        msg += "### Additional Information\n"
        msg += f"- **Company Duration:** {eng.get('company_duration') or eng.get('Company Duration', 'N/A')}\n"
        msg += f"- **Capital:** {eng.get('capital') or eng.get('Capital', 'N/A')}\n\n"
        
        msg += "Please respond with a confirmation word to verify the above details."
        return msg

    # Default
    else:
        return f"I've processed your {doc_type.upper()} document.\n\nPlease verify to confirm the extracted data."

# ============================================================================
# VERIFICATION HANDLING
# ============================================================================

def handle_verification_response(email: str, user_message: str, user_data: dict) -> dict:
    """
    Handle user verification with cross-validation + SurePass API validation
    ✅ Sends validation pending/failed/passed emails
    ✅ Saves validation results as JSON
    ✅ Displays results inline in chat
    ✅ Validates Emirates ID with government API (Savings & Single Owner only)
    """
    
    # ✅ UPDATED KEYWORDS: Subtle alternatives to "verified"
    verification_keywords = ["ok", "okay", "sure", "verify", "verified", "confirm", "correct", "yes", "approve", "looks good"]
    user_lower = user_message.lower().strip()
    
    is_verification = any(keyword in user_lower for keyword in verification_keywords)
    
    if not is_verification:
        return {
            "is_verification": False,
            "verified": False,
            "next_message": None,
            "is_complete": False
        }

    print(f"[DEBUG] 🔍 ✅ Verification detected from user: '{user_message}'")

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
        
        print(f"[DEBUG] 🔍 ✅ Document marked as verified:")
        print(f"  - Type: {doc_type}")
        print(f"  - Member: {latest_member_name or 'N/A (main user)'}")
        
        # ✅ CRITICAL FIX: If member EID, update progress and check completion
        if latest_member_name and doc_type.lower() == "eid":
            print(f"[INFO] 📋 👤 Member EID verified for: {latest_member_name}")
            
            progress_file = member_progress_path(email)
            if progress_file.exists():
                try:
                    with open(progress_file, "r", encoding="utf-8") as f:
                        progress_data = json.load(f)
                    
                    members = progress_data.get("members", [])
                    current_index = progress_data.get("current_index", 0)
                    
                    print(f"[DEBUG] 🔍 Member progress before update:")
                    print(f"  - Total members: {len(members)}")
                    print(f"  - Current index: {current_index}")
                    print(f"  - Current member: {members[current_index] if current_index < len(members) else 'N/A'}")
                    
                    # 🔧 CRITICAL FIX: Move to next member ONLY after verification
                    current_index += 1
                    progress_data["current_index"] = current_index
                    progress_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    
                    with open(progress_file, "w", encoding="utf-8") as f:
                        json.dump(progress_data, f, indent=2, ensure_ascii=False)
                    
                    print(f"[DEBUG] 🔍 Member progress after update:")
                    print(f"  - New current_index: {current_index}")
                    print(f"  - Next member: {members[current_index] if current_index < len(members) else 'ALL COMPLETE'}")
                    
                    # Count verified members
                    verified_count = current_index
                    total_members = len(members)
                    
                    print(f"[DEBUG] 🔍 Verification status:")
                    print(f"  - Verified: {verified_count}/{total_members}")
                    print(f"  - Is complete: {verified_count >= total_members}")
                    
                    # 🔧 CRITICAL FIX: Check if ALL members verified BEFORE declaring complete
                    if verified_count >= total_members:
                        print(f"[SUCCESS] ✅ 🎉 ALL MEMBERS VERIFIED! Running cross-validation...")
                        
                        # ============================================================================
                        # 🔍 RUN CROSS-VALIDATION BEFORE COMPLETING
                        # ============================================================================
                        try:
                            from app.services.cross_validator import CrossValidator
                            from app.services.email_sender import (
                                send_validation_pending_email,
                                send_validation_failed_email,
                                send_validation_passed_email
                            )
                            
                            validator = CrossValidator()
                            user_name = user_data.get("name", "User")
                            
                            # ✅ STEP 1: Send "Validation Pending" notification
                            print("[INFO] 📋 📧 Sending validation pending notification...")
                            send_validation_pending_email(email, user_name)
                            print("[SUCCESS] ✅ ✅ Validation pending email sent")
                            
                            # ✅ STEP 2: Run cross-validation
                            print("[INFO] 📋 🔍 Running cross-validation...")
                            validation_result = validator.validate_documents(email, user_data)
                            
                            # ✅ STEP 3: Save validation result as JSON
                            print("[INFO] 📋 💾 Saving validation result...")
                            validator.save_validation_result(email, validation_result)
                            print("[SUCCESS] ✅ ✅ Validation result saved to JSON")
                            
                            # ✅ STEP 4: Handle validation result
                            if validation_result["passed"]:
                                print("✅ [SUCCESS] Cross-validation passed!")
                                
                                # ============================================================================
                                # ✅ STEP 4A: SUREPASS API VALIDATION (Savings & Single Owner only)
                                # ============================================================================
                                print(f"\n{'='*80}")
                                print(f"🔍 [SUREPASS] Running government verification for Emirates ID...")
                                print(f"{'='*80}")
                                
                                surepass_valid, surepass_message = validate_eid_before_confirmation(email)
                                
                                if not surepass_valid:
                                    print(f"❌ ERROR: SurePass validation failed")
                                    print(f"❌ Reason: {surepass_message}")
                                    
                                    # Update next_message with failure info
                                    next_message = f"""⚠️ Verification Issue Detected

{surepass_message}

Please review your Emirates ID and re-upload if necessary. You can:
1. Reply with a corrected document
2. Upload via the Document Upload page

Our team is here to help if you need assistance."""
                                    
                                    # Failure email already sent by validate_eid_before_confirmation
                                    return {
                                        "is_verification": True,
                                        "verified": False,
                                        "next_message": next_message,
                                        "is_complete": False
                                    }
                                else:
                                    print(f"✅ SUCCESS: SurePass validation passed!")
                                    
                                    # Send success email
                                    send_validation_passed_email(email, user_name)
                                    print("[INFO] 📋 ✅ Validation success email sent")
                                    
                                    # ✅ ALL MEMBERS VERIFIED AND VALIDATION PASSED - COMPLETE!
                                    next_message = f"✅ {latest_member_name}'s EID verified!\n\n🎉 Document verification stage completed! All {total_members} member EIDs have been verified and cross-validated.\n\nYour partnership onboarding is complete! Your account will be activated within 3-4 business days."
                                    
                                    # ✅ UPDATE DATABASE TO COMPLETE
                                    update_user_onboarding_status(email, True, "onboarding_complete")
                                    
                                    # ✅ GENERATE PDF AND SEND COMPLETION EMAIL
                                    try:
                                        from llm_pipeline.handle_reply import send_completion_email
                                        account_type = user_data.get("account_type", "Corporate")
                                        print(f"[INFO] 📋 📄 Generating PDF summary and sending completion email...")
                                        send_completion_email(email, account_type)
                                        print(f"[SUCCESS] ✅ ✅ Completion email with PDF sent to {email}")
                                    except Exception as email_error:
                                        print(f"[ERROR] ❌ ❌ Failed to send completion email: {email_error}")
                                        import traceback
                                        traceback.print_exc()
                                    
                                    return {
                                        "is_verification": True,
                                        "verified": True,
                                        "next_message": next_message,
                                        "is_complete": True
                                    }
                            
                            else:
                                # ❌ CROSS-VALIDATION FAILED
                                print(f"❌ [ERROR] Cross-validation failed: {validation_result['mismatches']}")
                                
                                # Build chat message with errors
                                mismatch_details = "\n".join([f"  • {m}" for m in validation_result["mismatches"]])
                                
                                next_message = (
                                    f"⚠️ Cross-Validation Failed\n\n"
                                    f"I've detected some inconsistencies in your documents:\n\n"
                                    f"{mismatch_details}\n\n"
                                    f"Please review and re-upload the affected documents with correct information."
                                )
                                
                                # Send failure email with details
                                send_validation_failed_email(
                                    to_email=email,
                                    user_name=user_name,
                                    mismatches=validation_result["mismatches"],
                                    attempt_count=validation_result.get("attempt_count", 1)
                                )
                                print("[INFO] 📋 ✅ Validation failure email sent with detailed mismatches")
                                
                                # DO NOT mark as complete
                                return {
                                    "is_verification": True,
                                    "verified": False,
                                    "next_message": next_message,
                                    "is_complete": False
                                }
                        
                        except Exception as validation_error:
                            print(f"[ERROR] ❌ Cross-validation error: {validation_error}")
                            import traceback
                            traceback.print_exc()
                            
                            # Fallback: Show error but don't complete
                            return {
                                "is_verification": True,
                                "verified": False,
                                "next_message": f"❌ An error occurred during cross-validation: {str(validation_error)}\n\nPlease contact support.",
                                "is_complete": False
                            }
                    
                    else:
                        # More members to verify
                        next_member = members[current_index] if current_index < len(members) else None
                        
                        if next_member:
                            next_message = f"✅ {latest_member_name}'s EID verified!\n\nProgress: {verified_count}/{total_members} members completed\n\nNext, I need the Emirates ID for {next_member}.\n\nPlease upload {next_member}'s Emirates ID."
                            
                            print(f"[INFO] 📋 📤 Requesting next member EID: {next_member}")
                            
                            # ✅ UPDATE DATABASE STATUS (NOT complete yet)
                            update_user_onboarding_status(email, False, "member_eids")
                            
                            return {
                                "is_verification": True,
                                "verified": True,
                                "next_message": next_message,
                                "is_complete": False
                            }
                    
                except Exception as e:
                    print(f"[ERROR] ❌ Failed to update member progress: {e}")
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
                print("[INFO] 📋 Both Commercial and MOA verified - Extracting members!")
                
                member_data = extract_members_from_commercial(email)
                members = member_data["members"]
                
                if members and len(members) > 0:
                    save_member_progress(email, members, 0)
                    
                    # ✅ Create member folders with FIXED PATH
                    for member in members:
                        member_dir = user_docs_path(email) / member
                        member_dir.mkdir(parents=True, exist_ok=True)
                        print(f"[INFO] 📋 Created folder: {member_dir}")
                    
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
                        "is_complete": False
                    }
        
        # ============================================================================
        # 🔍 REGULAR FLOW - CHECK COMPLETION WITH CROSS-VALIDATION
        # ============================================================================
        status = get_onboarding_status(email, user_data, skip_welcome=True)
        
        if status["is_complete"]:
            print("\n🔍 [INFO] All documents submitted. Running cross-validation...")
            
            # ============================================================================
            # 🔍 CROSS-VALIDATION WITH NOTIFICATION SYSTEM
            # ============================================================================
            try:
                from app.services.cross_validator import CrossValidator
                from app.services.email_sender import (
                    send_validation_pending_email,
                    send_validation_failed_email,
                    send_validation_passed_email
                )
                
                validator = CrossValidator()
                user_name = user_data.get("name", "User")
                
                # ✅ STEP 1: Send "Validation Pending" notification (email)
                print("[INFO] 📋 📧 Sending validation pending notification...")
                send_validation_pending_email(email, user_name)
                print("[SUCCESS] ✅ ✅ Validation pending email sent")
                
                # ✅ STEP 2: Run cross-validation
                print("[INFO] 📋 🔍 Running cross-validation...")
                validation_result = validator.validate_documents(email, user_data)
                
                # ✅ STEP 3: Save validation result as JSON
                print("[INFO] 📋 💾 Saving validation result...")
                validator.save_validation_result(email, validation_result)
                print("[SUCCESS] ✅ ✅ Validation result saved to JSON")
                
                # ✅ STEP 4: Handle validation result
                if validation_result["passed"]:
                    print("✅ [SUCCESS] Cross-validation passed!")
                    
                    # ============================================================================
                    # ✅ STEP 4A: SUREPASS API VALIDATION (Savings & Single Owner only)
                    # ============================================================================
                    print(f"\n{'='*80}")
                    print(f"🔍 [SUREPASS] Running government verification for Emirates ID...")
                    print(f"{'='*80}")
                    
                    surepass_valid, surepass_message = validate_eid_before_confirmation(email)
                    
                    if not surepass_valid:
                        print(f"❌ ERROR: SurePass validation failed")
                        print(f"❌ Reason: {surepass_message}")
                        
                        # Update next_message with failure info
                        next_message = f"""⚠️ Verification Issue Detected

{surepass_message}

Please review your Emirates ID and re-upload if necessary. You can:
1. Reply with a corrected document
2. Upload via the Document Upload page

Our team is here to help if you need assistance."""
                        
                        # Failure email already sent by validate_eid_before_confirmation
                        return {
                            "is_verification": True,
                            "verified": False,
                            "next_message": next_message,
                            "is_complete": False
                        }
                    else:
                        print(f"✅ SUCCESS: SurePass validation passed!")
                        
                        # Send success email
                        send_validation_passed_email(email, user_name)
                        print("[INFO] 📋 ✅ Validation success email sent")
                        
                        # ✅ ONBOARDING COMPLETE
                        next_message = f"✅ {doc_type.upper()} verified!\n\n🎉 Document verification stage completed! All your documents have been cross-validated and verified.\n\nYour account will be activated within 3-4 business days."
                        
                        # ✅ UPDATE DATABASE TO COMPLETE
                        update_user_onboarding_status(email, True, "onboarding_complete")
                        
                        # ✅ GENERATE PDF AND SEND COMPLETION EMAIL
                        try:
                            from llm_pipeline.handle_reply import send_completion_email
                            account_type = user_data.get("account_type", "")
                            print(f"[INFO] 📋 📄 Generating PDF summary and sending completion email...")
                            send_completion_email(email, account_type)
                            print(f"[SUCCESS] ✅ ✅ Completion email with PDF sent to {email}")
                        except Exception as email_error:
                            print(f"[ERROR] ❌ ❌ Failed to send completion email: {email_error}")
                            import traceback
                            traceback.print_exc()
                        
                        return {
                            "is_verification": True,
                            "verified": True,
                            "next_message": next_message,
                            "is_complete": True
                        }
                
                else:
                    # ❌ CROSS-VALIDATION FAILED
                    print(f"❌ [ERROR] Cross-validation failed")
                    print(f"Mismatches: {validation_result['mismatches']}")
                    
                    # Build chat message with errors
                    mismatch_details = "\n".join([f"  • {m}" for m in validation_result["mismatches"]])
                    
                    next_message = (
                        f"⚠️ Cross-Validation Failed\n\n"
                        f"I've detected some inconsistencies in your documents:\n\n"
                        f"{mismatch_details}\n\n"
                        f"Please review and re-upload the affected documents with correct information."
                    )
                    
                    # Send failure email with details
                    send_validation_failed_email(
                        to_email=email,
                        user_name=user_name,
                        mismatches=validation_result["mismatches"],
                        attempt_count=validation_result.get("attempt_count", 1)
                    )
                    print("[INFO] 📋 ✅ Validation failure email sent with detailed mismatches")
                    
                    # DO NOT mark as complete
                    return {
                        "is_verification": True,
                        "verified": False,
                        "next_message": next_message,
                        "is_complete": False
                    }
            
            except Exception as validation_error:
                print(f"[ERROR] ❌ Cross-validation system error: {validation_error}")
                import traceback
                traceback.print_exc()
                
                # Fallback: Proceed without cross-validation (with warning)
                print("[WARN] ⚠️ Proceeding without cross-validation due to system error")
                
                next_message = f"✅ {doc_type.upper()} verified!\n\n🎉 Document verification stage completed!\n\nYour account will be activated within 3-4 business days."
                
                update_user_onboarding_status(email, True, "onboarding_complete")
                
                try:
                    from llm_pipeline.handle_reply import send_completion_email
                    account_type = user_data.get("account_type", "")
                    send_completion_email(email, account_type)
                    print(f"[INFO] 📋 Completion email sent (without cross-validation)")
                except Exception as email_error:
                    print(f"[ERROR] ❌ Failed to send completion email: {email_error}")
                
                return {
                    "is_verification": True,
                    "verified": True,
                    "next_message": next_message,
                    "is_complete": True
                }
        
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
        print(f"[ERROR] ❌ handle_verification_response: {e}")
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
# CONVERSATION LOG HELPER - WITH CHANNEL SUPPORT
# ============================================================================



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
    
    # ✅ FIXED: Add channel parameter
    try:
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=status["ai_message"],
            channel="chat"  # ✅ ADDED
        )
    except Exception as e:
        print(f"[WARN] ⚠️ Could not log conversation: {e}")
    
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
    """Upload document conversationally with proper conversation logging"""
    
    # DEBUG LOGGING
    print(f"\n{'='*80}")
    print(f"[DEBUG] 🔍 upload_conversational endpoint called")
    print(f"[DEBUG] 🔍 email: {email}")
    print(f"[DEBUG] 🔍 member_name received: '{member_name}'")
    print(f"{'='*80}\n")
    
    # Get user data
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not files:
        raise HTTPException(status_code=400, detail="No file provided")
    
    uploaded_file = files[0]
    user_name = user.get("name", "User")
    
    # Clean and validate member_name
    clean_member_name = None
    doc_stage = user.get("document_stage", "identification")
    ownership = user.get("ownership_type")
    
    if member_name is not None and member_name.strip():
        clean_member_name = member_name.strip()
        print(f"[INFO] 📋 ✅ Explicit member name provided: '{clean_member_name}'")
        
    elif (ownership in ["Partnership", "Multiple Owners"] and 
          doc_stage == "member_eids" and
          uploaded_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf'))):
        print(f"[INFO] 📋 Auto-detecting member mode...")
        mp = load_member_progress(email)
        if mp:
            members = mp.get("members", [])
            current_idx = mp.get("current_index", 0)
            if current_idx < len(members):
                clean_member_name = members[current_idx]
                print(f"[INFO] 📋 ✅ Auto-detected member: '{clean_member_name}'")
    else:
        print(f"[INFO] 📋 Processing as main user document")
    
    # ============================================================================
    # STEP 1: Process document to detect its type
    # ============================================================================
    result = process_uploaded_document(email, uploaded_file, clean_member_name)
    
    # ============================================================================
    # SECTION 1: If processing failed (unknown doc, technical error)
    # ============================================================================
    if not result["success"] or result["document_type"] == "unknown":
        # ✅ SEND ERROR EMAIL FOR UNKNOWN/FAILED DOCUMENTS
        print(f"📧 [INFO] Sending error email for unknown/failed document...")
        try:
            from app.services.email_sender import send_document_verification_email
            
            ai_reasoning = result.get("ai_reasoning") or result.get("message") or "Document could not be processed or identified"
            
            send_document_verification_email(
                to_email=email,
                user_name=user_name,
                document_type=result.get("document_type", "Unknown").upper(),
                status="error",
                filename=uploaded_file.filename,
                reason=ai_reasoning,
                extracted_data=None,
                member_name=clean_member_name
            )
            print(f"[SUCCESS] ✅ Error email sent for unknown document")
        except Exception as email_error:
            print(f"[WARN] ⚠️ Failed to send error email: {email_error}")
            import traceback
            traceback.print_exc()
        
        # ✅ FIXED: Add channel parameter to logging
        try:
            insert_conversation_log(
                user_email=email,
                role="agent",
                message=result["message"],
                channel="chat"  # ✅ ADDED
            )
        except Exception as e:
            print(f"[WARN] ⚠️ Failed to log conversation: {e}")
        
        return {
            "success": False,
            "message": result["message"],
            "document_type": result.get("document_type", "unknown"),
            "extracted_data": None,
            "is_valid": False,
            "is_complete": False,
            "awaiting_verification": False,
            "document_file_path": None,
            "wrong_document_type": False
        }
    
    # ============================================================================
    # STEP 2: VALIDATE DOCUMENT TYPE AGAINST ACCOUNT REQUIREMENTS
    # ============================================================================
    doc_type = result["document_type"]
    document_id = Path(uploaded_file.filename).stem
    
    print(f"[INFO] 📋 Validating document type: {doc_type}")
    
    is_valid_type, error_message, allowed_info = validate_document_type_for_account(
        email=email,
        doc_type=doc_type,
        user_data=user,
        member_name=clean_member_name
    )
    
    # ============================================================================
    # SECTION 2: HANDLE WRONG DOCUMENT TYPE (WITH DYNAMIC RESPONSE)
    # ============================================================================
    if not is_valid_type:
        print(f"[ERROR] ❌ Wrong document type detected: {doc_type}")
        
        # Delete the document
        deleted = delete_invalid_document(
            email=email,
            document_id=document_id,
            doc_type=doc_type,
            member_name=clean_member_name
        )
        
        if deleted:
            print(f"[SUCCESS] ✅ Invalid document deleted")
        
        # ✅ GENERATE DYNAMIC ERROR MESSAGE WITH REMAINING DOCS
        dynamic_error_message = generate_dynamic_invalid_document_response(
            uploaded_doc_type=doc_type,
            allowed_info=allowed_info,
            email=email,
            user_data=user,
            member_name=clean_member_name
        )
        
        # ✅ SEND DYNAMIC EMAIL WITH REMAINING DOCS
        send_wrong_document_type_email_dynamic(
            to_email=email,
            user_name=user_name,
            uploaded_doc_type=doc_type,
            allowed_info=allowed_info,
            email=email,
            user_data=user,
            member_name=clean_member_name
        )
        print(f"[INFO] 📋 ✅ Dynamic wrong document email sent")
        
        # ✅ FIXED: Add channel parameter to logging
        try:
            insert_conversation_log(
                user_email=email,
                role="user",
                message=f"Uploaded: {uploaded_file.filename} ({doc_type.upper()})",
                channel="chat"  # ✅ ADDED
            )
            
            insert_conversation_log(
                user_email=email,
                role="agent",
                message=dynamic_error_message,
                channel="chat"  # ✅ ADDED
            )
        except Exception as e:
            print(f"[WARN] ⚠️ Failed to log conversation: {e}")
        
        # Get remaining docs for response
        remaining_docs = get_remaining_required_documents(email, user)
        
        # Return error
        return {
            "success": False,
            "message": dynamic_error_message,
            "document_type": doc_type,
            "extracted_data": None,
            "is_valid": False,
            "is_complete": False,
            "awaiting_verification": False,
            "wrong_document_type": True,
            "document_deleted": deleted,
            "required_documents": allowed_info["required_docs"],
            "remaining_documents": remaining_docs,
            "document_file_path": None
        }
    
    # ============================================================================
    # STEP 4: CORRECT DOCUMENT TYPE - CONTINUE WITH DYNAMIC RESPONSES
    # ============================================================================
    print(f"[SUCCESS] ✅ Correct document type: {doc_type}")
    
    # Calculate file path
    if clean_member_name:
        file_path = f"backend/documents/id/{email}/{clean_member_name}/{document_id}/{uploaded_file.filename}"
    else:
        file_path = f"backend/documents/id/{email}/{document_id}/{uploaded_file.filename}"
    
    # ✅ GENERATE DYNAMIC ACKNOWLEDGMENT FOR VALID DOCUMENT
    dynamic_acknowledgment = generate_dynamic_valid_document_response(
        doc_type=doc_type,
        email=email,
        user_data=user,
        member_name=clean_member_name
    )
    
    # ============================================================================
    # 📧 SEND EMAIL BASED ON VALIDATION RESULT
    # ============================================================================
    if result["success"] and result["is_valid"]:
        # ✅ VALID DOCUMENT - No email sent (wait for confirmation)
        print(f"[INFO] 📋 ✅ Valid document processed - waiting for user confirmation (no email yet)")
    else:
        # ❌ INVALID DOCUMENT - Send error email with AI reasoning
        print(f"📧 [INFO] Sending error email for invalid document...")
        try:
            from app.services.email_sender import send_document_verification_email
            
            # Get remaining documents
            remaining_docs = get_remaining_required_documents(email, user)
            
            # Get AI reasoning from result
            ai_reasoning = result.get("ai_reasoning") or result.get("message") or "Document validation failed"
            
            # Send detailed error email
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
        except Exception as email_error:
            print(f"[WARN] ⚠️ Failed to send error email: {email_error}")
            import traceback
            traceback.print_exc()
    
    # ============================================================================
    # CHECK FOR STAGE TRANSITIONS
    # ============================================================================
    status = get_onboarding_status(email, user, skip_welcome=True)
    
    # Check for stage transition (identification -> member_eids)
    if status["stage"] == "member_eids" and user.get("document_stage") == "identification":
        print(f"[INFO] 📋 Stage transition detected: identification -> member_eids")
        
        member_data = extract_members_from_commercial(email)
        members = member_data.get("members", [])
        
        if members:
            save_member_progress(email, members, 0)
            
            for member in members:
                member_dir = user_docs_path(email) / member
                member_dir.mkdir(parents=True, exist_ok=True)
                print(f"[INFO] 📋 Created member folder: {member_dir}")
            
            update_user_onboarding_status(email, False, "member_eids")
            print(f"[INFO] 📋 Database updated to member_eids stage")
            
            status = get_onboarding_status(email, user, skip_welcome=True)
    
    # ============================================================================
    # SECTION 3: BUILD RESPONSE AND LOG SUCCESS
    # ============================================================================
    complete_message = f"{dynamic_acknowledgment}\n\n{result['message']}"
    
    # ✅ FIXED: Add channel parameter to logging
    try:
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=complete_message,
            channel="chat"  # ✅ ADDED
        )
        print(f"[INFO] 📋 Conversation logged")
    except Exception as e:
        print(f"[WARN] ⚠️ Failed to log conversation: {e}")
    
    # Determine if onboarding is complete
    is_complete = status.get("is_complete", False)
    
    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user)
    
    # ✅ RETURN SUCCESS RESPONSE
    return {
        "success": result["success"],
        "message": complete_message,
        "acknowledgment": dynamic_acknowledgment,
        "document_type": result["document_type"],
        "extracted_data": result.get("extracted_data"),
        "is_valid": result.get("is_valid", False),
        "is_complete": is_complete,
        "awaiting_verification": result["is_valid"],
        "document_file_path": file_path,
        "next_document": status.get("next_required_document"),
        "remaining_documents": remaining_docs,
        "wrong_document_type": False
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
        response = verification["next_message"]
        
        # ✅ FIXED: Add channel parameter to logging
        try:
            ts = datetime.now(timezone.utc)
            insert_conversation_log(
                user_email=email,
                role="user",
                message=request.message,
                channel="chat"  # ✅ ADDED
            )
            insert_conversation_log(
                user_email=email,
                role="agent",
                message=response,
                channel="chat"  # ✅ ADDED
            )
        except Exception as e:
            print(f"[WARN] ⚠️ Could not log conversation: {e}")
        
        return {
            "response": response,
            "verification_accepted": verification["verified"],
            "is_complete": verification.get("is_complete", False)
        }
    
    # Regular chat query
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
        print(f"[ERROR] ❌ LLM: {e}")
        answer = "Sorry, I'm having trouble answering right now. Please try uploading your documents or ask me again."
    
    # ✅ FIXED: Add channel parameter to logging
    try:
        ts = datetime.now(timezone.utc)
        insert_conversation_log(
            user_email=email,
            role="user",
            message=request.message,
            channel="chat"  # ✅ ADDED
        )
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=answer,
            channel="chat"  # ✅ ADDED
        )
    except Exception as e:
        print(f"[WARN] ⚠️ Could not log conversation: {e}")
    
    return {
        "response": answer,
        "verification_accepted": False,
        "is_complete": status["is_complete"]
    }
    
@router.get("/conversation-logs/{email}")
async def get_conversation_logs(email: str, limit: int = 20, channel: str = "chat"):
    """
    Get conversation history filtered by channel
    channel: 'chat', 'email', or 'all' (default: 'chat')
    """
    try:
        query = (
            supabase.table("conversations")
            .select("*")
            .eq("user_email", email)
        )
        
        # Filter by channel if specified
        if channel != "all":
            query = query.eq("channel", channel)
        
        response = (
            query
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        
        logs = response.data if response.data else []
        
        return {
            "email": email,
            "channel": channel,
            "logs": logs,
            "count": len(logs)
        }
    except Exception as e:
        print(f"[ERROR] ❌ get_conversation_logs: {e}")
        return {
            "email": email,
            "channel": channel,
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

def generate_ai_reasoning_for_invalid_document(
    raw_text: str,
    doc_type: str,
    validation_result: dict,
    extracted_fields: dict = None,
    expected_fields: list = None,
    member_name: str = None
) -> str:
    try:
        from llm_runner.run_model import call_local_llm
        
        print(f"[INFO] 📋 ðŸ¤– Generating AI reasoning for invalid {doc_type} document")
        
        # Build comprehensive context for LLM
        context_parts = []
        
        # 1. Document Type and Member Context
        if member_name:
            context_parts.append(f"Document Type: {doc_type.upper()} for member '{member_name}'")
        else:
            context_parts.append(f"Document Type: {doc_type.upper()}")
        
        # 2. Extracted Text Sample (first 1500 chars)
        text_sample = raw_text[:1500] if len(raw_text) > 1500 else raw_text
        context_parts.append(f"\n=== EXTRACTED TEXT FROM DOCUMENT ===\n{text_sample}")
        
        # 3. Validation Results
        if validation_result:
            context_parts.append("\n=== VALIDATION RESULTS ===")
            context_parts.append(f"Valid: {validation_result.get('is_valid', False)}")
            
            missing = validation_result.get('missing_fields', [])
            if missing:
                context_parts.append(f"Missing Required Fields: {', '.join(missing)}")
            
            issues = validation_result.get('issues', [])
            if issues:
                context_parts.append(f"Issues Found: {', '.join(issues)}")
            
            present = validation_result.get('present_fields', [])
            if present:
                context_parts.append(f"Fields Present: {', '.join(present)}")
            
            # Include validation reason if available
            val_reason = validation_result.get('validation_reason', '')
            if val_reason:
                context_parts.append(f"Validation Reason: {val_reason}")
        
        # 4. Extracted vs Expected Fields Comparison
        if extracted_fields:
            context_parts.append("\n=== EXTRACTED FIELDS ===")
            for key, value in extracted_fields.items():
                if isinstance(value, dict):
                    context_parts.append(f"{key}:")
                    for sub_key, sub_value in value.items():
                        context_parts.append(f"  - {sub_key}: {sub_value}")
                else:
                    context_parts.append(f"{key}: {value}")
        
        if expected_fields:
            context_parts.append(f"\n=== EXPECTED FIELDS ===\n{', '.join(expected_fields)}")
        
        # Build the full context
        full_context = "\n".join(context_parts)
        
        # Create LLM prompt
        prompt = f"""You are a helpful document verification assistant speaking directly to a user in a chat conversation. A user uploaded a {doc_type.upper()} document that failed validation.

{full_context}

Based on the validation logs above, provide a clear, friendly, and conversational explanation of why this document is invalid. Your response should:

1. Be written in first person as if you're talking directly to the user in a chat
2. Identify the specific issues (missing fields, incorrect format, unreadable sections, etc.)
3. Explain what was expected vs what was found
4. Provide actionable guidance on what the user needs to do to fix the issue
5. Be empathetic, professional, and encouraging in tone
6. Keep it concise (3-5 sentences) and easy to understand

Format your response as conversational chat message. DO NOT use bullet points or lists. Write in natural, flowing sentences.

Example good responses:
- "I analyzed your EID document but couldn't extract some critical information. Specifically, the ID Number and Expiry Date fields are missing or unclear. This usually happens when the document image is blurry or partially obscured. Please upload a clear, well-lit photo of your complete EID with all text clearly visible."
- "I had trouble processing your Commercial License. The license number and company name couldn't be read properly from the image. This typically occurs with low-quality scans or photos taken at an angle. Could you please upload a clearer, straight-on photo of your license?"
- "Your Ejari document appears to be incomplete. I couldn't find the contract number and tenant information which are required fields. Please make sure you upload the complete Ejari certificate with all pages visible and readable."

Now generate your response for this user:"""

        # Call LLM to generate reasoning
        reasoning = call_local_llm(prompt)
        
        # Clean up the response
        reasoning = reasoning.strip()
        
        # Validate response quality
        if not reasoning or len(reasoning) < 50:
            print("[WARN] ⚠️ LLM returned poor response, using fallback")
            reasoning = generate_fallback_reasoning_chat(doc_type, validation_result, member_name)
        
        print(f"[SUCCESS] ✅ AI reasoning generated: {len(reasoning)} characters")
        return reasoning
        
    except Exception as e:
        print(f"[ERROR] ❌ Failed to generate AI reasoning: {e}")
        import traceback
        traceback.print_exc()
        return generate_fallback_reasoning_chat(doc_type, validation_result, member_name)


def generate_fallback_reasoning_chat(
    doc_type: str, 
    validation_result: dict = None, 
    member_name: str = None
) -> str:
    """
    Generate fallback reasoning if LLM fails.
    Provides conversational explanation based on validation data.
    """
    member_context = f" for {member_name}" if member_name else ""
    
    missing = []
    if validation_result:
        missing = validation_result.get('missing_fields', [])
    
    if missing:
        fields_list = ', '.join(missing)
        return (
            f"I had trouble validating your {doc_type.upper()} document{member_context}. "
            f"The following required fields are missing or unclear: {fields_list}. "
            f"This usually happens when the document image is low quality or parts are cut off. "
            f"Please upload a clear, complete photo of your {doc_type.upper()} with all information visible and readable."
        )
    else:
        return (
            f"I couldn't validate your {doc_type.upper()} document{member_context}. "
            f"This may be due to poor image quality, incorrect document format, or missing required information. "
            f"Please ensure you upload a clear, high-quality scan or photo of the correct {doc_type.upper()} document."
        )


# ============================================================================
# Enhanced Email Function with AI Reasoning
# ============================================================================

def send_ai_reasoning_email(
    to_email: str, 
    user_name: str,
    filename: str,
    doc_type: str, 
    ai_reasoning: str,
    member_name: str = None
):
    """
    Send email with AI-generated reasoning for invalid document.
    Enhanced version that includes detailed AI analysis.
    """
    member_context = f" for member {member_name}" if member_name else ""
    subject = f"Document Processing Issue - {doc_type.upper()}{member_context}"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: #dc3545; color: white; padding: 30px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 28px; }}
            .content {{ padding: 30px; line-height: 1.6; }}
            .reasoning-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .reasoning-box h3 {{ margin: 0 0 15px 0; color: #856404; font-size: 18px; }}
            .reasoning-box p {{ margin: 0; color: #856404; font-size: 15px; }}
            .action-box {{ background: #e7f3ff; border-left: 4px solid #2196F3; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .action-box h3 {{ margin: 0 0 15px 0; color: #0c5460; font-size: 18px; }}
            .action-box ul {{ margin: 10px 0; padding-left: 20px; }}
            .action-box li {{ margin: 8px 0; color: #0c5460; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            .document-info {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📄 Document Validation Issue</h1>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                <p>We encountered an issue while processing your document.</p>
                
                <div class="document-info">
                    <strong>📋 Document:</strong> {filename}<br>
                    <strong>📄 Type:</strong> {doc_type.upper()}{f"<br><strong>👤Member:</strong> {member_name}" if member_name else ""}
                </div>
                
                <div class="reasoning-box">
                    <h3>🔍 Analysis Results</h3>
                    <p>{ai_reasoning}</p>
                </div>
                
                <div class="action-box">
                    <h3>👤 What to do next:</h3>
                    <ul>
                        <li><strong>Take a clear photo:</strong> Ensure good lighting and all text is visible</li>
                        <li><strong>Avoid glare:</strong> Make sure there are no reflections or shadows</li>
                        <li><strong>Capture the entire document:</strong> Don't crop out any important information</li>
                        <li><strong>Use high resolution:</strong> Avoid blurry or pixelated images</li>
                        <li><strong>Keep it flat:</strong> Place the document on a flat surface for best results</li>
                    </ul>
                </div>
                
                <p style="margin-top: 25px;">You can re-upload the corrected document through the chat interface or by replying to this email with the document attached.</p>
                
                <p style="margin-top: 25px; color: #666;">If you need any assistance or have questions, feel free to reply to this email. Our team is here to help!</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">Thrivv Onboarding Team</p>
                <p style="margin: 5px 0 0 0; font-size: 14px;">Automated Document Verification System</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[SUCCESS] ✅ AI reasoning email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send AI reasoning email: {e}")


def log_document_processing_to_conversation(
    email: str,
    filename: str,
    doc_type: str,
    is_valid: bool,
    ai_reasoning: str = None,
    channel: str = "chat"  # ✅ Already has channel parameter
):
    """
    Log document processing results to conversation table with AI reasoning.
    This creates a conversational record of the validation attempt.
    """
    try:
        timestamp = datetime.now(timezone.utc)
        
        # User message (upload action)
        user_message = f"📋 Uploaded document: {filename} ({doc_type.upper()})"
        insert_conversation_log(
            user_email=email,
            role="user",
            message=user_message,
            channel=channel  # ✅ Pass through channel
        )
        
        # Agent response (validation result)
        if is_valid:
            agent_message = f"✅ {doc_type.upper()} validated successfully!"
        else:
            if ai_reasoning:
                agent_message = f"❌ Validation failed for {doc_type.upper()}\n\n{ai_reasoning}"
            else:
                agent_message = f"❌ Failed to validate {doc_type.upper()} document"
        
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=agent_message,
            channel=channel  # ✅ Pass through channel
        )
        
        print(f"[INFO] 📋 Document processing logged to conversation history")
        
    except Exception as e:
        print(f"[ERROR] ❌ Failed to log to conversation: {e}")
       
@router.get("/get-conversations/{user_email}")
async def get_conversations(user_email: str):
    """
    Retrieve all chat conversations for a user
    """
    try:
        result = supabase.table("conversations").select("*").eq(
            "user_email", user_email
        ).order("timestamp", desc=False).execute()
        
        return {
            "conversations": result.data if result.data else [],
            "count": len(result.data) if result.data else 0
        }
    except Exception as e:
        print(f"[ERROR] Get conversations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# Export router
__all__ = ["router"]