# app/services/ocr_service.py

import os
import base64
import requests
import json
import re
from dotenv import load_dotenv
from app.services.supabase_client import supabase
from llm_runner.run_model import call_local_llm
from datetime import datetime, timezone
# Import specialized extractors
import sys

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from specialized_ocr import EjariExtractor, MOAExtractor, TradeLicenseExtractor
import time
from functools import wraps

load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))  # .../backend/app/services/
APP_DIR = os.path.dirname(CURRENT_DIR)  # .../backend/app/
BACKEND_DIR = os.path.dirname(APP_DIR)  # .../backend/
# DOCUMENTS_ROOT = os.path.join(BACKEND_DIR, "documents", "id")
DOCUMENTS_ROOT = os.getenv("DOCUMENTS_PATH", "/app/backend/documents") + "/id"
# === LLaMA 3.2 Vision CONFIG ===
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-7b-instruct"

# ---------------------------
# Keywords and Field Mapping for EID (Standard OCR)
# ---------------------------
DOCUMENT_KEYWORDS = {
    "eid": [
        "emirates id",
        "identity card",
        "resident identity card",
        "emirates identity",
        "id card",
        "residence card",
        "national id",
        "civil id",
        "eid",
        "united arab emirates",
        "federal authority for identity",
        "federal authority for identity & citizenship",
        "authority for identity",
        "resident",
        "identity",
        "بطاقة هوية",
        "بطاقة هوية مقيم",
        "بطاقة الهوية الإماراتية",
        "الإمارات العربية المتحدة",
        "رقم الهوية",
    ]
}

REQUIRED_FIELDS_EID = {
    "Document Type": [
        "resident identity card",
        "emirates id",
        "identity card",
        "بطاقة هوية",
    ],
    "ID Number": ["id number", "رقم الهوية", "784-", "card number"],
    "Name": ["name", "الاسم", "holder name"],
    "Date of Birth": ["date of birth", "تاريخ الميلاد", "birth date"],
    "Nationality": ["nationality", "الجنسية"],
    "Issuing Date": ["issuing date", "تاريخ الإصدار", "issue date"],
    "Expiry Date": ["expiry date", "تاريخ الانتهاء", "expiration"],
    "Sex": ["sex", "الجنس", "gender"],
}

# Document type identifiers for specialized extractors
SPECIALIZED_DOC_TYPES = {
    "commercial": [
        "commercial registration",
        "trade license",
        "business license",
        "رخصة تجارية",
        "license no",
    ],
    "ejari": ["ejari", "tenancy contract", "إيجاري", "عقد إيجار"],
    "moa": ["memorandum of association", "moa", "مذكرة تأسيس"],
}


