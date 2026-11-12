# app/services/ocr_service.py

from app.i18n import localized
from app.i18n.messages import doc_name
import os
import base64
import requests
import json
import re
from dotenv import load_dotenv
from datetime import datetime, timezone
# Import specialized extractors. These now live beside this module in
# app/services/, so the sys.path.insert that used to put backend/ on the path
# (needed while specialized_ocr was a top-level package) has been removed.
from app.services.specialized_ocr import EjariExtractor, MOAExtractor, TradeLicenseExtractor, BVIExtractor
from app.services.specialized_ocr.corporate_shareholder_detector import detect_corporate_shareholders
from app.services.specialized_ocr.passport_extractor import (
    process_passport,
    is_passport_filename,
    is_passport_text,
)
import time
from functools import wraps
from app.services.document_expiry_validator import (
    validate_document_expiry,
    generate_expiry_failure_message,
)
from app.services.document_helpers import get_documents_base_path
load_dotenv()

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.dirname(APP_DIR)
# NOTE: previously this reimplemented its own DOCUMENTS_PATH + "/id" logic with
# a hardcoded Linux-only fallback ("/app/backend/documents"), which silently
# disagreed with get_documents_base_path() (used by chatupload_helpers.py,
# etc.) whenever DOCUMENTS_PATH wasn't set — e.g. local
# runs outside Docker. Writes and reads must always resolve to the same
# folder, so this now delegates to the single shared helper instead of
# maintaining a second copy of the same path math.
DOCUMENTS_ROOT = str(get_documents_base_path())

# === AWS Bedrock CONFIG ===
# Model name and endpoint come from llm_client, which gets them from
# bedrock_client.py. These module-level aliases are kept because they're
# referenced throughout this file (and as default args) — all five now
# resolve to the same Bedrock Claude Haiku model since OpenRouter's
# multi-model routing was retired.
from app.services.llm_client import (
    LLM_API_URL as LLAMA_API_URL,
    VISION_PRIMARY  as LLAMA_MODEL_NAME,
    VISION_FALLBACK as QWEN_MODEL_NAME,
    TEXT_PRIMARY    as TEXT_MODEL_NAME,
    TEXT_FALLBACK   as TEXT_MODEL_FALLBACK,
)
from app.services import bedrock_client
import logging
from app import config
from app.utils.retry import retry_with_backoff
from app.domain.onboarding.stage_table import (
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_SINGLE,
)

logger = logging.getLogger(__name__)

LLAMA_API_KEY = config.AWS_BEARER_TOKEN_BEDROCK

# Document types that require the vision model
IDENTITY_DOC_TYPES = {"eid", "passport"}

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

# ENHANCED: Document type identifiers with PRIORITY ORDER
SPECIALIZED_DOC_TYPES = {
    # MOA KEYWORDS - Check FIRST to avoid confusion with commercial/passport
    "moa": [
        "memorandum of association",
        "memorandum and articles",
        "share transfer agreement",
        "amendment to memorandum",
        "shareholders agreement",
        "articles of association",
        "company constitution",
        "share purchase",
        "equity transfer",
        "partnership deed",
        # Arabic — standard UAE MOA/company-formation documents
        "نقل حصص",           # share transfer
        "عقد بيع حصص",       # share sale agreement
        "مذكرة تأسيس",       # MOA / memorandum of association
        "اتفاقية الشركاء",   # partnership agreement
        "عقد تأسيس",         # establishment deed (very common in UAE MOAs)
        "عقد الشركة",        # company contract
        "حصص الشركة",        # company shares
        "رأس المال",         # share capital
        "الشركاء",           # partners / shareholders
        "الحصة",             # share / quota
    ],
    # Commercial license keywords
    "commercial": [
        "commercial registration",
        "commercial license", 
        "trade license",
        "business license",
        "رخصة تجارية",
        "license no",
        "تجديد الرخصة",
        "department of economic development",
        "economic development",
    ],
    "ejari": [
        "ejari",
        "tenancy contract",
        "إيجاري",
        "عقد إيجار"
    ],
    # Passport — international travel document
    "passport": [
        "passport",
        "republic of india",
        "ministry of external affairs",
        "government of india",
        "republic of",
        "given names",
        "surname",
        "place of birth",
        "place of issue",
    ],
    # Certificate of Incorporation (CoI) — offshore / free-zone entities
    "certificate_of_incorporation": [
        "certificate of incorporation",
        "certificate of good standing",
        "certificate of registration",
        "incorporated under",
        "companies act",
        "registrar of companies",
        "british virgin islands",
        "bvi",
        "cayman islands",
        "difc",
        "adgm",
        "rak icc",
        "jafza",
        "tecom",
        "freezone authority",
        "free zone authority",
        "registered agent",
        "registered office",
    ],
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

@retry_with_backoff(max_retries=3, base_delay=10)
def run_ocr(image_path: str, model_name: str = LLAMA_MODEL_NAME) -> str:
    """Enhanced OCR with fallback model chain"""
    
    model_chain = [
        model_name,
        LLAMA_MODEL_NAME,
    ]

    model_chain = list(dict.fromkeys(model_chain))
    
    for attempt, current_model in enumerate(model_chain, 1):
        logger.info(f"OCR Attempt {attempt}/{len(model_chain)} with {current_model}")
        
        try:
            if not os.path.exists(image_path):
                raise RuntimeError(f"Image file not found: {image_path}")
            
            file_size = os.path.getsize(image_path)
            logger.debug(f"Image size: {file_size} bytes ({file_size/1024/1024:.2f}MB)")
            
            if file_size > 400 * 1024:
                logger.info(f"Compressing image for {current_model}...")
                from PIL import Image
                import io
                import base64
                
                img = Image.open(image_path)
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
                
                if "7b" in current_model.lower():
                    max_width = 1200
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
                
                logger.info(f"[SUCCESS] Compressed to {len(image_bytes)/1024:.1f}KB for {current_model}")
            else:
                image_url = encode_image(image_path)
            
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
                "max_tokens": 1500,
                "temperature": 0.0,
            }
            
            response = bedrock_client.post(
                LLAMA_API_URL, 
                headers=headers, 
                json=payload, 
                timeout=60
            )
            
            if response.status_code in [502, 503, 504, 429]:
                raise RuntimeError(f"Server error: {response.status_code}")
            
            if response.status_code == 400:
                logger.error(f"400 Bad Request with {current_model}")
                if attempt < len(model_chain):
                    continue
                raise RuntimeError("All models returned 400 Bad Request")
            
            response.raise_for_status()
            result = response.json()
            
            if "choices" not in result or not result["choices"]:
                raise RuntimeError("Invalid API response structure")
            
            extracted_text = result["choices"][0]["message"]["content"].strip()
            
            if not extracted_text or len(extracted_text) < 20:
                logger.warning(f"{current_model} returned insufficient text: '{extracted_text}'")
                if attempt < len(model_chain):
                    logger.info(f"Trying next model in chain...")
                    time.sleep(2)
                    continue
                else:
                    raise RuntimeError(f"All models failed to extract text")
            
            logger.info(f"[SUCCESS] {current_model} extracted {len(extracted_text)} characters")
            return extracted_text
            
        except Exception as e:
            logger.error(f"{current_model} failed: {e}")
            if attempt < len(model_chain):
                logger.info(f"Trying next model...")
                time.sleep(3)
                continue
            else:
                raise RuntimeError(f"All OCR models failed: {str(e)}")
    
    raise RuntimeError("OCR failed after all model attempts")


        
