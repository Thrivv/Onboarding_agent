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
from fpdf import FPDF
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
            status = "VALID" if submitted[doc_type] else "MISSING"
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
    """Process user/member documents with specialized extractors"""
    
    # First get user info and account type
    user_response = supabase.table("users").select("name", "dob", "account_type", "ownership_type").eq("email", from_email).execute()
    user_info = user_response.data[0] if user_response.data else {}
    account_type = user_info.get("account_type", "")
    ownership_type = user_info.get("ownership_type", "")
    user_name = user_info.get("name", "").strip().lower()

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

    # --- Fetch user info for name validation (EID only) ---
    user_response = supabase.table("users").select("name", "dob").eq("email", from_email).execute()
    user_info = user_response.data[0] if user_response.data else {}
    user_name = user_info.get("name", "").strip().lower()
    user_dob = user_info.get("dob", "").strip()

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

            # --- Name validation ONLY for EID ---
            extracted = result.get("extracted_fields", {})
            print("[DEBUG-375] Extracted Data:", extracted)
            extracted_name = ""
            name_match = True  # Default to True (no validation for non-EID docs)

            # ONLY extract and validate name for EID documents
            if doc_type == "eid":
                extracted_name = extracted.get("Name", "").strip().lower()
                print(f"[DEBUG] Document: {filename} | Type: {doc_type}")
                print(f"[DEBUG] Extracted Name: '{extracted_name}' | Expected Name: '{user_name}'")
                
                # Only validate name for Savings and Single Owner Corporate
                should_validate = (
                    account_type == "Savings" or 
                    (account_type == "Corporate" and ownership_type == "Single Owner")
                )
                
                if should_validate:
                    name_match = user_name and extracted_name and (user_name in extracted_name or extracted_name in user_name)
                    print(f"[DEBUG] Name validation performed: {name_match}")
                else:
                    name_match = True
                    print(f"[DEBUG] Name validation SKIPPED for Multiple Owners")

            # ONLY apply validation rejection for EID documents
            if doc_type == "eid" and not name_match:
                print(f"[WARN] Name mismatch for EID {filename}. Marking as invalid and requesting resubmission.")
                # Update output.json to reflect invalid status
                output_json_path = os.path.join(save_dir, os.path.splitext(filename)[0], "output.json")
                if os.path.exists(output_json_path):
                    try:
                        with open(output_json_path, "r", encoding="utf-8") as f:
                            output_data = json.load(f)
                        output_data["is_valid"] = False
                        output_data["validation"] = output_data.get("validation", {})
                        output_data["validation"]["name_mismatch"] = True
                        with open(output_json_path, "w", encoding="utf-8") as f:
                            json.dump(output_data, f, ensure_ascii=False, indent=2)
                        print(f"[DEBUG] Updated output.json for {filename} to set is_valid=False due to name mismatch.")
                    except Exception as e:
                        print(f"[ERROR] Could not update output.json for {filename}: {e}")

                processed_results["invalid"].append({
                    "filename": filename,
                    "type": doc_type,
                    "issues": ["Name mismatch with registration data"],
                    "extracted_name": extracted_name,
                    "expected_name": user_name
                })
                continue
            else:
                print(f"[DEBUG] Validation passed for {filename} (type: {doc_type})")

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
                        "issues": result.get("validation", {}).get("missing_fields", []),
                        "extracted_name": extracted_name,
                        "expected_name": user_name
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
                        "issues": result.get("validation", {}).get("missing_fields", []),
                        "extracted_name": extracted_name,
                        "expected_name": user_name
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
    """Send email about document processing results with a single confirm link and per-document resubmit links"""
    try:
        from urllib.parse import quote
        API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

        files_html = ""
        entries = []
        if isinstance(results, dict):
            for key in ("success", "failed", "invalid", "wrong_type"):
                entries.extend(results.get(key, []))
        elif isinstance(results, list):
            entries = results

        for item in entries:
            filename = item.get("filename") or item.get("name") or "Unknown"
            doc_type = item.get("document_type", item.get("type", "unknown")).upper()
            extracted = {}
            if "result" in item and isinstance(item["result"], dict):
                extracted = item["result"].get("extracted_fields", {})
            else:
                extracted = item.get("extracted_fields", {})

            # Format extracted fields in a user-friendly way
            extracted_html = ""
            if isinstance(extracted, dict):
                if "english" in extracted:
                    # For Commercial License and Ejari
                    eng_data = extracted["english"]
                    if doc_type == "COMMERCIAL":
                        fields_to_show = [
                            ("Company Name", eng_data.get("company_name_english")),
                            ("License Number", eng_data.get("license_number")),
                            ("Issue Date", eng_data.get("issue_date")),
                            ("Expiry Date", eng_data.get("expiry_date")),
                            ("Legal Type", eng_data.get("legal_type")),
                            ("Activities", "<br>".join(filter(None, [
                                eng_data.get("activity_1"),
                                eng_data.get("activity_2"),
                                eng_data.get("activity_3"),
                                eng_data.get("activity_4")
                            ])))
                        ]
                        # Add owner info if present
                        owner = extracted.get("owner", {})
                        if owner:
                            fields_to_show.extend([
                                ("Owner Name", owner.get("name_english")),
                                ("Nationality", owner.get("nationality_english")),
                                ("Share Percentage", owner.get("share_percentage"))
                            ])
                    elif doc_type == "EJARI":
                        fields_to_show = [
                            ("Contract Number", eng_data.get("contract_number")),
                            ("Registration Date", eng_data.get("registration_date")),
                            ("Owner Name", eng_data.get("owner_name")),
                            ("Owner Number", eng_data.get("owner_number")),
                            ("Tenant Company",eng_data.get("tenant_company")),
                            ("Start Date", eng_data.get("start_date")),
                            ("End Date", eng_data.get("end_date")),
                            ("Plot Number", eng_data.get("plot_number"))
                        ]
                else:
                    # For EID
                    fields_to_show = [
                        (k.replace("_", " ").title(), v) 
                        for k, v in extracted.items()
                        if v and k not in ["document_type", "raw_text"]
                    ]

                extracted_html = "".join([
                    f"""<div style='margin-bottom:8px;'>
                        <strong style='color:#444;'>{label}:</strong>
                        <span style='color:#666;'>{value}</span>
                    </div>"""
                    for label, value in fields_to_show
                    if value
                ])

            resubmit_link = f"{API_BASE}/chat/resubmit-document?email={quote(to_email)}&filename={quote(filename)}"

            files_html += f"""
                <div style='margin-bottom:24px;padding:16px;border:1px solid #e0e0e0;border-radius:8px;background:#fff;'>
                    <h3 style='margin:0 0 12px 0;color:#1976d2;font-size:16px;'>
                        {filename}
                        <span style='font-size:13px;color:#666;margin-left:8px;'>({doc_type})</span>
                    </h3>
                    <div style='background:#f5f5f5;padding:12px;border-radius:6px;margin-bottom:12px;'>
                        {extracted_html}
                    </div>
                    <a href="{resubmit_link}" style='display:inline-block;padding:8px 16px;background:#f44336;color:#fff;border-radius:4px;text-decoration:none;font-size:14px;'>
                        Request Resubmission
                    </a>
                </div>
            """

        # Only one confirm button at the end
        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"

        subject = "Your document extraction results — please confirm"
        body_html = f"""
        <html><body>
        <div style='font-family:Arial,Helvetica,sans-serif;'>
            <h3 style='margin-bottom:8px;'>We processed your document(s). Please verify the extracted information</h3>
            <p>Dear user,</p>
            <p>We have extracted the following data from your submitted document(s). Please review each file and either request a <strong>Resubmission</strong> if any detail is incorrect, or <strong>Confirm</strong> if all information is correct.</p>
            {files_html}
            <div style='margin-top:24px;text-align:center;'>
                <a href="{confirm_link}" style='display:inline-block;padding:12px 24px;background:#4caf50;color:#fff;border-radius:6px;text-decoration:none;font-size:18px;'>Confirm All Information is Correct</a>
            </div>
            <p>If you request resubmission, please reply to this email with corrected files or upload using the document upload feature in your account.</p>
            <p style='margin-top:24px;'>Best regards,<br/><strong>Thrivv Onboarding Team</strong></p>
        </div>
        </body></html>
        """

        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        print(f"[INFO] Sent document status email with single confirmation link to {to_email}")

    except Exception as e:
        print(f"[ERROR] Failed to send document status email: {e}")


