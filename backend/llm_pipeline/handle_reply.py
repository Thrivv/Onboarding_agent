# backend/llm_pipeline/handle_reply.py
from ingestion.faq_retriever import retrieve_similar_chunks
from llm_runner.prompt_templates import build_onboarding_prompt
from llm_runner.run_model import call_local_llm
from app.services.supabase_client import supabase
from app.services.email_sender import send_email
from app.services.ocr_service import process_document, format_document_name

from datetime import datetime
import os
import time
import json

LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-7b-instruct"

# ===========================
# DOCUMENT REQUIREMENTS LOGIC
# ===========================

def get_required_documents(account_type: str, ownership_type: str = None) -> dict:
    """
    Returns document requirements based on account flow
    """
    if account_type == "Savings":
        return {
            "stage": "single",
            "documents": ["eid", "ejari"],
            "message": "Please submit your Emirates ID (EID) and Ejari (Tenancy Contract)"
        }
    
    elif account_type == "Corporate":
        if ownership_type == "Single Owner":
            return {
                "stage": "single",
                "documents": ["commercial", "eid", "ejari"],
                "message": "Please submit your Commercial/Trade License, Emirates ID (EID), and Ejari"
            }
        
        elif ownership_type in ["Partnership", "@Multiple Owners"]:
            return {
                "stage": "identification",
                "documents": ["commercial", "moa"],
                "message": "First, please submit your Commercial License and MOA to identify all owners",
                "next_stage": "member_eids"
            }
    
    return None