# ---------------------------
# Helpers
# ---------------------------
def retry_with_backoff(max_retries=3, base_delay=5):
    """Retry decorator with exponential backoff for API failures"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RuntimeError as e:
                    error_msg = str(e)
                    # Check if it's a 503 or rate limit error
                    if (
                        any(code in error_msg for code in ["503", "429", "502", "504"])
                        and attempt < max_retries - 1
                    ):
                        delay = base_delay * (2**attempt)
                        print(
                            f"[WARN] API error (attempt {attempt + 1}/{max_retries}): {error_msg}"
                        )
                        print(f"[INFO] Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None

        return wrapper

    return decorator


def ensure_directory(path: str):
    os.makedirs(path, exist_ok=True)


def encode_image(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mime_type = "jpeg" if ext in [".jpg", ".jpeg"] else "png"
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/{mime_type};base64,{image_b64}"

# ADD THIS TO ocr_service.py - REPLACE the run_ocr function

# @retry_with_backoff(max_retries=3, base_delay=10)
# def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
#     """Standard OCR for EID documents with retry logic"""
    
#     print(f"[DEBUG] run_ocr called with model: {model_name}")
    
#     image_url = encode_image(image_path)
    
#     # Validate file exists and is readable
#     if not os.path.exists(image_path):
#         raise RuntimeError(f"Image file not found: {image_path}")
    
#     # Check file size (max 20MB for OpenRouter)
#     file_size = os.path.getsize(image_path)
#     if file_size > 20 * 1024 * 1024:
#         raise RuntimeError(f"Image file too large: {file_size} bytes (max 20MB)")
    
#     print(f"[DEBUG] Image encoded, file size: {file_size} bytes")
    
#     prompt = """You are an OCR system. Perform OCR on the provided image and extract all text accurately."""

#     headers = {
#         "Authorization": f"Bearer {LLAMA_API_KEY}",
#         "Content-Type": "application/json",
#         "X-Title": "OCR Extraction",
#     }

#     # CRITICAL: Ensure model supports vision
#     # Only these models support vision on OpenRouter:
#     vision_models = [
#         "meta-llama/llama-3.2-11b-vision-instruct",
#         "qwen/qwen-2.5-vl-7b-instruct",
#         "qwen/qwen-2.5-vl-32b-instruct",
#         "gpt-4-vision",
#         "claude-3-5-sonnet-20241022",
#     ]
    
#     if model_name not in vision_models:
#         print(f"[WARN] Model {model_name} may not support vision, trying qwen")
#         model_name = "qwen/qwen-2.5-vl-7b-instruct"
    
#     payload = {
#         "model": model_name,
#         "messages": [
#             {
#                 "role": "user",
#                 "content": [
#                     {"type": "text", "text": prompt},
#                     {"type": "image_url", "image_url": {"url": image_url}},
#                 ],
#             }
#         ],
#         "max_tokens": 1500,
#         "temperature": 0.1,
#     }

#     print(f"[DEBUG] Sending request to {model_name}")
#     print(f"[DEBUG] Payload keys: {list(payload.keys())}")

#     try:
#         response = requests.post(
#             LLAMA_API_URL, headers=headers, json=payload, timeout=120
#         )

#         print(f"[DEBUG] Response status: {response.status_code}")

#         # Check for server errors
#         if response.status_code in [502, 503, 504]:
#             raise RuntimeError(
#                 f"OCR failed: {response.status_code} Server temporarily unavailable"
#             )

#         if response.status_code == 429:
#             raise RuntimeError(
#                 f"OCR failed: {response.status_code} Rate limit exceeded"
#             )
        
#         # CRITICAL: Handle 400 errors properly
#         if response.status_code == 400:
#             print(f"[ERROR] 400 Bad Request from OpenRouter")
#             print(f"[DEBUG] Response body: {response.text}")
            
#             # Try to parse error details
#             try:
#                 error_data = response.json()
#                 error_msg = error_data.get("error", {}).get("message", "Unknown error")
#                 print(f"[DEBUG] Error details: {error_msg}")
#                 raise RuntimeError(f"OCR failed: 400 Bad Request - {error_msg}")
#             except:
#                 raise RuntimeError(f"OCR failed: 400 Bad Request - Invalid request payload")

#         response.raise_for_status()
#         result = response.json()
        
#         if "choices" not in result or not result["choices"]:
#             print(f"[ERROR] Invalid response structure: {result}")
#             raise RuntimeError("OCR failed: Invalid response from API")
        
#         extracted_text = result["choices"][0]["message"]["content"].strip()
        
#         if not extracted_text:
#             raise RuntimeError("OCR failed: No text extracted from image")
        
#         print(f"[SUCCESS] OCR extracted {len(extracted_text)} characters")
#         return extracted_text

#     except requests.exceptions.Timeout:
#         raise RuntimeError("OCR failed: Request timeout after 120 seconds")
#     except requests.exceptions.RequestException as e:
#         status_code = response.status_code if 'response' in locals() else 'Unknown'
#         raise RuntimeError(
#             f"OCR failed: {status_code} {str(e)}"
#         )
#     except Exception as e:
#         print(f"[ERROR] Unexpected error in run_ocr: {e}")
#         raise RuntimeError(f"OCR failed: {str(e)}")

####03-11-2025
# @retry_with_backoff(max_retries=3, base_delay=10)
# def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
#     """Standard OCR for EID documents with retry logic"""
#     image_url = encode_image(image_path)

#     prompt = """You are an OCR system. Perform OCR on the provided image and extract all text accurately."""

#     headers = {
#         "Authorization": f"Bearer {LLAMA_API_KEY}",
#         "Content-Type": "application/json",
#         "X-Title": "OCR Extraction",
#     }

#     payload = {
#         "model": model_name,
#         "messages": [
#             {
#                 "role": "user",
#                 "content": [
#                     {"type": "text", "text": prompt},
#                     {"type": "image_url", "image_url": {"url": image_url}},
#                 ],
#             }
#         ],
#         "max_tokens": 1500,
#         "temperature": 0.1,
#     }

#     try:
#         response = requests.post(
#             LLAMA_API_URL, headers=headers, json=payload, timeout=120
#         )

#         # Check for server errors
#         if response.status_code in [502, 503, 504]:
#             raise RuntimeError(
#                 f"OCR failed: {response.status_code} Server temporarily unavailable"
#             )

#         if response.status_code == 429:
#             raise RuntimeError(
#                 f"OCR failed: {response.status_code} Rate limit exceeded"
#             )

#         response.raise_for_status()
#         result = response.json()
#         return result["choices"][0]["message"]["content"].strip()

#     except requests.exceptions.Timeout:
#         raise RuntimeError("OCR failed: Request timeout after 120 seconds")
#     except requests.exceptions.RequestException as e:
#         raise RuntimeError(
#             f"OCR failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}"
#         )


@retry_with_backoff(max_retries=3, base_delay=10)
def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
    """Enhanced OCR with fallback model chain"""
    
    # ✅ FALLBACK MODEL CHAIN
    model_chain = [
        model_name,  # Try requested model first
        "meta-llama/llama-3.2-11b-vision-instruct",  # Fallback 1: Llama (more reliable)
        "qwen/qwen-2-vl-72b-instruct",  # Fallback 2: Larger Qwen
    ]
    
    # Remove duplicates while preserving order
    model_chain = list(dict.fromkeys(model_chain))
    
    for attempt, current_model in enumerate(model_chain, 1):
        print(f"[INFO] 🔄 OCR Attempt {attempt}/{len(model_chain)} with {current_model}")
        
        try:
            # Validate file
            if not os.path.exists(image_path):
                raise RuntimeError(f"Image file not found: {image_path}")
            
            file_size = os.path.getsize(image_path)
            print(f"[DEBUG] Image size: {file_size} bytes ({file_size/1024/1024:.2f}MB)")
            
            # ✅ AGGRESSIVE COMPRESSION for vision models
            if file_size > 400 * 1024:  # If larger than 500KB
                print(f"[INFO] Compressing image for {current_model}...")
                from PIL import Image
                import io
                import base64
                
                img = Image.open(image_path)
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                
                # ✅ More aggressive sizing for smaller models
                if "7b" in current_model.lower():
                    max_width = 1200  # Smaller for 7B models
                    quality = 85
                elif "11b" in current_model.lower():
                    max_width = 1400
                    quality = 88
                else:
                    max_width = 1600
                    quality = 90
                
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True)
                image_bytes = buffer.getvalue()
                
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                image_url = f"data:image/jpeg;base64,{image_b64}"
                
                print(f"[SUCCESS] Compressed to {len(image_bytes)/1024:.1f}KB for {current_model}")
            else:
                image_url = encode_image(image_path)
            
            # ✅ SIMPLIFIED PROMPT (shorter = better for vision models)
            prompt = """Extract all text from this Emirates ID card. Include:
- ID Number (784-...)
- Name
- Date of Birth
- Nationality
- Sex
- Issuing Date
- Expiry Date"""
            
            headers = {
                "Authorization": f"Bearer {LLAMA_API_KEY}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "model": current_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
                "max_tokens": 1500,  # ✅ Reduced for faster response
                "temperature": 0.0,
            }
            
            response = requests.post(
                LLAMA_API_URL, 
                headers=headers, 
                json=payload, 
                timeout=60  # ✅ Shorter timeout
            )
            
            if response.status_code in [502, 503, 504, 429]:
                raise RuntimeError(f"Server error: {response.status_code}")
            
            if response.status_code == 400:
                print(f"[ERROR] 400 Bad Request with {current_model}")
                if attempt < len(model_chain):
                    continue  # Try next model
                raise RuntimeError("All models returned 400 Bad Request")
            
            response.raise_for_status()
            result = response.json()
            
            if "choices" not in result or not result["choices"]:
                raise RuntimeError("Invalid API response structure")
            
            extracted_text = result["choices"][0]["message"]["content"].strip()
            
            # ✅ CHECK IF EMPTY
            if not extracted_text or len(extracted_text) < 20:
                print(f"[WARN] {current_model} returned insufficient text: '{extracted_text}'")
                if attempt < len(model_chain):
                    print(f"[INFO] Trying next model in chain...")
                    time.sleep(2)
                    continue  # Try next model
                else:
                    raise RuntimeError(f"All models failed to extract text")
            
            # ✅ SUCCESS!
            print(f"[SUCCESS] ✅ {current_model} extracted {len(extracted_text)} characters")
            return extracted_text
            
        except Exception as e:
            print(f"[ERROR] {current_model} failed: {e}")
            if attempt < len(model_chain):
                print(f"[INFO] Trying next model...")
                time.sleep(3)
                continue
            else:
                # All models failed
                raise RuntimeError(f"All OCR models failed: {str(e)}")
    
    # Should never reach here
    raise RuntimeError("OCR failed after all model attempts")


def identify_document_type_from_file(file_path: str) -> str:
    """
    ENHANCED: Quick identification from file content with better fallback logic
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            import fitz
            doc = fitz.open(file_path)
            text = ""
            for i in range(min(3, doc.page_count)):
                page = doc.load_page(i)
                text += page.get_text()
            doc.close()
            return identify_document_type_from_text(text[:5000])

        elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
            # CRITICAL FIX: Use enhanced OCR with better prompting
            print("[INFO] Running enhanced OCR for image document type identification")
            text = run_ocr(file_path, QWEN_MODEL_NAME)
            
            # ADDITIONAL FALLBACK: Check filename if OCR fails
            if not text or len(text) < 50:
                print("[WARN] OCR insufficient for type identification, checking filename")
                filename_lower = os.path.basename(file_path).lower()
                
                # Filename-based detection as fallback
                if any(keyword in filename_lower for keyword in ["eid", "emirates", "identity", "id_card", "resident"]):
                    print("[INFO] Identified as EID from filename")
                    return "eid"
                elif any(keyword in filename_lower for keyword in ["license", "commercial", "trade"]):
                    print("[INFO] Identified as commercial from filename")
                    return "commercial"
                elif any(keyword in filename_lower for keyword in ["ejari", "tenancy", "contract"]):
                    print("[INFO] Identified as ejari from filename")
                    return "ejari"
            
            return identify_document_type_from_text(text)

        elif ext in [".docx", ".doc"]:
            with open(file_path, "rb") as f:
                doc_bytes = f.read()
            extractor = EjariExtractor()
            text = extractor.extract_text_from_docx(doc_bytes)
            return identify_document_type_from_text(text)

    except Exception as e:
        print(f"[ERROR] Document type identification failed: {e}")
        return "unknown"

    return "unknown"


        