def send_missing_documents_email(to_email: str, missing_docs: list, context: str, invalid_reasons: dict = None):
    """Send email requesting missing documents, with reasons if available"""
    doc_names = [format_document_name(doc) for doc in missing_docs]
    invalid_reasons = invalid_reasons or {}

    subject = f"Missing Documents - {context}"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#ff9800;'>📋 Missing Documents</h2>
            <p>Dear User,</p>
            <p>To continue your <strong>{context}</strong> onboarding, please submit the following documents:</p>
            <ul style='margin-left:20px;background:#fff3e0;padding:20px;border-radius:5px;'>
                {''.join([
                    f'<li><strong>{format_document_name(doc)}</strong>'
                    + (f'<br><span style="color:#e53935;">Reason: {invalid_reasons.get(doc, "")}</span>' if invalid_reasons.get(doc) else '')
                    + '</li>'
                    for doc in missing_docs
                ])}
            </ul>
            <p>Please reply to this email with the required documents attached.</p>
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)

# ===========================
# GENERATE SUMMARY
# ===========================

def generate_user_summary_pdf(user: dict, user_docs_dir: str, output_path: str):
    """
    Generate a comprehensive PDF summary with user data and all extracted document fields
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ===== HEADER =====
    pdf.set_font("Arial", "B", 24)
    pdf.set_text_color(65, 105, 225)  # Royal Blue
    pdf.cell(0, 15, "Onboarding Summary", ln=True, align="C")
    pdf.ln(3)
    
    pdf.set_font("Arial", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Generated on: {datetime.now().strftime('%B %d, %Y at %H:%M')}", ln=True, align="C")
    pdf.ln(8)

    # ===== USER DETAILS SECTION =====
    pdf.set_font("Arial", "B", 16)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(0, 10, " User Information", ln=True, fill=True)
    pdf.ln(3)
    
    pdf.set_font("Arial", "", 11)
    user_fields = [
        ("Name", "name"),
        ("Email", "email"),
        ("Phone Number", "phone_number"),
        ("Date of Birth", "dob"),
        ("Business Name", "business_name"),
        ("Account Type", "account_type"),
        ("Ownership Type", "ownership_type"),
    ]
    
    for label, key in user_fields:
        value = user.get(key, "N/A")
        if value and value != "N/A":
            pdf.set_font("Arial", "B", 11)
            pdf.cell(50, 7, f"{label}:", 0)
            pdf.set_font("Arial", "", 11)
            pdf.cell(0, 7, str(value), ln=True)
    
    pdf.ln(8)

    # ===== DOCUMENTS SECTION =====
    pdf.set_font("Arial", "B", 16)
    pdf.set_fill_color(255, 245, 230)
    pdf.cell(0, 10, " Submitted Documents", ln=True, fill=True)
    pdf.ln(3)

    if not os.path.exists(user_docs_dir):
        pdf.set_font("Arial", "I", 11)
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 8, f"No documents found at: {user_docs_dir}", ln=True)
    else:
        all_items = os.listdir(user_docs_dir)
        doc_count = 0
        
        for item in all_items:
            item_path = os.path.join(user_docs_dir, item)
            if not os.path.isdir(item_path):
                continue
            
            output_path_json = os.path.join(item_path, "output.json")
            if not os.path.exists(output_path_json):
                continue
            
            try:
                with open(output_path_json, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                
                doc_count += 1
                filename = analysis.get("filename", item)
                doc_type = analysis.get("document_type", "unknown").lower()
                is_valid = analysis.get("is_valid", False)
                extracted = analysis.get("extracted_fields", {})
                
                # Document Header
                pdf.set_font("Arial", "B", 13)
                pdf.set_text_color(40, 70, 150)
                status_icon = "Right" if is_valid else "Wrong"
                pdf.cell(0, 8, f"{doc_count}. {filename} ({doc_type.upper()}) {status_icon}", ln=True)
                
                pdf.set_font("Arial", "", 10)
                pdf.set_text_color(0, 0, 0)
                
                # Extracted Fields
                if isinstance(extracted, dict) and extracted:
                    pdf.set_font("Arial", "B", 10)
                    pdf.cell(0, 6, "Extracted Information:", ln=True)
                    pdf.set_font("Arial", "", 10)
                    
                    for key, value in extracted.items():
                        # Skip fields with 'arabic' in the key
                        if "arabic" in key.lower():
                            continue
                        
                        # Make keys bold
                        pdf.set_font("Arial", "B", 10)
                        pdf.cell(50, 6, f"{key}:", 0)
                        pdf.set_font("Arial", "", 10)
                        
                        # Handle nested dictionaries
                        if isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                # Skip subfields with Arabic values for commercial or trade documents
                                if doc_type in ["commercial", "trade"] and isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                    continue
                                pdf.cell(0, 6, f"{sub_key}: {str(sub_value)}", ln=True)
                        
                        # Handle lists
                        elif isinstance(value, list):
                            for idx, list_item in enumerate(value, 1):
                                if isinstance(list_item, dict):
                                    for sub_key, sub_value in list_item.items():
                                        # Skip subfields with Arabic values for commercial or trade documents
                                        if doc_type in ["commercial", "trade"] and isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                            continue
                                        pdf.cell(0, 6, f"{sub_key}: {str(sub_value)}", ln=True)
                                else:
                                    pdf.cell(0, 6, f"{str(list_item)}", ln=True)
                        
                        # Handle simple values
                        else:
                            # Skip values in Arabic for commercial or trade documents
                            if doc_type in ["commercial", "trade"] and isinstance(value, str) and any("\u0600" <= char <= "\u06FF" for char in value):
                                continue
                            pdf.cell(0, 6, str(value), ln=True)
                else:
                    pdf.set_font("Arial", "I", 10)
                    pdf.cell(0, 6, "  No extracted data available", ln=True)
                
                pdf.ln(5)
                
            except Exception as e:
                continue
        
        if doc_count == 0:
            pdf.set_font("Arial", "I", 11)
            pdf.cell(0, 8, "No valid documents processed.", ln=True)

    # ===== FOOTER =====
    pdf.ln(10)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "This is an automated summary generated by Thrivv Onboarding System.", ln=True, align="C")
    pdf.cell(0, 6, "For any questions, please contact support@thrivv.com", ln=True, align="C")

    # Save PDF
    pdf.output(output_path)
# ===========================
# UPDATED send_completion_email FUNCTION
# ===========================
def send_completion_email(to_email: str, account_type: str):
    """
    Send onboarding completion email with PDF summary attached
    """
    # Fetch user details
    user_response = supabase.table("users").select("*").eq("email", to_email).execute()
    user = user_response.data[0] if user_response.data else {}

    # Only for single users (not multiple owners during member collection)
    ownership_type = user.get("ownership_type", "")
    
    # FIX: Correct path construction for unique folder structure
    # handle_reply.py is at:
    # F:\...\Srini - Onboarding_agent-multiple_owners\Onboarding_agent-multiple_owners\backend\llm_pipeline\handle_reply.py
    # 
    # Documents are at:
    # F:\...\Srini - Onboarding_agent-multiple_owners\backend\documents\id\{email}
    # 
    # Structure:
    # Srini - Onboarding_agent-multiple_owners/
    #   ├── backend/                          ← Documents location
    #   │   └── documents/id/{email}/
    #   ├── Onboarding_agent-multiple_owners/ ← Code location
    #   │   └── backend/
    #   │       └── llm_pipeline/handle_reply.py
    #   └── chroma_store/
    
    current_file_dir = os.path.dirname(os.path.abspath(__file__))  # .../Onboarding_agent-Srini-Multiple-Owners-Logic/backend/llm_pipeline/
    code_backend_dir = os.path.dirname(current_file_dir)  # .../Onboarding_agent-Srini-Multiple-Owners-Logic/backend/
    project_root = os.path.dirname(code_backend_dir)  # .../Onboarding_agent-Srini-Multiple-Owners-Logic/
    
    # Now use project_root directly since documents are in the same backend folder
    user_docs_dir = os.path.join(project_root, "backend", "documents", "id", to_email)
    summary_dir = os.path.join(project_root, "backend", "summary")

    # Create summary directory
    os.makedirs(summary_dir, exist_ok=True)
    
    print(f"[DEBUG] Current file: {__file__}")
    print(f"[DEBUG] Current file dir: {current_file_dir}")
    print(f"[DEBUG] Code backend dir: {code_backend_dir}")
    print(f"[DEBUG] Project root: {project_root}")
    print(f"[DEBUG] User docs directory: {user_docs_dir}")
    print(f"[DEBUG] Summary directory: {summary_dir}")
    print(f"[DEBUG] User docs exists: {os.path.exists(user_docs_dir)}")
    
    if os.path.exists(user_docs_dir):
        items = os.listdir(user_docs_dir)
        print(f"[DEBUG] Items in user docs: {items}")
    
    # Generate PDF filename
    safe_email = to_email.replace('@', '_at_').replace('.', '_')
    pdf_filename = f"{safe_email}_onboarding_summary.pdf"
    pdf_path = os.path.join(summary_dir, pdf_filename)
    
    # Generate PDF
    try:
        generate_user_summary_pdf(user, user_docs_dir, pdf_path)
        print(f"[INFO] PDF Summary saved: {pdf_path}")
    except Exception as e:
        print(f"[ERROR] Failed to generate PDF: {e}")
        pdf_path = None  # Continue without PDF if generation fails

    # Email body
    subject = "Onboarding Complete!"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>Onboarding Complete!</h2>
            <p>Dear {user.get('name', 'User')},</p>
            <p>Congratulations! Your <strong>{account_type}</strong> account onboarding is complete.</p>
            <p>All required documents have been verified successfully.</p>
            
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>Attached Document:</strong></p>
                <p style='margin:10px 0 0 0;'>Please find your comprehensive onboarding summary attached to this email. This document contains all your submitted information and extracted document details.</p>
            </div>
            
            <div style='background:#e3f2fd;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>Next Steps:</strong></p>
                <p style='margin:10px 0 0 0;'>Your account will be activated within <strong>3-4 business days</strong>. You will receive a confirmation email with your account details.</p>
            </div>
            
            <p>If you have any questions, feel free to reply to this email.</p>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """

    # Send email WITH PDF attachment
    try:
        if pdf_path and os.path.exists(pdf_path):
            # Read PDF file
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            send_email(
                to_email=to_email,
                subject=subject,
                body=body_html,
                html=True,
                attachments=[{
                    'filename': pdf_filename,
                    'data': pdf_data,
                    'mime_type': 'application/pdf'
                }]
            )
            print(f"[SUCCESS] Completion email sent with PDF attachment to {to_email}")
        else:
            # Send without attachment if PDF generation failed
            send_email(to_email=to_email, subject=subject, body=body_html, html=True)
            print(f"[WARN] Completion email sent WITHOUT PDF attachment to {to_email}")
    except Exception as e:
        print(f"[ERROR] Failed to send completion email: {e}")


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
    subject = "All Member Documents Verified - Onboarding Complete!"
    
    member_list_html = "".join([f"<li><strong>{name}</strong></li>" for name in members])
    
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>All Member Documents Verified!</h2>
            <p>Dear User,</p>
            <p>Congratulations! We have successfully verified EID documents for all <strong>{len(members)} members/owners</strong>:</p>
            
            <div style='background:#e8f5e9;padding:20px;border-radius:5px;margin:20px 0;'>
                <ul style='margin:0;padding-left:20px;'>
                    {member_list_html}
                </ul>
            </div>
            
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong> All {len(members)} EIDs Verified Successfully</strong></p>
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
# PDF GENERATION - ALL COMMENTED OUT
# ===========================

