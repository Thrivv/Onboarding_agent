# backend/llm_pipeline/handle_reply.py

from ingestion.faq_retriever import retrieve_similar_chunks
from llm_runner.prompt_templates import build_onboarding_prompt
from llm_runner.run_model import call_local_llm
from app.services.supabase_client import supabase
from app.services.email_sender import send_email
from app.services.ocr_service import extract_text_from_user_documents

from datetime import datetime
import os
import time

def check_documents_in_ocr(ocr_results: dict) -> dict:
    """
    Checks OCR results for presence of commercial and eid documents.
    ocr_results: dict with format {'filename': {'type': 'commercial'/'eid'/'unknown', 'text': 'extracted_text'}}
    Returns a dict: {'commercial': bool, 'eid': bool, 'missing': list}
    """
    has_commercial = False
    has_eid = False
    
    for filename, data in ocr_results.items():
        doc_type = data.get('type', 'unknown')
        if doc_type == 'commercial':
            has_commercial = True
        elif doc_type == 'eid':
            has_eid = True
    
    missing = []
    if not has_commercial:
        missing.append("Commercial Registration Document")
    if not has_eid:
        missing.append("Resident Identity Card (EID)")
    
    return {
        "commercial": has_commercial, 
        "eid": has_eid,
        "missing": missing
    }

def process_user_reply(from_email: str, body: str, attachments: list = None):
    # `Step 1: Get the user
    user_response = supabase.table("users").select("*").eq("email", from_email).execute()
    if not user_response.data or len(user_response.data) == 0:
        print(f"[WARN] Email not found in users table: {from_email}")
        return

    user = user_response.data[0]

    # Save attachments to backend/documents/id/{email}/
    if attachments:
        print(f"[DEBUG] Attachments received: {[a['filename'] for a in attachments]}")
        save_dir = os.path.join("backend", "documents", "id", from_email)
        os.makedirs(save_dir, exist_ok=True)
        
        # Filter and save only image files
        image_files_saved = []
        for a in attachments:
            filename = a["filename"]
            filedata = a["data"]
            
            # Check if file is an image
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                filepath = os.path.join(save_dir, filename)
                print(f"[DEBUG] Saving image attachment: {filepath} (size: {len(filedata)} bytes)")
                with open(filepath, "wb") as f:
                    f.write(filedata)
                image_files_saved.append(filename)
            else:
                print(f"[WARN] Skipping non-image file: {filename}")
        
        if not image_files_saved:
            subject = "No Valid Documents Received"
            body = "Please attach image files (PNG, JPG, JPEG, WEBP) containing your Commercial Registration Document and Resident Identity Card (EID)."
            send_email(to_email=from_email, subject=subject, body=body)
            print(f"[WARN] No image files found in attachments for: {from_email}")
            return
        
        supabase.table("users").update({"onboarding_step": "document_verification"}).eq("email", from_email).execute()
        print("[INFO] Waiting 1.5 minutes before running OCR...")
        time.sleep(20)

        try:
            # Get OCR results as structured data
            ocr_results = extract_text_from_user_documents(from_email)
            print(f"[INFO] OCR completed for {len(ocr_results)} documents")

            # Check OCR results for required documents
            doc_status = check_documents_in_ocr(ocr_results)
            
            # Identify wrongly submitted documents
            wrong_docs = [
                (filename, data.get("type", "unknown"))
                for filename, data in ocr_results.items()
                if data.get("type") == "unknown"
            ]
            
            if not doc_status["missing"] and not wrong_docs:
                subject = "Documents Received and Verified"
                body = "Great! Both your Commercial Registration Document and Resident Identity Card (EID) have been successfully received and verified. Your onboarding will proceed to the next step."
            else:
                subject = "Missing or Incorrect Document(s)"
                body = "We have processed your submitted documents.\n\n"
                if doc_status["missing"]:
                    body += "We still need the following:\n"
                    for missing_doc in doc_status["missing"]:
                        body += f"• {missing_doc}\n"
                if wrong_docs:
                    body += "\nThe following document(s) you submitted are not required or could not be recognized:\n"
                    for filename, doc_type in wrong_docs:
                        extracted_text = ocr_results[filename].get("text", "")
                        body += (
                            f"• {filename}: You have submitted this document (detected type: {doc_type}).\n"
                            "This is not the required document for onboarding.\n"
                            "Extracted text from your document:\n"
                            f"{extracted_text}\n"
                            "Please submit only your Commercial Registration Document and Resident Identity Card (EID) containing the required fields.\n"
                        )
                body += "\nPlease reply to this email with the correct document(s) attached as image files."

            send_email(to_email=from_email, subject=subject, body=body)
            print(f"[INFO] Document verification result sent to: {from_email}")

            # If missing or wrong documents, don't proceed further
            if doc_status["missing"] or wrong_docs:
                return

        except Exception as e:
            print(f"[ERROR] OCR failed for {from_email}: {e}")
            subject = "Error Processing Your Documents"
            body = f"We encountered an error while processing your documents. Please ensure your images are clear and readable, then try submitting them again.\n\nError details: {str(e)}"
            send_email(to_email=from_email, subject=subject, body=body)
            return

    # Step 2: Log user message in conversation
    supabase.table("conversations").insert({
        "user_email": from_email,
        "role": "user",
        "message": body,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()

    # Step 3: Search FAQ for context
    top_chunks = retrieve_similar_chunks(body, top_k=3)
    faq_context = "\n\n".join(top_chunks)

    # Step 3.1: Get conversation history for context
    convo_response = supabase.table("conversations").select("*").eq("user_email", from_email).order("timestamp").execute()
    convo_history = convo_response.data if convo_response.data else []
    convo_context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in convo_history])

    # dd onboarding_step to context
    onboarding_step = user.get("onboarding_step", "welcome")
    full_context = f"Onboarding Step: {onboarding_step}\n\n{convo_context}\n\nFAQ:\n{faq_context}"

    # Step 4: Build prompt and call LLM with both contexts
    prompt = build_onboarding_prompt(user_message=body, context=full_context)

    llm_response = call_local_llm(prompt)

    # Step 5: Send reply
    subject = "Re: Your query with Thrivv"
    send_email(to_email=from_email, subject=subject, body=llm_response)

    #  Step 6: Log agent message in conversation
    supabase.table("conversations").insert({
        "user_email": from_email,
        "role": "agent",
        "message": llm_response,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()

    print(f"[INFO] Replied to: {from_email}")
