# backend/llm_pipeline/handle_reply.py
from ingestion.faq_retriever import retrieve_similar_chunks
from llm_runner.prompt_templates import build_onboarding_prompt
from llm_runner.run_model import call_local_llm
from app.services.supabase_client import supabase
from app.services.email_sender import send_email
from app.services.ocr_service import process_document, format_document_name, run_ocr
from specialized_ocr import ejari_extractor,trade_extractor,moa_extractor
from datetime import datetime
import os
import time
import json
from fpdf import FPDF
#from fpdf2 import FPDF
import json
import re
from app.services.eid_validation import validate_eid_before_confirmation

LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-7b-instruct"

import os
import socket
from urllib.parse import quote

def get_api_base_url():
    """
    Get the correct API base URL for external access.
    Priority: 
    1. Environment variable API_BASE_URL
    2. Auto-detect public IP
    3. Fallback to localhost
    """
    # Check for environment variable first
    env_url = os.getenv("API_BASE_URL")
    if env_url:
        print(f"[INFO] 📋 Using API_BASE_URL from environment: {env_url}")
        return env_url
    
    # Try to get public IP
    try:
        import requests
        public_ip = requests.get('https://api.ipify.org', timeout=3).text.strip()
        api_url = f"http://{public_ip}:9000"
        print(f"[INFO] 📋 Auto-detected public IP API URL: {api_url}")
        return api_url
    except Exception as e:
        print(f"[WARN] ⚠️ Could not detect public IP: {e}")
        # Fallback to localhost
        fallback = "http://localhost:9000"
        print(f"[INFO] 📋 Using fallback API URL: {fallback}")
        return fallback