def check_document_stage_completion(user_email: str, required_docs: list) -> dict:
    """
    Check if all required documents for current stage are submitted and valid
    FIXED VERSION - Actually reads output.json files
    """
    user_docs_dir = os.path.join("backend", "documents", "id", user_email)
    
    submitted = {
        "commercial": False,
        "eid": False,
        "ejari": False,
        "moa": False
    }
    
    if not os.path.exists(user_docs_dir):
        print(f"[DEBUG] Directory does not exist: {user_docs_dir}")
        return {
            "complete": False, 
            "submitted": submitted, 
            "missing": required_docs
        }
    
    print(f"[DEBUG] Scanning directory: {user_docs_dir}")
    print(f"[DEBUG] Looking for: {required_docs}")
    
    # List all items in directory
    all_items = os.listdir(user_docs_dir)
    print(f"[DEBUG] Found {len(all_items)} items in directory: {all_items}")
    
    # Check each item
    for item in all_items:
        item_path = os.path.join(user_docs_dir, item)
        
        # Skip files (only check directories)
        if not os.path.isdir(item_path):
            print(f"[DEBUG] Skipping file: {item}")
            continue
        
        # Skip member_progress.json directory (shouldn't exist but just in case)
        if item == "member_progress.json":
            print(f"[DEBUG] Skipping member_progress.json")
            continue
        
        # Check for output.json
        output_path = os.path.join(item_path, "output.json")
        print(f"[DEBUG] Checking: {item}/")
        
        if not os.path.exists(output_path):
            print(f"[DEBUG]   → No output.json found")
            continue
        
        # Read and parse output.json
        try:
            print(f"[DEBUG]   → Reading output.json...")
            with open(output_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            
            doc_type = analysis.get("document_type", "unknown")
            is_valid = analysis.get("is_valid", False)
            filename = analysis.get("filename", item)
            
            print(f"[DEBUG]   → Filename: {filename}")
            print(f"[DEBUG]   → Document type: {doc_type}")
            print(f"[DEBUG]   → Is valid: {is_valid}")
            
            # Update submission status if valid
            if doc_type in submitted:
                if is_valid:
                    submitted[doc_type] = True
                    print(f"[DEBUG]   → ✅ MARKED {doc_type.upper()} AS VALID")
                else:
                    print(f"[DEBUG]   → ❌ {doc_type.upper()} is INVALID")
            else:
                print(f"[DEBUG]   → ⚠️  Unknown document type: {doc_type}")
            
        except json.JSONDecodeError as e:
            print(f"[ERROR]   → Failed to parse JSON: {e}")
        except Exception as e:
            print(f"[ERROR]   → Error reading file: {e}")
    
    # Calculate missing documents
    missing = [doc for doc in required_docs if not submitted.get(doc, False)]
    complete = len(missing) == 0
    
    # Print final summary
    print(f"\n{'='*70}")
    print(f"[DEBUG] 📊 VALIDATION SUMMARY FOR {user_email}")
    print(f"{'='*70}")
    print(f"[DEBUG] Required documents: {required_docs}")
    print(f"[DEBUG] ")
    print(f"[DEBUG] Status by document type:")
    for doc_type in ["eid", "ejari", "commercial", "moa"]:
        if doc_type in required_docs:
            status = "✅ VALID" if submitted[doc_type] else "❌ MISSING"
            print(f"[DEBUG]   {doc_type:12} : {status}")
    print(f"[DEBUG] ")
    print(f"[DEBUG] Missing: {missing if missing else 'None'}")
    print(f"[DEBUG] Complete: {'YES ✅' if complete else 'NO ❌'}")
    print(f"{'='*70}\n")
    
    return {
        "complete": complete,
        "submitted": submitted,
        "missing": missing
    }

# ===========================
# MEMBER EXTRACTION LOGIC
# ===========================

def extract_members_from_documents(user_email: str) -> dict:
    """
    Extract member names from Commercial License and MOA
    FIXED: Only extract from MANAGERS field (not partners)
    
    Returns: {
        "members": list of member names (managers only),
        "includes_user": bool (whether registered user is in members list)
    }
    """
    user_docs_dir = os.path.join("backend", "documents", "id", user_email)
    member_names = []
    
    # Get registered user's name
    try:
        user_response = supabase.table("users").select("name").eq("email", user_email).execute()
        registered_user_name = user_response.data[0].get("name") if user_response.data else None
    except Exception as e:
        print(f"[ERROR] Failed to get user name: {e}")
        registered_user_name = None
    
    if not os.path.exists(user_docs_dir):
        return {"members": member_names, "includes_user": False}
    
    # Extract from documents
    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)
        
        # Skip member directories
        if os.path.isdir(item_path) and all(c.isalpha() or c.isspace() for c in item):
            continue
        
        if os.path.isdir(item_path):
            output_path = os.path.join(item_path, "output.json")
            
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    
                    doc_type = analysis.get("document_type")
                    
                    # Extract from Commercial License - MANAGERS ONLY
                    if doc_type == "commercial":
                        extracted_fields = analysis.get("extracted_fields", {})
                        
                        # Get MANAGERS ONLY (company officers/members who need EIDs)
                        managers = extracted_fields.get("managers", [])
                        
                        print(f"[DEBUG] Found {len(managers)} managers in Commercial License")
                        
                        # Extract manager names
                        for manager in managers:
                            name = manager.get("name_english", "").strip()
                            if name:
                                member_names.append(name)
                                print(f"[DEBUG] Added manager: {name}")
                        
                        # NOTE: We IGNORE partners - they are shareholders only
                    
                    # Extract from MOA
                    elif doc_type == "moa":
                        extracted_fields = analysis.get("extracted_fields", {})
                        english_data = extracted_fields.get("english", {})
                        
                        # Get owner and manager names
                        owner_name = english_data.get("owner_name", "").strip()
                        manager_name = english_data.get("manager_name", "").strip()
                        
                        if owner_name:
                            member_names.append(owner_name)
                            print(f"[DEBUG] Added MOA owner: {owner_name}")
                        if manager_name and manager_name != owner_name:
                            member_names.append(manager_name)
                            print(f"[DEBUG] Added MOA manager: {manager_name}")
                
                except Exception as e:
                    print(f"[ERROR] Failed to read {output_path}: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_names = []
    for name in member_names:
        name_lower = name.lower()
        if name and name_lower not in seen:
            seen.add(name_lower)
            unique_names.append(name)
    
    print(f"[INFO] Extracted {len(unique_names)} unique managers from documents")
    
    # Check if registered user is already in the list
    user_in_list = False
    if registered_user_name:
        registered_name_lower = registered_user_name.lower()
        
        for member in unique_names:
            member_lower = member.lower()
            if (registered_name_lower in member_lower or 
                member_lower in registered_name_lower or
                registered_name_lower == member_lower):
                user_in_list = True
                print(f"[INFO] Registered user '{registered_user_name}' found as '{member}'")
                break
        
        # If user NOT in list, add them at the beginning
        if not user_in_list:
            unique_names.insert(0, registered_user_name)
            print(f"[INFO] Added registered user '{registered_user_name}' to member list")
    
    print(f"[INFO] Final member list ({len(unique_names)} managers): {unique_names}")
    
    return {
        "members": unique_names,
        "includes_user": user_in_list or (registered_user_name in unique_names if registered_user_name else False)
    }


# ===========================
# MEMBER PROGRESS TRACKING
# ===========================

def get_member_progress(user_email: str):
    """Load member processing progress from JSON file."""
    progress_file = os.path.join("backend", "documents", "id", user_email, "member_progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to load member progress: {e}")
            return None
    return None


def save_member_progress(user_email: str, members: list, current_index: int):
    """Save member processing progress to JSON file."""
    progress_dir = os.path.join("backend", "documents", "id", user_email)
    os.makedirs(progress_dir, exist_ok=True)
    
    progress_file = os.path.join(progress_dir, "member_progress.json")
    progress_data = {
        "members": members,
        "current_index": current_index,
        "updated_at": datetime.utcnow().isoformat()
    }
    
    try:
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Saved member progress: Member {current_index + 1}/{len(members)}")
    except Exception as e:
        print(f"[ERROR] Failed to save member progress: {e}")


# ===========================
# DOCUMENT PROCESSING
# ===========================

def process_user_documents(from_email: str, attachments: list, is_member: bool = False, member_name: str = None):
    """
    Process user/member documents with specialized extractors
    """
    if is_member and member_name:
        save_dir = os.path.join("backend", "documents", "id", from_email, member_name)
        user_path = f"{from_email}/{member_name}"
    else:
        save_dir = os.path.join("backend", "documents", "id", from_email)
        user_path = from_email
        
    os.makedirs(save_dir, exist_ok=True)
    
    processed_results = {
        "success": [],
        "failed": [],
        "invalid": [],
        "wrong_type": []
    }
    
    for attachment in attachments:
        filename = attachment["filename"]
        filedata = attachment["data"]
        
        filepath = os.path.join(save_dir, filename)
        with open(filepath, "wb") as f:
            f.write(filedata)
        
        document_id = os.path.splitext(filename)[0]
        
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            model = LLAMA_MODEL_NAME
        else:
            model = QWEN_MODEL_NAME
        
        try:
            result = process_document(
                user_email=user_path,
                document_id=document_id,
                file_path=filepath,
                model_name=model,
                is_member=is_member
            )
            
            doc_type = result.get("document_type", "unknown")
            is_valid = result.get("is_valid", False)
            
            if is_member:
                # For members, ONLY accept EID
                if doc_type == "eid" and is_valid:
                    processed_results["success"].append({
                        "filename": filename,
                        "type": doc_type,
                        "result": result
                    })
                elif doc_type != "eid":
                    processed_results["wrong_type"].append({
                        "filename": filename,
                        "type": doc_type,
                        "expected": "eid"
                    })
                else:
                    processed_results["invalid"].append({
                        "filename": filename,
                        "type": doc_type,
                        "issues": result.get("validation", {}).get("missing_fields", [])
                    })
            else:
                # For main user, accept any valid document
                if is_valid:
                    processed_results["success"].append({
                        "filename": filename,
                        "type": doc_type,
                        "result": result
                    })
                elif doc_type == "unknown":
                    processed_results["wrong_type"].append({
                        "filename": filename,
                        "type": doc_type,
                        "expected": "eid, commercial, ejari, or moa"
                    })
                else:
                    processed_results["invalid"].append({
                        "filename": filename,
                        "type": doc_type,
                        "issues": result.get("validation", {}).get("missing_fields", [])
                    })
            
            # Wait 60 seconds between API calls to avoid rate limits
            time.sleep(60)
            
        except Exception as e:
            print(f"[ERROR] Failed to process {filename}: {e}")
            processed_results["failed"].append({
                "filename": filename,
                "error": str(e)
            })
    
    return processed_results


# ===========================
# EMAIL NOTIFICATIONS
# ===========================

def send_document_status_email(to_email: str, results: dict, is_member: bool = False, member_name: str = None):
    """Send email about document processing results"""
    
    success_docs = results.get("success", [])
    invalid_docs = results.get("invalid", [])
    wrong_type_docs = results.get("wrong_type", [])
    failed_docs = results.get("failed", [])
    
    if is_member:
        subject = f"Document Processing Results for {member_name}"
        greeting = f"<p>Dear User,</p><p>We have processed the documents for <strong>{member_name}</strong>:</p>"
    else:
        subject = "Document Processing Results"
        greeting = "<p>Dear User,</p><p>We have processed your submitted documents:</p>"
    
    body_parts = [
        "<html><body style='font-family:Arial,sans-serif;color:#333;'>",
        "<div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>",
        f"<h2 style='color:#4CAF50;'>{subject}</h2>",
        greeting
    ]
    
    if success_docs:
        body_parts.append("<div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:15px 0;'>")
        body_parts.append("<h3 style='color:#2e7d32;margin-top:0;'>✅ Successfully Verified</h3>")
        body_parts.append("<ul>")
        for doc in success_docs:
            doc_name = format_document_name(doc["type"])
            body_parts.append(f"<li><strong>{doc_name}</strong> ({doc['filename']})</li>")
        body_parts.append("</ul>")
        body_parts.append("</div>")
    
    if invalid_docs:
        body_parts.append("<div style='background:#fff3e0;padding:15px;border-radius:5px;margin:15px 0;'>")
        body_parts.append("<h3 style='color:#f57c00;margin-top:0;'>⚠️ Documents with Missing Fields</h3>")
        body_parts.append("<ul>")
        for doc in invalid_docs:
            doc_name = format_document_name(doc["type"])
            missing = ", ".join(doc.get("issues", []))
            body_parts.append(f"<li><strong>{doc_name}</strong> ({doc['filename']})<br>Missing: {missing}</li>")
        body_parts.append("</ul>")
        body_parts.append("<p>Please resubmit these documents with all required fields visible.</p>")
        body_parts.append("</div>")
    
    if wrong_type_docs:
        body_parts.append("<div style='background:#ffebee;padding:15px;border-radius:5px;margin:15px 0;'>")
        body_parts.append("<h3 style='color:#c62828;margin-top:0;'>❌ Incorrect Document Type</h3>")
        body_parts.append("<ul>")
        for doc in wrong_type_docs:
            expected = doc.get("expected", "correct document")
            body_parts.append(f"<li><strong>{doc['filename']}</strong><br>Expected: {expected}</li>")
        body_parts.append("</ul>")
        body_parts.append("<p>Please submit the correct document types.</p>")
        body_parts.append("</div>")
    
    if failed_docs:
        body_parts.append("<div style='background:#ffebee;padding:15px;border-radius:5px;margin:15px 0;'>")
        body_parts.append("<h3 style='color:#c62828;margin-top:0;'>❌ Processing Errors</h3>")
        body_parts.append("<ul>")
        for doc in failed_docs:
            body_parts.append(f"<li><strong>{doc['filename']}</strong><br>Error: {doc.get('error', 'Unknown error')}</li>")
        body_parts.append("</ul>")
        body_parts.append("<p>Please try resubmitting these documents.</p>")
        body_parts.append("</div>")
    
    body_parts.append("<p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>")
    body_parts.append("</div></body></html>")
    
    body_html = "".join(body_parts)
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_missing_documents_email(to_email: str, missing_docs: list, context: str):
    """Send email requesting missing documents"""
    doc_names = [format_document_name(doc) for doc in missing_docs]
    
    subject = f"Missing Documents - {context}"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#ff9800;'>📋 Missing Documents</h2>
            <p>Dear User,</p>
            <p>To continue your <strong>{context}</strong> onboarding, please submit the following documents:</p>
            <ul style='margin-left:20px;background:#fff3e0;padding:20px;border-radius:5px;'>
                {''.join([f'<li><strong>{doc}</strong></li>' for doc in doc_names])}
            </ul>
            <p>Please reply to this email with the required documents attached.</p>
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_completion_email(to_email: str, account_type: str):
    """Send onboarding completion email"""
    subject = "🎉 Onboarding Complete!"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>🎉 Onboarding Complete!</h2>
            <p>Dear User,</p>
            <p>Congratulations! Your <strong>{account_type}</strong> account onboarding is complete.</p>
            <p>All required documents have been verified successfully.</p>
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>✅ Next Steps:</strong></p>
                <p style='margin:10px 0 0 0;'>Your account will be activated within <strong>3-4 business days</strong>. You will receive a confirmation email with your account details.</p>
            </div>
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_member_identification_email(to_email: str, members: list, includes_user: bool):
    """
    Send email after identifying all members, listing everyone
    """
    try:
        user_response = supabase.table("users").select("name").eq("email", to_email).execute()
        user_name = user_response.data[0].get("name") if user_response.data else "User"
    except:
        user_name = "User"
    
    subject = "✅ Multiple Owners Identified - EID Collection Process"
    
    # Build member list HTML
    member_list_html = ""
    for i, member in enumerate(members, 1):
        is_registered_user = (member.lower() == user_name.lower())
        marker = " <span style='color:#2196F3;'>(You - Registered User)</span>" if is_registered_user else ""
        member_list_html += f"<li><strong>{member}</strong>{marker}</li>"
    
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>✅ Owners Identified Successfully</h2>
            <p>Dear {user_name},</p>
            
            <p>We have analyzed your Commercial License and MOA documents and identified the following <strong>{len(members)} owners/members</strong>:</p>
            
            <div style='background:#f8f9fa;padding:20px;border-radius:5px;margin:20px 0;'>
                <ol style='margin:0;padding-left:20px;'>
                    {member_list_html}
                </ol>
            </div>
            
            <p><strong>Next Step:</strong> We will now collect Emirates ID (EID) for each member/owner, one by one.</p>
            
            <div style='background:#e3f2fd;padding:15px;border-left:4px solid #2196F3;margin:20px 0;'>
                <p style='margin:0;'><strong>📋 Total EIDs Required: {len(members)}</strong></p>
                <p style='margin:10px 0 0 0;'>{'✓ Including your EID as the registered user' if not includes_user else '✓ Your EID is included in the member list'}</p>
            </div>
            
            <p>You will receive a separate email requesting the EID for the first member shortly.</p>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_member_eid_request_email(to_email: str, member_name: str, member_num: int, total_members: int):
    """Request EID for specific member"""
    subject = f"📄 EID Required for {member_name} (Member {member_num}/{total_members})"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>📄 EID Required for {member_name}</h2>
            <p>Dear User,</p>
            
            <div style='background:#e3f2fd;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>Progress:</strong> Member {member_num} of {total_members}</p>
            </div>
            
            <p>Please submit the <strong>Emirates ID (EID)</strong> for:</p>
            <div style='background:#f8f9fa;padding:15px;border-radius:5px;margin:15px 0;text-align:center;'>
                <h3 style='margin:0;color:#2196F3;'>{member_name}</h3>
            </div>
            
            <p><strong>Instructions:</strong></p>
            <ul style='margin-left:20px;'>
                <li>Reply to this email with the EID document attached</li>
                <li>Accepted formats: PDF, PNG, JPG, JPEG</li>
                <li>Ensure all fields are clearly visible</li>
            </ul>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_all_members_complete_email(to_email: str, members: list):
    """Send completion email after all members processed"""
    subject = "🎉 All Member Documents Verified - Onboarding Complete!"
    
    member_list_html = "".join([f"<li><strong>{name}</strong></li>" for name in members])
    
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>🎉 All Member Documents Verified!</h2>
            <p>Dear User,</p>
            <p>Congratulations! We have successfully verified EID documents for all <strong>{len(members)} members/owners</strong>:</p>
            
            <div style='background:#e8f5e9;padding:20px;border-radius:5px;margin:20px 0;'>
                <ul style='margin:0;padding-left:20px;'>
                    {member_list_html}
                </ul>
            </div>
            
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>✅ All {len(members)} EIDs Verified Successfully</strong></p>
            </div>
            
            <p>Your onboarding process is now complete. Welcome to Thrivv!</p>
            
            <p><strong>Next Steps:</strong></p>
            <ul style='margin-left:20px;'>
                <li>Your account will be activated within 3-4 business days</li>
                <li>You will receive account details via email</li>
                <li>If you have any questions, feel free to reply to this email</li>
            </ul>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


# ===========================
# MAIN REPLY HANDLER
# ===========================

def process_user_reply(from_email: str, body: str, attachments: list = None):
    """
    Enhanced reply handler with flow-based document requests
    """
    print(f"\n{'='*80}")
    print(f"[INFO] NEW EMAIL PROCESSING STARTED")
    print(f"[INFO] From: {from_email}")
    print(f"[INFO] Attachments: {len(attachments) if attachments else 0}")
    print(f"{'='*80}\n")
    # Get user data
    user_response = supabase.table("users").select("*").eq("email", from_email).execute()
    if not user_response.data:
        print(f"[WARN] Email not found: {from_email}")
        return
    
    user = user_response.data[0]
    account_type = user.get("account_type")
    ownership_type = user.get("ownership_type")
    onboarding_step = user.get("onboarding_step", "welcome")
    document_stage = user.get("document_stage", "identification")
    
    print(f"[INFO] Processing reply from {from_email}")
    print(f"       Account Type: {account_type}")
    print(f"       Ownership Type: {ownership_type}")
    print(f"       Onboarding Step: {onboarding_step}")
    print(f"       Document Stage: {document_stage}")
    
    # Get document requirements for this user's flow
    doc_requirements = get_required_documents(account_type, ownership_type)
    
    if not doc_requirements:
        print(f"[ERROR] Could not determine document requirements for {from_email}")
        return
    
    # ========================================
    # PROCESS ATTACHMENTS
    # ========================================
    if attachments:
        print(f"[INFO] Processing {len(attachments)} documents for {from_email}")
        
        # === CORPORATE - MULTIPLE OWNERS - MEMBER EID COLLECTION ===
        if (account_type == "Corporate" and 
            ownership_type in ["Partnership", "@Multiple Owners"] and
            document_stage == "member_eids"):
            
            print("[INFO] Processing member EID documents")
            
            progress = get_member_progress(from_email)
            
            if not progress:
                print(f"[ERROR] No member progress found for {from_email}")
                return
            
            members = progress["members"]
            current_index = progress["current_index"]
            
            if current_index >= len(members):
                print(f"[ERROR] Invalid member index: {current_index}/{len(members)}")
                return
            
            current_member = members[current_index]
            print(f"[INFO] Processing documents for member {current_index + 1}/{len(members)}: {current_member}")
            
            # Process documents for current member
            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=True,
                member_name=current_member
            )
            
            # Check if valid EID received
            success_eid = any(
                doc["type"] == "eid" 
                for doc in results.get("success", [])
            )
            
            if success_eid:
                print(f"[SUCCESS] Valid EID received for {current_member}")
                
                # Move to next member
                current_index += 1
                
                if current_index < len(members):
                    # Request next member's EID
                    next_member = members[current_index]
                    save_member_progress(from_email, members, current_index)
                    
                    print(f"[INFO] Requesting EID for next member: {next_member}")
                    
                    send_member_eid_request_email(
                        from_email,
                        next_member,
                        current_index + 1,
                        len(members)
                    )
                    return
                else:
                    # All members processed - Complete onboarding
                    print(f"[SUCCESS] All {len(members)} member EIDs collected!")
                    
                    supabase.table("users").update({
                        "onboarding_step": "verification_complete"
                    }).eq("email", from_email).execute()
                    
                    send_all_members_complete_email(from_email, members)
                    return
            else:
                # Invalid/missing EID - request again
                print(f"[WARN] Invalid EID for {current_member}, requesting resubmission")
                
                send_document_status_email(
                    from_email,
                    results,
                    is_member=True,
                    member_name=current_member
                )
                
                # Keep same index - user needs to resubmit
                save_member_progress(from_email, members, current_index)
                return
        
        # === REGULAR DOCUMENT PROCESSING (NON-MEMBER) ===
        else:
            print("[INFO] Processing user documents (non-member flow)")
            
            # Process documents
            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=False
            )
            
            # Send processing results email
            send_document_status_email(from_email, results, is_member=False)
            
            # === CHECK FLOW STAGE COMPLETION ===
            
            # ====================================
            # STAGE 1: SAVINGS ACCOUNT
            # ====================================
            if account_type == "Savings":
                print("[INFO] Checking Savings Account completion")
                
                stage_check = check_document_stage_completion(
                    from_email, 
                    ["eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] All Savings Account documents received")
                    
                    # All documents received - Complete onboarding
                    supabase.table("users").update({
                        "onboarding_step": "verification_complete"
                    }).eq("email", from_email).execute()
                    
                    send_completion_email(from_email, "Savings Account")
                    return
                else:
                    # Request missing documents
                    print(f"[INFO] Missing documents: {stage_check['missing']}")
                    
                    send_missing_documents_email(
                        from_email, 
                        stage_check["missing"],
                        "Savings Account"
                    )
                    return
            
            # ====================================
            # STAGE 2: CORPORATE - SINGLE OWNER
            # ====================================
            elif account_type == "Corporate" and ownership_type == "Single Owner":
                print("[INFO] Checking Corporate Single Owner completion")
                
                stage_check = check_document_stage_completion(
                    from_email,
                    ["commercial", "eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] All Corporate Single Owner documents received")
                    
                    # All documents received - Complete onboarding
                    supabase.table("users").update({
                        "onboarding_step": "verification_complete"
                    }).eq("email", from_email).execute()
                    
                    send_completion_email(from_email, "Corporate - Single Owner")
                    return
                else:
                    # Request missing documents
                    print(f"[INFO] Missing documents: {stage_check['missing']}")
                    
                    send_missing_documents_email(
                        from_email,
                        stage_check["missing"],
                        "Corporate Single Owner"
                    )
                    return
            
            # ====================================
            # STAGE 3: CORPORATE - MULTIPLE OWNERS
            # ====================================
            elif account_type == "Corporate" and ownership_type in ["Partnership", "@Multiple Owners"]:
                print("[INFO] Checking Corporate Multiple Owners stage")
                
                # Check current stage
                if document_stage == "identification":
                    print("[INFO] Stage: Identification (need Commercial + MOA)")
                    
                    # Stage 1: Need Commercial + MOA to identify owners
                    stage_check = check_document_stage_completion(
                        from_email,
                        ["commercial", "moa"]
                    )
                    
                    if stage_check["complete"]:
                        print("[SUCCESS] Commercial + MOA received, extracting members")
                        
                        # Extract members from documents
                        member_data = extract_members_from_documents(from_email)
                        member_names = member_data["members"]
                        includes_user = member_data["includes_user"]
                        
                        if member_names and len(member_names) > 0:
                            print(f"[INFO] Identified {len(member_names)} total members/owners")
                            print(f"       - Registered user included in list: {includes_user}")
                            print(f"       - Total EIDs to collect: {len(member_names)}")
                            
                            # Create directories for each member
                            base_docs_dir = os.path.join("backend", "documents", "id", from_email)
                            for member_name in member_names:
                                member_dir = os.path.join(base_docs_dir, member_name)
                                os.makedirs(member_dir, exist_ok=True)
                                print(f"       Created directory: {member_dir}")
                            
                            # Save progress - start with first member
                            save_member_progress(from_email, member_names, 0)
                            
                            # Update stage
                            supabase.table("users").update({
                                "document_stage": "member_eids",
                                "onboarding_step": "member_documents_required"
                            }).eq("email", from_email).execute()
                            
                            # Send identification summary email
                            send_member_identification_email(
                                from_email,
                                member_names,
                                includes_user
                            )
                            
                            # Request first member's EID
                            send_member_eid_request_email(
                                from_email,
                                member_names[0],
                                1,
                                len(member_names)
                            )
                            
                            print(f"[INFO] Requested EID for first member: {member_names[0]}")
                            return
                        else:
                            # No members found - error
                            print("[ERROR] Could not identify owners from documents")
                            
                            subject = "Error Identifying Owners"
                            body_html = """
                            <html><body style='font-family:Arial,sans-serif;color:#333;'>
                                <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
                                    <h2 style='color:#c62828;'>❌ Error Identifying Owners</h2>
                                    <p>Dear User,</p>
                                    <p>We could not identify the owners/members from your Commercial License and MOA documents.</p>
                                    <p>Please ensure:</p>
                                    <ul>
                                        <li>The Commercial License contains the partners/members section</li>
                                        <li>The MOA contains owner/manager information</li>
                                        <li>All text is clearly visible and readable</li>
                                    </ul>
                                    <p>Please resubmit clear copies of both documents.</p>
                                    <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
                                </div>
                            </body></html>
                            """
                            send_email(to_email=from_email, subject=subject, body=body_html, html=True)
                            return
                    else:
                        # Still need Commercial and/or MOA
                        print(f"[INFO] Still need documents: {stage_check['missing']}")
                        
                        send_missing_documents_email(
                            from_email,
                            stage_check["missing"],
                            "Multiple Owners - Identification Stage"
                        )
                        return
    
    # ========================================
    # NO ATTACHMENTS - REGULAR CHAT
    # ========================================
    print("[INFO] No attachments, processing as chat message")
    
    # Log user message
    supabase.table("conversations").insert({
        "user_email": from_email,
        "role": "user",
        "message": body,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()
    
    # Get conversation context
    try:
        top_chunks = retrieve_similar_chunks(body, top_k=3)
        faq_context = "\n\n".join(top_chunks)
    except Exception as e:
        print(f"[WARN] FAQ retrieval failed: {e}")
        faq_context = ""
    
    # Get conversation history
    try:
        convo_response = supabase.table("conversations").select("*").eq("user_email", from_email).order("timestamp").execute()
        convo_history = convo_response.data if convo_response.data else []
        convo_context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in convo_history[-6:]])  # Last 6 messages
    except Exception as e:
        print(f"[WARN] Conversation history retrieval failed: {e}")
        convo_context = ""
    
    full_context = f"Onboarding Step: {onboarding_step}\n\n{convo_context}\n\nFAQ:\n{faq_context}"
    
    # Build prompt and get LLM response
    try:
        prompt = build_onboarding_prompt(
            user_message=body, 
            context=full_context,
            registration_data={
                'name': user.get('name'),
                'email': user.get('email'),
                'business_name': user.get('business_name'),
                'account_type': user.get('account_type'),
                'ownership_type': user.get('ownership_type'),
            }
        )
        
        llm_response = call_local_llm(prompt)
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        llm_response = "Thank you for your message. Our team will respond to you shortly."
    
    # Send reply email
    subject = "Re: Your query with Thrivv"
    send_email(to_email=from_email, subject=subject, body=llm_response)
    
    # Log agent response
    supabase.table("conversations").insert({
        "user_email": from_email,
        "role": "agent",
        "message": llm_response,
        "timestamp": datetime.utcnow().isoformat()
    }).execute()
    
    print(f"[INFO] Chat response sent to: {from_email}")