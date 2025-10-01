# backend/llm_pipeline/handle_reply.py
from ingestion.faq_retriever import retrieve_similar_chunks
from llm_runner.prompt_templates import build_onboarding_prompt
from llm_runner.run_model import call_local_llm
from app.services.supabase_client import supabase
from app.services.email_sender import send_email, send_wrong_document_email
from app.services.ocr_service import process_document
from app.services.pdf_utils import pdf_to_images_pymupdf

LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-7b-instruct"

from datetime import datetime
import os
import time
import json

def extract_license_members(members_data):
    """
    Extract member names from license members data, handling both string arrays and object arrays.
    
    Args:
        members_data: Can be:
            - List of strings: ["MEMBER1", "MEMBER2"]
            - List of objects: [{"Name": "MEMBER1", "License No.": "123"}, {"Name": "MEMBER2", "License No.": "456"}]
            - None or empty
    
    Returns:
        List of member names (strings)
    """
    if not members_data or not isinstance(members_data, list):
        return []
    
    member_names = []
    for member in members_data:
        if isinstance(member, str):
            # Direct string format
            member_names.append(member.strip())
        elif isinstance(member, dict):
            # Object format - extract name
            name = member.get("Name") or member.get("name")
            if name:
                member_names.append(name.strip())
        # Skip any other formats
    
    # Remove duplicates while preserving order
    seen = set()
    unique_names = []
    for name in member_names:
        if name and name not in seen:
            seen.add(name)
            unique_names.append(name)
    
    return unique_names

def get_member_progress(user_email):
    """
    Load member processing progress from JSON file.
    Returns: dict with 'members' list and 'current_index'
    """
    progress_file = os.path.join("backend", "documents", "id", user_email, "member_progress.json")
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_member_progress(user_email, members, current_index):
    """
    Save member processing progress to JSON file.
    """
    progress_file = os.path.join("backend", "documents", "id", user_email, "member_progress.json")
    progress_data = {
        "members": members,
        "current_index": current_index,
        "updated_at": datetime.utcnow().isoformat()
    }
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress_data, f, ensure_ascii=False, indent=2)
    print(f"[DEBUG] Saved member progress: {progress_data}")

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

def check_member_documents(user_email, member_name):
    """
    Check if a specific member has both required documents.
    Returns: dict with OCR results for that member's folder
    """
    member_dir = os.path.join("backend", "documents", "id", user_email, member_name)
    ocr_results = {}
    
    if not os.path.exists(member_dir):
        return ocr_results
    
    # Check all subdirectories in member folder for output.json
    for item in os.listdir(member_dir):
        item_path = os.path.join(member_dir, item)
        if os.path.isdir(item_path):
            output_path = os.path.join(item_path, "output.json")
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                ocr_results[item] = {
                    "type": analysis.get("document_type", "unknown"),
                    "raw_text": analysis.get("raw_text", ""),
                    "status_message": analysis.get("status_message", ""),
                    "extracted_fields": analysis.get("extracted_fields", {}),
                    "validation": analysis.get("validation", {}),
                    "is_valid": analysis.get("is_valid", False)
                }
    
    return ocr_results

