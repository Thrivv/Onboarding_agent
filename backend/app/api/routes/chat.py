# app/api/routes/chat.py
import asyncio  # BUGFIX: used by upload_documents() but was never imported
import os
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from typing import List
from fastapi.responses import HTMLResponse
from email.utils import formataddr

from app.services.supabase_client import supabase
# See the note in handle_reply.py: the documents root is {DOCUMENTS_PATH}/{ref_no},
# not the email-keyed relative path this module used to build by hand.
from app.services.chatupload_helpers import user_docs_path
from app.services.ocr_service import process_document
from app.services.email_sender import send_email
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.chat import UserVerifyRequest, ResumeRequest
from app.domain.exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# MODELS
# ============================================================================


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_by_email(email: str) -> dict:
    """Get user from database"""
    try:
        response = UserRepository.get_by_email(email)
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return None

# NOTE (prompt-remediation Phase 4): build_chat_prompt() used to live here --
# confirmed dead (defined, never called anywhere in the codebase) and removed.
# Prompt-building for the actual conversation pipeline the frontend calls
# (/chatupload/chat-conversational in conversation.py) lives in
# message_generator.py / run_model.py, not in this module.

def check_documents_status(email: str) -> dict:
    """Check current document status for user"""
    user_docs_dir = str(user_docs_path(email))
    status = {
        "commercial": False,
        "eid": False,
        "tenancy": False,
        "moa": False,
        "total_documents": 0
    }
    
    if not os.path.exists(user_docs_dir):
        return status
    
    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)
        if os.path.isdir(item_path):
            output_path = os.path.join(item_path, "output.json")
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    doc_type = analysis.get("document_type", "unknown").lower().strip()
                    is_valid = analysis.get("is_valid", False)

                    # ✅ FIX C: Normalize aliases before checking
                    if doc_type in ["ejari", "tenancy", "tenancy contract"]:
                        doc_type = "tenancy"    # canonical key in THIS function's status dict
                    elif doc_type in ["memorandum", "memorandum of association"]:
                        doc_type = "moa"
                    elif doc_type in ["emirates id", "emirates_id", "identity card"]:
                        doc_type = "eid"

                    if is_valid and doc_type in ["commercial", "eid", "tenancy", "moa"]:
                        status[doc_type] = True
                        status["total_documents"] += 1
                except:
                    pass
    
    return status

def process_single_document(email: str, filename: str, file_path: str, model_name: str = None) -> dict:
    """Process a single document and return result"""
    document_id = os.path.splitext(filename)[0]
    
    try:
        logger.info(f"Processing: {filename}")
        analysis = process_document(email, document_id, file_path, model_name=model_name)
        
        doc_type = analysis.get("document_type", "unknown")
        is_valid = analysis.get("is_valid", False)
        
        if is_valid:
            return {
                "filename": filename,
                "status": "success",
                "summary": f"{doc_type.upper()} verified successfully",
                "document_type": doc_type
            }
        elif doc_type == "unknown":
            return {
                "filename": filename,
                "status": "error",
                "summary": "Document type not recognized",
                "document_type": doc_type
            }
        else:
            missing_fields = analysis.get("validation", {}).get("missing_fields", [])
            if missing_fields:
                return {
                    "filename": filename,
                    "status": "warning",
                    "summary": f"âš ï¸ {doc_type.upper()} incomplete. Missing: {', '.join(missing_fields[:3])}",
                    "document_type": doc_type
                }
            else:
                return {
                    "filename": filename,
                    "status": "warning",
                    "summary": f"âš ï¸ {doc_type.upper()} needs review",
                    "document_type": doc_type
                }
    except Exception as e:
        logger.error(f"Processing failed for {filename}: {e}")
        return {
            "filename": filename,
            "status": "error",
            "summary": f"âŒ Processing failed: {str(e)}"
        }