def call_api_with_retry(prompt: str, model_name: str, max_retries: int = 3) -> str:
    """Call OpenRouter API with retry logic - same pattern as Ejari"""
    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(
                LLAMA_API_URL, headers=headers, json=data, timeout=120
            )
            
            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Server error: {response.status_code}")
            
            if response.status_code == 429:
                raise RuntimeError(f"Rate limit exceeded")
            
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except (RuntimeError, requests.exceptions.RequestException) as e:
            if attempt < max_retries - 1:
                delay = 10 * (2 ** attempt)
                print(f"[WARN] API error (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"[INFO] Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"API call failed after {max_retries} attempts: {e}")


def ensure_all_eid_fields(data: dict) -> dict:
    """Ensure all 8 EID fields exist - same pattern as Ejari"""
    required_fields = list(REQUIRED_FIELDS_EID.keys())
    complete_data = {}
    
    for field in required_fields:
        complete_data[field] = data.get(field, "")
    
    return complete_data


def post_process_eid_data(data: dict, raw_text: str) -> dict:
    """Fix incomplete EID fields using regex fallback - same pattern as Ejari"""
    incomplete_patterns = {
        "ID Number": [
            r'(784-\d{4}-\d{7}-\d)',
            r'ID.*?Number[:\s]+(784-[\d-]+)',
        ],
        "Name": [
            r'Name[:\s]+([A-Z\s]+?)(?:\n|Date)',
            r'(?:Full Name|Name)[:\s]+([A-Z\s]+)',
        ],
        "Date of Birth": [
            r'Date of Birth[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
            r'Birth[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
        ],
        "Nationality": [
            r'Nationality[:\s]+([A-Za-z\s]+?)(?:\n|Sex)',
        ],
        "Issuing Date": [
            r'Issuing Date[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
            r'Issue[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
        ],
        "Expiry Date": [
            r'Expiry Date[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
            r'Expir[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
        ],
        "Sex": [
            r'Sex[:\s]+(Male|Female|M|F)',
            r'Gender[:\s]+(Male|Female)',
        ],
    }

    for field, patterns in incomplete_patterns.items():
        # If field is empty or too short, try regex
        if field in data and (not data[field] or len(str(data[field])) < 2):
            for pattern in patterns:
                match = re.search(pattern, raw_text, re.IGNORECASE)
                if match:
                    data[field] = match.group(1).strip()
                    print(f"[INFO] Regex fallback filled: {field}")
                    break

    return data

# ---------------------------
# Document Type Identification
# ---------------------------


def identify_document_type_from_text(text: str) -> str:
    """Identify document type from extracted text"""
    text_lower = text.lower()

    for doc_type, keywords in SPECIALIZED_DOC_TYPES.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            return doc_type

    eid_score = sum(1 for kw in DOCUMENT_KEYWORDS["eid"] if kw.lower() in text_lower)
    if eid_score > 0:
        return "eid"

    return "unknown"


def identify_document_type_from_file(file_path: str) -> str:
    """Quick identification from file content"""
    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            import fitz

            doc = fitz.open(file_path)
            text = ""
            for i in range(min(3, doc.page_count)):
                page = doc.load_page(i)
                text += page.get_text()
            doc.close()
            return identify_document_type_from_text(text[:5000])

        elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
            text = run_ocr(file_path, QWEN_MODEL_NAME)
            return identify_document_type_from_text(text)

        elif ext in [".docx", ".doc"]:
            with open(file_path, "rb") as f:
                doc_bytes = f.read()
            extractor = EjariExtractor()
            text = extractor.extract_text_from_docx(doc_bytes)
            return identify_document_type_from_text(text)

    except Exception as e:
        print(f"[ERROR] Document type identification failed: {e}")
        return "unknown"

    return "unknown"


# ---------------------------
# Standard EID Extraction
# ---------------------------


def extract_eid_fields(text: str) -> dict:
    """Extract EID fields using standard method"""
    extracted = {}
    text_lower = text.lower()

    for field, keywords in REQUIRED_FIELDS_EID.items():
        found = None
        for kw in keywords:
            match = re.search(
                rf"{re.escape(kw)}\s*[:\-]?\s*([^\n\r]+)", text_lower, re.IGNORECASE
            )
            if match:
                found = match.group(1).strip()
                break
        if found:
            extracted[field] = found

    return extracted


def validate_eid_fields(extracted: dict) -> dict:
    """Validate EID fields"""
    required = list(REQUIRED_FIELDS_EID.keys())
    present = list(extracted.keys())
    missing = [f for f in required if f not in present]

    return {
        "is_valid": len(missing) == 0,
        "required_fields": required,
        "present_fields": present,
        "missing_fields": missing,
    }


# ---------------------------
# Main Pipeline with Specialized Extractors
# ---------------------------