def process_member_documents(user_email, member_name, attachments):
    """
    Process documents for a specific member.
    Returns: True if EID doc valid, False otherwise
    """
    member_dir = os.path.join("backend", "documents", "id", user_email, member_name)
    
    print(f"[DEBUG] Processing documents for member: {member_name}")
    
    # Save attachments to member's folder
    image_files_saved = []
    pdf_image_names = []
    
    for a in attachments:
        filename = a["filename"]
        filedata = a["data"]
        
        if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            filepath = os.path.join(member_dir, filename)
            with open(filepath, "wb") as f:
                f.write(filedata)
            image_files_saved.append(filename)
            
        elif filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(member_dir, filename)
            with open(pdf_path, "wb") as f:
                f.write(filedata)
            pdf_images = pdf_to_images_pymupdf(pdf_path, member_dir)
            pdf_image_names = [os.path.basename(img) for img in pdf_images]
            image_files_saved.extend(pdf_image_names)
            
            # OCR each PDF image
            for img_name in pdf_image_names:
                document_id = os.path.splitext(img_name)[0]
                file_path = os.path.join(member_dir, img_name)
                try:
                    process_document(f"{user_email}/{member_name}", document_id, file_path, model_name=LLAMA_MODEL_NAME)
                    time.sleep(60)
                except Exception as e:
                    print(f"[ERROR] OCR failed for {img_name}: {e}")
    
    # Process regular images with Qwen
    for filename in image_files_saved:
        if filename in pdf_image_names:
            continue
        document_id = os.path.splitext(filename)[0]
        file_path = os.path.join(member_dir, filename)
        try:
            process_document(f"{user_email}/{member_name}", document_id, file_path, model_name=QWEN_MODEL_NAME)
            time.sleep(60)
        except Exception as e:
            print(f"[ERROR] OCR failed for {filename}: {e}")
    
    # Check OCR results for this member
    ocr_results = check_member_documents(user_email, member_name)
    # --- CHANGED LOGIC: Only require EID for each member ---
    eid_present = False
    eid_info = None
    for doc_name, doc_info in ocr_results.items():
        if doc_info.get("type") == "eid":
            eid_present = True
            eid_info = doc_info
            break

    if not eid_present:
        subject = f"Missing EID Document for {member_name}"
        body_html = (
            f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
            "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
            f"<h2 style='color:#e53935;'>Missing EID Document for {member_name}</h2>"
            "<p>Dear User,</p>"
            f"<p>Please submit the Resident Identity Card (EID) for <strong>{member_name}</strong> as an image or PDF file.</p>"
            "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
            "</div></body></html>"
        )
        send_email(to_email=user_email, subject=subject, body=body_html, html=True)
        return False

    # Validate EID fields
    validation = eid_info.get("validation", {})
    fields = eid_info.get("extracted_fields", {})
    missing_fields_msgs = []
    extracted_fields_msgs = []
    if fields:
        field_lines = "\n".join([f"- {k}: {v}" for k, v in fields.items()])
        extracted_fields_msgs.append(
            f"EID Document ({doc_name}):\n{field_lines}"
        )
    if not validation.get("is_valid", False):
        missing_fields = validation.get("missing_fields", [])
        if missing_fields:
            missing_fields_msgs.append(
                f"• {doc_name}: Missing fields - {', '.join(missing_fields)}"
            )
    if missing_fields_msgs:
        subject = f"EID Document for {member_name} - Missing Fields"
        body_html = (
            f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
            "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
            f"<h2 style='color:#ff9800;'>Missing Fields in EID Document for {member_name}</h2>"
            "<p>Dear User,</p>"
            f"<p>The EID document for <strong>{member_name}</strong> is missing required fields:</p>"
            "<ul>"
            + "".join([f"<li>{msg}</li>" for msg in missing_fields_msgs])
            + "</ul>"
            f"<p>Please resend the EID document for <strong>{member_name}</strong> ensuring all required fields are visible and readable.</p>"
            "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
            "</div></body></html>"
        )
        send_email(to_email=user_email, subject=subject, body=body_html, html=True)
        return False

    # All valid - send success message
    subject = f"EID Document Verified for {member_name}"
    body_html = (
        f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
        "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
        f"<h2 style='color:#4CAF50;'>EID Document Verified for {member_name}</h2>"
        "<p>Dear User,</p>"
        f"<p>The EID document for <strong>{member_name}</strong> has been successfully verified!</p>"
        "<p><strong>Extracted Information:</strong></p>"
        f"<pre>{'<br><br>'.join(extracted_fields_msgs)}</pre>"
        "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
        "</div></body></html>"
    )
    send_email(to_email=user_email, subject=subject, body=body_html, html=True)
    return True