async def send_results_email(email: str, user_name: str, results: list, doc_status: dict):
    """Send email notification in background"""
    try:
        subject = "Document Upload - Processing Results"
        
        results_html = ""
        for result in results:
            status = result.get("status", "unknown")
            if status == "success":
                color = "#28a745"
                icon = "âœ…"
            elif status == "warning":
                color = "#ffc107"
                icon = "âš ï¸"
            else:
                color = "#dc3545"
                icon = "âŒ"
            
            results_html += f"""
            <div style="padding: 10px; margin: 8px 0; border-left: 4px solid {color}; background: #f8f9fa;">
                <strong>{icon} {result.get('filename', 'Unknown')}</strong><br>
                {result.get('summary', '')}
            </div>
            """
        
        missing_docs = []
        if not doc_status["commercial"]:
            missing_docs.append("Commercial Registration")
        if not doc_status["eid"]:
            missing_docs.append("Emirates ID (EID)")
        if not doc_status["tenancy"]:
            missing_docs.append("Tenancy Contract (Ejari)")
        if not doc_status["moa"]:
            missing_docs.append("Memorandum of Association (MOA)")
        
        status_html = f"""
        <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <h3 style="color: #1976d2; margin-top: 0;">ðŸ“Š Overall Status</h3>
            <p><strong>{doc_status['total_documents']} out of 4</strong> required documents verified</p>
            {f"<p><strong>Still needed:</strong> {', '.join(missing_docs)}</p>" if missing_docs else "<p style='color: #28a745;'><strong>âœ… All documents received!</strong></p>"}
        </div>
        """
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee;">
                <h2 style="color: #4CAF50;">Document Processing Results</h2>
                <p>Dear {user_name},</p>
                <p>We have processed your uploaded documents. Here are the results:</p>
                
                {results_html}
                
                {status_html}
                
                <p>If you need to upload additional documents, please log in to your account and use the document upload feature.</p>
                
                <p style="margin-top: 32px;">Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
            </div>
        </body>
        </html>
        """
        
        send_email(to_email=email, subject=subject, body=body_html, html=True)
        logger.info(f"Email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/verify-user")
def verify_user_email(request: UserVerifyRequest):
    """Verify if user email exists in database"""
    try:
        user = get_user_by_email(request.email)
        if not user:
            raise NotFoundError("User not found. Please register first.")
        
        return {
            "message": "User verified", 
            "user_name": user.get("name", "User"),
            "onboarding_step": user.get("onboarding_step", "welcome")
        }
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"User verification error: {e}")
        raise DomainError(context=str(e))

# NOTE (prompt-remediation Phase 4): POST /chat (chat_with_bot, delegated to
# onboarding_chat_service.generate_chat_response) and GET /chat-history/{email}
# (get_chat_history_by_email, delegated to onboarding_chat_service.
# get_chat_history_for_user) used to live here. Removed: confirmed via a
# repo-wide grep of frontend/src that neither route is called anywhere --
# the frontend's chat UI talks exclusively to /chatupload/chat-conversational
# and /chatupload/conversation-logs/{email} in conversation.py, which is the
# one actual conversation pipeline. onboarding_chat_service.py (only ever
# imported from these two now-removed routes) was deleted alongside this.

@router.post("/upload-documents")
async def upload_documents(
    email: str, 
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    Handle document upload from Streamlit with optimized processing
    Returns immediately with processing status, sends email in background
    """
    try:
        logger.info(f"Document upload request for: {email}")
        
        # Verify user exists
        user = get_user_by_email(email)
        if not user:
            raise NotFoundError("User not found")
        
        # Validate files
        if not files:
            raise ValidationError("No files uploaded")
        
        # Prepare save directory
        save_dir = str(user_docs_path(email))
        os.makedirs(save_dir, exist_ok=True)
        
        # Save files first (fast operation)
        files_saved = []
        supported_extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".pdf", ".doc", ".docx", ".txt"]
        
        for file in files:
            if file.filename:
                file_ext = os.path.splitext(file.filename)[1].lower()
                if file_ext in supported_extensions:
                    try:
                        file_content = await file.read()
                        filepath = os.path.join(save_dir, file.filename)
                        
                        with open(filepath, "wb") as f:
                            f.write(file_content)
                        
                        files_saved.append(file.filename)
                        logger.info(f"Saved: {file.filename} ({len(file_content)} bytes)")
                    except Exception as e:
                        logger.error(f"Failed to save {file.filename}: {e}")
        
        if not files_saved:
            raise ValidationError("No valid files could be saved")
        
        # Process documents with reduced delays
        # Model selection is handled automatically inside process_document
        # based on doc_type (vision for EID/Passport, text for all others)
        results = []

        for idx, filename in enumerate(files_saved):
            file_path = os.path.join(save_dir, filename)

            # Process document — model_name=None triggers auto-selection
            result = process_single_document(email, filename, file_path, model_name=None)
            results.append(result)

            # Reduced delay - only between documents, not after last one
            if idx < len(files_saved) - 1:
                await asyncio.sleep(1)  # â† REDUCED FROM 3 to 1 second
                logger.info(f"Waiting 1 second before processing next document...")
        
        # Check overall status
        doc_status = check_documents_status(email)
        
        # Send email in background (async)
        if background_tasks:
            background_tasks.add_task(
                send_results_email, 
                email, 
                user.get('name', 'User'), 
                results, 
                doc_status
            )
        else:
            # Fallback: send synchronously if background tasks not available
            await send_results_email(email, user.get('name', 'User'), results, doc_status)
        
        return {
            "results": results,
            "email_sent": True,
            "status": "success",
            "message": f"Processed {len(results)} documents",
            "document_status": doc_status
        }
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Document upload error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=f"Upload failed: {str(e)}")