def call_api_with_retry(prompt: str, model_name: str, max_retries: int = 6) -> str:
    """
    Call the Bedrock API with retry logic - same pattern as Ejari.

    max_retries raised from 3 to 6: this used to only retry on an HTTP-level
    error (502/503/504/429). A concurrent 4-file EID batch showed a case
    where the provider returned HTTP 200 with a null `content` — no error to
    catch, so this returned None straight to the caller, which then crashed
    on `re.search(pattern, None)` and fell into a regex fallback that mangles
    markdown-formatted OCR text. Empty/null content is now treated as a
    retryable failure just like a 5xx, and retried until a real value comes
    back or attempts run out — same exponential backoff (10s, 20s, 40s, 80s,
    160s) as every other retryable error here.
    """
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
            response = bedrock_client.post(
                LLAMA_API_URL, headers=headers, json=data, timeout=120
            )

            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Server error: {response.status_code}")

            if response.status_code == 429:
                raise RuntimeError(f"Rate limit exceeded")

            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]

            if not content or not content.strip():
                raise RuntimeError("Empty/null completion content")

            return content

        except (RuntimeError, requests.exceptions.RequestException) as e:
            if attempt < max_retries - 1:
                delay = 10 * (2 ** attempt)
                logger.warning(f"API error (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {delay} seconds...")
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
                    logger.info(f"Regex fallback filled: {field}")
                    break

    return data

# ---------------------------
# Document Type Identification
# ---------------------------

def identify_document_type_from_text(text: str) -> str:
    """
    ENHANCED: Better EID keyword matching with lower threshold
    """
    text_lower = text.lower()

    # PRIORITY 0: Check MOA FIRST — MOA documents contain partner passport
    # numbers/nationalities/names which can falsely trigger passport detection.
    moa_score_quick = sum(1 for kw in SPECIALIZED_DOC_TYPES["moa"] if kw.lower() in text_lower)
    if moa_score_quick >= 2:
        logger.info(f"Identified as MOA (score: {moa_score_quick})")
        return "moa"

    # PRIORITY 0b: Check CoI BEFORE passport — CoI documents contain registration
    # numbers and director details that can falsely trigger passport detection.
    coi_score = sum(1 for kw in SPECIALIZED_DOC_TYPES["certificate_of_incorporation"] if kw.lower() in text_lower)
    if coi_score >= 1:
        logger.info(f"Identified as certificate_of_incorporation (score: {coi_score})")
        return "certificate_of_incorporation"

    # PRIORITY 1: Passport heuristic — only if NO MOA/CoI keyword was found
    if moa_score_quick == 0 and is_passport_text(text):
        logger.info(f"Identified as passport (passport text signals detected)")
        return "passport"
    elif moa_score_quick >= 1:
        logger.info(f"Skipping passport check — MOA keyword found; continuing to specialized doc check")

    # Check specialized documents first (higher priority)
    for doc_type, keywords in SPECIALIZED_DOC_TYPES.items():
        if doc_type in ("moa", "certificate_of_incorporation"):
            continue  # Already checked above
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            logger.info(f"Identified as {doc_type} (score: {score})")
            return doc_type

    # Also return moa if it scored 1 (partial match) and nothing else matched
    if moa_score_quick >= 1:
        logger.info(f"Identified as MOA via partial score ({moa_score_quick}) — no other doc type matched")
        return "moa"

    # CRITICAL FIX: More flexible EID detection
    eid_indicators = [
        # Pattern matching
        re.search(r'784-\d{4}-\d{7}-\d', text),  # ID number pattern
        
        # Keyword matching (need at least 2)
        "resident identity" in text_lower,
        "identity card" in text_lower,
        "resident card" in text_lower,
        "emirates id" in text_lower,
        "federal authority" in text_lower,
        "uae" in text_lower or "emirates" in text_lower,
        
        # Single strong indicators
        "784-" in text and "identity" in text_lower,
        "resident" in text_lower and "nationality" in text_lower,
    ]
    
    # Count how many indicators are present
    eid_score = sum(1 for indicator in eid_indicators if indicator)
    
    # LOWER THRESHOLD: Need only 1 strong indicator for EID
    if eid_score >= 1:
        logger.info(f"Identified as EID (score: {eid_score})")
        return "eid"
    
    # If no match found
    logger.error(f"Could not identify document type")
    logger.debug(f"Text preview: {text[:300]}")
    return "unknown"