# def generate_user_summary_pdf(user: dict, results: dict, output_path: str):
#     pdf = FPDF()
#     pdf.add_page()
#     pdf.set_auto_page_break(auto=True, margin=15)

#     # Title
#     pdf.set_font("Arial", "B", 20)
#     pdf.set_text_color(40, 70, 150)
#     pdf.cell(0, 15, "Onboarding Summary", ln=True, align="C")
#     pdf.ln(5)

#     # User Details
#     pdf.set_font("Arial", "B", 14)
#     pdf.set_text_color(0, 0, 0)
#     pdf.cell(0, 10, "User Details", ln=True)
#     pdf.set_font("Arial", "", 12)
#     for key, label in [
#         ("name", "Name"),
#         ("email", "Email"),
#         ("business_name", "Business Name"),
#         ("account_type", "Account Type"),
#         ("ownership_type", "Ownership Type"),
#         ("dob", "Date of Birth"),
#         ("phone_number", "Phone Number"),
#     ]:
#         value = user.get(key, "")
#         if value:
#             pdf.cell(0, 8, f"{label}: {value}", ln=True)
#     pdf.ln(5)

#     # Documents Section
#     pdf.set_font("Arial", "B", 14)
#     pdf.cell(0, 10, "All Submitted Documents", ln=True)
#     pdf.ln(2)

