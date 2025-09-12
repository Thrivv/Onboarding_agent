# app/services/ocr_service.py

import os
import base64
import requests
import json
import re
from dotenv import load_dotenv
from app.services.supabase_client import supabase
from llm_runner.run_model import call_local_llm


load_dotenv()

DOCUMENTS_ROOT = os.path.join("backend", "documents", "id")

# === LLaMA 3.2 Vision CONFIG ===
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"

# ---------------------------
# Keywords and Field Mapping
# ---------------------------
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
        "federal authority for identity & citizenship",
        "authority for identity", "resident", "identity",
        "بطاقة هوية", "بطاقة هوية مقيم", "بطاقة الهوية الإماراتية",
        "الإمارات العربية المتحدة", "رقم الهوية"
    ]
}

REQUIRED_FIELDS = {
    "commercial": {
        "License No.": ["license no", "license number", "رقم الرخصة"],
        "Company Name": ["company name", "اسم الشركة"],
        "Business Name": ["business name", "الإسم التجاري", "trade name"],
        "License Category": ["license category", "فئة الرخصة", "category"],
        "Legal Type": ["legal type", "الشكل القانوني", "company type"],
        "Expiry Date": ["expiry date", "تاريخ انتهاء", "expiration"],
        "Register No.": ["register no", "رقم السجل التجاري", "registration number"],
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

# ---------------------------
# Helpers
# ---------------------------

def ensure_directory(path: str):
    os.makedirs(path, exist_ok=True)

def encode_image(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "jpeg" if ext in [".jpg", ".jpeg"] else "png"
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/{mime_type};base64,{image_b64}"

def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
    image_url = encode_image(image_path)

    prompt = """You are an OCR system. Perform OCR on the provided image and extract all text accurately.
"""

    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "OCR Extraction"
    }

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 1500,
        "temperature": 0.1
    }

    response = requests.post(LLAMA_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    else:
        raise RuntimeError(f"OCR failed: {response.status_code} {response.text}")

# ---------------------------
# Document Analysis
# ---------------------------

def identify_document_type(extracted_text: str) -> str:
    text_lower = extracted_text.lower()
    commercial_score = sum(1 for kw in DOCUMENT_KEYWORDS["commercial"] if kw in text_lower)
    eid_score = sum(1 for kw in DOCUMENT_KEYWORDS["eid"] if kw in text_lower)
    if commercial_score > 0 and commercial_score >= eid_score:
        return "commercial"
    elif eid_score > 0:
        return "eid"
    return "unknown"

def extract_fields(text: str, doc_type: str) -> dict:
    if doc_type not in REQUIRED_FIELDS:
        return {}
    extracted = {}
    text_lower = text.lower()
    for field, keywords in REQUIRED_FIELDS[doc_type].items():
        found = None
        for kw in keywords:
            # Try "keyword: value"
            match = re.search(rf"{re.escape(kw)}\s*[:\-]?\s*([^\n\r]+)", text_lower, re.IGNORECASE)
            if match:
                found = match.group(1).strip()
                break
        if found:
            extracted[field] = found
    return extracted

def validate_fields(extracted: dict, doc_type: str) -> dict:
    required = list(REQUIRED_FIELDS.get(doc_type, {}).keys())
    present = list(extracted.keys())
    missing = [f for f in required if f not in present]
    return {
        "is_valid": len(missing) == 0,
        "required_fields": required,
        "present_fields": present,
        "missing_fields": missing,
    }

# ---------------------------
# Main Pipeline
# ---------------------------

def process_document(user_email: str, document_id: str, file_path: str, model_name: str = LLAMA_MODEL_NAME) -> dict:
    """
    Full pipeline:
    1. Perform OCR
    2. Identify doc type
    3. Extract fields using LLM with schema prompt
    4. Validate
    5. Save JSON into backend/documents/id/<user>/<doc_id>/output.json
    """
    print(f"[INFO] Processing {file_path} for {user_email} with model {model_name}")

    try:
        raw_text = run_ocr(file_path, model_name)
    except Exception as e:
        raw_text = ""
        analysis = {
            "filename": os.path.basename(file_path),
            "document_type": "error",
            "raw_text": f"[OCR ERROR] {str(e)}",
            "extracted_fields": {},
            "validation": {"is_valid": False, "required_fields": [], "present_fields": [], "missing_fields": []},
            "status_message": f"❌ ERROR: Failed to process {os.path.basename(file_path)}",
            "is_valid": False
        }
    else:
        doc_type = identify_document_type(raw_text)
        # Prepare schema prompt
        schema = REQUIRED_FIELDS.get(doc_type, {})
        schema_prompt = (
            f"You are an information extraction system. Extract the following fields from the document text according to this schema:\n"
            f"{json.dumps(list(schema.keys()), indent=2)}\n"
            "Return ONLY a valid JSON object with keys as field names and values as extracted values. Do not include any explanation or extra text.\n"
            f"Document text:\n{raw_text}"
        )
        # Call LLM for extraction
        llm_extracted = {}
        try:
            llm_response = call_local_llm(schema_prompt)
            # Try to extract JSON from the response
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            llm_json_str = llm_response[json_start:json_end]
            llm_extracted = json.loads(llm_json_str)
        except Exception as e:
            print(f"[ERROR] LLM extraction failed: {e}")
            llm_extracted = {}

        validation = validate_fields(llm_extracted, doc_type)

        if doc_type == "unknown":
            status = f"❌ WRONG DOCUMENT: {file_path} is not a recognized document type."
        elif not validation["is_valid"]:
            status = f"❌ INCOMPLETE DOCUMENT: missing {', '.join(validation['missing_fields'])}"
        else:
            status = f"✅ VALID DOCUMENT: {doc_type} with all required fields."

        analysis = {
            "filename": os.path.basename(file_path),
            "document_type": doc_type,
            "raw_text": raw_text,
            "extracted_fields": llm_extracted,
            "validation": validation,
            "status_message": status,
            "is_valid": doc_type in ["commercial", "eid"] and validation["is_valid"]
        }

    # Save JSON
    output_dir = os.path.join(DOCUMENTS_ROOT, user_email, document_id)
    ensure_directory(output_dir)
    output_path = os.path.join(output_dir, "output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    print(f"[INFO] Output saved: {output_path}")
    return analysis