def identify_document_type_from_file(file_path: str) -> str:
    """
    ENHANCED: Better fallback logic for image files
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()
        filename_lower = os.path.basename(file_path).lower()

        if ext == ".pdf":
            # Check filename FIRST for PDFs — avoids misclassification from text content
            if any(kw in filename_lower for kw in ["moa", "memorandum", "share transfer"]):
                logger.info(f"PDF filename suggests MOA: {filename_lower}")
                return "moa"
            elif any(kw in filename_lower for kw in ["coi", "certificate_of_inc", "incorporation",
                                                       "certificate_of_registration", "bvi", "cayman",
                                                       "difc", "adgm", "rak_icc", "jafza"]):
                logger.info(f"PDF filename suggests CoI: {filename_lower}")
                return "certificate_of_incorporation"
            elif any(kw in filename_lower for kw in ["license", "commercial", "trade", "ded"]):
                logger.info(f"PDF filename suggests commercial: {filename_lower}")
                return "commercial"
            elif any(kw in filename_lower for kw in ["ejari", "tenancy", "contract"]):
                logger.info(f"PDF filename suggests ejari: {filename_lower}")
                return "ejari"
            elif is_passport_filename(filename_lower):
                logger.info(f"PDF filename suggests passport: {filename_lower}")
                return "passport"
            # Fall through to text extraction
            import fitz
            doc = fitz.open(file_path)
            text = ""
            for i in range(min(3, doc.page_count)):
                page = doc.load_page(i)
                text += page.get_text()
            doc.close()
            return identify_document_type_from_text(text[:5000])

        elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
            logger.info("Running OCR for image document type identification")
            
            # TRY FILENAME FIRST (fastest method)
            if is_passport_filename(filename_lower):
                logger.info(f"Filename suggests passport: {filename_lower}")
                return "passport"
            elif any(kw in filename_lower for kw in ["eid", "emirates", "identity", "id_card", "resident", "national_id"]):
                logger.info(f"Filename suggests EID: {filename_lower}")
                return "eid"
            elif any(kw in filename_lower for kw in ["coi", "certificate_of_inc", "incorporation", "certificate_of_registration", "bvi", "cayman", "difc", "adgm"]):
                logger.info(f"Filename suggests CoI: {filename_lower}")
                return "certificate_of_incorporation"
            elif any(kw in filename_lower for kw in ["license", "commercial", "trade"]):
                logger.info(f"Filename suggests commercial: {filename_lower}")
                return "commercial"
            elif any(kw in filename_lower for kw in ["ejari", "tenancy", "contract"]):
                logger.info(f"Filename suggests ejari: {filename_lower}")
                return "ejari"
            elif any(kw in filename_lower for kw in ["moa", "memorandum"]):
                logger.info(f"Filename suggests MOA: {filename_lower}")
                return "moa"
            
            # FALLBACK: Try OCR if filename doesn't match
            try:
                text = run_ocr(file_path, QWEN_MODEL_NAME)

                # CRITICAL: Check if OCR returned valid text
                if text and len(text) > 30:
                    doc_type = identify_document_type_from_text(text)

                    # If still unknown, try passport heuristic on raw text
                    if doc_type == "unknown":
                        if is_passport_text(text):
                            logger.info(f"OCR text signals passport (fallback heuristic)")
                            return "passport"
                        logger.warning("OCR+text failed, defaulting to filename match")
                        # Generic fallback for common patterns
                        if "id" in filename_lower or "card" in filename_lower:
                            logger.info(f"Assuming EID from filename: {filename_lower}")
                            return "eid"

                    return doc_type
                else:
                    logger.warning(f"OCR returned insufficient text ({len(text) if text else 0} chars)")
                    # Try passport heuristic even on short text (MRZ can be short)
                    if text and is_passport_text(text):
                        logger.info(f"Short OCR text signals passport")
                        return "passport"
                    # Last resort: assume EID for any ID-like filename
                    if "id" in filename_lower:
                        logger.info(f"Assuming EID from filename pattern")
                        return "eid"

            except Exception as ocr_error:
                logger.error(f"OCR failed during identification: {ocr_error}")
                # Emergency fallback
                if "id" in filename_lower:
                    return "eid"

            return "unknown"

        elif ext in [".docx", ".doc"]:
            with open(file_path, "rb") as f:
                doc_bytes = f.read()
            extractor = EjariExtractor()
            text = extractor.extract_text_from_docx(doc_bytes)
            return identify_document_type_from_text(text)

    except Exception as e:
        logger.error(f"Document type identification failed: {e}")
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

def log_eid_extraction_debug(stage: str, data: dict, raw_text: str = None):
    """
    Enhanced logging for EID extraction debugging
    Tracks why the same ID number appears repeatedly
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"[EID DEBUG] Stage: {stage}")
    logger.info(f"{'='*80}")
    
    if raw_text:
        logger.info(f"[OCR TEXT] Length: {len(raw_text)} chars")
        logger.info(f"[OCR TEXT] Preview: {raw_text[:200]}...")
        
        # Check for rejection phrases
        rejection_phrases = ["not an emirates id", "screenshot", "photograph", "conversation"]
        found_phrases = [p for p in rejection_phrases if p in raw_text.lower()]
        if found_phrases:
            logger.warning(f"[OCR TEXT]  REJECTION PHRASES FOUND: {found_phrases}")
    
    if data:
        logger.info(f"[EXTRACTED] Fields count: {len(data)}")
        for key, value in data.items():
            logger.info(f"[EXTRACTED]   {key}: '{value}'")
        
        # Flag suspicious patterns
        id_num = data.get("ID Number", "")
        if id_num == "784-1999-0405761-1":
            logger.info(f"[EXTRACTED] WARNING: This is the CACHED ID number!")
        
        name = data.get("Name", "").lower()
        if "varsha balaji" in name:
            logger.info(f"[EXTRACTED] WARNING: This is the CACHED name!")
    
    logger.info(f"{'='*80}\n")