def process_user_reply(from_email: str, body: str, attachments: list = None):
    # Step 0: Get user data
    user_response = supabase.table("users").select("*").eq("email", from_email).execute()
    if not user_response.data or len(user_response.data) == 0:
        print(f"[WARN] Email not found in users table: {from_email}")
        return
    
    user = user_response.data[0]
    account_type = user.get("account_type")
    ownership_type = user.get("ownership_type")
    onboarding_step = user.get("onboarding_step", "welcome")
    
    # Check if we're in member document collection mode
    if account_type == "Corporate" and ownership_type in ["@Multiple Owners", "Partnership"]:
        progress = get_member_progress(from_email)
        
        # If we have member progress, we're collecting member documents
        if progress and attachments:
            members = progress["members"]
            current_index = progress["current_index"]
            
            if current_index < len(members):
                current_member = members[current_index]
                print(f"[INFO] Processing documents for member {current_index + 1}/{len(members)}: {current_member}")
                
                # Process documents for current member
                is_valid = process_member_documents(from_email, current_member, attachments)
                
                if is_valid:
                    # Move to next member
                    current_index += 1
                    
                    if current_index < len(members):
                        # Request documents for next member
                        next_member = members[current_index]
                        save_member_progress(from_email, members, current_index)
                        
                        subject = f"Documents Required for {next_member}"
                        body_html = (
                            f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
                            "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
                            f"<h2 style='color:#4CAF50;'>Documents Required for {next_member}</h2>"
                            "<p>Dear User,</p>"
                            f"<p>Great! We've verified the documents for <strong>{members[current_index - 1]}</strong>.</p>"
                            f"<p>Now, please submit the following documents for <strong>{next_member}</strong> (Member {current_index + 1} of {len(members)}):</p>"
                            "<ul style='margin-left:20px;'>"
                            "<li>Resident Identity Card (EID)</li>"
                            "</ul>"
                            "<p>Please reply to this email with the required documents attached as image files.</p>"
                            "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
                            "</div></body></html>"
                        )
                        send_email(to_email=from_email, subject=subject, body=body_html, html=True)
                        print(f"[INFO] Requested documents for next member: {next_member}")
                    else:
                        # All members processed
                        supabase.table("users").update({"onboarding_step": "verification_complete"}).eq("email", from_email).execute()
                        
                        subject = "All Member Documents Verified - Onboarding Complete!"
                        body_html = (
                            f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
                            "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
                            "<h2 style='color:#4CAF50;'>🎉 All Member Documents Verified!</h2>"
                            "<p>Dear User,</p>"
                            "<p>Congratulations! We have successfully verified documents for all {len(members)} license members:</p>"
                            "<ul>"
                            + "".join([f"<li><strong>{name}</strong></li>" for name in members])
                            + "</ul>"
                            "<p>Your onboarding process is now complete. Welcome to Thrivv!</p>"
                            "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
                            "</div></body></html>"
                        )
                        send_email(to_email=from_email, subject=subject, body=body_html, html=True)
                        print(f"[INFO] All members processed for {from_email}. Onboarding complete!")
                else:
                    # Keep same index, user needs to resubmit
                    save_member_progress(from_email, members, current_index)
                    print(f"[INFO] Waiting for correct documents for member: {current_member}")
                
                return
    
    # Original validation request flow
    convo_response = supabase.table("conversations").select("*").eq("user_email", from_email).order("timestamp", desc=True).limit(2).execute()
    convo_history = convo_response.data if convo_response.data else []
    last_agent_msg = None
    for msg in convo_history:
        if msg["role"] == "agent":
            last_agent_msg = msg["message"]
            break

    print(f"[DEBUG] last_agent_msg: {last_agent_msg}")
    print(f"[DEBUG] user reply: {body.strip().lower()}")

    if last_agent_msg and "yes" in last_agent_msg:
        print("[DEBUG] Validation request detected.")
        if body.strip().lower() == "yes":
            print("[DEBUG] User replied YES.")
            user_docs_dir = os.path.join("backend", "documents", "id", from_email)
            ocr_results = {}
            if os.path.exists(user_docs_dir):
                for doc_dir in os.listdir(user_docs_dir):
                    output_path = os.path.join(user_docs_dir, doc_dir, "output.json")
                    if os.path.exists(output_path):
                        with open(output_path, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
                        ocr_results[doc_dir] = {
                            "type": analysis.get("document_type", "unknown"),
                            "is_valid": analysis.get("is_valid", False)
                        }
            
            doc_status = check_documents_in_ocr(ocr_results)
            print(f"[DEBUG] doc_status: {doc_status}")
            if doc_status["commercial"] and doc_status["eid"]:
                print("Changing onboarding_step to verification_complete in Supabase")
                supabase.table("users").update({"onboarding_step": "verification_complete"}).eq("email", from_email).execute()
                print(f"[INFO] User {from_email} confirmed both documents. Onboarding complete.")
                return
            else:
                missing = []
                if not doc_status["commercial"]:
                    missing.append("Commercial Registration Document")
                if not doc_status["eid"]:
                    missing.append("Resident Identity Card (EID)")
                subject = "Please Submit Missing Document"
                body_text = (
                    "Thank you for submitting your document. We have received your "
                    f"{'Commercial Registration Document' if doc_status['commercial'] else 'Resident Identity Card (EID'}.\n"
                    f"Please submit the following missing document(s) to continue onboarding:\n"
                    + "\n".join([f"- {doc}" for doc in missing])
                )
                send_email(to_email=from_email, subject=subject, body=body_text)
                supabase.table("users").update({"onboarding_step": "verification_in_progress"}).eq("email", from_email).execute()
                print(f"[INFO] User {from_email} submitted one document. Requested missing document(s).")
                return
        else:
            subject = "Document Correction Required"
            body_text = (
                "It appears there are corrections needed in your submitted information. "
                "Please reply to this email with both your Commercial Registration Document and Resident Identity Card (EID) attached as image files."
            )
            send_email(to_email=from_email, subject=subject, body=body_text)
            print(f"[INFO] User {from_email} did not confirm extracted fields. Requested both documents again.")
            return

    # Save attachments to backend/documents/id/{email}/
    if attachments:
        print(f"[DEBUG] Attachments received: {[a['filename'] for a in attachments]}")
        save_dir = os.path.join("backend", "documents", "id", from_email)
        os.makedirs(save_dir, exist_ok=True)
        
        image_files_saved = []
        pdf_image_names = []

        for a in attachments:
            filename = a["filename"]
            filedata = a["data"]
            if filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                filepath = os.path.join(save_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(filedata)
                image_files_saved.append(filename)
            elif filename.lower().endswith(".pdf"):
                pdf_path = os.path.join(save_dir, filename)
                with open(pdf_path, "wb") as f:
                    f.write(filedata)
                pdf_images = pdf_to_images_pymupdf(pdf_path, save_dir)
                pdf_image_names = [os.path.basename(img) for img in pdf_images]
                image_files_saved.extend(pdf_image_names)
                pdf_results = []
                for img_name in pdf_image_names:
                    document_id = os.path.splitext(img_name)[0]
                    file_path = os.path.join(save_dir, img_name)
                    try:
                        result = process_document(f"{from_email}", document_id, file_path, model_name=LLAMA_MODEL_NAME)
                        pdf_results.append(result)
                    except Exception as e:
                        print(f"[ERROR] OCR failed for {img_name}: {e}")
                ocr_response_path = os.path.join(save_dir, "ocr-response.json")
                with open(ocr_response_path, "w", encoding="utf-8") as f:
                    json.dump(pdf_results, f, ensure_ascii=False, indent=2)
                print(f"[INFO] Aggregated OCR response saved: {ocr_response_path}")

        for filename in image_files_saved:
            if filename in pdf_image_names:
                continue
            document_id = os.path.splitext(filename)[0]
            file_path = os.path.join(save_dir, filename)
            try:
                process_document(f"{from_email}", document_id, file_path, model_name=QWEN_MODEL_NAME)
                time.sleep(60)
            except Exception as e:
                print(f"[ERROR] OCR failed for {filename}: {e}")

        # --- ENHANCED LOGIC: Partnership License Members Processing ---
        if account_type == "Corporate" and ownership_type in ["@Multiple Owners", "Partnership"]:
            print(f"[DEBUG] Processing partnership/multiple owners for {from_email}")
            
            ocr_response_path = os.path.join(save_dir, "ocr-response.json")
            member_names = []
            
            if os.path.exists(ocr_response_path):
                print(f"[DEBUG] Reading OCR response from: {ocr_response_path}")
                with open(ocr_response_path, "r", encoding="utf-8") as f:
                    ocr_results = json.load(f)
                
                for doc in ocr_results:
                    filename = doc.get("filename", "")
                    doc_type = doc.get("document_type", "")
                    
                    print(f"[DEBUG] Checking document: {filename}, type: {doc_type}")
                    
                    if "page_1" in filename.lower() and doc_type == "commercial":
                        extracted_fields = doc.get("extracted_fields", {})
                        license_members = extracted_fields.get("License Members", [])
                        
                        print(f"[DEBUG] Found license members in {filename}: {license_members}")
                        
                        member_names = extract_license_members(license_members)
                        print(f"[DEBUG] Extracted member names: {member_names}")
                        break
            
            if not member_names:
                print("[DEBUG] No members found in PDF OCR, checking individual image OCR results")
                for filename in image_files_saved:
                    if "page_1" in filename.lower() or filename.lower().startswith("page1"):
                        document_id = os.path.splitext(filename)[0]
                        output_path = os.path.join(save_dir, document_id, "output.json")
                        if os.path.exists(output_path):
                            with open(output_path, "r", encoding="utf-8") as f:
                                analysis = json.load(f)
                            
                            if analysis.get("document_type") == "commercial":
                                extracted_fields = analysis.get("extracted_fields", {})
                                license_members = extracted_fields.get("License Members", [])
                                member_names = extract_license_members(license_members)
                                print(f"[DEBUG] Found members in individual OCR {filename}: {member_names}")
                                if member_names:
                                    break
            
            if member_names:
                if len(member_names) == 1:
                    print(f"[WARN] Only one license member extracted: {member_names}. Re-running full OCR pipeline.")
                    pdf_files = [f for f in os.listdir(save_dir) if f.lower().endswith(".pdf")]
                    if pdf_files:
                        original_pdf = pdf_files[0]
                        for f in os.listdir(save_dir):
                            if f != original_pdf:
                                file_path = os.path.join(save_dir, f)
                                if os.path.isfile(file_path):
                                    os.remove(file_path)
                                elif os.path.isdir(file_path):
                                    import shutil
                                    shutil.rmtree(file_path)
                        print(f"[INFO] Cleaned up folder, kept only: {original_pdf}")
                        pdf_path = os.path.join(save_dir, original_pdf)
                        pdf_images = pdf_to_images_pymupdf(pdf_path, save_dir)
                        pdf_image_names = [os.path.basename(img) for img in pdf_images]
                        pdf_results = []
                        for img_name in pdf_image_names:
                            document_id = os.path.splitext(img_name)[0]
                            file_path = os.path.join(save_dir, img_name)
                            try:
                                result = process_document(f"{from_email}", document_id, file_path, model_name=LLAMA_MODEL_NAME)
                                pdf_results.append(result)
                            except Exception as e:
                                print(f"[ERROR] OCR failed for {img_name}: {e}")
                        ocr_response_path = os.path.join(save_dir, "ocr-response.json")
                        with open(ocr_response_path, "w", encoding="utf-8") as f:
                            json.dump(pdf_results, f, ensure_ascii=False, indent=2)
                        print(f"[INFO] Re-aggregated OCR response saved: {ocr_response_path}")
                        member_names = []
                        for doc in pdf_results:
                            filename = doc.get("filename", "")
                            doc_type = doc.get("document_type", "")
                            if "page_1" in filename.lower() and doc_type == "commercial":
                                extracted_fields = doc.get("extracted_fields", {})
                                license_members = extracted_fields.get("License Members", [])
                                member_names = extract_license_members(license_members)
                                print(f"[DEBUG] After re-run, extracted member names: {member_names}")
                                break
                
                print(f"[INFO] Creating directories for {len(member_names)} license members")
                
                # Create directory for each member INSIDE the user's email directory
                base_docs_dir = os.path.join("backend", "documents", "id", from_email)
                for member_name in member_names:
                    member_dir = os.path.join(base_docs_dir, member_name)
                    os.makedirs(member_dir, exist_ok=True)
                    print(f"[DEBUG] Created directory: {member_dir}")
                
                # Save member progress - start with first member (index 0)
                save_member_progress(from_email, member_names, 0)
                
                # Request documents for FIRST member only
                first_member = member_names[0]
                subject = f"Documents Required for {first_member}"
                body_html = (
                    f"<html><body style='font-family:Arial,sans-serif;color:#333;'>"
                    "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
                    f"<h2 style='color:#4CAF50;'>Documents Required for {first_member}</h2>"
                    "<p>Dear User,</p>"
                    "<p>We have successfully processed your Commercial Registration Document and identified the following license members:</p>"
                    "<ul style='background:#f8f9fa;padding:15px;border-radius:5px;'>"
                    + "".join([f"<li><strong>{name}</strong></li>" for name in member_names])
                    + "</ul>"
                    f"<p>We will collect documents for each member one by one. Let's start with <strong>{first_member}</strong> (Member 1 of {len(member_names)}).</p>"
                    f"<p><strong>Required Documents for {first_member}:</strong></p>"
                    "<ul style='margin-left:20px;'>"
                    "<li>Resident Identity Card (EID)</li>"
                    "</ul>"
                    f"<p>Please reply to this email with the required documents for <strong>{first_member}</strong> attached as image or PDF files.</p>"
                    "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
                    "</div></body></html>"
                )
                
                send_email(to_email=from_email, subject=subject, body=body_html, html=True)
                
                # Update onboarding step
                supabase.table("users").update({"onboarding_step": "member_documents_required"}).eq("email", from_email).execute()
                
                print(f"[INFO] Successfully processed partnership. Requested documents for first member: {first_member}")
                return
            else:
                print("[WARN] No license members found in commercial document for partnership/multiple owners")

        # Now extract structured OCR results (for non-partnership flow)
        try:
            ocr_results = {}
            for filename in image_files_saved:
                document_id = os.path.splitext(filename)[0]
                output_path = os.path.join(save_dir, document_id, "output.json")
                if os.path.exists(output_path):
                    with open(output_path, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    ocr_results[filename] = {
                        "type": analysis.get("document_type", "unknown"),
                        "raw_text": analysis.get("raw_text", ""),
                        "status_message": analysis.get("status_message", ""),
                        "extracted_fields": analysis.get("extracted_fields", {}),
                        "validation": analysis.get("validation", {}),
                        "is_valid": analysis.get("is_valid", False)
                    }
                else:
                    ocr_results[filename] = {
                        "type": "error",
                        "raw_text": "",
                        "status_message": "❌ ERROR: No OCR output found.",
                        "extracted_fields": {},
                        "validation": {},
                        "is_valid": False
                    }
            ocr_response_path = os.path.join(save_dir, "ocr-response.json")
            if os.path.exists(ocr_response_path):
                with open(ocr_response_path, "r", encoding="utf-8") as f:
                    pdf_ocr_list = json.load(f)
                for pdf_ocr in pdf_ocr_list:
                    fname = pdf_ocr.get("filename", "")
                    ocr_results[fname] = {
                        "type": pdf_ocr.get("document_type", "unknown"),
                        "raw_text": pdf_ocr.get("raw_text", ""),
                        "status_message": pdf_ocr.get("status_message", ""),
                        "extracted_fields": pdf_ocr.get("extracted_fields", {}),
                        "validation": pdf_ocr.get("validation", {}),
                        "is_valid": pdf_ocr.get("is_valid", False)
                    }
            user_docs_dir = os.path.join("backend", "documents", "id", from_email)
            if os.path.exists(user_docs_dir):
                for doc_dir in os.listdir(user_docs_dir):
                    output_path = os.path.join(user_docs_dir, doc_dir, "output.json")
                    if os.path.exists(output_path):
                        with open(output_path, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
                        ocr_results[doc_dir] = {
                            "type": analysis.get("document_type", "unknown"),
                            "raw_text": analysis.get("raw_text", ""),
                            "status_message": analysis.get("status_message", ""),
                            "extracted_fields": analysis.get("extracted_fields", {}),
                            "validation": analysis.get("validation", {}),
                            "is_valid": analysis.get("is_valid", False)
                        }
            print(f"[INFO] OCR completed for {len(ocr_results)} documents")

            doc_status = check_documents_in_ocr(ocr_results)
            
            wrong_docs = [
                (filename, data.get("type", "unknown"))
                for filename, data in ocr_results.items()
                if data.get("type") == "unknown"
            ]
            summary_texts = []
            if wrong_docs:
                for filename, doc_type in wrong_docs:
                    doc_info = ocr_results.get(filename, {})
                    raw_text = doc_info.get("raw_text", "")
                    summary = ""
                    if raw_text:
                        prompt = (
                            "Summarize the document and tell what the document is about and tell what it is and give it a title.\n"
                            "Document text:\n"
                            f"{raw_text}\n"
                        )
                        summary = call_local_llm(prompt)
                    summary_texts.append(summary)
                    required_docs = []
                    if not doc_status["commercial"]:
                        required_docs.append("Commercial Registration Document")
                    if not doc_status["eid"]:
                        required_docs.append("Resident Identity Card (EID)")
                    send_wrong_document_email(from_email, filename, summary, required_docs)
                    
                    image_path = os.path.join("backend", "documents", "id", from_email, filename)
                    if os.path.exists(image_path):
                        os.remove(image_path)
                    doc_id = os.path.splitext(filename)[0]
                    ocr_dir = os.path.join("backend", "documents", "id", from_email, doc_id)
                    if os.path.exists(ocr_dir):
                        import shutil
                        shutil.rmtree(ocr_dir)
                    print(f"[INFO] Deleted wrong document and OCR results: {filename}")
            
            if not doc_status["missing"] and not wrong_docs:
                missing_fields_msgs = []
                extracted_fields_msgs = []
                for doc_name, doc_info in ocr_results.items():
                    if doc_info.get("type") in ["commercial", "eid"]:
                        validation = doc_info.get("validation", {})
                        fields = doc_info.get("extracted_fields", {})
                        if fields:
                            field_lines = "\n".join([f"- {k}: {v}" for k, v in fields.items()])
                            extracted_fields_msgs.append(
                                f"{doc_info.get('type').capitalize()} Document ({doc_name}):\n{field_lines}"
                            )
                        if not validation.get("is_valid", False):
                            missing_fields = validation.get("missing_fields", [])
                            if missing_fields:
                                missing_fields_msgs.append(
                                    f"• {doc_name}: Missing fields - {', '.join(missing_fields)}"
                                )
                if missing_fields_msgs:
                    subject = "Documents Received but Missing Fields"
                    body = (
                        "Both your Commercial Registration Document and Resident Identity Card (EID) have been received and identified correctly.\n"
                        "However, some required fields are missing:\n"
                        + "\n".join(missing_fields_msgs)
                        + "\n\nPlease resend the documents ensuring all required fields are visible and readable."
                    )
                    send_email(to_email=from_email, subject=subject, body=body)
                    print(f"[INFO] Sent missing fields notification to: {from_email}")
                    return
                else:
                    subject = "Please Validate Your Extracted Information"
                    body = (
                        "<html><body style='font-family:Arial,sans-serif;'>"
                        "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
                        "<h2 style='color:#4CAF50;'>Extracted Information</h2>"
                        "<p>Dear User,</p>"
                        "<p>We have extracted the following information from your submitted documents:</p>"
                        f"<pre>{'<br><br>'.join(extracted_fields_msgs)}</pre>"
                        "<p>Please reply <strong>Yes</strong> if all the information above is correct. If anything is incorrect, reply with the corrections or resubmit your documents.</p>"
                        "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
                        "</div></body></html>"
                    )
                    send_email(to_email=from_email, subject=subject, body=body, html=True)
                    print(f"[INFO] Sent extracted fields for validation to: {from_email}")
                    return

            if doc_status["missing"]:
                subject = "Missing Document(s)"
                missing_list = "".join([f"<li>{doc}</li>" for doc in doc_status["missing"]])
                body = (
                    f"<html><body style='font-family:Arial,sans-serif;'>"
                    "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>"
                    "<h2 style='color:#e53935;'>Missing Document(s)</h2>"
                    "<p>Dear User,</p>"
                    "<p>We have received your submission. However, the following document(s) are still required:</p>"
                    f"<ul>{missing_list}</ul>"
                    "<p>Please reply to this email with the missing document(s) attached as image files.</p>"
                    "<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>"
                    "</div></body></html>"
                )
                send_email(to_email=from_email, subject=subject, body=body, html=True)
                return
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
                        doc_info = ocr_results.get(filename, {})
                        status_message = doc_info.get("status_message", "")
                        body += (
                            f"• {filename}: {status_message}\n"
                        )
                    body += "\n".join(summary_texts)
                    body += "\nYou need to submit commercial and eid documents.\n"
                body += "\nPlease reply to this email with the correct document(s) attached as image files."

            send_email(to_email=from_email, subject=subject, body=body)
            print(f"[INFO] Document verification result sent to: {from_email}")

            if doc_status["missing"] or wrong_docs:
                for filename, _ in wrong_docs:
                    image_path = os.path.join("backend", "documents", "id", from_email, filename)
                    if os.path.exists(image_path):
                        os.remove(image_path)
                    doc_id = os.path.splitext(filename)[0]
                    ocr_dir = os.path.join("backend", "documents", "id", from_email, doc_id)
                    print(f"[DEBUG] Checking to delete OCR dir: {ocr_dir},{image_path}")
                    if os.path.exists(ocr_dir):
                        import shutil
                        shutil.rmtree(ocr_dir)
                    print(f"[INFO] Deleted wrong document and OCR results: {from_email}")
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
