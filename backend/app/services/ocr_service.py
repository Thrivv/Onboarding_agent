
import os
import base64
import requests
import json
import re
from dotenv import load_dotenv
from app.services.supabase_client import supabase

load_dotenv()

DOCUMENTS_ROOT = os.path.join("backend", "documents", "id")

# === LLaMA 3.2 Vision CONFIG ===
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Add this key to your .env file
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"

# Required fields for each document type
REQUIRED_FIELDS = {
    "commercial": {
        "License No.": ["license no", "license number", "رقم الرخصة"],
        "Company Name": ["company name", "اسم الشركة"],
        "Business Name": ["business name", "الإسم التجاري", "trade name"],
        "License Category": ["license category", "فئة الرخصة", "category"],
        "Legal Type": ["legal type", "الشكل القانوني", "company type"],
        "Expiry Date": ["expiry date", "تاريخ انتهاء", "expiration"],
        "Register No.": ["register no", "رقم السجل التجاري", "registration number"],
        "Issue Date": ["issue date", "تاريخ الإصدار", "issuing date"],
        "DCCI No.": ["dcci no", "عضوية الغرفة", "chamber number"],
        "License Members": ["license members", "الشركاء", "members", "shareholders"]
    },
    "eid": {
        "Document Type": ["resident identity card", "emirates id", "identity card", "بطاقة هوية"],
        "ID Number": ["id number", "رقم الهوية", "784-", "card number"],
        "Name": ["name", "الاسم", "holder name"],
        "Date of Birth": ["date of birth", "تاريخ الميلاد", "birth date"],
        "Nationality": ["nationality", "الجنسية"],
        "Issuing Date": ["issuing date", "تاريخ الإصدار", "issue date"],
        "Expiry Date": ["expiry date", "تاريخ الانتهاء", "expiration"],
        "Sex": ["sex", "الجنس", "gender"]
    }
}

# Document type identification keywords
DOCUMENT_KEYWORDS = {
    "commercial": [
        "commercial registration", "trade license", "business license",
        "commercial license", "establishment card", "commerce", "trading",
        "company registration", "business registration", "commercial permit",
        "رخصة تجارية", "government of dubai", "dubai economy"
    ],
    "eid": [
        "emirates id", "identity card", "resident identity card", "emirates identity",
        "id card", "residence card", "national id", "civil id", "eid",
        "united arab emirates", "federal authority for identity",
        "بطاقة هوية", "الإمارات العربية المتحدة"
    ]
}

def identify_document_type(extracted_text: str) -> str:
    text_lower = extracted_text.lower()
    commercial_score = sum(1 for keyword in DOCUMENT_KEYWORDS["commercial"] if keyword in text_lower)
    eid_score = sum(1 for keyword in DOCUMENT_KEYWORDS["eid"] if keyword in text_lower)
    if commercial_score > 0 and commercial_score >= eid_score:
        return "commercial"
    elif eid_score > 0:
        return "eid"
    else:
        return "unknown"

def extract_fields_from_text(text: str, doc_type: str) -> dict:
    if doc_type not in REQUIRED_FIELDS:
        return {}
    extracted_fields = {}
    text_lower = text.lower()
    for field_name, field_keywords in REQUIRED_FIELDS[doc_type].items():
        found_value = None
        for keyword in field_keywords:
            pattern1 = rf"{re.escape(keyword)}\s*:?\s*([^\n\r]+)"
            match = re.search(pattern1, text_lower, re.IGNORECASE)
            if match:
                found_value = match.group(1).strip()
                break
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if keyword in line.lower() and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and len(next_line) > 1:
                        found_value = next_line
                        break
            if found_value:
                break
        if found_value:
            found_value = re.sub(r'^[:\-\s]+', '', found_value)
            found_value = re.sub(r'[:\-\s]+$', '', found_value)
            found_value = found_value.strip()
            if len(found_value) > 2:
                extracted_fields[field_name] = found_value
    return extracted_fields

def validate_document_fields(extracted_fields: dict, doc_type: str) -> dict:
    required_fields = list(REQUIRED_FIELDS.get(doc_type, {}).keys())
    present_fields = list(extracted_fields.keys())
    missing_fields = [field for field in required_fields if field not in present_fields]
    return {
        "is_valid": len(missing_fields) == 0,
        "required_fields": required_fields,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "extracted_data": extracted_fields
    }