# ---------------------------
# Main Pipeline with Specialized Extractors
# ---------------------------

def process_document(
    user_email: str,
    document_id: str,
    file_path: str,
    model_name: str = None,          # None → auto-selected by doc_type below
    is_member: bool = False,
) -> dict:
    """
    Enhanced pipeline with retry loop until validation succeeds
    - Retries extraction up to 3 times if validation fails
    - EID / Passport  → vision model (llama-3.2-11b-vision-instruct)
    - All other docs  → text  model (llama-3.3-70b-instruct)
    """
    logger.info(f"Processing {file_path} for {user_email}")
    logger.info(f"Is member document: {is_member}")

    # Configurable via DOC_EXTRACTION_MAX_RETRIES in .env.docker — change +
    # restart the container to raise/lower this without editing code.
    MAX_RETRIES = config.DOC_EXTRACTION_MAX_RETRIES
    analysis = None

    try:
        # Identify document type first
        doc_type = identify_document_type_from_file(file_path)
        logger.info(f"Identified document type: {doc_type}")

        # ── Auto-select primary/fallback pair based on doc_type ───────────────
        if doc_type in IDENTITY_DOC_TYPES:
            primary_model  = LLAMA_MODEL_NAME    # vision primary
            fallback_model = QWEN_MODEL_NAME     # vision fallback
        else:
            primary_model  = TEXT_MODEL_NAME     # text primary
            fallback_model = TEXT_MODEL_FALLBACK # text fallback

        # Allow explicit override (rarely needed)
        if model_name:
            primary_model = model_name

        # Member documents must be EID or Passport (identity documents)
        if is_member and doc_type not in ("eid", "passport"):
            analysis = {
                "filename": os.path.basename(file_path),
                "document_type": doc_type,
                "raw_text": "",
                "extracted_fields": {},
                "validation": {
                    "is_valid": False,
                    "required_fields": [],
                    "present_fields": [],
                    "missing_fields": ["Emirates ID or Passport"],
                },
                "status_message": f"❌ ERROR: Members must submit Emirates ID or Passport. Received: {doc_type}",
                "is_valid": False,
            }
            return analysis

        # ============================================================
        # RETRY LOOP - Try extraction up to MAX_RETRIES times
        # ============================================================
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"\n[INFO]  Extraction Attempt {attempt}/{MAX_RETRIES}")

            # Attempt 1 → primary, Attempt 2 → fallback, Attempt 3 → primary again
            if attempt == 2:
                current_model = fallback_model
            else:
                current_model = primary_model

            logger.info(f"Using model: {current_model}")

            # ====================
            # COMMERCIAL LICENSE
            # ====================
            if doc_type == "commercial":
                logger.info("Using Trade License Extractor")
                extractor = TradeLicenseExtractor(api_key=LLAMA_API_KEY)

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                raw_text = extractor.extract_text_from_pdf(file_bytes)

                if raw_text.startswith("[PDF EXTRACTION ERROR]"):
                    logger.error(f"PDF extraction failed: {raw_text}")
                    continue

                result = extractor.extract_with_ai(raw_text)

                # Single Owner → 3 values
                if len(result) == 3:
                    english_data, arabic_data, owner = result

                    validation_result = extractor.validate_extraction(
                        english_data, arabic_data, owner, ownership_type=OWNERSHIP_SINGLE
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
                            "VALID: Sole Proprietorship Commercial License extracted"
                            if validation_result["is_valid"]
                            else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                        ),
                        "is_valid": validation_result["is_valid"],
                    }

                # Multiple Owners → 4 values (old extractor) or 5 values (new extractor)
                elif len(result) in (4, 5):
                    if len(result) == 5:
                        english_data, arabic_data, managers, partners, skipped = result
                    else:
                        english_data, arabic_data, managers, partners = result
                        skipped = []

                    validation_result = extractor.validate_extraction(
                        english_data,
                        arabic_data,
                        managers,
                        partners,
                        ownership_type=OWNERSHIP_MULTIPLE,
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
                            "skipped_members": skipped,
                        },
                        "validation": validation_result,
                        "status_message": (
                            "VALID: Joint Ownership Commercial License extracted"
                            if validation_result["is_valid"]
                            else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                        ),
                        "is_valid": validation_result["is_valid"],
                    }

                else:
                    logger.error(
                        f"Unexpected return format from extractor: {len(result)} values"
                    )
                    continue

                # ============================================================
                # TYPE-2 DETECTION: Scan partners list for corporate entities
                # Only runs for Multiple Owners (4/5-value extractor result)
                # ============================================================
                if analysis and analysis.get("is_valid") and len(result) in (4, 5):
                    partners_list = analysis.get("extracted_fields", {}).get("partners", [])
                    if partners_list:
                        detection = detect_corporate_shareholders(partners_list)
                        if detection["has_corporate_shareholders"]:
                            analysis["corporate_shareholders_detected"] = True
                            analysis["corporate_shareholder_names"] = [
                                c["name"] for c in detection["corporate_shareholders"]
                            ]
                            logger.info(
                                f"[TYPE-2] Corporate shareholders detected: "
                                f"{analysis['corporate_shareholder_names']}"
                            )
                        else:
                            analysis["corporate_shareholders_detected"] = False
                            analysis["corporate_shareholder_names"] = []

            # ====================
            # EJARI
            # ====================
            elif doc_type == "ejari":
                logger.info("Using Ejari Extractor")
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
                    logger.error(f"Text extraction failed: {raw_text}")
                    continue

                # ── Timeout / transient-error guard ───────────────────────────
                # extract_with_ai() raises RuntimeError on API timeout (60s, see
                # specialized_ocr/ejari_extractor.py). Previously this exception
                # was uncaught here, so it skipped straight past the retry loop
                # (MAX_RETRIES attempts, incl. the model-fallback on attempt 2)
                # to the top-level except further down — hard-failing the whole
                # document as document_type="error" after only ONE attempt. That
                # also silently blocked the so_as_trigger role card, since the
                # trigger requires document_type == "ejari" and is_valid == True.
                # Catch it here so a timeout is treated like any other failed
                # attempt and retried with the next model instead of aborting.
                try:
                    english_data, arabic_data = extractor.extract_with_ai(
                        raw_text,
                        model_choice="llama" if "llama" in current_model else "qwen",
                    )
                except Exception as ejari_extract_error:
                    logger.warning(f"Ejari extraction attempt {attempt}/{MAX_RETRIES} failed: {ejari_extract_error}")
                    if attempt < MAX_RETRIES:
                        logger.info(f"Retrying Ejari extraction with next model...")
                        time.sleep(3)
                    continue

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
                        "VALID: Ejari extracted"
                        if validation_result["is_valid"]
                        else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                    ),
                    "is_valid": validation_result["is_valid"],
                }

            # ====================
            # MOA
            # ====================
            elif doc_type == "moa":
                logger.info("Using MOA Extractor")
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
                    logger.error(f"Text extraction failed: {raw_text}")
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
                        "VALID: MOA extracted"
                        if validation_result["is_valid"]
                        else f"❌ INCOMPLETE: {', '.join(validation_result.get('issues', []))}"
                    ),
                    "is_valid": validation_result["is_valid"],
                }

            # ====================
            # CERTIFICATE OF INCORPORATION (CoI)  ← Type-2 Flow
            # ====================
            elif doc_type == "certificate_of_incorporation":
                logger.info("Using Certificate of Incorporation Extractor (BVI/CoI)")
                extractor = BVIExtractor(api_key=LLAMA_API_KEY)

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                result = extractor.extract(
                    file_bytes,
                    filename=os.path.basename(file_path),
                    model_name=current_model if "llama" not in current_model else None,
                )

                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "certificate_of_incorporation",
                    "raw_text": result.get("raw_text", "")[:1000],
                    "extracted_fields": result.get("extracted_fields", {}),
                    "validation": result.get("validation", {}),
                    "status_message": result.get("status_message", ""),
                    "is_valid": result.get("is_valid", False),
                }

                # If valid, break out of retry loop immediately
                if analysis["is_valid"]:
                    break

            # ====================
            # EID
            # ====================
            elif doc_type == "eid":
                logger.info("Using Enhanced EID Extractor")

                # STEP 1: RUN OCR
                raw_text = ""
                try:
                    raw_text = run_ocr(file_path, current_model)
                except Exception as ocr_error:
                    logger.error(f"OCR failed with {current_model}: {ocr_error}")

                    if "7b" in current_model.lower() and attempt < MAX_RETRIES:
                        fallback_model = LLAMA_MODEL_NAME
                        logger.info(f"Trying fallback model: {fallback_model}")
                        try:
                            raw_text = run_ocr(file_path, fallback_model)
                        except Exception as e:
                            logger.error(f"Fallback OCR also failed: {e}")
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

                # STEP 2: OCR REJECTION DETECTION
                if not raw_text or len(raw_text) < 20:
                    logger.error(f"OCR returned insufficient text: {len(raw_text)} characters")
                    if attempt < MAX_RETRIES:
                        logger.info(f"Will retry with different model...")
                        continue
                    else:
                        analysis = {
                            "filename": os.path.basename(file_path),
                            "document_type": "unknown",
                            "raw_text": raw_text if raw_text else "",
                            "extracted_fields": {},
                            "validation": {
                                "is_valid": False,
                                "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                                "present_fields": [],
                                "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                                "rejection_reason": "OCR returned insufficient text",
                            },
                            "status_message": "❌ INCOMPLETE: OCR failed to extract text from ID card image",
                            "is_valid": False,
                        }
                        break

                text_lower = raw_text.lower()
                rejection_phrases = [
                    "not an emirates id",
                    "does not contain an emirates id",
                    "not contain an emirates id card",
                    "is a screenshot",
                    "is a photograph of a person",
                    "appears to be a form",
                    "conversation between",
                    "i cannot extract",
                    "unable to provide",
                    "can't identify people",
                    "this is not an id",
                    "this image does not",
                    "provided image is not",
                    "appears that the image",
                    "image you provided is a",
                    "cannot identify",
                    "unable to identify",
                ]

                if any(phrase in text_lower for phrase in rejection_phrases):
                    logger.error(f"[SAFETY CHECK] OCR explicitly rejected document as non-EID")
                    logger.info(f"[SAFETY CHECK] Raw text preview: {raw_text[:200]}")
                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "unknown",
                        "raw_text": raw_text[:500],
                        "extracted_fields": {},
                        "validation": {
                            "is_valid": False,
                            "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                            "present_fields": [],
                            "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                            "rejection_reason": "OCR identified document as non-EID",
                        },
                        "status_message": "❌ WRONG DOCUMENT: This is not an Emirates ID card",
                        "is_valid": False,
                    }
                    break

                logger.info(f"OCR accepted as potential EID, extracting...")
                logger.info(f"OCR extracted {len(raw_text)} characters")
                logger.debug(f"OCR preview: {raw_text[:200]}...")

                # STEP 3: BUILD PROMPT
                schema_prompt = f"""You are an expert at extracting information from UAE Emirates ID documents.

            Extract ALL 8 required fields from this Emirates ID.

            Required Fields (must extract ALL 8):
            1. Document Type
            2. ID Number
            3. Name
            4. Date of Birth
            5. Nationality
            6. Issuing Date
            7. Expiry Date
            8. Sex

            STRICT EXTRACTION RULES:
            1. Extract values EXACTLY as they appear on the ID card
            2. For dates, use format: DD/MM/YYYY or DD-MM-YYYY
            3. ID Number MUST include "784-" prefix (e.g., 784-XXXX-XXXXXXX-X)
            4. All field names must match exactly as shown above
            5. If a field is not found, use empty string ""
            6. Do NOT make up or invent data
            7. Do NOT use placeholder values

            Document Text:
            {raw_text}

            Return ONLY valid JSON in this format (NO other text):
            {{
            "Document Type": "<extracted value or empty>",
            "ID Number": "<extracted value or empty>",
            "Name": "<extracted value or empty>",
            "Date of Birth": "<extracted value or empty>",
            "Nationality": "<extracted value or empty>",
            "Issuing Date": "<extracted value or empty>",
            "Expiry Date": "<extracted value or empty>",
            "Sex": "<extracted value or empty>"
            }}

            CRITICAL: Return ONLY the JSON object. No explanation. No preamble."""

                # STEP 4: LLM EXTRACTION
                # Use text model for JSON extraction — current_model is a vision model,
                # but this step is pure text (no image), so TEXT_MODEL_NAME is correct here.
                llm_extracted = {}
                try:
                    logger.info("Attempting AI-based field extraction")
                    llm_response = call_api_with_retry(schema_prompt, TEXT_MODEL_NAME)

                    json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        json_str = re.sub(r'//.*?\n', '', json_str)
                        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                        json_str = re.sub(r'(\w+):', r'"\1":', json_str)
                        try:
                            llm_extracted = json.loads(json_str)
                            logger.info(f"[SUCCESS] AI extracted {len(llm_extracted)} fields")
                        except Exception as json_error:
                            logger.warning(f"JSON parse failed: {json_error}, falling back to regex")
                            llm_extracted = extract_eid_fields(raw_text)
                    else:
                        logger.warning("No JSON found in AI response, using regex fallback")
                        llm_extracted = extract_eid_fields(raw_text)

                except Exception as e:
                    logger.error(f"LLM extraction failed: {e}")
                    llm_extracted = extract_eid_fields(raw_text)

                # STEP 5: VALIDATE / SAFETY CHECK
                llm_extracted = ensure_all_eid_fields(llm_extracted)
                llm_extracted = post_process_eid_data(llm_extracted, raw_text)

                suspicious_values = [
                    "john doe", "jane doe", "xxxx-xxxx-xxxxxxx-x",
                    "0000-0000-0000000-0", "n/a", "null", "undefined",
                    "not found", "<extracted value or empty>",
                    "extracted value", "[empty]", "none",
                ]

                id_number   = str(llm_extracted.get("ID Number",     "")).strip()
                name        = str(llm_extracted.get("Name",           "")).strip()
                nationality = str(llm_extracted.get("Nationality",    "")).strip()
                dob         = str(llm_extracted.get("Date of Birth",  "")).strip()

                is_suspicious = (
                    not id_number or len(id_number) < 10
                    or not name or len(name) < 3
                    or not nationality or len(nationality) < 2
                    or not dob or len(dob) < 8
                    or id_number.lower() in [v.lower() for v in suspicious_values]
                    or name.lower() in [v.lower() for v in suspicious_values]
                    or nationality.lower() in [v.lower() for v in suspicious_values]
                    or not id_number.startswith("784-")
                    or not re.match(r'\d{2}[/-]\d{2}[/-]\d{4}', dob)
                )

                ocr_contains_id_pattern = bool(re.search(r'784-\d{4}-\d{7}-\d', raw_text))
                ocr_contains_name = name.lower() in raw_text.lower() if name else False
                data_in_ocr = ocr_contains_id_pattern or ocr_contains_name

                if is_suspicious or not data_in_ocr:
                    logger.error(f"[SAFETY CHECK] Detected invalid/suspicious extraction")
                    logger.info(f"[SAFETY CHECK] ID Number: '{id_number}' (length: {len(id_number)})")
                    logger.info(f"[SAFETY CHECK] Name: '{name}' (length: {len(name)})")
                    logger.info(f"[SAFETY CHECK] Nationality: '{nationality}'")
                    logger.info(f"[SAFETY CHECK] DOB: '{dob}'")
                    logger.info(f"[SAFETY CHECK] Data found in OCR: {data_in_ocr}")
                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "unknown",
                        "raw_text": raw_text[:500],
                        "extracted_fields": {},
                        "validation": {
                            "is_valid": False,
                            "required_fields": list(REQUIRED_FIELDS_EID.keys()),
                            "present_fields": [],
                            "missing_fields": list(REQUIRED_FIELDS_EID.keys()),
                            "rejection_reason": "Could not extract valid EID data or data not found in OCR text",
                        },
                        "status_message": "❌ INVALID: Could not extract valid EID data from document",
                        "is_valid": False,
                    }
                    break

                # STEP 6: STANDARD VALIDATION
                validation = validate_eid_fields(llm_extracted)

                logger.info(f"[VALIDATION] EID: {len(validation['present_fields'])}/{len(validation['required_fields'])} fields")
                if validation['missing_fields']:
                    logger.info(f"[VALIDATION] Missing fields: {validation['missing_fields']}")

                analysis = {
                    "filename": os.path.basename(file_path),
                    "document_type": "eid",
                    "raw_text": raw_text,
                    "extracted_fields": llm_extracted,
                    "validation": validation,
                    "status_message": (
                        "VALID: EID extracted"
                        if validation["is_valid"]
                        else f"❌ INCOMPLETE: missing {', '.join(validation['missing_fields'])}"
                    ),
                    "is_valid": validation["is_valid"],
                }

                if validation["is_valid"]:
                    logger.info(f"[SUCCESS] Validation passed on attempt {attempt}")
                    break
                else:
                    logger.error(f"Validation failed on attempt {attempt}")
                    if attempt < MAX_RETRIES:
                        logger.info(f"Retrying with different approach...")
                        continue
                    else:
                        logger.error(f"All {MAX_RETRIES} attempts exhausted")

            # ====================
            # PASSPORT
            # ====================
            elif doc_type == "passport":
                logger.info("Using Passport Extractor")

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                try:
                    passport_result = process_passport(file_bytes, os.path.basename(file_path))

                    extracted_fields = passport_result.get("extracted_data", {})
                    is_valid = passport_result.get("is_valid", False)
                    validation_errors = passport_result.get("validation_errors", [])
                    warnings = passport_result.get("warnings", [])
                    full_name = passport_result.get("full_name", "")

                    validation_result = {
                        "is_valid": is_valid,
                        "required_fields": list(f.value for f in __import__(
                            "app.services.specialized_ocr.passport_extractor",
                            fromlist=["MandatoryFields"]
                        ).MandatoryFields),
                        "present_fields": [k for k, v in extracted_fields.items() if v],
                        "missing_fields": [e.replace("Missing required field: ", "") for e in validation_errors],
                        "issues": validation_errors,
                    }

                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "passport",
                        "raw_text": "",
                        "extracted_fields": extracted_fields,
                        "extracted_data": extracted_fields,
                        "validation": validation_result,
                        "status_message": (
                            f"VALID: Passport extracted for {full_name}"
                            if is_valid
                            else f"❌ INCOMPLETE: {'; '.join(validation_errors)}"
                        ),
                        "is_valid": is_valid,
                        "full_name": full_name,
                        "warnings": warnings,
                    }

                    if is_valid:
                        logger.info(f"[SUCCESS] Passport extraction passed: {full_name}")
                        break
                    else:
                        logger.warning(f"Passport validation failed: {validation_errors}")
                        if attempt < MAX_RETRIES:
                            logger.info(f"Retrying passport extraction...")
                            continue
                        else:
                            logger.error(f"All {MAX_RETRIES} passport attempts exhausted")

                except Exception as passport_error:
                    logger.error(f"Passport extraction failed: {passport_error}")
                    if attempt < MAX_RETRIES:
                        continue
                    analysis = {
                        "filename": os.path.basename(file_path),
                        "document_type": "passport",
                        "raw_text": "",
                        "extracted_fields": {},
                        "validation": {"is_valid": False, "issues": [str(passport_error)]},
                        "status_message": f"❌ INCOMPLETE: Passport extraction failed - {str(passport_error)}",
                        "is_valid": False,
                    }
                    break

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

            # CHECK IF VALID — break out of retry loop if successful
            if analysis and analysis.get("is_valid", False):
                logger.info(f"[SUCCESS] Validation passed on attempt {attempt}")
                break
            else:
                logger.error(f"Validation failed on attempt {attempt}")
                if attempt < MAX_RETRIES:
                    logger.info(f"Retrying with different approach...")
                    time.sleep(3)
                else:
                    logger.error(f"All {MAX_RETRIES} attempts exhausted")

    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
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
                "missing_fields": [],
            },
            "status_message": "Processing incomplete",
            "is_valid": False,
        }

    # ============================================================================
    # EXPIRY DATE VALIDATION
    # ============================================================================
    expiry_validation = None
    expiry_failed_message = None

    doc_type_mapping = {
        "eid": "eid",
        "ejari": "ejari",
        "commercial": "commercial_license",
        "passport": "passport",          # ← Passport expiry now validated
    }

    validator_doc_type = doc_type_mapping.get(analysis.get("document_type"))

    # Skip expiry validation only for genuine Multiple Owner commercial licenses.
    # Single Owner extracted_fields = {"english", "arabic", "owner"}  — no "partners" key.
    # Multiple Owner extracted_fields = {"english", "arabic", "managers", "partners"}.
    # Using "managers" as the signal was wrong: a Single Owner document whose ownership_type
    # is mis-detected also gets a "managers" key, causing expiry to be silently skipped.
    # "partners" is the reliable discriminator — it only appears in Multi-Owner output.
    _ef = analysis.get("extracted_fields", {})
    is_multi_owner_commercial = (
        analysis.get("document_type") == "commercial"
        and "partners" in _ef
        and isinstance(_ef.get("partners"), list)
        and len(_ef.get("partners", [])) > 0
    )
    if is_multi_owner_commercial:
        validator_doc_type = None
        logger.info(f"[EXPIRY] Skipping expiry validation for Multiple Owner commercial license")

    if validator_doc_type:
        logger.info(f"\n[EXPIRY] Validating expiry date for {analysis.get('document_type')}...")
        extracted_data = analysis.get("extracted_fields", {})
        try:
            expiry_result = validate_document_expiry(
                document_data=extracted_data,
                doc_type=validator_doc_type,
            )
            expiry_validation = expiry_result["validation"]

            logger.info(f"[EXPIRY] Status: {expiry_validation['document_status']}")
            logger.info(f"[EXPIRY] Expiry date found: {expiry_validation.get('expiry_date_found')}")
            logger.info(f"[EXPIRY] Current date: {expiry_validation.get('current_date')}")

            if expiry_result["status"] == "EXPIRED":
                logger.error(f"[EXPIRY] Document is EXPIRED - generating AI message...")
                try:
                    expiry_failed_message = generate_expiry_failure_message(
                        doc_type=validator_doc_type,
                        expiry_date_found=expiry_validation.get("expiry_date_found"),
                        current_date=expiry_validation.get("current_date"),
                        reason=expiry_validation.get("expiry_reason"),
                    )
                    logger.info(f"[EXPIRY] AI message generated: {expiry_failed_message[:100]}...")
                except Exception as e:
                    logger.warning(f"[EXPIRY] Failed to generate AI message: {e}")
                    doc_display_name = {
                        "eid": "Emirates ID",
                        "ejari": "Ejari Contract",
                        "commercial_license": "Commercial License",
                        "passport": "Passport",
                    }.get(validator_doc_type, "document")
                    expiry_failed_message = localized(None,
                        en=f"Your {doc_display_name} has expired. Please upload a valid document with a current expiry date.",
                        es=f"Su {doc_name(doc_display_name, 'spanish')} ha vencido. Cargue un documento vigente con una fecha de vencimiento actual.",
                        ar=f"انتهت صلاحية {doc_name(doc_display_name, 'arabic')}. يُرجى تحميل مستند ساري المفعول بتاريخ انتهاء حالي.")
                analysis["is_valid"] = False
                analysis["status_message"] = expiry_failed_message
            else:
                logger.info(f"[EXPIRY] Document is VALID - expiry check passed")

        except Exception as e:
            logger.warning(f"[EXPIRY] Expiry validation error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    else:
        logger.info(f"[EXPIRY] Skipping expiry validation for {analysis.get('document_type')} (document type not in expiry check list)")

    # STANDARDIZED OUTPUT FORMAT
    final_output = {
        "filename":         analysis.get("filename", os.path.basename(file_path)),
        "document_type":    analysis.get("document_type", "unknown"),
        "raw_text":         str(analysis.get("raw_text", ""))[:1000],
        "extracted_fields": analysis.get("extracted_fields", {}) if not expiry_failed_message else {},
        "validation":       analysis.get("validation", {}),
        "expiry_validation": expiry_validation,
        "status_message":   analysis.get("status_message", ""),
        "is_valid":         analysis.get("is_valid", False),
        "created_at":       datetime.now(timezone.utc).isoformat(),
        "human_verified":   False,
    }

    # Save to disk
    output_dir = os.path.join(DOCUMENTS_ROOT, user_email, document_id)
    ensure_directory(output_dir)
    output_path = os.path.join(output_dir, "output.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    logger.info(f"Output saved: {output_path}")
    logger.debug(f"Document type: {final_output.get('document_type')}")
    logger.debug(f"Is valid: {final_output.get('is_valid')}")
    logger.debug(f"Extracted fields count: {len(final_output.get('extracted_fields', {}))}")

    if expiry_validation:
        logger.debug(f"Expiry status: {expiry_validation.get('document_status')}")

    if final_output.get("extracted_fields"):
        logger.debug(f"Field names: {list(final_output['extracted_fields'].keys())[:5]}")

    return final_output

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