def process_document(
    user_email: str,
    document_id: str,
    file_path: str,
    model_name: str = LLAMA_MODEL_NAME,
    is_member: bool = False,
) -> dict:
    """
    Enhanced pipeline with retry loop until validation succeeds
    - Retries extraction up to 3 times if validation fails
    - Uses different models for retries
    """
    print(f"[INFO] Processing {file_path} for {user_email} with model {model_name}")
    print(f"[INFO] Is member document: {is_member}")

    MAX_RETRIES = 3
    analysis = None

    try:
        # Identify document type first
        doc_type = identify_document_type_from_file(file_path)
        print(f"[INFO] Identified document type: {doc_type}")

        # Member documents must be EID only
        if is_member and doc_type != "eid":
            analysis = {
                "filename": os.path.basename(file_path),
                "document_type": doc_type,
                "raw_text": "",
                "extracted_fields": {},
                "validation": {
                    "is_valid": False,
                    "required_fields": [],
                    "present_fields": [],
                    "missing_fields": ["EID"],
                },
                "status_message": f"❌ ERROR: Members must submit EID only. Received: {doc_type}",
                "is_valid": False,
            }
            return analysis

        # ============================================================
        # RETRY LOOP - Try extraction up to MAX_RETRIES times
        # ============================================================
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"\n[INFO] ⚙️  Extraction Attempt {attempt}/{MAX_RETRIES}")

            # Alternate between models on retries
            if attempt == 1:
                current_model = model_name
            elif attempt == 2:
                current_model = (
                    QWEN_MODEL_NAME
                    if model_name == LLAMA_MODEL_NAME
                    else LLAMA_MODEL_NAME
                )
            else:
                current_model = LLAMA_MODEL_NAME

            print(f"[INFO] Using model: {current_model}")

            # ====================
            # COMMERCIAL LICENSE
            # ====================
            if doc_type == "commercial":
                print("[INFO] 📜 Using Trade License Extractor")
                extractor = TradeLicenseExtractor(api_key=LLAMA_API_KEY)

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                raw_text = extractor.extract_text_from_pdf(file_bytes)

                if raw_text.startswith("[PDF EXTRACTION ERROR]"):
                    print(f"[ERROR] PDF extraction failed: {raw_text}")
                    continue

                # CRITICAL FIX: Handle different return types based on ownership
                result = extractor.extract_with_ai(raw_text)

                # Check if it's Single Owner (3 values) or Multiple Owners (4 values)
                if len(result) == 3:
                    # Single Owner case
                    english_data, arabic_data, owner = result

                    # Validate single owner extraction
                    validation_result = extractor.validate_extraction(
                        english_data, arabic_data, owner, ownership_type="Single Owner"
                    )

                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "commercial",
                        "raw_text": raw_text[:1000],
                        "extracted_fields": {
                            "english": english_data,
                            "arabic": arabic_data,
                            "owner": owner,
                        },
                        "validation": validation_result,
                        "status_message": (
                            "✅ VALID: Single Owner Commercial License extracted"
                            if validation_result["is_valid"]
                            else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                        ),
                        "is_valid": validation_result["is_valid"],
                    }

                elif len(result) == 4:
                    # Multiple Owners case
                    english_data, arabic_data, managers, partners = result

                    # Validate multi-owner extraction
                    validation_result = extractor.validate_extraction(
                        english_data,
                        arabic_data,
                        managers,
                        partners,
                        ownership_type="Multiple Owners",
                    )

                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "commercial",
                        "raw_text": raw_text[:1000],
                        "extracted_fields": {
                            "english": english_data,
                            "arabic": arabic_data,
                            "managers": managers,
                            "partners": partners,
                        },
                        "validation": validation_result,
                        "status_message": (
                            "✅ VALID: Multiple Owners Commercial License extracted"
                            if validation_result["is_valid"]
                            else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                        ),
                        "is_valid": validation_result["is_valid"],
                    }

                else:
                    # Unexpected return format
                    print(
                        f"[ERROR] Unexpected return format from extractor: {len(result)} values"
                    )
                    continue

            # ====================
            # EJARI
            # ====================
            elif doc_type == "ejari":
                print("[INFO] Using Ejari Extractor")
                extractor = EjariExtractor(api_key=LLAMA_API_KEY)

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                ext = os.path.splitext(file_path)[1].lower()
                if ext == ".pdf":
                    raw_text = extractor.extract_text_from_pdf(file_bytes)
                elif ext in [".docx", ".doc"]:
                    raw_text = extractor.extract_text_from_docx(file_bytes)
                else:
                    raw_text = run_ocr(file_path, current_model)

                if raw_text.startswith("[") and "ERROR" in raw_text:
                    print(f"[ERROR] Text extraction failed: {raw_text}")
                    continue

                english_data, arabic_data = extractor.extract_with_ai(
                    raw_text,
                    model_choice="llama" if "llama" in current_model else "qwen",
                )
                validation_result = extractor.validate_extraction(
                    english_data, arabic_data
                )

                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "ejari",
                    "raw_text": raw_text[:1000],
                    "extracted_fields": {
                        "english": english_data,
                        "arabic": arabic_data,
                    },
                    "validation": validation_result,
                    "status_message": (
                        "✅ VALID: Ejari extracted"
                        if validation_result["is_valid"]
                        else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                    ),
                    "is_valid": validation_result["is_valid"],
                }

            # ====================
            # MOA
            # ====================
            elif doc_type == "moa":
                print("[INFO] Using MOA Extractor")
                extractor = MOAExtractor(api_key=LLAMA_API_KEY)

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                ext = os.path.splitext(file_path)[1].lower()
                if ext == ".pdf":
                    raw_text = extractor.extract_text_from_pdf(file_bytes)
                elif ext in [".docx", ".doc"]:
                    raw_text = extractor.extract_text_from_docx(file_bytes)
                else:
                    raw_text = run_ocr(file_path, current_model)

                if raw_text.startswith("[") and "ERROR" in raw_text:
                    print(f"[ERROR] Text extraction failed: {raw_text}")
                    continue

                english_data, arabic_data = extractor.extract_with_ai(
                    raw_text,
                    model_choice="llama" if "llama" in current_model else "qwen",
                )
                validation_result = extractor.validate_extraction(
                    english_data, arabic_data
                )

                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "moa",
                    "raw_text": raw_text[:1000],
                    "extracted_fields": {
                        "english": english_data,
                        "arabic": arabic_data,
                    },
                    "validation": validation_result,
                    "status_message": (
                        "✅ VALID: MOA extracted"
                        if validation_result["is_valid"]
                        else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                    ),
                    "is_valid": validation_result["is_valid"],
                }

            # ====================
            # EID
            # ====================
            elif doc_type == "eid":
                print("[INFO] Using Enhanced EID Extractor")
                
                # Try OCR with current model
                raw_text = ""
                try:
                    raw_text = run_ocr(file_path, current_model)
                except Exception as ocr_error:
                    print(f"[ERROR] OCR failed with {current_model}: {ocr_error}")
                    
                    # Try fallback to larger Qwen model if using 7B
                    if "7b" in current_model.lower() and attempt < MAX_RETRIES:
                        fallback_model = "qwen/qwen-2-vl-72b-instruct"
                        print(f"[INFO] Trying fallback model: {fallback_model}")
                        try:
                            raw_text = run_ocr(file_path, fallback_model)
                        except Exception as e:
                            print(f"[ERROR] Fallback OCR also failed: {e}")
                            if attempt < MAX_RETRIES:
                                continue
                            else:
                                analysis = {
                                    "filename": os.path.basename(file_path),
                                    "document_type": "eid",
                                    "raw_text": "",
                                    "extracted_fields": {},
                                    "validation": {
                                        "is_valid": False,
                                        "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                                        "present_fields": [],
                                        "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                                    },
                                    "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
                                    "is_valid": False,
                                }
                                break
                    else:
                        if attempt < MAX_RETRIES:
                            continue
                        else:
                            analysis = {
                                "filename": os.path.basename(file_path),
                                "document_type": "eid",
                                "raw_text": "",
                                "extracted_fields": {},
                                "validation": {
                                    "is_valid": False,
                                    "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                                    "present_fields": [],
                                    "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                                },
                                "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
                                "is_valid": False,
                            }
                            break
                
                # Check if OCR returned valid text
                if not raw_text or len(raw_text) < 20:
                    print(f"[ERROR] OCR returned insufficient text: {len(raw_text)} characters")
                    if attempt < MAX_RETRIES:
                        print(f"[INFO] Will retry with different model...")
                        continue
                    else:
                        analysis = {
                            "filename": os.path.basename(file_path),
                            "document_type": "eid",
                            "raw_text": raw_text if raw_text else "",
                            "extracted_fields": {},
                            "validation": {
                                "is_valid": False,
                                "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                                "present_fields": [],
                                "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                            },
                            "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
                            "is_valid": False,
                        }
                        break
                
                print(f"[INFO] OCR extracted {len(raw_text)} characters")
                print(f"[DEBUG] OCR preview: {raw_text[:200]}...")

                # Build structured prompt with schema
                schema_prompt = f"""You are an expert at extracting information from UAE Emirates ID documents.

Extract ALL 8 required fields from this Emirates ID.

Required Fields:
{json.dumps(list(REQUIRED_FIELDS_EID.keys()), indent=2)}

EXTRACTION RULES:
1. Extract values EXACTLY as they appear on the ID
2. For dates, use format: DD/MM/YYYY or DD-MM-YYYY
3. ID Number must include "784-" prefix
4. All field names must match exactly as shown above

Document Text:
{raw_text}

Example Output Format:
{{
"Document Type": "Resident Identity Card",
"ID Number": "784-1999-0405761-1",
"Name": "VARSHA BALAJI BALAJI",
"Date of Birth": "10/10/1999",
"Nationality": "India",
"Issuing Date": "08/11/2024",
"Expiry Date": "07/11/2026",
"Sex": "F"
}}

Return ONLY valid JSON in this EXACT format with ALL 8 fields populated.
Do not include any explanation or extra text."""

                # Try LLM extraction
                llm_extracted = {}
                try:
                    print("[INFO] Attempting AI-based field extraction")
                    llm_response = call_api_with_retry(schema_prompt, current_model)
                    
                    # Parse JSON response
                    json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        
                        # Clean up common JSON issues
                        json_str = re.sub(r'//.*?\n', '', json_str)
                        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                        json_str = re.sub(r'(\w+):', r'"\1":', json_str)
                        
                        try:
                            llm_extracted = json.loads(json_str)
                            print(f"[SUCCESS] AI extracted {len(llm_extracted)} fields")
                        except Exception as json_error:
                            print(f"[WARN] JSON parse failed: {json_error}, falling back to regex")
                            llm_extracted = extract_eid_fields(raw_text)
                    else:
                        print("[WARN] No JSON found in AI response, using regex fallback")
                        llm_extracted = extract_eid_fields(raw_text)
                        
                except Exception as e:
                    print(f"[ERROR] LLM extraction failed: {e}")
                    llm_extracted = extract_eid_fields(raw_text)

                # CRITICAL: Ensure all required fields exist
                llm_extracted = ensure_all_eid_fields(llm_extracted)
                
                # CRITICAL: Post-process to fix incomplete fields using regex
                llm_extracted = post_process_eid_data(llm_extracted, raw_text)

                # Validate
                validation = validate_eid_fields(llm_extracted)
                
                # Log validation results
                print(f"[VALIDATION] EID: {len(validation['present_fields'])}/{len(validation['required_fields'])} fields")
                if validation['missing_fields']:
                    print(f"[VALIDATION] Missing fields: {validation['missing_fields']}")

                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "eid",
                    "raw_text": raw_text,
                    "extracted_fields": llm_extracted,
                    "validation": validation,
                    "status_message": (
                        "✅ VALID: EID extracted"
                        if validation["is_valid"]
                        else f"❌ INCOMPLETE: missing {', '.join(validation['missing_fields'])}"
                    ),
                    "is_valid": validation["is_valid"],
                }
                
                # Check if validation passed
                if validation["is_valid"]:
                    print(f"[SUCCESS] ✅ Validation passed on attempt {attempt}")
                    break
                else:
                    print(f"[WARNING] ❌ Validation failed on attempt {attempt}")
                    if attempt < MAX_RETRIES:
                        print(f"[INFO] Retrying with different approach...")
                        continue
                    else:
                        print(f"[ERROR] All {MAX_RETRIES} attempts exhausted")

            # ====================
            # UNKNOWN
            # ====================
            else:
                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "unknown",
                    "raw_text": "",
                    "extracted_fields": {},
                    "validation": {
                        "is_valid": False,
                        "required_fields": [],
                        "present_fields": [],
                        "missing_fields": [],
                    },
                    "status_message": f"❌ WRONG DOCUMENT: {os.path.basename(file_path)} is not a recognized document type",
                    "is_valid": False,
                }
                break

            # ====================
            # CHECK IF VALID
            # ====================
            if analysis and analysis.get("is_valid", False):
                print(f"[SUCCESS] ✅ Validation passed on attempt {attempt}")
                break
            else:
                print(f"[WARNING] ❌ Validation failed on attempt {attempt}")
                if attempt < MAX_RETRIES:
                    print(f"[INFO] Retrying with different approach...")
                    time.sleep(3)
                else:
                    print(f"[ERROR] All {MAX_RETRIES} attempts exhausted")

    except Exception as e:
        print(f"[ERROR] Processing failed: {e}")
        import traceback
        traceback.print_exc()

        analysis = {
            "filename": os.path.basename(file_path),
            "document_type": "error",
            "raw_text": f"[PROCESSING ERROR] {str(e)}",
            "extracted_fields": {},
            "validation": {
                "is_valid": False,
                "required_fields": [],
                "present_fields": [],
                "missing_fields": [],
            },
            "status_message": f"❌ ERROR: Failed to process {os.path.basename(file_path)}",
            "is_valid": False,
        }

    # ============================================================================
    # SAVE OUTPUT WITH STANDARDIZED STRUCTURE
    # ============================================================================
    
    # Ensure analysis exists and has the correct structure
    if not analysis:
        analysis = {
            "filename": os.path.basename(file_path),
            "document_type": "unknown",
            "raw_text": "",
            "extracted_fields": {},
            "validation": {
                "is_valid": False,
                "required_fields": [],
                "present_fields": [],
                "missing_fields": []
            },
            "status_message": "Processing incomplete",
            "is_valid": False
        }
    
    # ✅ STANDARDIZED OUTPUT FORMAT
    final_output = {
        "filename": analysis.get("filename", os.path.basename(file_path)),
        "document_type": analysis.get("document_type", "unknown"),
        "raw_text": str(analysis.get("raw_text", ""))[:1000],
        "extracted_fields": analysis.get("extracted_fields", {}),
        "validation": analysis.get("validation", {}),
        "status_message": analysis.get("status_message", ""),
        "is_valid": analysis.get("is_valid", False),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "human_verified": False
    }
    
    # Save to disk
    output_dir = os.path.join(DOCUMENTS_ROOT, user_email, document_id)
    ensure_directory(output_dir)
    output_path = os.path.join(output_dir, "output.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print(f"[INFO] ✅ Output saved: {output_path}")
    print(f"[DEBUG] 📊 Document type: {final_output.get('document_type')}")
    print(f"[DEBUG] 📊 Is valid: {final_output.get('is_valid')}")
    print(f"[DEBUG] 📊 Extracted fields count: {len(final_output.get('extracted_fields', {}))}")
    
    if final_output.get('extracted_fields'):
        print(f"[DEBUG] 📋 Field names: {list(final_output['extracted_fields'].keys())[:5]}")
    
    return final_output

# def process_document(
#     user_email: str,
#     document_id: str,
#     file_path: str,
#     model_name: str = LLAMA_MODEL_NAME,
#     is_member: bool = False,
# ) -> dict:
#     """
#     Enhanced pipeline with retry loop until validation succeeds
#     - Retries extraction up to 3 times if validation fails
#     - Uses different models for retries
#     """
#     print(f"[INFO] Processing {file_path} for {user_email} with model {model_name}")
#     print(f"[INFO] Is member document: {is_member}")

#     MAX_RETRIES = 3
#     analysis = None

#     try:
#         # Identify document type first
#         doc_type = identify_document_type_from_file(file_path)
#         print(f"[INFO] Identified document type: {doc_type}")

#         # Member documents must be EID only
#         if is_member and doc_type != "eid":
#             analysis = {
#                 "filename": os.path.basename(file_path),
#                 "document_type": doc_type,
#                 "raw_text": "",
#                 "extracted_fields": {},
#                 "validation": {
#                     "is_valid": False,
#                     "required_fields": [],
#                     "present_fields": [],
#                     "missing_fields": ["EID"],
#                 },
#                 "status_message": f"❌ ERROR: Members must submit EID only. Received: {doc_type}",
#                 "is_valid": False,
#             }
#             return analysis

#         # ============================================================
#         # RETRY LOOP - Try extraction up to MAX_RETRIES times
#         # ============================================================
#         for attempt in range(1, MAX_RETRIES + 1):
#             print(f"\n[INFO] ⚙️  Extraction Attempt {attempt}/{MAX_RETRIES}")

#             # Alternate between models on retries
#             if attempt == 1:
#                 current_model = model_name
#             elif attempt == 2:
#                 current_model = (
#                     QWEN_MODEL_NAME
#                     if model_name == LLAMA_MODEL_NAME
#                     else LLAMA_MODEL_NAME
#                 )
#             else:
#                 current_model = LLAMA_MODEL_NAME

#             print(f"[INFO] Using model: {current_model}")

#             # ====================
#             # COMMERCIAL LICENSE
#             # ====================
#             if doc_type == "commercial":
#                 print("[INFO] 📜 Using Trade License Extractor")
#                 extractor = TradeLicenseExtractor(api_key=LLAMA_API_KEY)

#                 with open(file_path, "rb") as f:
#                     file_bytes = f.read()

#                 raw_text = extractor.extract_text_from_pdf(file_bytes)

#                 if raw_text.startswith("[PDF EXTRACTION ERROR]"):
#                     print(f"[ERROR] PDF extraction failed: {raw_text}")
#                     continue

#                 # CRITICAL FIX: Handle different return types based on ownership
#                 result = extractor.extract_with_ai(raw_text)

#                 # Check if it's Single Owner (3 values) or Multiple Owners (4 values)
#                 if len(result) == 3:
#                     # Single Owner case
#                     english_data, arabic_data, owner = result

#                     # Validate single owner extraction
#                     validation_result = extractor.validate_extraction(
#                         english_data, arabic_data, owner, ownership_type="Single Owner"
#                     )

#                     analysis = {
#                         "filename": os.path.basename(file_path),
#                         "document_type": "commercial",
#                         "raw_text": raw_text[:1000],
#                         "extracted_fields": {
#                             "english": english_data,
#                             "arabic": arabic_data,
#                             "owner": owner,  # Single owner information
#                         },
#                         "validation": validation_result,
#                         "status_message": (
#                             "✅ VALID: Single Owner Commercial License extracted"
#                             if validation_result["is_valid"]
#                             else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
#                         ),
#                         "is_valid": validation_result["is_valid"],
#                     }

#                 elif len(result) == 4:
#                     # Multiple Owners case
#                     english_data, arabic_data, managers, partners = result

#                     # Validate multi-owner extraction
#                     validation_result = extractor.validate_extraction(
#                         english_data,
#                         arabic_data,
#                         managers,
#                         partners,
#                         ownership_type="Multiple Owners",
#                     )

#                     analysis = {
#                         "filename": os.path.basename(file_path),
#                         "document_type": "commercial",
#                         "raw_text": raw_text[:1000],
#                         "extracted_fields": {
#                             "english": english_data,
#                             "arabic": arabic_data,
#                             "managers": managers,
#                             "partners": partners,
#                         },
#                         "validation": validation_result,
#                         "status_message": (
#                             "✅ VALID: Multiple Owners Commercial License extracted"
#                             if validation_result["is_valid"]
#                             else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
#                         ),
#                         "is_valid": validation_result["is_valid"],
#                     }

#                 else:
#                     # Unexpected return format
#                     print(
#                         f"[ERROR] Unexpected return format from extractor: {len(result)} values"
#                     )
#                     continue

#             # ====================
#             # EJARI
#             # ====================
#             elif doc_type == "ejari":
#                 print("[INFO] Using Ejari Extractor")
#                 extractor = EjariExtractor(api_key=LLAMA_API_KEY)

#                 with open(file_path, "rb") as f:
#                     file_bytes = f.read()

#                 ext = os.path.splitext(file_path)[1].lower()
#                 if ext == ".pdf":
#                     raw_text = extractor.extract_text_from_pdf(file_bytes)
#                 elif ext in [".docx", ".doc"]:
#                     raw_text = extractor.extract_text_from_docx(file_bytes)
#                 else:
#                     raw_text = run_ocr(file_path, current_model)

#                 if raw_text.startswith("[") and "ERROR" in raw_text:
#                     print(f"[ERROR] Text extraction failed: {raw_text}")
#                     continue

#                 english_data, arabic_data = extractor.extract_with_ai(
#                     raw_text,
#                     model_choice="llama" if "llama" in current_model else "qwen",
#                 )
#                 validation_result = extractor.validate_extraction(
#                     english_data, arabic_data
#                 )

#                 analysis = {
#                     "filename": os.path.basename(file_path),
#                     "document_type": "ejari",
#                     "raw_text": raw_text[:1000],
#                     "extracted_fields": {
#                         "english": english_data,
#                         "arabic": arabic_data,
#                     },
#                     "validation": validation_result,
#                     "status_message": (
#                         "✅ VALID: Ejari extracted"
#                         if validation_result["is_valid"]
#                         else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
#                     ),
#                     "is_valid": validation_result["is_valid"],
#                 }

#             # ====================
#             # MOA
#             # ====================
#             elif doc_type == "moa":
#                 print("[INFO] Using MOA Extractor")
#                 extractor = MOAExtractor(api_key=LLAMA_API_KEY)

#                 with open(file_path, "rb") as f:
#                     file_bytes = f.read()

#                 ext = os.path.splitext(file_path)[1].lower()
#                 if ext == ".pdf":
#                     raw_text = extractor.extract_text_from_pdf(file_bytes)
#                 elif ext in [".docx", ".doc"]:
#                     raw_text = extractor.extract_text_from_docx(file_bytes)
#                 else:
#                     raw_text = run_ocr(file_path, current_model)

#                 if raw_text.startswith("[") and "ERROR" in raw_text:
#                     print(f"[ERROR] Text extraction failed: {raw_text}")
#                     continue

#                 english_data, arabic_data = extractor.extract_with_ai(
#                     raw_text,
#                     model_choice="llama" if "llama" in current_model else "qwen",
#                 )
#                 validation_result = extractor.validate_extraction(
#                     english_data, arabic_data
#                 )

#                 analysis = {
#                     "filename": os.path.basename(file_path),
#                     "document_type": "moa",
#                     "raw_text": raw_text[:1000],
#                     "extracted_fields": {
#                         "english": english_data,
#                         "arabic": arabic_data,
#                     },
#                     "validation": validation_result,
#                     "status_message": (
#                         "✅ VALID: MOA extracted"
#                         if validation_result["is_valid"]
#                         else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
#                     ),
#                     "is_valid": validation_result["is_valid"],
#                 }

#             # ====================
#             # EID
#             # ====================
#             elif doc_type == "eid":
#                 print("[INFO] Using Enhanced EID Extractor")
                
#                 # Try OCR with current model
#                 raw_text = ""
#                 try:
#                     raw_text = run_ocr(file_path, current_model)
#                 except Exception as ocr_error:
#                     print(f"[ERROR] OCR failed with {current_model}: {ocr_error}")
                    
#                     # Try fallback to larger Qwen model if using 7B
#                     if "7b" in current_model.lower() and attempt < MAX_RETRIES:
#                         fallback_model = "qwen/qwen-2-vl-72b-instruct"
#                         print(f"[INFO] Trying fallback model: {fallback_model}")
#                         try:
#                             raw_text = run_ocr(file_path, fallback_model)
#                         except Exception as e:
#                             print(f"[ERROR] Fallback OCR also failed: {e}")
#                             if attempt < MAX_RETRIES:
#                                 continue  # Try next retry with different model
#                             else:
#                                 # Mark as failed after all retries
#                                 analysis = {
#                                     "filename": os.path.basename(file_path),
#                                     "document_type": "eid",
#                                     "raw_text": "",
#                                     "extracted_fields": {},
#                                     "validation": {
#                                         "is_valid": False,
#                                         "required_fields": list(REQUIRED_FIELDS_EID.keys()),
#                                         "present_fields": [],
#                                         "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
#                                     },
#                                     "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
#                                     "is_valid": False,
#                                 }
#                                 break
#                     else:
#                         # No fallback available or last attempt
#                         if attempt < MAX_RETRIES:
#                             continue
#                         else:
#                             analysis = {
#                                 "filename": os.path.basename(file_path),
#                                 "document_type": "eid",
#                                 "raw_text": "",
#                                 "extracted_fields": {},
#                                 "validation": {
#                                     "is_valid": False,
#                                     "required_fields": list(REQUIRED_FIELDS_EID.keys()),
#                                     "present_fields": [],
#                                     "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
#                                 },
#                                 "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
#                                 "is_valid": False,
#                             }
#                             break
                
#                 # Check if OCR returned valid text
#                 if not raw_text or len(raw_text) < 20:
#                     print(f"[ERROR] OCR returned insufficient text: {len(raw_text)} characters")
#                     if attempt < MAX_RETRIES:
#                         print(f"[INFO] Will retry with different model...")
#                         continue
#                     else:
#                         # Last attempt failed
#                         analysis = {
#                             "filename": os.path.basename(file_path),
#                             "document_type": "eid",
#                             "raw_text": raw_text if raw_text else "",
#                             "extracted_fields": {},
#                             "validation": {
#                                 "is_valid": False,
#                                 "required_fields": list(REQUIRED_FIELDS_EID.keys()),
#                                 "present_fields": [],
#                                 "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
#                             },
#                             "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
#                             "is_valid": False,
#                         }
#                         break
                
#                 print(f"[INFO] OCR extracted {len(raw_text)} characters")
#                 print(f"[DEBUG] OCR preview: {raw_text[:200]}...")

#                 # Build structured prompt with schema
#                 schema_prompt = f"""You are an expert at extracting information from UAE Emirates ID documents.

#             Extract ALL 8 required fields from this Emirates ID.

#             Required Fields:
#             {json.dumps(list(REQUIRED_FIELDS_EID.keys()), indent=2)}

#             EXTRACTION RULES:
#             1. Extract values EXACTLY as they appear on the ID
#             2. For dates, use format: DD/MM/YYYY or DD-MM-YYYY
#             3. ID Number must include "784-" prefix
#             4. All field names must match exactly as shown above

#             Document Text:
#             {raw_text}

#             Example Output Format:
#             {{
#             "Document Type": "Resident Identity Card",
#             "ID Number": "784-1999-0405761-1",
#             "Name": "VARSHA BALAJI BALAJI",
#             "Date of Birth": "10/10/1999",
#             "Nationality": "India",
#             "Issuing Date": "08/11/2024",
#             "Expiry Date": "07/11/2026",
#             "Sex": "F"
#             }}

#             Return ONLY valid JSON in this EXACT format with ALL 8 fields populated.
#             Do not include any explanation or extra text."""

#                 # Try LLM extraction
#                 llm_extracted = {}
#                 try:
#                     print("[INFO] Attempting AI-based field extraction")
#                     llm_response = call_api_with_retry(schema_prompt, current_model)
                    
#                     # Parse JSON response
#                     json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
#                     if json_match:
#                         json_str = json_match.group(0)
                        
#                         # Clean up common JSON issues
#                         json_str = re.sub(r'//.*?\n', '', json_str)
#                         json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
#                         json_str = re.sub(r'(\w+):', r'"\1":', json_str)
                        
#                         try:
#                             llm_extracted = json.loads(json_str)
#                             print(f"[SUCCESS] AI extracted {len(llm_extracted)} fields")
#                         except Exception as json_error:
#                             print(f"[WARN] JSON parse failed: {json_error}, falling back to regex")
#                             llm_extracted = extract_eid_fields(raw_text)
#                     else:
#                         print("[WARN] No JSON found in AI response, using regex fallback")
#                         llm_extracted = extract_eid_fields(raw_text)
                        
#                 except Exception as e:
#                     print(f"[ERROR] LLM extraction failed: {e}")
#                     llm_extracted = extract_eid_fields(raw_text)

#                 # CRITICAL: Ensure all required fields exist
#                 llm_extracted = ensure_all_eid_fields(llm_extracted)
                
#                 # CRITICAL: Post-process to fix incomplete fields using regex
#                 llm_extracted = post_process_eid_data(llm_extracted, raw_text)

#                 # Validate
#                 validation = validate_eid_fields(llm_extracted)
                
#                 # Log validation results
#                 print(f"[VALIDATION] EID: {len(validation['present_fields'])}/{len(validation['required_fields'])} fields")
#                 if validation['missing_fields']:
#                     print(f"[VALIDATION] Missing fields: {validation['missing_fields']}")

#                 analysis = {
#                     "filename": os.path.basename(file_path),
#                     "document_type": "eid",
#                     "raw_text": raw_text,
#                     "extracted_fields": llm_extracted,
#                     "validation": validation,
#                     "status_message": (
#                         "✅ VALID: EID extracted"
#                         if validation["is_valid"]
#                         else f"❌ INCOMPLETE: missing {', '.join(validation['missing_fields'])}"
#                     ),
#                     "is_valid": validation["is_valid"],
#                 }
                
#                 # Check if validation passed
#                 if validation["is_valid"]:
#                     print(f"[SUCCESS] ✅ Validation passed on attempt {attempt}")
#                     break  # Exit retry loop
#                 else:
#                     print(f"[WARNING] ❌ Validation failed on attempt {attempt}")
#                     if attempt < MAX_RETRIES:
#                         print(f"[INFO] Retrying with different approach...")
#                         continue
#                     else:
#                         print(f"[ERROR] All {MAX_RETRIES} attempts exhausted")
#             ###-----------standardized JSON via OpenAi-----------###
#             # elif doc_type == "eid":
#             #     print("[INFO] Using Standard EID Extractor")
#             #     raw_text = run_ocr(file_path, current_model)

#             #     if raw_text.startswith("OCR failed"):
#             #         print(f"[ERROR] OCR failed: {raw_text}")
#             #         continue

#             #     schema_prompt = (
#             #         f"You are an information extraction system. Extract the following fields from the Emirates ID document:\n"
#             #         f"{json.dumps(list(REQUIRED_FIELDS_EID.keys()), indent=2)}\n"
#             #         "Return ONLY a valid JSON object with keys as field names and values as extracted values. Do not include any explanation or extra text.\n"
#             #         f"Document text:\n{raw_text}"
#             #     )

#             #     llm_extracted = {}
#             #     try:
#             #         llm_response = call_local_llm(schema_prompt)
#             #         json_start = llm_response.find("{")
#             #         json_end = llm_response.rfind("}") + 1
#             #         llm_json_str = llm_response[json_start:json_end]
#             #         llm_extracted = json.loads(llm_json_str)
#             #     except Exception as e:
#             #         print(f"[ERROR] LLM extraction failed: {e}")
#             #         llm_extracted = extract_eid_fields(raw_text)

#             #     validation = validate_eid_fields(llm_extracted)

#             #     analysis = {
#             #         "filename": os.path.basename(file_path),
#             #         "document_type": "eid",
#             #         "raw_text": raw_text,
#             #         "extracted_fields": llm_extracted,
#             #         "validation": validation,
#             #         "status_message": (
#             #             "✅ VALID: EID extracted"
#             #             if validation["is_valid"]
#             #             else f"❌ INCOMPLETE: missing {', '.join(validation['missing_fields'])}"
#             #         ),
#             #         "is_valid": validation["is_valid"],
#             #     }

#             # ====================
#             # UNKNOWN
#             # ====================
#             else:
#                 analysis = {
#                     "filename": os.path.basename(file_path),
#                     "document_type": "unknown",
#                     "raw_text": "",
#                     "extracted_fields": {},
#                     "validation": {
#                         "is_valid": False,
#                         "required_fields": [],
#                         "present_fields": [],
#                         "missing_fields": [],
#                     },
#                     "status_message": f"❌ WRONG DOCUMENT: {os.path.basename(file_path)} is not a recognized document type",
#                     "is_valid": False,
#                 }
#                 break  # Don't retry for unknown documents

#             # ====================
#             # CHECK IF VALID
#             # ====================
#             if analysis and analysis.get("is_valid", False):
#                 print(f"[SUCCESS] ✅ Validation passed on attempt {attempt}")
#                 break
#             else:
#                 print(f"[WARNING] ❌ Validation failed on attempt {attempt}")
#                 if attempt < MAX_RETRIES:
#                     print(f"[INFO] Retrying with different approach...")
#                     time.sleep(3)  # Wait before retry
#                 else:
#                     print(f"[ERROR] All {MAX_RETRIES} attempts exhausted")

#     except Exception as e:
#         print(f"[ERROR] Processing failed: {e}")
#         import traceback

#         traceback.print_exc()

#         analysis = {
#             "filename": os.path.basename(file_path),
#             "document_type": "error",
#             "raw_text": f"[PROCESSING ERROR] {str(e)}",
#             "extracted_fields": {},
#             "validation": {
#                 "is_valid": False,
#                 "required_fields": [],
#                 "present_fields": [],
#                 "missing_fields": [],
#             },
#             "status_message": f"❌ ERROR: Failed to process {os.path.basename(file_path)}",
#             "is_valid": False,
#         }

#     # Save output
#     output_dir = os.path.join(DOCUMENTS_ROOT, user_email, document_id)
#     ensure_directory(output_dir)
#     output_path = os.path.join(output_dir, "output.json")

#     with open(output_path, "w", encoding="utf-8") as f:
#         json.dump(analysis, f, ensure_ascii=False, indent=2)

#     print(f"[INFO] Output saved: {output_path}")
#     return analysis


# ---------------------------
# Required Documents Checker
# ---------------------------


def check_user_documents(user_email: str) -> dict:
    """
    Check if user has submitted all 4 required documents:
    1. EID
    2. Commercial License (Trade License)
    3. Ejari
    4. MOA
    """
    user_docs_dir = os.path.join(DOCUMENTS_ROOT, user_email)

    required_docs = {"eid": False, "commercial": False, "ejari": False, "moa": False}

    if not os.path.exists(user_docs_dir):
        return {
            "all_submitted": False,
            "documents": required_docs,
            "missing": list(required_docs.keys()),
        }

    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)
        if os.path.isdir(item_path):
            output_path = os.path.join(item_path, "output.json")
            if os.path.exists(output_path):
                with open(output_path, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                    doc_type = analysis.get("document_type", "unknown")
                    is_valid = analysis.get("is_valid", False)

                    if doc_type in required_docs and is_valid:
                        required_docs[doc_type] = True

    missing = [doc for doc, present in required_docs.items() if not present]

    return {
        "all_submitted": len(missing) == 0,
        "documents": required_docs,
        "missing": missing,
    }


def format_document_name(doc_type: str) -> str:
    """Convert document type to friendly name"""
    doc_names = {
        "eid": "Emirates ID (EID)",
        "commercial": "Commercial License (Trade License)",
        "ejari": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)",
    }
    return doc_names.get(doc_type, doc_type.upper())