#     entries = []
#     if isinstance(results, dict):
#         for key in ("success", "failed", "invalid", "wrong_type", "warning"):
#             entries.extend(results.get(key, []))
#     elif isinstance(results, list):
#         entries = results
#     else:
#         entries = []

#     if not entries:
#         pdf.set_font("Arial", "I", 12)
#         pdf.set_text_color(200, 0, 0)
#         pdf.cell(0, 8, "No submitted document data found.", ln=True)
#     else:
#         for item in entries:
#             filename = item.get("filename") or item.get("name") or "Unknown"
#             doc_type = item.get("document_type", item.get("type", "unknown"))
#             summary = item.get("summary", "")
#             extracted = {}
#             if "result" in item and isinstance(item["result"], dict):
#                 extracted = item["result"].get("extracted_fields", {})
#             else:
#                 extracted = item.get("extracted_fields", {})

#             pdf.set_font("Arial", "B", 12)
#             pdf.set_text_color(40, 70, 150)
#             pdf.cell(0, 8, f"{filename} ({doc_type})", ln=True)
#             pdf.set_font("Arial", "", 11)
#             pdf.set_text_color(0, 0, 0)
#             if summary:
#                 pdf.cell(0, 6, f"Summary: {summary}", ln=True)
#             if isinstance(extracted, dict) and extracted:
#                 for k, v in extracted.items():
#                     if isinstance(v, dict):
#                         pdf.multi_cell(0, 6, f"{k}: {json.dumps(v, ensure_ascii=False, indent=2)}")
#                     else:
#                         pdf.cell(0, 6, f"{k}: {v}", ln=True)
#             elif extracted:
#                 pdf.cell(0, 6, f"{json.dumps(extracted)}", ln=True)
#             else:
#                 pdf.cell(0, 6, "No extracted fields", ln=True)
#             pdf.ln(3)