def generate_enhanced_prompt(doc_type_hint: str = None) -> str:
    base_prompt = """You are an expert OCR system. Analyze this document image and extract ALL visible text with high accuracy.

IMPORTANT INSTRUCTIONS:
1. Extract ALL text you can see, including headers, field names, values, numbers, dates, and Arabic text
2. Maintain the structure and formatting as much as possible
3. For each piece of information, try to identify what field it represents
4. Pay special attention to dates (format: DD/MM/YYYY), numbers, and proper names
5. Include both English and Arabic text where visible

"""
    if doc_type_hint == "commercial":
        base_prompt += """
This appears to be a Commercial License/Registration document. Focus on extracting:
- License Number/رقم الرخصة
- Company Name/اسم الشركة  
- Business/Trade Name/الإسم التجاري
- License Category/فئة الرخصة
- Legal Type/الشكل القانوني
- Issue Date/تاريخ الإصدار
- Expiry Date/تاريخ انتهاء
- Register Number/رقم السجل التجاري
- DCCI Number/عضوية الغرفة
- Owner/Member details/الشركاء
"""
    elif doc_type_hint == "eid":
        base_prompt += """
This appears to be an Emirates ID/Identity Card. Focus on extracting:
- ID Number/رقم الهوية (format: 784-YYYY-XXXXXXX-X)
- Full Name/الاسم
- Date of Birth/تاريخ الميلاد
- Nationality/الجنسية
- Sex/Gender/الجنس
- Issuing Date/تاريخ الإصدار
- Expiry Date/تاريخ الانتهاء
- Document Type (Resident Identity Card)
"""
    base_prompt += """
Format your response as clear, structured text with field names and values clearly separated.
Extract ALL visible text, even if you're not sure about a field - include everything you can read."""
    return base_prompt

def process_ocr_result(filename: str, extracted_text: str) -> dict:
    doc_type = identify_document_type(extracted_text)
    extracted_fields = extract_fields_from_text(extracted_text, doc_type)
    validation = validate_document_fields(extracted_fields, doc_type)
    status_message = ""
    if doc_type == "unknown":
        status_message = f"❌ WRONG DOCUMENT: {filename} is not a recognized document type (Commercial License or Emirates ID). Please submit the correct documents."
    elif not validation["is_valid"]:
        status_message = f"❌ INCOMPLETE DOCUMENT: {filename} is missing required fields: {', '.join(validation['missing_fields'])}. Please submit a clear, complete document."
    else:
        status_message = f"✅ VALID DOCUMENT: {filename} is a valid {doc_type} document with all required fields."
    return {
        "filename": filename,
        "type": doc_type,
        "raw_text": extracted_text,
        "extracted_fields": extracted_fields,
        "validation": validation,
        "status_message": status_message,
        "is_valid": doc_type in ["commercial", "eid"] and validation["is_valid"]
    }