@router.get("/document-status/{email}")
def get_document_status(email: str):
    """Get current document status for user"""
    try:
        user = get_user_by_email(email)
        if not user:
            raise NotFoundError("User not found")
        
        user_docs_dir = str(user_docs_path(email))
        documents = []
        
        if os.path.exists(user_docs_dir):
            for item in os.listdir(user_docs_dir):
                item_path = os.path.join(user_docs_dir, item)
                if os.path.isdir(item_path):
                    output_path = os.path.join(item_path, "output.json")
                    if os.path.exists(output_path):
                        try:
                            with open(output_path, "r", encoding="utf-8") as f:
                                analysis = json.load(f)
                            
                            doc_type = analysis.get("document_type", "unknown")
                            is_valid = analysis.get("is_valid", False)
                            
                            if is_valid:
                                status = "valid"
                                summary = f"{doc_type.title()} document verified successfully"
                            elif doc_type == "unknown":
                                status = "invalid"
                                summary = "âŒ Document type not recognized"
                            else:
                                status = "warning"
                                missing_fields = analysis.get("validation", {}).get("missing_fields", [])
                                if missing_fields:
                                    summary = f"âš ï¸ {doc_type.title()} document incomplete. Missing: {', '.join(missing_fields[:3])}"
                                else:
                                    summary = f"âš ï¸ {doc_type.title()} document needs review"
                            
                            documents.append({
                                "filename": analysis.get("filename", item),
                                "document_type": doc_type,
                                "status": status,
                                "extracted_fields": analysis.get("extracted_fields", {}),
                                "validation": analysis.get("validation", {}),
                                "summary": summary
                            })
                        except Exception as e:
                            logger.error(f"Failed to read analysis for {item}: {e}")
        
        return {"documents": documents}
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Document status error: {e}")
        raise DomainError(context=str(e))