# DEFINE API_BASE GLOBALLY AT MODULE LEVEL
API_BASE = get_api_base_url()
print(f"[INFO] 📋 API_BASE initialized: {API_BASE}")

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
        print(f"[DEBUG] 🔍 Directory does not exist: {user_docs_dir}")
        return {
            "complete": False, 
            "submitted": submitted, 
            "missing": required_docs
        }
    
    print(f"[DEBUG] 🔍 Scanning directory: {user_docs_dir}")
    print(f"[DEBUG] 🔍 Looking for: {required_docs}")
    
    # List all items in directory
    all_items = os.listdir(user_docs_dir)
    print(f"[DEBUG] 🔍 Found {len(all_items)} items in directory: {all_items}")
    
    # Check each item
    for item in all_items:
        item_path = os.path.join(user_docs_dir, item)
        
        # Skip files (only check directories)
        if not os.path.isdir(item_path):
            print(f"[DEBUG] 🔍 Skipping file: {item}")
            continue
        
        # Skip member_progress.json directory (shouldn't exist but just in case)
        if item == "member_progress.json":
            print(f"[DEBUG] 🔍 Skipping member_progress.json")
            continue
        
        # Check for output.json
        output_path = os.path.join(item_path, "output.json")
        print(f"[DEBUG] 🔍 Checking: {item}/")
        
        if not os.path.exists(output_path):
            print(f"[DEBUG] 🔍 No output.json found")
            continue
        
        # Read and parse output.json
        try:
            print(f"[DEBUG] 🔍    Reading output.json...")
            with open(output_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            
            doc_type = analysis.get("document_type", "unknown")
            is_valid = analysis.get("is_valid", False)
            filename = analysis.get("filename", item)
            
            print(f"[DEBUG] 🔍    Filename: {filename}")
            print(f"[DEBUG] 🔍    Document type: {doc_type}")
            print(f"[DEBUG] 🔍    Is valid: {is_valid}")
            
            # Update submission status if valid
            if doc_type in submitted:
                if is_valid:
                    submitted[doc_type] = True
                    print(f"[DEBUG] 🔍    MARKED {doc_type.upper()} AS VALID")
                else:
                    print(f"[DEBUG] 🔍     {doc_type.upper()} is INVALID")
            else:
                print(f"[DEBUG] 🔍      Unknown document type: {doc_type}")
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] ❌    Failed to parse JSON: {e}")
        except Exception as e:
            print(f"[ERROR] ❌    Error reading file: {e}")
    
    # Calculate missing documents
    missing = [doc for doc in required_docs if not submitted.get(doc, False)]
    complete = len(missing) == 0
    
    # Print final summary
    print(f"\n{'='*70}")
    print(f"[DEBUG] 🔍 📁 VALIDATION SUMMARY FOR {user_email}")
    print(f"{'='*70}")
    print(f"[DEBUG] 🔍 Required documents: {required_docs}")
    print(f"[DEBUG] 🔍 ")
    print(f"[DEBUG] 🔍 Status by document type:")
    for doc_type in ["eid", "ejari", "commercial", "moa"]:
        if doc_type in required_docs:
            status = "VALID" if submitted[doc_type] else "MISSING"
            print(f"[DEBUG] 🔍   {doc_type:12} : {status}")
    print(f"[DEBUG] 🔍 ")
    print(f"[DEBUG] 🔍 Missing: {missing if missing else 'None'}")
    print(f"[DEBUG] 🔍 Complete: {'YES ✓' if complete else 'NO '}")
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
    
    NEW LOGIC:
    - Extract managers from Commercial License
    - Extract owner/manager from MOA
    - Check if registered user is in company documents
    - If user IS in documents: Include them in member list
    - If user NOT in documents: Exclude them from member list
    
    Returns: {
        "members": list of member names (managers only),
        "includes_user": bool (whether registered user is in documents),
        "user_validation": dict (validation details)
    }
    """
    user_docs_dir = os.path.join("backend", "documents", "id", user_email)
    member_names = []
    
    # STEP 1: Check if registered user is in company documents
    print(f"\n{'='*80}")
    print(f"[INFO] 📋 ðŸš€ EXTRACTING MEMBERS FROM DOCUMENTS")
    print(f"{'='*80}\n")
    
    user_validation = is_registered_user_in_company_documents(user_email)
    user_in_documents = user_validation["found"]
    registered_user_name = user_validation["registered_name"]
    
    print(f"[INFO] 📋  Registered User Validation:")
    print(f"   - Name: '{registered_user_name}'")
    print(f"   - Found in Documents: {user_in_documents}")
    print(f"   - Found In: {user_validation['found_in']}")
    print(f"   - Matched Field: {user_validation['matched_field']}")
    
    if not os.path.exists(user_docs_dir):
        return {
            "members": member_names,
            "includes_user": False,
            "user_validation": user_validation
        }
    
    # STEP 2: Extract members from documents
    print(f"\n[INFO]  Extracting members from documents...")
    
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
                        managers = extracted_fields.get("managers", [])
                        
                        print(f"[DEBUG] 🔍 Found {len(managers)} managers in Commercial License")
                        
                        for manager in managers:
                            name = manager.get("name_english", "").strip()
                            if name:
                                member_names.append(name)
                                print(f"[DEBUG] 🔍 Added manager: {name}")
                    
                    # Extract from MOA
                    elif doc_type == "moa":
                        extracted_fields = analysis.get("extracted_fields", {})
                        english_data = extracted_fields.get("english", {})
                        
                        owner_name = english_data.get("owner_name", "").strip()
                        manager_name = english_data.get("manager_name", "").strip()
                        
                        if owner_name:
                            member_names.append(owner_name)
                            print(f"[DEBUG] 🔍 Added MOA owner: {owner_name}")
                        if manager_name and manager_name != owner_name:
                            member_names.append(manager_name)
                            print(f"[DEBUG] 🔍 Added MOA manager: {manager_name}")
                
                except Exception as e:
                    print(f"[ERROR] ❌ Failed to read {output_path}: {e}")
    
    # STEP 3: Remove duplicates
    seen = set()
    unique_names = []
    for name in member_names:
        name_lower = name.lower()
        if name and name_lower not in seen:
            seen.add(name_lower)
            unique_names.append(name)
    
    print(f"\n[INFO] 📁 Extracted {len(unique_names)} unique managers from documents")
    
    # STEP 4: Handle registered user inclusion/exclusion
    print(f"\n[INFO]  Processing registered user inclusion...")
    
    if user_in_documents:
        # User IS in documents - ensure they're in the list
        print(f"[INFO] 📋 User '{registered_user_name}' IS in company documents")
        
        # Check if already in list
        user_already_in_list = False
        if registered_user_name:
            for member in unique_names:
                if (registered_user_name.lower() in member.lower() or 
                    member.lower() in registered_user_name.lower()):
                    user_already_in_list = True
                    print(f"[INFO] 📋 User already in extracted list as '{member}'")
                    break
        
        # Add if not present
        if not user_already_in_list and registered_user_name:
            unique_names.insert(0, registered_user_name)
            print(f"[INFO] 📋 Added registered user '{registered_user_name}' to beginning of list")
    
    else:
        # User NOT in documents - remove them if present
        print(f"[INFO] 📋  User '{registered_user_name}' NOT in company documents")
        
        if registered_user_name:
            original_count = len(unique_names)
            
            # Remove user from list
            unique_names = [
                member for member in unique_names 
                if not (registered_user_name.lower() in member.lower() or 
                       member.lower() in registered_user_name.lower())
            ]
            
            if len(unique_names) < original_count:
                print(f"[INFO] 📋 Removed registered user from member list")
            else:
                print(f"[INFO] 📋  User was not in extracted list")
    
    print(f"\n[INFO]  Final member list ({len(unique_names)} managers): {unique_names}")
    print(f"[INFO] 📋  User in documents: {user_in_documents}")
    
    # STEP 5: Save validation result to database for future reference
    try:
        supabase.table("users").update({
            "user_in_company_docs": user_in_documents,
            "user_doc_validation": json.dumps(user_validation)
        }).eq("email", user_email).execute()
        print(f"[INFO] 📋 Saved validation result to database")
    except Exception as e:
        print(f"[WARN] ⚠️ Could not save validation to database: {e}")
    
    print(f"{'='*80}\n")
    
    return {
        "members": unique_names,
        "includes_user": user_in_documents,
        "user_validation": user_validation
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
            print(f"[ERROR] ❌ Failed to load member progress: {e}")
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
        print(f"[INFO] 📋 Saved member progress: Member {current_index + 1}/{len(members)}")
    except Exception as e:
        print(f"[ERROR] ❌ Failed to save member progress: {e}")


# ===========================
# DOCUMENT PROCESSING
# ===========================

def generate_reasoning_for_wrong_document(raw_text: str, doc_type: str) -> str:
    """
    Generate reasoning for why the document is wrong using call_local_llm.
    """
    try:
        prompt = f"""
        You are an AI assistant. The following raw text was extracted from a document of type '{doc_type}'.
        The document was marked as invalid. Please summarize the extracted text and provide a detailed reason
        why the document is invalid. Ensure the response is clear and user-friendly.

        Raw Text:
        {raw_text}
        """
        reasoning = call_local_llm(prompt)
        return reasoning
    except Exception as e:
        print(f"[ERROR] ❌ Failed to generate reasoning for wrong document: {e}")
        return "Unable to generate reasoning due to an error."


def send_reasoning_email(to_email: str, filename: str, doc_type: str, reasoning: str):
    """
    Send an email with the reasoning for why the document is invalid.
    """
    subject = f"Reasoning for Invalid Document: {filename}"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#f44336;'> Document Invalid: {filename}</h2>
            <p>Dear User,</p>
            <p>We analyzed your submitted document of type <strong>{doc_type.upper()}</strong> and found it to be invalid. Below is the reasoning:</p>
            <div style='background:#f8f9fa;padding:15px;border-radius:5px;margin:15px 0;'>
                <p style='margin:0;'><strong>Reasoning:</strong></p>
                <p>{reasoning}</p>
            </div>
            <p>Please review the reasoning and submit the correct document.</p>
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    print(f"[INFO] 📋 Sent reasoning email for invalid document: {filename} to {to_email}")


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
            raw_text = result.get("raw_text", "")

            if doc_type == "unknown":
                print("[WARN] ⚠️ Unknown document type - extracting text for reasoning")
                
                # EXTRACT TEXT FIRST before marking as unknown
                try:
                    if ext == '.pdf':
                        import fitz
                        doc = fitz.open(filepath)
                        raw_text = ""
                        for i in range(min(5, doc.page_count)):
                            page = doc.load_page(i)
                            raw_text += page.get_text()
                        doc.close()
                        print(f"[INFO] 📋 Extracted {len(raw_text)} characters from PDF")
                    elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
                        # Use OCR for images
                        raw_text = run_ocr(filepath, model)
                        print(f"[INFO] 📋 OCR extracted {len(raw_text)} characters from image")
                    elif ext in ['.docx', '.doc']:
                        with open(filepath, 'rb') as f:
                            doc_bytes = f.read()
                        extractor = EjariExtractor()
                        raw_text = extractor.extract_text_from_docx(doc_bytes)
                        print(f"[INFO] 📋 Extracted {len(raw_text)} characters from DOCX")
                    else:
                        raw_text = "[UNSUPPORTED FILE FORMAT]"
                        print(f"[WARN] ⚠️ Unsupported file format: {ext}")
                        
                except Exception as e:
                    print(f"[ERROR] ❌ Failed to extract text from unknown document: {e}")
                    raw_text = "[TEXT EXTRACTION FAILED]"

                # Generate reasoning for the invalid document
                reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)

                # Send reasoning email
                send_reasoning_email(
                    to_email=from_email,
                    filename=filename,
                    doc_type=doc_type,
                    reasoning=reasoning
                )

                # Add to invalid results with extracted text
                processed_results["invalid"].append({
                    "filename": filename,
                    "type": "unknown",
                    "issues": ["Unknown document type"],
                    "raw_text": raw_text,
                    "reasoning": reasoning
                })
                continue

            if not is_valid:
                # Generate reasoning for the invalid document
                reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)

                # Send reasoning email
                send_reasoning_email(
                    to_email=from_email,
                    filename=filename,
                    doc_type=doc_type,
                    reasoning=reasoning
                )

                # Add to invalid results
                processed_results["invalid"].append({
                    "filename": filename,
                    "type": doc_type,
                    "issues": result.get("validation", {}).get("missing_fields", []),
                    "reasoning": reasoning
                })
                continue

            # --- Name validation ONLY for EID ---
            extracted = result.get("extracted_fields", {})
            print("[DEBUG-375] Extracted Data:", extracted)
            extracted_name = ""
            name_match = True  # Default to True (no validation for non-EID docs)

            # ONLY extract and validate name for EID documents
            if doc_type == "eid":
                extracted_name = extracted.get("Name", "").strip().lower()
                print(f"[DEBUG] 🔍 Document: {filename} | Type: {doc_type}")
                print(f"[DEBUG] 🔍 Extracted Name: '{extracted_name}' | Expected Name: '{user_name}'")
                
                # Only validate name for Savings and Single Owner Corporate
                should_validate = (
                    account_type == "Savings" or 
                    (account_type == "Corporate" and ownership_type == "Single Owner")
                )
                
                if should_validate:
                    name_match = user_name and extracted_name and (user_name in extracted_name or extracted_name in user_name)
                    print(f"[DEBUG] 🔍 Name validation performed: {name_match}")
                else:
                    name_match = True
                    print(f"[DEBUG] 🔍 Name validation SKIPPED for Multiple Owners")

            # ONLY apply validation rejection for EID documents
            if doc_type == "eid" and not name_match:
                print(f"[WARN] ⚠️ Name mismatch for EID {filename}. Marking as invalid and requesting resubmission.")
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
                        print(f"[DEBUG] 🔍 Updated output.json for {filename} to set is_valid=False due to name mismatch.")
                    except Exception as e:
                        print(f"[ERROR] ❌ Could not update output.json for {filename}: {e}")

                processed_results["invalid"].append({
                    "filename": filename,
                    "type": doc_type,
                    "issues": ["Name mismatch with registration data"],
                    "extracted_name": extracted_name,
                    "expected_name": user_name
                })
                continue
            else:
                print(f"[DEBUG] 🔍 Validation passed for {filename} (type: {doc_type})")

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
            print(f"[ERROR] ❌ Failed to process {filename}: {e}")
            processed_results["failed"].append({
                "filename": filename,
                "error": str(e)
            })
    
    return processed_results

# ===========================
# EMAIL NOTIFICATIONS
# ===========================

def send_document_status_email(to_email: str, results: dict, is_member: bool = False, member_name: str = None):
    """
    Send email about document processing results with a single confirm link and per-document resubmit links.
    COMBINES NEWLY PROCESSED DOCUMENTS + ALL EXISTING VALIDATED DOCUMENTS FROM DISK.
    FIXED: filename variable scope issue resolved
    """
    try:
        from urllib.parse import quote

        # ========================================
        # STEP 1: COLLECT NEWLY PROCESSED DOCUMENTS FROM results PARAMETER
        # ========================================
        newly_processed = []
        if isinstance(results, dict):
            # Only take SUCCESSFUL documents from current submission
            for item in results.get("success", []):
                filename = item.get("filename", "Unknown")
                doc_type = item.get("type", "unknown")
                result_data = item.get("result", {})
                extracted = result_data.get("extracted_fields", {})

                newly_processed.append({
                    "filename": filename,
                    "document_type": doc_type,
                    "type": doc_type,
                    "result": result_data,
                    "extracted_fields": extracted
                })

                print(f"[DEBUG] 🔍 Added newly processed: {filename} ({doc_type})")

        print(f"[DEBUG] 🔍 Total newly processed documents: {len(newly_processed)}")

        # ========================================
        # STEP 2: READ ALL EXISTING VALIDATED DOCUMENTS FROM DISK
        # ========================================
        if is_member and member_name:
            user_docs_dir = os.path.join("backend", "documents", "id", to_email, member_name)
        else:
            user_docs_dir = os.path.join("backend", "documents", "id", to_email)

        existing_validated_docs = []
        newly_processed_filenames = {doc["filename"] for doc in newly_processed}

        if os.path.exists(user_docs_dir):
            print(f"[DEBUG] 🔍 Reading existing documents from: {user_docs_dir}")

            for item in os.listdir(user_docs_dir):
                item_path = os.path.join(user_docs_dir, item)

                # Skip files and member_progress.json
                if not os.path.isdir(item_path) or item == "member_progress.json":
                    continue

                output_path = os.path.join(item_path, "output.json")

                if os.path.exists(output_path):
                    try:
                        with open(output_path, "r", encoding="utf-8") as f:
                            analysis = json.load(f)

                        doc_type = analysis.get("document_type", "unknown")
                        is_valid = analysis.get("is_valid", False)
                        filename = analysis.get("filename", item)

                        # Include only VALID documents that are not in the newly processed list
                        if is_valid and filename not in newly_processed_filenames:
                            existing_validated_docs.append({
                                "filename": filename,
                                "document_type": doc_type,
                                "type": doc_type,
                                "result": analysis,
                                "extracted_fields": analysis.get("extracted_fields", {})
                            })
                            print(f"[DEBUG] 🔍 Added existing validated: {filename} ({doc_type})")

                    except Exception as e:
                        print(f"[ERROR] ❌ Failed to read {output_path}: {e}")

        print(f"[INFO] 📋 Existing validated documents (excluding newly processed): {len(existing_validated_docs)}")

        # ========================================
        # STEP 3: COMBINE BOTH LISTS
        # ========================================
        all_validated_docs = newly_processed + existing_validated_docs

        print(f"[INFO] 📋 Total documents to show in email: {len(all_validated_docs)}")
        for doc in all_validated_docs:
            print(f"  - {doc['filename']} ({doc['document_type']})")

        if not all_validated_docs:
            print(f"[ERROR] ❌ No documents to display in email!")
            return

        # ========================================
        # STEP 4: BUILD EMAIL HTML FROM ALL VALIDATED DOCS
        # ========================================
        files_html = ""

        for item in all_validated_docs:
            filename = item.get("filename", "Unknown")
            doc_type = item.get("document_type", item.get("type", "unknown")).upper()
            extracted = item.get("extracted_fields", {})

            # Format extracted fields in a user-friendly way
            extracted_html = ""
            if isinstance(extracted, dict) and extracted:
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

            # FIXED: resubmit_link created INSIDE loop with correct filename
            resubmit_link = f"{API_BASE}/chat/resubmit-document?email={quote(to_email)}&filename={quote(filename)}"

            files_html += f"""
                <div style='margin-bottom:24px;padding:16px;border:1px solid #e0e0e0;border-radius:8px;background:#fff;'>
                    <h3 style='margin:0 0 12px 0;color:#1976d2;font-size:16px;'>
                        {filename}
                        <span style='font-size:13px;color:#666;margin-left:8px;'>({doc_type})</span>
                    </h3>
                    <div style='background:#f5f5f5;padding:12px;border-radius:6px;margin-bottom:12px;'>
                        {extracted_html if extracted_html else '<p style="color:#999;">No extracted data available</p>'}
                    </div>
                    <a href="{resubmit_link}" style='display:inline-block;padding:8px 16px;background:#f44336;color:#fff;border-radius:4px;text-decoration:none;font-size:14px;'>
                        Request Resubmission
                    </a>
                </div>
            """

        # FIXED: confirm_link created AFTER loop (applies to all documents)
        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"

        subject = "Your document extraction results 📋 please confirm"
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
        print(f"[INFO] 📋 Sent document status email with {len(all_validated_docs)} validated documents to {to_email}")

    except Exception as e:
        print(f"[ERROR] ❌ Failed to send document status email: {e}")
        import traceback
        traceback.print_exc()

def send_missing_documents_email(to_email: str, missing_docs: list, context: str, invalid_reasons: dict = None):
    """Send email requesting missing documents, with reasons if available"""
    doc_names = [format_document_name(doc) for doc in missing_docs]
    invalid_reasons = invalid_reasons or {}

    subject = f"Missing Documents - {context}"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#ff9800;'> Missing Documents</h2>
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
    Includes member EIDs for Corporate Multiple Owners
    FIXED: Correctly identifies member directories vs document folders
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Get user account info for conditional logic
    account_type = user.get("account_type", "")
    ownership_type = user.get("ownership_type", "")

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
        
        # Track member directories for later processing
        member_dirs = []
        
        print(f"[PDF-DEBUG] Scanning directory: {user_docs_dir}")
        print(f"[PDF-DEBUG] Found {len(all_items)} items: {all_items}")
        
        for item in all_items:
            item_path = os.path.join(user_docs_dir, item)
            
            # Skip files (not directories)
            if not os.path.isdir(item_path):
                print(f"[PDF-DEBUG] Skipping file: {item}")
                continue
            
            # Skip member_progress.json
            if item == "member_progress.json":
                print(f"[PDF-DEBUG] Skipping member_progress.json")
                continue
            
            # FOR MULTIPLE OWNERS: Check if this is a member directory FIRST
            # Member directories contain only letters/spaces and have member EID subdirectories
            is_member_directory = False
            if account_type == "Corporate" and ownership_type in ["Partnership", "@Multiple Owners"]:
                # Check if folder name contains only letters/spaces (typical for member names)
                if all(c.isalpha() or c.isspace() for c in item):
                    # Verify it has subdirectories with output.json (member EID structure)
                    for subitem in os.listdir(item_path):
                        subitem_path = os.path.join(item_path, subitem)
                        if os.path.isdir(subitem_path):
                            if os.path.exists(os.path.join(subitem_path, "output.json")):
                                is_member_directory = True
                                member_dirs.append(item)
                                print(f"[PDF-DEBUG] Identified as member directory: {item}")
                                break
            
            # If it's a member directory, skip to next item
            if is_member_directory:
                continue
            
            # Check if this folder contains an output.json (regular document)
            output_path_json = os.path.join(item_path, "output.json")
            
            if os.path.exists(output_path_json):
                # This is a DOCUMENT FOLDER (has output.json)
                print(f"[PDF-DEBUG] Processing document folder: {item}")
                
                try:
                    with open(output_path_json, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    
                    doc_count += 1
                    filename = analysis.get("filename", item)
                    doc_type = analysis.get("document_type", "unknown").lower()
                    is_valid = analysis.get("is_valid", False)
                    extracted = analysis.get("extracted_fields", {})
                    
                    print(f"[PDF-DEBUG]    Document #{doc_count}: {filename} ({doc_type}) - Valid: {is_valid}")
                    
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
                        
                        field_count = 0
                        for key, value in extracted.items():
                            # Skip fields with 'arabic' in the key
                            if "arabic" in key.lower():
                                continue
                            
                            field_count += 1
                            
                            # Make keys bold
                            pdf.set_font("Arial", "B", 10)
                            pdf.cell(50, 6, f"{key}:", 0)
                            pdf.set_font("Arial", "", 10)
                            
                            # Handle nested dictionaries
                            if isinstance(value, dict):
                                pdf.ln()
                                for sub_key, sub_value in value.items():
                                    # Skip subfields with Arabic values
                                    if doc_type in ["commercial", "trade"] and isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                        continue
                                    pdf.cell(10, 6, "", 0)  # Indent
                                    pdf.cell(0, 6, f"{sub_key}: {str(sub_value)}", ln=True)
                            
                            # Handle lists
                            elif isinstance(value, list):
                                pdf.ln()
                                for idx, list_item in enumerate(value, 1):
                                    if isinstance(list_item, dict):
                                        pdf.cell(10, 6, "", 0)  # Indent
                                        pdf.cell(0, 6, f"Item {idx}:", ln=True)
                                        for sub_key, sub_value in list_item.items():
                                            if doc_type in ["commercial", "trade"] and isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                                continue
                                            pdf.cell(20, 6, "", 0)  # Double indent
                                            pdf.cell(0, 6, f"{sub_key}: {str(sub_value)}", ln=True)
                                    else:
                                        pdf.cell(10, 6, "", 0)  # Indent
                                        pdf.cell(0, 6, f"- {str(list_item)}", ln=True)
                            
                            # Handle simple values
                            else:
                                # Skip Arabic text for commercial/trade documents
                                if doc_type in ["commercial", "trade"] and isinstance(value, str) and any("\u0600" <= char <= "\u06FF" for char in value):
                                    pdf.cell(0, 6, "[Arabic text omitted]", ln=True)
                                else:
                                    pdf.cell(0, 6, str(value), ln=True)
                        
                        print(f"[PDF-DEBUG]    Added {field_count} fields to PDF")
                    else:
                        pdf.set_font("Arial", "I", 10)
                        pdf.cell(0, 6, "  No extracted data available", ln=True)
                        print(f"[PDF-DEBUG]    No extracted data")
                    
                    pdf.ln(5)
                    
                except Exception as e:
                    print(f"[ERROR] ❌ PDF generation error for {item}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            else:
                # No output.json found in this directory
                print(f"[PDF-DEBUG] Skipping directory without output.json: {item}")
        
        print(f"[PDF-DEBUG] Total documents processed: {doc_count}")
        print(f"[PDF-DEBUG] Total member directories: {len(member_dirs)}")
        
        if doc_count == 0:
            pdf.set_font("Arial", "I", 11)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 8, "No valid documents processed.", ln=True)
            print(f"[PDF-WARN] No documents were added to PDF!")

        # ===== MEMBER EMIRATES IDs SECTION (FOR MULTIPLE OWNERS) =====
        if account_type == "Corporate" and ownership_type in ["Partnership", "@Multiple Owners"] and member_dirs:
            pdf.ln(8)
            pdf.set_font("Arial", "B", 16)
            pdf.set_fill_color(230, 255, 230)
            pdf.cell(0, 10, " Member Emirates IDs", ln=True, fill=True)
            pdf.ln(3)
            
            member_count = 0
            for member_name in member_dirs:
                member_dir = os.path.join(user_docs_dir, member_name)
                
                # Find EID in member directory
                eid_found = False
                for item in os.listdir(member_dir):
                    item_path = os.path.join(member_dir, item)
                    if not os.path.isdir(item_path):
                        continue
                    
                    output_path_json = os.path.join(item_path, "output.json")
                    if os.path.exists(output_path_json):
                        try:
                            with open(output_path_json, "r", encoding="utf-8") as f:
                                analysis = json.load(f)
                            
                            doc_type = analysis.get("document_type", "unknown")
                            is_valid = analysis.get("is_valid", False)
                            
                            if doc_type == "eid" and is_valid:
                                member_count += 1
                                extracted = analysis.get("extracted_fields", {})
                                
                                # Member Header
                                pdf.set_font("Arial", "B", 13)
                                pdf.set_text_color(76, 175, 80)
                                pdf.cell(0, 8, f"{member_count}. Member: {member_name}", ln=True)
                                pdf.set_font("Arial", "", 10)
                                pdf.set_text_color(0, 0, 0)
                                
                                # Extracted EID Fields
                                if isinstance(extracted, dict) and extracted:
                                    for key, value in extracted.items():
                                        if value and not isinstance(value, (dict, list)):
                                            pdf.set_font("Arial", "B", 10)
                                            pdf.cell(50, 6, f"{key}:", 0)
                                            pdf.set_font("Arial", "", 10)
                                            pdf.cell(0, 6, str(value), ln=True)
                                else:
                                    pdf.set_font("Arial", "I", 10)
                                    pdf.cell(0, 6, "  No extracted data available", ln=True)
                                
                                pdf.ln(5)
                                eid_found = True
                                break
                        except Exception as e:
                            print(f"[ERROR] ❌ Failed to process member EID for {member_name}: {e}")
                            continue
                
                if not eid_found:
                    pdf.set_font("Arial", "I", 11)
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 8, f"No valid EID found for member: {member_name}", ln=True)
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln(3)
            
            if member_count == 0:
                pdf.set_font("Arial", "I", 11)
                pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 8, "No member EIDs processed.", ln=True)

    # ===== FOOTER =====
    pdf.ln(10)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "This is an automated summary generated by Thrivv Onboarding System.", ln=True, align="C")
    pdf.cell(0, 6, "For any questions, please contact support@thrivv.com", ln=True, align="C")

    # Save PDF
    pdf.output(output_path)
    print(f"[INFO] 📋 PDF successfully generated at: {output_path}")
# ===========================
# UPDATED send_completion_email FUNCTION
# ===========================

def send_completion_email(to_email: str, account_type: str):
    """
    Send onboarding completion email with PDF summary attached
    FIXED: Unified path construction for all flows (email/chat/document upload)
    """
    # Fetch user details
    user_response = supabase.table("users").select("*").eq("email", to_email).execute()
    user = user_response.data[0] if user_response.data else {}

    ownership_type = user.get("ownership_type", "")
    
    # UNIFIED PATH CONSTRUCTION - Works for ALL flows
    current_file_dir = os.path.dirname(os.path.abspath(__file__))  
    # Result: .../backend/llm_pipeline/
    
    code_backend_dir = os.path.dirname(current_file_dir)  
    # Result: .../backend/
    
    # Use absolute path with /app/backend for Docker compatibility
    if os.path.exists("/app/backend"):
        # Docker environment
        user_docs_dir = f"/app/backend/documents/id/{to_email}"
        summary_dir = "/app/backend/summary"
    else:
        # Local environment
        user_docs_dir = os.path.join(code_backend_dir, "documents", "id", to_email)
        summary_dir = os.path.join(code_backend_dir, "summary")

    # Create summary directory with proper permissions
    os.makedirs(summary_dir, exist_ok=True)
    
    print(f"\n{'='*80}")
    print(f"[DEBUG] 🔍 PDF GENERATION PATH DEBUG")
    print(f"{'='*80}")
    print(f"[DEBUG] 🔍 Current file: {__file__}")
    print(f"[DEBUG] 🔍 User docs directory: {user_docs_dir}")
    print(f"[DEBUG] 🔍 Summary directory: {summary_dir}")
    print(f"[DEBUG] 🔍 User docs exists: {os.path.exists(user_docs_dir)}")
    print(f"[DEBUG] 🔍 Summary dir exists: {os.path.exists(summary_dir)}")
    
    if os.path.exists(user_docs_dir):
        items = os.listdir(user_docs_dir)
        print(f"[DEBUG] 🔍 Items in user docs ({len(items)}): {items[:5]}")  # Show first 5
    else:
        print(f"[DEBUG] 🔍  User docs directory does NOT exist!")
    
    print(f"{'='*80}\n")
    
    # Generate PDF filename
    safe_email = to_email.replace('@', '_at_').replace('.', '_')
    pdf_filename = f"{safe_email}_onboarding_summary.pdf"
    pdf_path = os.path.join(summary_dir, pdf_filename)
    
    print(f"[INFO] 📋  Generating PDF at: {pdf_path}")
    
    # Generate PDF
    try:
        generate_user_summary_pdf(user, user_docs_dir, pdf_path)
        print(f"[SUCCESS] ✅ PDF Summary generated successfully: {pdf_path}")
        
        # Verify PDF was created and has content
        if os.path.exists(pdf_path):
            pdf_size = os.path.getsize(pdf_path)
            print(f"[INFO] 📋 📁 PDF file size: {pdf_size:,} bytes ({pdf_size/1024:.2f} KB)")
            
            if pdf_size < 1000:
                print(f"[WARN] ⚠️ PDF seems too small ({pdf_size} bytes) - may be empty!")
            else:
                print(f"[SUCCESS] ✅ PDF validated - contains data")
        else:
            print(f"[ERROR] ❌  PDF file was not created at expected path!")
            pdf_path = None
            
    except Exception as e:
        print(f"[ERROR] ❌  Failed to generate PDF: {e}")
        import traceback
        traceback.print_exc()
        pdf_path = None

    # Email body
    subject = "Onboarding Complete!"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>🎉 Onboarding Complete!</h2>
            <p>Dear {user.get('name', 'User')},</p>
            <p>Congratulations! Your <strong>{account_type}</strong> account onboarding is complete.</p>
            <p>All required documents have been verified successfully.</p>
            
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>📄 Attached Document:</strong></p>
                <p style='margin:10px 0 0 0;'>Please find your comprehensive onboarding summary attached to this email. This document contains all your submitted information and extracted document details.</p>
            </div>
            
            <div style='background:#e3f2fd;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>📝 Next Steps:</strong></p>
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
            print(f"[SUCCESS] ✅ Completion email sent with PDF attachment ({len(pdf_data):,} bytes) to {to_email}")
            print(f"[INFO] 📋  PDF saved at: {pdf_path}")
        else:
            send_email(to_email=to_email, subject=subject, body=body_html, html=True)
            print(f"[WARN] ⚠️  Completion email sent WITHOUT PDF attachment to {to_email}")
    except Exception as e:
        print(f"[ERROR] ❌  Failed to send completion email: {e}")
        import traceback
        traceback.print_exc()

def send_member_eid_request_email(to_email: str, member_name: str, member_num: int, total_members: int):
    """
    Request EID for specific member
    """
    subject = f" EID Required for {member_name} (Member {member_num}/{total_members})"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'> EID Required for {member_name}</h2>
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
    print(f"[INFO] 📋 Sent EID request email for {member_name} (Member {member_num}/{total_members}) to {to_email}")
    

def send_member_identification_email(to_email: str, members: list, user_in_documents: bool, user_validation: dict = None):
    """
    Send email after identifying all members
    UPDATED: Shows validation details and EID requirements
    """
    try:
        user_response = supabase.table("users").select("name").eq("email", to_email).execute()
        user_name = user_response.data[0].get("name") if user_response.data else "User"
    except:
        user_name = "User"
    
    subject = "Multiple Owners Identified - EID Collection Process"
    
    # Build member list
    member_list_html = ""
    for i, member in enumerate(members, 1):
        member_list_html += f"<li><strong>{member}</strong></li>"
    
    # Dynamic message based on validation
    if user_in_documents:
        found_in = user_validation.get("found_in", "company documents") if user_validation else "company documents"
        matched_field = user_validation.get("matched_field", "").replace("_", " ").title() if user_validation else ""
        
        eid_message = f"""
        <div style='background:#fff3cd;border-left:4px solid #ffc107;padding:15px;margin:20px 0;'>
            <p style='margin:0;'><strong> Your EID Required</strong></p>
            <p style='margin:10px 0 0 0;'>Your name appears in the <strong>{found_in}</strong> ({matched_field}), so we will need <strong>your Emirates ID</strong> along with all member EIDs.</p>
        </div>
        """
    else:
        eid_message = f"""
        <div style='background:#e3f2fd;border-left:4px solid #2196F3;padding:15px;margin:20px 0;'>
            <p style='margin:0;'><strong> Your EID Not Required</strong></p>
            <p style='margin:10px 0 0 0;'>Your name does not appear in the company documents as a manager/owner, so we only need EIDs for the members listed above.</p>
        </div>
        """
    
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>Owners Identified Successfully</h2>
            <p>Dear {user_name},</p>
            
            <p>We have analyzed your Commercial License and MOA documents and identified the following <strong>{len(members)} owners/members</strong>:</p>
            
            <div style='background:#f8f9fa;padding:20px;border-radius:5px;margin:20px 0;'>
                <ol style='margin:0;padding-left:20px;'>
                    {member_list_html}
                </ol>
            </div>
            
            {eid_message}
            
            <div style='background:#e3f2fd;padding:15px;border-left:4px solid #2196F3;margin:20px 0;'>
                <p style='margin:0;'><strong> Total EIDs Required: {len(members)}</strong></p>
            </div>
            
            <p><strong>Next Step:</strong> We will now collect Emirates ID (EID) for each member, one by one.</p>
            
            <p>You will receive a separate email requesting the EID for the first member shortly.</p>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)

    
def send_member_documents_confirmation_email(to_email: str, members: list):
    """
    Send confirmation email with ALL member documents for verification
    Similar to single owner flow - shows all extracted data and asks for confirmation
    """
    try:
        from urllib.parse import quote
        # API_BASE = os.getenv("API_BASE_URL", "http://backend:8080")

        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"

        # ========================================
        # COLLECT ALL MEMBER DOCUMENTS FROM DISK
        # ========================================
        user_docs_dir = os.path.join("backend", "documents", "id", to_email)
        
        all_member_docs = []
        
        for member_name in members:
            member_dir = os.path.join(user_docs_dir, member_name)
            
            if not os.path.exists(member_dir):
                print(f"[WARN] ⚠️ Member directory not found: {member_name}")
                continue
            
            # Find EID output.json for this member
            for item in os.listdir(member_dir):
                item_path = os.path.join(member_dir, item)
                
                if not os.path.isdir(item_path):
                    continue
                
                output_path = os.path.join(item_path, "output.json")
                
                if os.path.exists(output_path):
                    try:
                        with open(output_path, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
                        
                        doc_type = analysis.get("document_type", "unknown")
                        is_valid = analysis.get("is_valid", False)
                        filename = analysis.get("filename", item)
                        
                        if doc_type == "eid" and is_valid:
                            all_member_docs.append({
                                "member_name": member_name,
                                "filename": filename,
                                "document_type": doc_type,
                                "extracted_fields": analysis.get("extracted_fields", {})
                            })
                            print(f"[DEBUG] 🔍 Added EID for member: {member_name}")
                            break
                    
                    except Exception as e:
                        print(f"[ERROR] ❌ Failed to read {output_path}: {e}")
        
        # Also collect main user's documents (Commercial, MOA, EID, Ejari if any)
        main_user_docs = []
        
        for item in os.listdir(user_docs_dir):
            item_path = os.path.join(user_docs_dir, item)
            
            # Skip member directories
            if any(item == member for member in members):
                continue
            
            if not os.path.isdir(item_path) or item == "member_progress.json":
                continue
            
            output_path = os.path.join(item_path, "output.json")
            
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    
                    doc_type = analysis.get("document_type", "unknown")
                    is_valid = analysis.get("is_valid", False)
                    filename = analysis.get("filename", item)
                    
                    if is_valid:
                        main_user_docs.append({
                            "filename": filename,
                            "document_type": doc_type,
                            "extracted_fields": analysis.get("extracted_fields", {})
                        })
                        print(f"[DEBUG] 🔍 Added main document: {filename} ({doc_type})")
                
                except Exception as e:
                    print(f"[ERROR] ❌ Failed to read {output_path}: {e}")
        
        print(f"[INFO] 📋 Total documents collected: {len(main_user_docs)} main + {len(all_member_docs)} member EIDs")
        
        # ========================================
        # BUILD EMAIL HTML
        # ========================================
        
        # Main user documents section
        main_docs_html = ""
        if main_user_docs:
            for doc in main_user_docs:
                filename = doc.get("filename", "Unknown")
                doc_type = doc.get("document_type", "unknown").upper()
                extracted = doc.get("extracted_fields", {})
                
                extracted_html = ""
                if isinstance(extracted, dict) and extracted:
                    fields_to_show = [
                        (k.replace("_", " ").title(), v)
                        for k, v in extracted.items()
                        if v and k not in ["document_type", "raw_text"] and "arabic" not in k.lower()
                    ]
                    
                    extracted_html = "".join([
                        f"""<div style='margin-bottom:8px;'>
                            <strong style='color:#444;'>{label}:</strong>
                            <span style='color:#666;'>{value}</span>
                        </div>"""
                        for label, value in fields_to_show[:10]  # Limit to 10 fields
                        if value
                    ])
                
                main_docs_html += f"""
                    <div style='margin-bottom:20px;padding:14px;border:1px solid #e0e0e0;border-radius:6px;background:#fff;'>
                        <h4 style='margin:0 0 10px 0;color:#1976d2;font-size:15px;'>
                            {filename} <span style='font-size:12px;color:#666;'>({doc_type})</span>
                        </h4>
                        <div style='background:#f5f5f5;padding:10px;border-radius:4px;'>
                            {extracted_html if extracted_html else '<p style="color:#999;">No data</p>'}
                        </div>
                    </div>
                """
        
        # Member EIDs section
        member_docs_html = ""
        for doc in all_member_docs:
            member_name = doc.get("member_name", "Unknown")
            filename = doc.get("filename", "Unknown")
            extracted = doc.get("extracted_fields", {})
            
            extracted_html = ""
            if isinstance(extracted, dict) and extracted:
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
                    for label, value in fields_to_show[:10]
                    if value
                ])
            
            member_docs_html += f"""
                <div style='margin-bottom:20px;padding:14px;border:1px solid #e0e0e0;border-radius:6px;background:#fff;'>
                    <h4 style='margin:0 0 10px 0;color:#4caf50;font-size:15px;'>
                        {member_name} - Emirates ID
                    </h4>
                    <div style='background:#f5f5f5;padding:10px;border-radius:4px;'>
                        {extracted_html if extracted_html else '<p style="color:#999;">No data</p>'}
                    </div>
                </div>
            """
        
        # Confirmation link
        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"
        
        subject = " Please Confirm All Member Documents"
        body_html = f"""
        <html><body style='font-family:Arial,sans-serif;color:#333;'>
            <div style='max-width:700px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
                <h2 style='color:#4CAF50;'>All Member Documents Collected</h2>
                <p>Dear User,</p>
                <p>We have successfully collected and processed documents for all <strong>{len(members)} members/owners</strong>. Please review the extracted information below and confirm if everything is correct.</p>
                
                <div style='background:#e3f2fd;padding:15px;border-radius:5px;margin:20px 0;'>
                    <p style='margin:0;'><strong>📁 Summary:</strong></p>
                    <ul style='margin:10px 0 0 20px;'>
                        <li>Total Members: <strong>{len(members)}</strong></li>
                        <li>Company Documents: <strong>{len(main_user_docs)}</strong></li>
                        <li>Member EIDs: <strong>{len(all_member_docs)}</strong></li>
                    </ul>
                </div>
                
                <h3 style='color:#1976d2;margin-top:30px;'>Company Documents</h3>
                {main_docs_html if main_docs_html else '<p style="color:#999;">No company documents found</p>'}
                
                <h3 style='color:#4caf50;margin-top:30px;'>Member Emirates IDs</h3>
                {member_docs_html if member_docs_html else '<p style="color:#999;">No member EIDs found</p>'}
                
                <div style='margin-top:30px;text-align:center;background:#f8f9fa;padding:20px;border-radius:8px;'>
                    <p style='margin:0 0 15px 0;font-size:16px;'><strong>Please verify all information is correct</strong></p>
                    <a href="{confirm_link}" style='display:inline-block;padding:14px 32px;background:#4caf50;color:#fff;border-radius:6px;text-decoration:none;font-size:18px;font-weight:bold;'>
                        Confirm All Information
                    </a>
                </div>
                
                <p style='margin-top:20px;color:#666;font-size:14px;'>If any information is incorrect, please reply to this email with corrections or request resubmission.</p>
                
                <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
            </div>
        </body></html>
        """
        
        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        print(f"[INFO] 📋 Member documents confirmation email sent to {to_email}")
    
    except Exception as e:
        print(f"[ERROR] ❌ Failed to send member documents confirmation email: {e}")
        import traceback
        traceback.print_exc()


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



def is_registered_user_in_company_documents(user_email: str) -> dict:
    """
    Check if registered user's name appears in Commercial License or MOA
    
    Returns: {
        "found": bool,
        "found_in": str,  # "commercial", "moa", "both", or "none"
        "matched_field": str,  # Which field matched
        "registered_name": str
    }
    """
    user_docs_dir = os.path.join("backend", "documents", "id", user_email)
    
    # Get registered user's name
    try:
        user_response = supabase.table("users").select("name").eq("email", user_email).execute()
        registered_name = user_response.data[0].get("name", "").strip().lower() if user_response.data else None
        
        if not registered_name:
            print(f"[WARN] ⚠️ No registered name found for {user_email}")
            return {
                "found": False,
                "found_in": "none",
                "matched_field": None,
                "registered_name": None
            }
            
    except Exception as e:
        print(f"[ERROR] ❌ Failed to get registered user name: {e}")
        return {
            "found": False,
            "found_in": "none",
            "matched_field": None,
            "registered_name": None
        }
    
    if not os.path.exists(user_docs_dir):
        return {
            "found": False,
            "found_in": "none",
            "matched_field": None,
            "registered_name": registered_name
        }
    
    print(f"\n{'='*80}")
    print(f"[INFO] 📋  CHECKING IF '{registered_name}' APPEARS IN COMPANY DOCUMENTS")
    print(f"{'='*80}\n")
    
    found_in = []
    matched_fields = []
    
    # Check Commercial License and MOA documents
    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)
        
        if not os.path.isdir(item_path):
            continue
        
        output_path = os.path.join(item_path, "output.json")
        
        if os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                
                doc_type = analysis.get("document_type", "")
                
                # Only check Commercial and MOA documents
                if doc_type not in ["commercial", "moa"]:
                    continue
                
                print(f"[INFO] 📋  Checking {doc_type.upper()} document...")
                
                extracted = analysis.get("extracted_fields", {})
                
                # Convert entire extracted data to string for searching
                extracted_text = json.dumps(extracted, ensure_ascii=False).lower()
                
                # Check if registered name appears anywhere
                if registered_name in extracted_text:
                    found_in.append(doc_type)
                    print(f"[SUCCESS] ✅ Found '{registered_name}' in {doc_type.upper()} (general match)")
                    matched_fields.append(f"{doc_type}_general")
                    continue
                
                # Detailed field checking
                if doc_type == "commercial":
                    # Check managers
                    managers = extracted.get("managers", [])
                    for mgr in managers:
                        mgr_name = mgr.get("name_english", "").strip().lower()
                        if mgr_name and (registered_name in mgr_name or mgr_name in registered_name):
                            found_in.append("commercial")
                            matched_fields.append("commercial_manager")
                            print(f"[SUCCESS] ✅ Found '{registered_name}' as MANAGER in Commercial License")
                            break
                    
                    # Check owner
                    if "commercial" not in found_in:
                        owner = extracted.get("owner", {})
                        owner_name = owner.get("name_english", "").strip().lower()
                        if owner_name and (registered_name in owner_name or owner_name in registered_name):
                            found_in.append("commercial")
                            matched_fields.append("commercial_owner")
                            print(f"[SUCCESS] ✅ Found '{registered_name}' as OWNER in Commercial License")
                
                elif doc_type == "moa":
                    eng = extracted.get("english", {})
                    
                    # Check owner
                    owner_name = eng.get("owner_name", "").strip().lower()
                    if owner_name and (registered_name in owner_name or owner_name in registered_name):
                        found_in.append("moa")
                        matched_fields.append("moa_owner")
                        print(f"[SUCCESS] ✅ Found '{registered_name}' as OWNER in MOA")
                        continue
                    
                    # Check manager
                    manager_name = eng.get("manager_name", "").strip().lower()
                    if manager_name and (registered_name in manager_name or manager_name in registered_name):
                        found_in.append("moa")
                        matched_fields.append("moa_manager")
                        print(f"[SUCCESS] ✅ Found '{registered_name}' as MANAGER in MOA")
                
            except Exception as e:
                print(f"[ERROR] ❌ Failed to check {output_path}: {e}")
                continue
    
    # Determine result
    found = len(found_in) > 0
    
    if len(found_in) == 2:
        location = "both"
    elif len(found_in) == 1:
        location = found_in[0]
    else:
        location = "none"
    
    result = {
        "found": found,
        "found_in": location,
        "matched_field": ", ".join(matched_fields) if matched_fields else None,
        "registered_name": registered_name
    }
    
    print(f"\n{'='*80}")
    print(f"[INFO] 📋 📁 VALIDATION RESULT")
    print(f"{'='*80}")
    print(f"[INFO] 📋 Registered Name: '{registered_name}'")
    print(f"[INFO] 📋 Found in Documents: {found}")
    print(f"[INFO] 📋 Found In: {location}")
    print(f"[INFO] 📋 Matched Fields: {matched_fields}")
    print(f"{'='*80}\n")
    
    return result

def process_user_reply(from_email: str, body: str, attachments: list = None):
    """
    Enhanced reply handler with cross-validation + SurePass API validation
    
    VALIDATION REQUIREMENT:
    - SAVINGS: Validate EID + Ejari, then SurePass API, then ask for confirmation
    - CORPORATE (Single Owner): Validate Commercial + EID + Ejari, then SurePass API, then ask for confirmation
    - CORPORATE (Multiple Owners): NO validation, NO SurePass - proceed directly to member EID collection
      * NEW: Check if registered user appears in Commercial/MOA, request their EID only if found
    """
    print(f"\n{'='*80}")
    print(f"[INFO] 📋 NEW EMAIL PROCESSING STARTED")
    print(f"[INFO] 📋 From: {from_email}")
    print(f"[INFO] 📋 Attachments: {len(attachments) if attachments else 0}")
    print(f"{'='*80}\n")
    
    # Get user data
    user_response = supabase.table("users").select("*").eq("email", from_email).execute()
    if not user_response.data:
        print(f"[WARN] ⚠️ Email not found: {from_email}")
        return
    
    user = user_response.data[0]
    account_type = user.get("account_type")
    ownership_type = user.get("ownership_type")
    onboarding_step = user.get("onboarding_step", "welcome")
    document_stage = user.get("document_stage", "identification")
    user_name = user.get("name", "User")
    
    print(f"[INFO] 📋 Processing reply from {from_email}")
    print(f"       Account Type: {account_type}")
    print(f"       Ownership Type: {ownership_type}")
    print(f"       Onboarding Step: {onboarding_step}")
    print(f"       Document Stage: {document_stage}")
    
    # Get document requirements for this user's flow
    doc_requirements = get_required_documents(account_type, ownership_type)
    
    if not doc_requirements:
        print(f"[ERROR] ❌ Could not determine document requirements for {from_email}")
        return
    
    # ========================================
    # PROCESS ATTACHMENTS
    # ========================================
    if attachments:
        print(f"[INFO] 📋 Processing {len(attachments)} documents for {from_email}")
        
        # === CORPORATE - MULTIPLE OWNERS - MEMBER EID COLLECTION ===
        if (account_type == "Corporate" and 
            ownership_type in ["Partnership", "Multiple Owners"] and
            document_stage == "member_eids"):
            
            print("[INFO] 📋 Processing member EID documents (no validation needed)")
            
            progress = get_member_progress(from_email)
            
            if not progress:
                print(f"[ERROR] ❌ No member progress found for {from_email}")
                return
            
            members = progress["members"]
            current_index = progress["current_index"]
            
            if current_index >= len(members):
                print(f"[ERROR] ❌ Invalid member index: {current_index}/{len(members)}")
                return
            
            current_member = members[current_index]
            print(f"[INFO] 📋 Processing documents for member {current_index + 1}/{len(members)}: {current_member}")
            
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
                print(f"[SUCCESS] ✅ Valid EID received for {current_member}")
                
                # Move to next member
                current_index += 1
                
                if current_index < len(members):
                    # Request next member's EID
                    next_member = members[current_index]
                    save_member_progress(from_email, members, current_index)
                    
                    print(f"[INFO] 📋 Requesting EID for next member: {next_member}")
                    
                    send_member_eid_request_email(
                        from_email,
                        next_member,
                        current_index + 1,
                        len(members)
                    )
                    return
                else:
                    # All members processed - Send confirmation request (NOT completion yet)
                    print(f"[SUCCESS] ✅ All {len(members)} member EIDs collected!")
                    
                    # Update status to awaiting confirmation
                    supabase.table("users").update({
                        "onboarding_step": "awaiting_confirmation",
                        "document_stage": "member_eids_complete"
                    }).eq("email", from_email).execute()
                    
                    # Send confirmation email with ALL member data
                    send_member_documents_confirmation_email(from_email, members)
                    print("[INFO] 📋 Confirmation email sent. Awaiting user confirmation.")
                    return
            else:
                # Invalid/missing EID - request again
                print(f"[WARN] ⚠️ Invalid EID for {current_member}, requesting resubmission")
                
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
            print("[INFO] 📋 Processing user documents (validation required for this flow)")
            
            # Process documents
            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=False
            )
            
            # ====================================
            # STAGE 1: SAVINGS ACCOUNT
            # Requires: EID + Ejari validation + SurePass API + confirmation
            # ====================================
            if account_type == "Savings":
                print("[INFO] 📋 Checking Savings Account completion (with confirmation)")
                
                stage_check = check_document_stage_completion(
                    from_email, 
                    ["eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] ✅ All Savings Account documents valid")
                    
                    # ============================================================================
                    # 🔍 CROSS-VALIDATION WITH NOTIFICATION SYSTEM
                    # ============================================================================
                    print("\n🔍 [INFO] Running cross-validation for Savings Account...")
                    
                    try:
                        from app.services.cross_validator import CrossValidator
                        from app.services.email_sender import (
                            send_validation_pending_email,
                            send_validation_failed_email,
                            send_validation_passed_email
                        )
                        
                        validator = CrossValidator()
                        
                        # STEP 1: Send "Validation Pending" notification
                        print("[INFO] 📋 📧 Sending validation pending notification...")
                        send_validation_pending_email(from_email, user_name)
                        print("[SUCCESS] ✅ Validation pending email sent")
                        
                        # STEP 2: Run cross-validation
                        print("[INFO] 📋 🔍 Running cross-validation...")
                        validation_result = validator.validate_documents(from_email, user)
                        
                        # STEP 3: Save validation result as JSON
                        print("[INFO] 📋 💾 Saving validation result...")
                        validator.save_validation_result(from_email, validation_result)
                        print("[SUCCESS] ✅ Validation result saved to JSON")
                        
                        # STEP 4: Handle validation result
                        if validation_result["passed"]:
                            print("[SUCCESS] Cross-validation passed!")
                            
                            # ============================================================================
                            # ✅ STEP 4A: SUREPASS API VALIDATION (Savings & Single Owner only)
                            # ============================================================================
                            print(f"\n{'='*80}")
                            print(f"🔍 [SUREPASS] Running government verification for Emirates ID...")
                            print(f"{'='*80}")
                            
                            surepass_valid, surepass_message = validate_eid_before_confirmation(from_email)
                            
                            if not surepass_valid:
                                print(f"❌ ERROR: SurePass validation failed")
                                print(f"❌ Reason: {surepass_message}")
                                # Failure email already sent by validate_eid_before_confirmation
                                # Do NOT send completion email
                                return
                            else:
                                print(f"✅ SUCCESS: SurePass validation passed!")
                                
                                # Send success notification
                                send_validation_passed_email(from_email, user_name)
                                print("[INFO] 📋 Validation success email sent")
                                
                                # ALL DOCUMENTS VALID AND CROSS-VALIDATED - ASK FOR CONFIRMATION
                                send_document_status_email(from_email, results, is_member=False)
                                print("[INFO] 📋 Confirmation email sent. Awaiting user confirmation.")
                                return
                        
                        else:
                            #  CROSS-VALIDATION FAILED
                            print(f" [ERROR] Cross-validation failed for Savings Account")
                            print(f"Mismatches: {validation_result['mismatches']}")
                            
                            # Send failure notification with details
                            send_validation_failed_email(
                                to_email=from_email,
                                user_name=user_name,
                                mismatches=validation_result["mismatches"],
                                attempt_count=validation_result.get("attempt_count", 1)
                            )
                            print("[INFO] 📋 Validation failure email sent with detailed mismatches")
                            return
                    
                    except Exception as e:
                        print(f"[ERROR] ❌ Cross-validation system error: {e}")
                        import traceback
                        traceback.print_exc()
                        
                        # Fallback: Proceed without cross-validation (with warning email)
                        print("[WARN] ⚠️ Proceeding without cross-validation due to system error")
                        send_document_status_email(from_email, results, is_member=False)
                        print("[INFO] 📋 Confirmation email sent (cross-validation skipped due to error)")
                        return
                else:
                    # Missing or invalid documents - request resubmission
                    print(f"[INFO] 📋 Missing/invalid documents: {stage_check['missing']}")
                    
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
            # Requires: Commercial + EID + Ejari validation + SurePass API + confirmation
            # ====================================
            elif account_type == "Corporate" and ownership_type == "Single Owner":
                print("[INFO] 📋 Checking Corporate Single Owner completion (with confirmation)")
                
                stage_check = check_document_stage_completion(
                    from_email,
                    ["commercial", "eid", "ejari"]
                )
                
                if stage_check["complete"]:
                    print("[SUCCESS] ✅ All Corporate Single Owner documents valid")
                    
                    # ============================================================================
                    # 🔍 CROSS-VALIDATION WITH NOTIFICATION SYSTEM
                    # ============================================================================
                    print("\n🔍 [INFO] Running cross-validation for Corporate Single Owner...")
                    
                    try:
                        from app.services.cross_validator import CrossValidator
                        from app.services.email_sender import (
                            send_validation_pending_email,
                            send_validation_failed_email,
                            send_validation_passed_email
                        )
                        
                        validator = CrossValidator()
                        
                        # STEP 1: Send "Validation Pending" notification
                        print("[INFO] 📋 📧 Sending validation pending notification...")
                        send_validation_pending_email(from_email, user_name)
                        print("[SUCCESS] ✅ Validation pending email sent")
                        
                        # STEP 2: Run cross-validation
                        print("[INFO] 📋 🔍 Running cross-validation...")
                        validation_result = validator.validate_documents(from_email, user)
                        
                        # STEP 3: Save validation result as JSON
                        print("[INFO] 📋 💾 Saving validation result...")
                        validator.save_validation_result(from_email, validation_result)
                        print("[SUCCESS] ✅ Validation result saved to JSON")
                        
                        # STEP 4: Handle validation result
                        if validation_result["passed"]:
                            print("[SUCCESS] Cross-validation passed!")
                            
                            # ============================================================================
                            # ✅ STEP 4A: SUREPASS API VALIDATION (Savings & Single Owner only)
                            # ============================================================================
                            print(f"\n{'='*80}")
                            print(f"🔍 [SUREPASS] Running government verification for Emirates ID...")
                            print(f"{'='*80}")
                            
                            surepass_valid, surepass_message = validate_eid_before_confirmation(from_email)
                            
                            if not surepass_valid:
                                print(f"❌ ERROR: SurePass validation failed")
                                print(f"❌ Reason: {surepass_message}")
                                # Failure email already sent by validate_eid_before_confirmation
                                # Do NOT send completion email
                                return
                            else:
                                print(f"✅ SUCCESS: SurePass validation passed!")
                                
                                # Send success notification
                                send_validation_passed_email(from_email, user_name)
                                print("[INFO] 📋 Validation success email sent")
                                
                                # ALL DOCUMENTS VALID AND CROSS-VALIDATED - ASK FOR CONFIRMATION
                                send_document_status_email(from_email, results, is_member=False)
                                print("[INFO] 📋 Confirmation email sent. Awaiting user confirmation.")
                                return
                        
                        else:
                            #  CROSS-VALIDATION FAILED
                            print(f" [ERROR] Cross-validation failed for Corporate Single Owner")
                            print(f"Mismatches: {validation_result['mismatches']}")
                            
                            # Send failure notification with details
                            send_validation_failed_email(
                                to_email=from_email,
                                user_name=user_name,
                                mismatches=validation_result["mismatches"],
                                attempt_count=validation_result.get("attempt_count", 1)
                            )
                            print("[INFO] 📋 Validation failure email sent with detailed mismatches")
                            return
                    
                    except Exception as e:
                        print(f"[ERROR] ❌ Cross-validation system error: {e}")
                        import traceback
                        traceback.print_exc()
                        
                        # Fallback: Proceed without cross-validation (with warning email)
                        print("[WARN] ⚠️ Proceeding without cross-validation due to system error")
                        send_document_status_email(from_email, results, is_member=False)
                        print("[INFO] 📋 Confirmation email sent (cross-validation skipped due to error)")
                        return
                else:
                    # Missing or invalid documents - request resubmission
                    print(f"[INFO] 📋 Missing/invalid documents: {stage_check['missing']}")
                    
                    send_missing_documents_email(
                        from_email,
                        stage_check["missing"],
                        "Corporate Single Owner"
                    )
                    return
            
            # ====================================
            # STAGE 3: CORPORATE - MULTIPLE OWNERS
            # NO validation, NO confirmation - proceed directly to member identification
            # NEW: Check if registered user is in company docs, request their EID conditionally
            # ====================================
            elif account_type == "Corporate" and ownership_type in ["Partnership", "Multiple Owners"]:
                print("[INFO] 📋 Corporate Multiple Owners - Identification Stage (no confirmation needed)")
                
                # Check current stage
                if document_stage == "identification":
                    print("[INFO] 📋 Stage: Identification (need Commercial + MOA)")
                    
                    # Stage 1: Need Commercial + MOA to identify owners
                    # NOTE: No validation/confirmation here - just collect documents
                    stage_check = check_document_stage_completion(
                        from_email,
                        ["commercial", "moa"]
                    )
                    
                    if stage_check["complete"]:
                        print("[SUCCESS] ✅ Commercial + MOA received, extracting members")
                        
                        # UPDATED: Extract members with validation
                        member_data = extract_members_from_documents(from_email)
                        member_names = member_data["members"]
                        user_in_documents = member_data["includes_user"]
                        user_validation = member_data["user_validation"]  # NEW
                        
                        if member_names and len(member_names) > 0:
                            print(f"[INFO] 📋 Identified {len(member_names)} total members/owners")
                            print(f"       - Registered user in documents: {user_in_documents}")
                            print(f"       - Found in: {user_validation['found_in']}")  # NEW
                            print(f"       - Total EIDs to collect: {len(member_names)}")
                            
                            # Create directories for each member
                            base_docs_dir = os.path.join("backend", "documents", "id", from_email)
                            for member_name in member_names:
                                member_dir = os.path.join(base_docs_dir, member_name)
                                os.makedirs(member_dir, exist_ok=True)
                            
                            # Save progress - start with first member
                            save_member_progress(from_email, member_names, 0)
                            
                            # Update stage
                            supabase.table("users").update({
                                "document_stage": "member_eids",
                                "onboarding_step": "member_documents_required"
                            }).eq("email", from_email).execute()
                            
                            # UPDATED: Send identification email with validation info
                            send_member_identification_email(
                                from_email,
                                member_names,
                                user_in_documents,
                                user_validation  # Pass validation details
                            )
                            
                            # Request first member's EID immediately
                            send_member_eid_request_email(
                                from_email,
                                member_names[0],
                                1,
                                len(member_names)
                            )
                            
                            print(f"[INFO] 📋 Proceeding to member EID collection")
                            return
                        else:
                            # No members found - error
                            print("[ERROR] ❌ Could not identify owners from documents")
                            
                            subject = "Error Identifying Owners"
                            body_html = """
                            <html><body style='font-family:Arial,sans-serif;color:#333;'>
                                <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
                                    <h2 style='color:#c62828;'> Error Identifying Owners</h2>
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
                        print(f"[INFO] 📋 Still need documents: {stage_check['missing']}")
                        
                        send_missing_documents_email(
                            from_email,
                            stage_check["missing"],
                            "Multiple Owners - Identification Stage"
                        )
                        return
    
    # ========================================
    # NO ATTACHMENTS - REGULAR CHAT
    # ========================================
    print("[INFO] 📋 No attachments, processing as chat message")
    
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
        print(f"[WARN] ⚠️ FAQ retrieval failed: {e}")
        faq_context = ""
    
    # Get conversation history
    try:
        convo_response = supabase.table("conversations").select("*").eq("email", from_email).order("timestamp").execute()
        convo_history = convo_response.data if convo_response.data else []
        convo_context = "\n".join([f"{msg['role']}: {msg['message']}" for msg in convo_history[-6:]])
    except Exception as e:
        print(f"[WARN] ⚠️ Conversation history retrieval failed: {e}")
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
        print(f"[ERROR] ❌ LLM call failed: {e}")
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
    
    print(f"[INFO] 📋 Chat response sent to: {from_email}")

