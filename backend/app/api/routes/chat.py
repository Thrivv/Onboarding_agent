# app/api/routes/chat.py
import os
import sys
import json
import time
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, EmailStr
from typing import List
import asyncio
from fastapi.responses import HTMLResponse
from email.utils import formataddr

# Import from app services
from app.services.supabase_client import supabase
from app.services.ocr_service import process_document
from app.services.email_sender import send_email

# Import backend modules
try:
    from ingestion.faq_retriever import retrieve_similar_chunks
except ImportError:
    print("[WARN] FAQ retriever not available")
    def retrieve_similar_chunks(query: str, top_k: int = 3):
        return []

from llm_runner.run_model import call_local_llm

router = APIRouter()

# ============================================================================
# MODELS
# ============================================================================

class ChatRequest(BaseModel):
    email: EmailStr
    message: str

class ChatResponse(BaseModel):
    response: str
    success: bool

class UserVerifyRequest(BaseModel):
    email: EmailStr

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_by_email(email: str) -> dict:
    """Get user from database"""
    try:
        response = supabase.table("users").select("*").eq("email", email).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"[ERROR] Failed to get user: {e}")
        return None

def build_chat_prompt(user_message: str, context: str = "", registration_data: dict = None) -> str:
    """Build chat-specific prompt"""
    onboarding_step = "welcome"
    if context and context.startswith("Onboarding Step:"):
        try:
            onboarding_step = context.split("\n")[0].split(":")[1].strip()
        except:
            pass

    reg_details = ""
    if registration_data:
        reg_details = (
            f"- Name: {registration_data.get('name', 'N/A')}\n"
            f"- Account Type: {registration_data.get('account_type', 'N/A')}\n"
            f"- Business Name: {registration_data.get('business_name', 'N/A')}\n"
        )

    account_type = registration_data.get('account_type') if registration_data else None
    if account_type == "Savings":
        doc_info = "Required documents: Emirates ID, Commercial Registration, Tenancy Contract (Ejari), Memorandum of Association (MOA)"
    elif account_type == "Corporate":
        doc_info = "Required documents: Emirates ID, Commercial Registration, Tenancy Contract (Ejari), Memorandum of Association (MOA)"
    else:
        doc_info = "Required documents: Emirates ID, Commercial Registration, Tenancy Contract (Ejari), Memorandum of Association (MOA)"

    prompt = f"""You are a helpful onboarding assistant at Thrivv Bank. Answer questions directly and concisely.

Current onboarding step: {onboarding_step}

User details:
{reg_details}

{doc_info}

User question: "{user_message}"

Context from previous conversation:
{context}

Instructions:
- Be direct and helpful
- Keep responses concise (2-4 sentences)
- No formal email signatures
- If asked about documents, mention all 4 required documents
- If asked about timeline, mention 3-4 business days for verification

Answer:"""
    
    return prompt.strip()

def check_documents_status(email: str) -> dict:
    """Check current document status for user"""
    user_docs_dir = os.path.join("backend", "documents", "id", email)
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
                    doc_type = analysis.get("document_type", "unknown")
                    is_valid = analysis.get("is_valid", False)
                    
                    if is_valid and doc_type in ["commercial", "eid", "tenancy", "moa"]:
                        status[doc_type] = True
                        status["total_documents"] += 1
                except:
                    pass
    
    return status