@router.get("/confirm-document", response_class=HTMLResponse)
def confirm_document(email: str, filename: str = None):
    """
    User clicked Confirm in email. Mark progress and log confirmation.
    Handles both single-user and multiple-owner flows.
    """
    try:
        user = get_user_by_email(email)
        if not user:
            return HTMLResponse(content="<h3>User not found.</h3>", status_code=404)

        account_type = user.get("account_type", "Account")
        ownership_type = user.get("ownership_type", "")
        
        logger.info(f"Confirmation received from: {email}")
        logger.info(f"       Account Type: {account_type}")
        logger.info(f"       Ownership Type: {ownership_type}")

        # âœ… Update user onboarding step to verification_complete
        try:
            UserRepository.update_by_email(email, {
                "onboarding_step": "verification_complete",
                "document_stage": "complete",
                "document_confirmation_sent": True,  # âœ… ADD THIS
                "confirmation_timestamp": datetime.utcnow().isoformat()  # âœ… ADD THIS
            })
            logger.info(f"Updated onboarding_step to verification_complete for {email}")
        except Exception as e:
            logger.warning(f"Could not update user onboarding step: {e}")

        # Log confirmation to conversations table
        try:
            ConversationRepository.insert({
                "user_email": email,
                "role": "user",
                "message": f"Confirmed extracted data for {filename or 'all documents'}",
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.warning(f"Could not insert conversation log: {e}")

        # Send onboarding complete email with PDF
        try:
            from app.services.handle_reply import send_completion_email
            logger.info(f"Generating PDF and sending completion email...")
            send_completion_email(email, account_type)
            logger.info(f"Completion email sent to {email}")
        except Exception as e:
            logger.error(f"Could not send onboarding complete email: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Return success HTML page
        return HTMLResponse(content="""
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Confirmation Received</title>
                </head>
                <body style='font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;'>
                    <div style='max-width:600px;margin:auto;background:#fff;padding:40px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);text-align:center;'>
                        <h1 style='color:#4CAF50;margin-bottom:20px;'>âœ” Confirmation Received!</h1>
                        <p style='font-size:16px;color:#333;'>Thank you for confirming your documents.</p>
                        <p style='font-size:16px;color:#333;'>Your onboarding is now complete.</p>
                        
                        <div style='margin-top:30px;padding:20px;background:#e8f5e9;border-radius:5px;'>
                            <p style='margin:0;color:#2e7d32;font-weight:bold;'>ðŸ“§ Check your email</p>
                            <p style='margin:10px 0 0 0;color:#555;'>You will receive a completion email with your onboarding summary PDF shortly.</p>
                        </div>
                        
                        <div style='margin-top:30px;padding:15px;background:#fff3e0;border-radius:5px;'>
                            <p style='margin:0;color:#f57c00;'><strong>Next Steps:</strong></p>
                            <p style='margin:10px 0 0 0;color:#666;'>Your account will be activated within <strong>3-4 business days</strong>.</p>
                        </div>
                        
                        <p style='margin-top:30px;font-size:14px;color:#999;'>You can close this window.</p>
                    </div>
                </body>
            </html>
        """, status_code=200)

    except Exception as e:
        logger.error(f"confirm-document error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        return HTMLResponse(content=f"""
            <html>
                <body style='font-family:Arial;text-align:center;padding:50px;'>
                    <h1 style='color:#f44336;'>âŒ Error</h1>
                    <p>Failed to process confirmation. Please contact support.</p>
                    <p style='color:#999;font-size:12px;'>{str(e)}</p>
                </body>
            </html>
        """, status_code=500)

@router.get("/resubmit-document", response_class=HTMLResponse)
def resubmit_document(email: str, filename: str = None):
    """
    User clicked Request Resubmission in email. Log and send resubmission instructions.
    """
    try:
        user = get_user_by_email(email)
        if not user:
            return HTMLResponse(content="<h3>User not found.</h3>", status_code=404)

        # Log the resubmission request
        try:
            ConversationRepository.insert({
                "user_email": email,
                "role": "user",
                "message": f"Requested resubmission for {filename or 'document(s)'}",
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.warning(f"Could not insert conversation log: {e}")

        # Send an email with resubmission instructions
        try:
            subject = "Please resubmit your document"
            body_html = f"""
            <html><body>
            <div style='font-family:Arial,Helvetica,sans-serif;'>
                <h3>Please resubmit your document</h3>
                <p>We received your request to resubmit <strong>{filename or 'your document(s)'}</strong>. Please reply to this email with the corrected file(s) attached or use the document upload feature in your account.</p>
                <p>If you need help, reply to this email and our onboarding team will assist you.</p>
                <p style='margin-top:24px;'>Best regards,<br/><strong>Thrivv Onboarding Team</strong></p>
            </div>
            </body></html>
            """
            send_email(to_email=email, subject=subject, body=body_html, html=True)
        except Exception as e:
            logger.warning(f"Failed to send resubmission email: {e}")

        return HTMLResponse(content=f"<h3>Resubmission requested.</h3><p>Please upload corrected file(s) for <strong>{filename or 'your documents'}</strong>. An email with instructions has been sent.</p>", status_code=200)

    except Exception as e:
        logger.error(f"resubmit-document error: {e}")
        return HTMLResponse(content=f"<h3>Error</h3><p>{e}</p>", status_code=500)

@router.get("/history/{user_email}")
def get_chat_history(user_email: str):
    """Get conversation history for a user"""
    try:
        result = ConversationRepository.list_all(user_email)

        return {"conversation": result.data if result.data else []}
    except Exception as e:
        logger.error(f"Get chat history error: {e}")
        raise DomainError(context=str(e))


# ============================================================================
# SESSION RESUME VIA REFERENCE NUMBER (Issue 3)
# ============================================================================


@router.post("/resume")
async def resume_session(req: ResumeRequest):
    """
    Validate a reference number and return the associated session data
    and conversation history so the user can continue from where they left off.
    """
    try:
        from app.services.reference_service import resolve_reference

        result = resolve_reference(req.ref_id.strip())

        if not result.get("valid"):
            return {
                "success": False,
                "valid": False,
                "error": result.get("reason", "Invalid or expired reference number."),
            }

        email = result["email"]
        snapshot = result.get("session_snapshot", {})

        # Fetch live conversation history from Supabase
        conversation = []
        try:
            hist = ConversationRepository.list_chat_transcript(email, limit=100)
            conversation = hist.data if hist and hist.data else []
        except Exception as hist_err:
            logger.info(f"[RESUME] Could not fetch conversation history: {hist_err}")
            conversation = snapshot.get("conversation_history", [])

        return {
            "success": True,
            "valid": True,
            "email": email,
            "ref_id": req.ref_id,
            "expires_at": result.get("expires_at"),
            "session_snapshot": snapshot,
            "conversation": conversation,
        }

    except Exception as e:
        logger.error(f"/resume error: {e}")
        raise DomainError(context=str(e))