def extract_text_from_user_documents(user_email: str) -> dict:
    user_folder = os.path.join(DOCUMENTS_ROOT, user_email)
    if not os.path.exists(user_folder):
        raise FileNotFoundError(f"[ERROR] No folder found for user: {user_folder}")

    ocr_json_path = os.path.join(user_folder, "ocr-results.json")
    if os.path.exists(ocr_json_path):
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            ocr_results = json.load(f)
    else:
        ocr_results = {}

    image_files = [f for f in os.listdir(user_folder) 
                   if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]

    result_summary = ""
    processing_results = {}

    for filename in image_files:
        if filename in ocr_results:
            if isinstance(ocr_results[filename], dict) and "validation" in ocr_results[filename]:
                processing_results[filename] = ocr_results[filename]
            else:
                print(f"[INFO] Reprocessing {filename} with new format")
            continue

        file_path = os.path.join(user_folder, filename)
        print(f"[INFO] Processing file: {filename}")

        try:
            with open(file_path, "rb") as img_file:
                image_bytes = img_file.read()
            ext = os.path.splitext(file_path)[1].lower()
            mime_type = "jpeg" if ext in [".jpg", ".jpeg"] else "png"
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            image_url = f"data:image/{mime_type};base64,{image_b64}"

            prompt = generate_enhanced_prompt()

            headers = {
                "Authorization": f"Bearer {LLAMA_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "OCR Extraction"
            }

            payload = {
                "model": LLAMA_MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            }

            response = requests.post(LLAMA_API_URL, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                extracted_text = result["choices"][0]["message"]["content"].strip()
                analysis = process_ocr_result(filename, extracted_text)
                processing_results[filename] = analysis
                ocr_results[filename] = analysis
                result_summary += f"\n{analysis['status_message']}\n"
                if analysis['extracted_fields']:
                    result_summary += f"Extracted fields: {', '.join(analysis['extracted_fields'].keys())}\n"
                print(f"[INFO] Successfully processed {filename} as {analysis['type']}")
            else:
                error_msg = f"HTTP {response.status_code} - {response.text}"
                error_analysis = {
                    "filename": filename,
                    "type": "error",
                    "raw_text": f"[ERROR: {error_msg}]",
                    "extracted_fields": {},
                    "validation": {"is_valid": False, "missing_fields": [], "present_fields": []},
                    "status_message": f"❌ ERROR: Failed to process {filename} - {error_msg}",
                    "is_valid": False
                }
                processing_results[filename] = error_analysis
                ocr_results[filename] = error_analysis
                print(f"[ERROR] Failed to process {filename}: {error_msg}")

        except Exception as e:
            error_msg = str(e)
            error_analysis = {
                "filename": filename,
                "type": "error",
                "raw_text": f"[ERROR: {error_msg}]",
                "extracted_fields": {},
                "validation": {"is_valid": False, "missing_fields": [], "present_fields": []},
                "status_message": f"❌ ERROR: Failed to process {filename} - {error_msg}",
                "is_valid": False
            }
            processing_results[filename] = error_analysis
            ocr_results[filename] = error_analysis
            print(f"[ERROR] Exception processing {filename}: {e}")

    save_results_to_files(user_folder, processing_results, result_summary)
    validation_summary = check_document_completion(processing_results, user_email)
    ocr_results["validation_summary"] = validation_summary
    return ocr_results

def save_results_to_files(user_folder: str, processing_results: dict, result_summary: str):
    output_file = os.path.join(user_folder, "ocr-res.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=== DOCUMENT VALIDATION RESULTS ===\n")
        f.write(result_summary)
        f.write("\n" + "="*50 + "\n")
        for filename, analysis in processing_results.items():
            f.write(f"\n--- {filename} [{analysis['type'].upper()}] ---\n")
            f.write(f"Status: {analysis['status_message']}\n")
            if analysis['extracted_fields']:
                f.write("\nExtracted Fields:\n")
                for field, value in analysis['extracted_fields'].items():
                    f.write(f"  {field}: {value}\n")
            if analysis['validation']['missing_fields']:
                f.write(f"\nMissing Fields: {', '.join(analysis['validation']['missing_fields'])}\n")
            f.write(f"\nRaw OCR Text:\n{analysis['raw_text']}\n")
            f.write("-" * 50 + "\n")
    ocr_json_path = os.path.join(user_folder, "ocr-results.json")
    with open(ocr_json_path, "w", encoding="utf-8") as f:
        json.dump(processing_results, f, ensure_ascii=False, indent=2)

def check_document_completion(processing_results: dict, user_email: str) -> dict:
    valid_commercial = any(
        analysis["type"] == "commercial" and analysis["is_valid"] 
        for analysis in processing_results.values()
    )
    valid_eid = any(
        analysis["type"] == "eid" and analysis["is_valid"] 
        for analysis in processing_results.values()
    )
    commercial_docs = [name for name, analysis in processing_results.items() if analysis["type"] == "commercial"]
    eid_docs = [name for name, analysis in processing_results.items() if analysis["type"] == "eid"]
    unknown_docs = [name for name, analysis in processing_results.items() if analysis["type"] == "unknown"]
    error_docs = [name for name, analysis in processing_results.items() if analysis["type"] == "error"]
    validation_summary = {
        "has_valid_commercial": valid_commercial,
        "has_valid_eid": valid_eid,
        "is_complete": valid_commercial and valid_eid,
        "commercial_documents": commercial_docs,
        "eid_documents": eid_docs,
        "unknown_documents": unknown_docs,
        "error_documents": error_docs,
        "total_documents": len(processing_results)
    }
    if validation_summary["is_complete"]:
        validation_summary["message"] = "✅ Document verification complete! Both Commercial License and Emirates ID have been successfully validated."
        try:
            supabase.table("users").update({"onboarding_step": "verification_complete"}).eq("email", user_email).execute()
            print(f"[INFO] Onboarding step set to verification_complete for {user_email}")
        except Exception as e:
            print(f"[ERROR] Failed to update onboarding step: {e}")
    else:
        messages = []
        if not valid_commercial:
            if not commercial_docs:
                messages.append("❌ Commercial License missing - please upload your Commercial License/Trade License")
            else:
                messages.append("❌ Commercial License incomplete or invalid - please upload a clear, complete Commercial License")
        if not valid_eid:
            if not eid_docs:
                messages.append("❌ Emirates ID missing - please upload your Emirates ID/Identity Card")
            else:
                messages.append("❌ Emirates ID incomplete or invalid - please upload a clear, complete Emirates ID")
        if unknown_docs:
            messages.append(f"❌ Wrong document(s) submitted: {', '.join(unknown_docs)} - please upload only Commercial License and Emirates ID")
        validation_summary["message"] = "\n".join(messages)
    return validation_summary

def get_user_document_status(user_email: str) -> dict:
    ocr_json_path = os.path.join(DOCUMENTS_ROOT, user_email, "ocr-results.json")
    if not os.path.exists(ocr_json_path):
        return {
            "status": "no_documents",
            "message": "No documents have been uploaded yet. Please upload your Commercial License and Emirates ID.",
            "details": {}
        }
    try:
        with open(ocr_json_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        if "validation_summary" in results:
            return {
                "status": "processed",
                "message": results["validation_summary"]["message"],
                "details": results["validation_summary"]
            }
        else:
            return {
                "status": "needs_reprocessing",
                "message": "Documents need to be reprocessed with updated validation. Please re-upload your documents.",
                "details": {}
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error reading document status: {str(e)}",
            "details": {}
        }