#     pdf.output(output_path)
#     print(f"[DEBUG] PDF written to {output_path}")

# ===========================
# MAIN REPLY HANDLER
# ===========================

# KEY CHANGES TO process_user_reply() FUNCTION
# This shows the corrected flow logic

def process_user_reply(from_email: str, body: str, attachments: list = None):
    """
    Enhanced reply handler with corrected flow-based document requests
    
    VALIDATION REQUIREMENT:
    - SAVINGS: Validate EID + Ejari, then ask for confirmation
    - CORPORATE (Single Owner): Validate Commercial + EID + Ejari, then ask for confirmation
    - CORPORATE (Multiple Owners): NO validation, NO confirmation - proceed directly to member EID collection
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
            
            print("[INFO] Processing member EID documents (no validation needed)")
            
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
            
            # Process documents for current member (NO VALIDATION - just collect)
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
                    # All members processed - Complete onboarding WITHOUT confirmation
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
            print("[INFO] Processing user documents (validation required for this flow)")
            
            # Process documents
            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=False
            )
            
            # ====================================
            # STAGE 1: SAVINGS ACCOUNT
            # Requires: EID + Ejari validation + confirmation
            # ====================================
            if account_type == "Savings":
                print("[INFO] Checking Savings Account completion (with confirmation)")
                
                stage_check = check_document_stage_completion(
                    from_email, 
                    ["eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] All Savings Account documents valid")
                    
                    # ALL DOCUMENTS VALID - ASK FOR CONFIRMATION
                    send_document_status_email(from_email, results, is_member=False)
                    print("[INFO] Confirmation email sent. Awaiting user confirmation.")
                    return
                else:
                    # Missing or invalid documents - request resubmission
                    print(f"[INFO] Missing/invalid documents: {stage_check['missing']}")
                    
                    invalid_reasons = {}
                    for doc in results.get("invalid", []):
                        doc_type = doc.get("type")
                        issues = doc.get("issues", [])
                        if doc_type and issues:
                            invalid_reasons[doc_type] = "; ".join(issues)

                    send_missing_documents_email(
                        from_email, 
                        stage_check["missing"],
                        "Savings Account",
                        invalid_reasons=invalid_reasons
                    )
                    return
            
            # ====================================
            # STAGE 2: CORPORATE - SINGLE OWNER
            # Requires: Commercial + EID + Ejari validation + confirmation
            # ====================================
            elif account_type == "Corporate" and ownership_type == "Single Owner":
                print("[INFO] Checking Corporate Single Owner completion (with confirmation)")
                
                stage_check = check_document_stage_completion(
                    from_email,
                    ["commercial", "eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] All Corporate Single Owner documents valid")
                    
                    # ALL DOCUMENTS VALID - ASK FOR CONFIRMATION
                    send_document_status_email(from_email, results, is_member=False)
                    print("[INFO] Confirmation email sent. Awaiting user confirmation.")
                    return
                else:
                    # Missing or invalid documents - request resubmission
                    print(f"[INFO] Missing/invalid documents: {stage_check['missing']}")
                    
                    send_missing_documents_email(
                        from_email,
                        stage_check["missing"],
                        "Corporate Single Owner"
                    )
                    return
            
            # ====================================
            # STAGE 3: CORPORATE - MULTIPLE OWNERS
            # NO validation, NO confirmation - proceed directly to member identification
            # ====================================
            elif account_type == "Corporate" and ownership_type in ["Partnership", "@Multiple Owners"]:
                print("[INFO] Corporate Multiple Owners - Identification Stage (no confirmation needed)")
                
                # Check current stage
                if document_stage == "identification":
                    print("[INFO] Stage: Identification (need Commercial + MOA)")
                    
                    # Stage 1: Need Commercial + MOA to identify owners
                    # NOTE: No validation/confirmation here - just collect documents
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
                            print(f"       - Registered user included: {includes_user}")
                            print(f"       - Total EIDs to collect: {len(member_names)}")
                            
                            # Create directories for each member
                            base_docs_dir = os.path.join("backend", "documents", "id", from_email)
                            for member_name in member_names:
                                member_dir = os.path.join(base_docs_dir, member_name)
                                os.makedirs(member_dir, exist_ok=True)
                            
                            # Save progress - start with first member
                            save_member_progress(from_email, member_names, 0)
                            
                            # Update stage - SKIP CONFIRMATION, GO DIRECTLY TO MEMBER EIDS
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
                            
                            # Request first member's EID immediately
                            send_member_eid_request_email(
                                from_email,
                                member_names[0],
                                1,
                                len(member_names)
                            )
                            
                            print(f"[INFO] Proceeding to member EID collection (no confirmation step)")
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
    
    # Get conversation context (FAQ + history)
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
        convo_context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in convo_history[-6:]])
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