def process_single_document(email: str, filename: str, file_path: str, model_name: str) -> dict:
    """Process a single document and return result"""
    document_id = os.path.splitext(filename)[0]
    
    try:
        print(f"[INFO] Processing: {filename}")
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
                    "summary": f"⚠️ {doc_type.upper()} incomplete. Missing: {', '.join(missing_fields[:3])}",
                    "document_type": doc_type
                }
            else:
                return {
                    "filename": filename,
                    "status": "warning",
                    "summary": f"⚠️ {doc_type.upper()} needs review",
                    "document_type": doc_type
                }
    except Exception as e:
        print(f"[ERROR] Processing failed for {filename}: {e}")
        return {
            "filename": filename,
            "status": "error",
            "summary": f"❌ Processing failed: {str(e)}"
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
                icon = "✅"
            elif status == "warning":
                color = "#ffc107"
                icon = "⚠️"
            else:
                color = "#dc3545"
                icon = "❌"
            
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
            <h3 style="color: #1976d2; margin-top: 0;">📊 Overall Status</h3>
            <p><strong>{doc_status['total_documents']} out of 4</strong> required documents verified</p>
            {f"<p><strong>Still needed:</strong> {', '.join(missing_docs)}</p>" if missing_docs else "<p style='color: #28a745;'><strong>✅ All documents received!</strong></p>"}
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
        print(f"[INFO] Email sent to {email}")
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/verify-user")
def verify_user_email(request: UserVerifyRequest):
    """Verify if user email exists in database"""
    try:
        user = get_user_by_email(request.email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found. Please register first.")
        
        return {
            "message": "User verified", 
            "user_name": user.get("name", "User"),
            "onboarding_step": user.get("onboarding_step", "welcome")
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] User verification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat", response_model=ChatResponse)
def chat_with_bot(request: ChatRequest):
    """Handle chat conversation with bot"""
    try:
        # Verify user exists
        user = get_user_by_email(request.email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get conversation history (filter chat-only messages)
        try:
            convo_response = supabase.table("conversations").select("*").eq("user_email", request.email).order("timestamp").execute()
            all_conversations = convo_response.data if convo_response.data else []
        except Exception as e:
            print(f"[WARN] Could not fetch conversations: {e}")
            all_conversations = []
        
        # Filter chat conversations (ignore email-style messages)
        chat_conversations = []
        email_keywords = ["dear user", "best regards", "thrivv onboarding team", "welcome to thrivv"]
        
        for conv in all_conversations:
            message = conv.get("message", "").lower()
            if not any(keyword in message for keyword in email_keywords):
                chat_conversations.append(conv)
        
        # Use last 6 conversations for context
        recent_conversations = chat_conversations[-6:] if chat_conversations else []
        convo_context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in recent_conversations])
        
        # Search FAQ for context
        try:
            top_chunks = retrieve_similar_chunks(request.message, top_k=3)
            faq_context = "\n\n".join(top_chunks)
        except Exception as e:
            print(f"[WARN] FAQ retrieval failed: {e}")
            faq_context = ""
        
        # Build context
        onboarding_step = user.get("onboarding_step", "welcome")
        full_context = f"Onboarding Step: {onboarding_step}\n\n{convo_context}\n\nFAQ:\n{faq_context}"
        
        # Build registration data
        registration_data = {
            'name': user.get('name'),
            'email': user.get('email'),
            'business_name': user.get('business_name'),
            'account_type': user.get('account_type'),
            'ownership_type': user.get('ownership_type'),
        }
        
        # Build chat prompt and get response
        prompt = build_chat_prompt(
            user_message=request.message, 
            context=full_context,
            registration_data=registration_data
        )
        
        llm_response = call_local_llm(prompt)
        
        # Log conversation with chat marker
        try:
            supabase.table("conversations").insert({
                "user_email": request.email,
                "role": "user",
                "message": f"[CHAT] {request.message}",
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
            
            supabase.table("conversations").insert({
                "user_email": request.email,
                "role": "assistant",
                "message": llm_response,
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f"[WARN] Could not log conversation: {e}")
        
        return ChatResponse(response=llm_response, success=True)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat-history/{email}")
def get_chat_history(email: str):
    """Get chat history for user"""
    try:
        conversations_response = supabase.table("conversations").select("*").eq("user_email", email).order("timestamp").execute()
        all_conversations = conversations_response.data if conversations_response.data else []
        
        # Filter to show only chat conversations
        filtered_conversations = []
        email_keywords = ["dear user", "best regards", "thrivv onboarding team", "welcome to thrivv"]
        
        for conv in all_conversations:
            message = conv.get("message", "")
            
            # Include if it's a chat message or doesn't look like email
            if message.startswith("[CHAT]") or not any(keyword in message.lower() for keyword in email_keywords):
                clean_message = conv.copy()
                if clean_message["message"].startswith("[CHAT] "):
                    clean_message["message"] = clean_message["message"][7:]
                filtered_conversations.append(clean_message)
        
        return {"conversations": filtered_conversations}
        
    except Exception as e:
        print(f"[ERROR] Chat history error: {e}")
        return {"conversations": []}

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
        print(f"[INFO] Document upload request for: {email}")
        
        # Verify user exists
        user = get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Validate files
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded")
        
        # Prepare save directory
        save_dir = os.path.join("backend", "documents", "id", email)
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
                        print(f"[INFO] Saved: {file.filename} ({len(file_content)} bytes)")
                    except Exception as e:
                        print(f"[ERROR] Failed to save {file.filename}: {e}")
        
        if not files_saved:
            raise HTTPException(status_code=400, detail="No valid files could be saved")
        
        # Process documents with reduced delays
        LLAMA_MODEL = "meta-llama/llama-3.2-11b-vision-instruct"
        QWEN_MODEL = "meta-llama/llama-3.2-11b-vision-instruct"
        
        results = []
        
        for idx, filename in enumerate(files_saved):
            file_path = os.path.join(save_dir, filename)
            model_name = LLAMA_MODEL if idx == 0 else QWEN_MODEL
            
            # Process document
            result = process_single_document(email, filename, file_path, model_name)
            results.append(result)
            
            # Reduced delay - only between documents, not after last one
            if idx < len(files_saved) - 1:
                await asyncio.sleep(1)  # ← REDUCED FROM 3 to 1 second
                print(f"[INFO] Waiting 1 second before processing next document...")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Document upload error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@router.get("/document-status/{email}")
def get_document_status(email: str):
    """Get current document status for user"""
    try:
        user = get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_docs_dir = os.path.join("backend", "documents", "id", email)
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
                                summary = f"✅ {doc_type.title()} document verified successfully"
                            elif doc_type == "unknown":
                                status = "invalid"
                                summary = "❌ Document type not recognized"
                            else:
                                status = "warning"
                                missing_fields = analysis.get("validation", {}).get("missing_fields", [])
                                if missing_fields:
                                    summary = f"⚠️ {doc_type.title()} document incomplete. Missing: {', '.join(missing_fields[:3])}"
                                else:
                                    summary = f"⚠️ {doc_type.title()} document needs review"
                            
                            documents.append({
                                "filename": analysis.get("filename", item),
                                "document_type": doc_type,
                                "status": status,
                                "extracted_fields": analysis.get("extracted_fields", {}),
                                "validation": analysis.get("validation", {}),
                                "summary": summary
                            })
                        except Exception as e:
                            print(f"[ERROR] Failed to read analysis for {item}: {e}")
        
        return {"documents": documents}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Document status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/confirm-document", response_class=HTMLResponse)
def confirm_document(email: str, filename: str = None):
    """
    User clicked Confirm in email. Mark progress and log confirmation.
    """
    try:
        user = get_user_by_email(email)
        if not user:
            return HTMLResponse(content="<h3>User not found.</h3>", status_code=404)

        # Update user onboarding step to verification_in_progress (or a suitable state)
        try:
            supabase.table("users").update({"onboarding_step": "verification_complete"}).eq("email", email).execute()
        except Exception as e:
            print(f"[WARN] Could not update user onboarding step: {e}")

        # Log confirmation to conversations table
        try:
            supabase.table("conversations").insert({
                "user_email": email,
                "role": "user",
                "message": f"Confirmed extracted data for {filename or 'documents'}",
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f"[WARN] Could not insert conversation log: {e}")

        # --- ADD THIS BLOCK ---
        # Send onboarding complete email after confirmation
        try:
            from llm_pipeline.handle_reply import send_completion_email
            send_completion_email(email, user.get("account_type", "Account"))
        except Exception as e:
            print(f"[WARN] Could not send onboarding complete email: {e}")
        # --- END BLOCK ---

        # Respond with a friendly HTML page
        return HTMLResponse(content=f"<h3>Thank you — confirmed.</h3><p>We received your confirmation. for <strong>{filename or 'your documents'}</strong>. Thank You for your support.</p>", status_code=200)

    except Exception as e:
        print(f"[ERROR] confirm-document error: {e}")
        return HTMLResponse(content=f"<h3>Error</h3><p>{e}</p>", status_code=500)


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
            supabase.table("conversations").insert({
                "user_email": email,
                "role": "user",
                "message": f"Requested resubmission for {filename or 'document(s)'}",
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        except Exception as e:
            print(f"[WARN] Could not insert conversation log: {e}")

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
            print(f"[WARN] Failed to send resubmission email: {e}")

        return HTMLResponse(content=f"<h3>Resubmission requested.</h3><p>Please upload corrected file(s) for <strong>{filename or 'your documents'}</strong>. An email with instructions has been sent.</p>", status_code=200)

    except Exception as e:
        print(f"[ERROR] resubmit-document error: {e}")
        return HTMLResponse(content=f"<h3>Error</h3><p>{e}</p>", status_code=500)
