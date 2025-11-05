# specialized_ocr/trade_extractor.py

import os
import json
import re
import requests
import time
from typing import Dict, Tuple, List, Union, Optional
from functools import wraps
from dataclasses import dataclass, asdict
import fitz  # PyMuPDF
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('trade_license_extraction.log')
    ]
)
logger = logging.getLogger(__name__)

# API Configuration
API_KEY = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-...")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-32b-instruct"

# Request timeout configuration
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
BASE_RETRY_DELAY = 5

# Fields for Multiple Owner Trade License (33 fields)
MULTI_OWNER_ENGLISH_FIELDS = [
    "license_number", "main_license_number", "commercial_register_number",
    "issue_date", "expiry_date", "receipt_number", "print_date",
    "company_name_english", "company_name_arabic", "trade_name_english",
    "trade_name_arabic", "legal_type", "duns_number",
    "activity_1", "activity_2", "activity_3",
    "phone", "fax", "mobile", "po_box",
    "license_address", "parcel_id", "commerce_address",
    "nominated_capital", "paid_capital", "currency", "number_of_shares",
    "payment_voucher_number", "payment_mode", "payment_amount",
]

MULTI_OWNER_ARABIC_FIELDS = [
    "رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
    "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
    "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية", "الاسم_التجاري_بالإنجليزية",
    "الاسم_التجاري_بالعربية", "الشكل_القانوني", "رقم_دنز",
    "النشاط_1", "النشاط_2", "النشاط_3",
    "هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد",
    "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
    "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
    "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع",
]

# Fields for Single Owner Trade License (39 fields)
SINGLE_OWNER_ENGLISH_FIELDS = [
    "license_number", "main_license_number", "commercial_register_number",
    "issue_date", "expiry_date", "receipt_number", "print_date",
    "company_name_english", "company_name_arabic", "trade_name_english",
    "trade_name_arabic", "legal_type", "duns_number", "dcci_number",
    "activity_1", "activity_2", "activity_3", "activity_4",
    "phone", "fax", "mobile", "po_box", "email",
    "license_address", "parcel_id", "commerce_address",
    "nominated_capital", "paid_capital", "currency", "number_of_shares",
    "payment_voucher_number", "payment_mode", "payment_amount",
    "contract_number", "contract_date",
]

SINGLE_OWNER_ARABIC_FIELDS = [
    "رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
    "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
    "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية", "الاسم_التجاري_بالإنجليزية",
    "الاسم_التجاري_بالعربية", "الشكل_القانوني", "رقم_دنز", "رقم_عضوية_الغرفة",
    "النشاط_1", "النشاط_2", "النشاط_3", "النشاط_4",
    "هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد", "البريد_الإلكتروني",
    "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
    "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
    "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع",
    "رقم_العقد", "تاريخ_العقد",
]

# Data classes for type safety
@dataclass
class Owner:
    """Single owner information"""
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    passport_number: str = ""
    date_of_birth: str = ""
    share_percentage: str = ""
    role: str = ""

@dataclass
class Manager:
    """Manager information"""
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    role: str = ""

@dataclass
class Partner:
    """Partner/shareholder information"""
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    share_percentage: str = ""

@dataclass
class ExtractionMetrics:
    """Extraction performance metrics"""
    ai_extracted: int = 0
    regex_recovered: int = 0
    final_completeness: int = 0
    processing_time: float = 0.0
    api_calls: int = 0
    api_errors: int = 0


# ===========================
# RETRY LOGIC DECORATOR
# ===========================
def retry_with_backoff(max_retries: int = 3, base_delay: int = 10):
    """Retry decorator with exponential backoff for API failures"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RuntimeError as e:
                    error_msg = str(e)
                    error_codes = ["503", "429", "502", "504"]
                    
                    if any(code in error_msg for code in error_codes) and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"API error (attempt {attempt + 1}/{max_retries}): {error_msg}. "
                            f"Retrying in {delay} seconds..."
                        )
                        time.sleep(delay)
                    else:
                        raise
            return None
        return wrapper
    return decorator


class TradeLicenseExtractor:
    """
    Unified Trade License extractor with bilingual support, retry logic, and comprehensive regex fallback.
    Supports both Single Owner and Multiple Owner/Partnership companies.
    """

    def __init__(self, api_key: Optional[str] = None, ownership_type: Optional[str] = None):
        """
        Initialize the extractor

        Args:
            api_key: OpenRouter API key (or read from OPENROUTER_API_KEY env var)
            ownership_type: "Single Owner" or "Multiple Owners" (auto-detected if None)
        """
        self.api_key = api_key or API_KEY
        self.api_url = API_URL
        self.ownership_type = ownership_type
        self.extraction_metrics = ExtractionMetrics()
        self.start_time = None
        logger.info("TradeLicenseExtractor initialized")

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text content from PDF using PyMuPDF - FIXED VERSION"""
        doc = None
        try:
            # Open PDF from bytes
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            # Check if PDF has pages
            if doc.page_count == 0:
                logger.error("PDF has no pages")
                return "[PDF EXTRACTION ERROR] PDF has no pages"

            # Extract text from all pages
            text = ""
            for i in range(doc.page_count):
                try:
                    page = doc[i]  # Simpler way to access page
                    page_text = page.get_text()
                    text += page_text + "\n"
                except Exception as e:
                    logger.warning(f"Error extracting page {i}: {e}")
                    continue

            # Validate extracted content
            if not text or len(text.strip()) < 100:
                logger.error("PDF appears empty or contains very little text")
                return "[PDF EXTRACTION ERROR] PDF appears to be empty or contains very little text"

            logger.info(f"[SUCCESS] Extracted {len(text)} characters from PDF with {doc.page_count} pages")
            return text
            
        except Exception as e:
            error_msg = f"[PDF EXTRACTION ERROR] {str(e)}"
            logger.error(error_msg)
            return error_msg
        
        finally:
            # CRITICAL: Always close the document, even if error occurs
            if doc is not None:
                try:
                    doc.close()
                except Exception as e:
                    logger.warning(f"Error closing PDF document: {e}")

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def call_ai_api(self, prompt: str, model_name: Optional[str] = None) -> str:
        """Call OpenRouter API with retry logic"""
        if not self.api_key:
            logger.error("API key not configured")
            return "API key not configured"

        model = model_name or LLAMA_MODEL_NAME

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000,
        }

        try:
            self.extraction_metrics.api_calls += 1
            response = requests.post(
                self.api_url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
            )

            if response.status_code in [502, 503, 504]:
                self.extraction_metrics.api_errors += 1
                raise RuntimeError(
                    f"Trade License API failed: {response.status_code} Server temporarily unavailable"
                )
            if response.status_code == 429:
                self.extraction_metrics.api_errors += 1
                raise RuntimeError(
                    f"Trade License API failed: {response.status_code} Rate limit exceeded"
                )

            response.raise_for_status()
            result = response.json()
            logger.info(f"API call successful - Model: {model}")
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            self.extraction_metrics.api_errors += 1
            logger.error("API request timeout after 120 seconds")
            raise RuntimeError(
                "Trade License API failed: Request timeout after 60 seconds"
            )
        except requests.exceptions.RequestException as e:
            self.extraction_metrics.api_errors += 1
            status_code = response.status_code if 'response' in locals() else 'Unknown'
            logger.error(f"API request failed: {status_code} {str(e)}")
            raise RuntimeError(
                f"Trade License API failed: {status_code} {str(e)}"
            )

    def detect_ownership_type(self, raw_text: str) -> str:
        """
        Detect if the license is for Single Owner or Multiple Owner company
        Returns: "Single Owner" or "Multiple Owners"
        """
        single_owner_patterns = [
            r"Single Owner",
            r"LLC - SO",
            r"L\.L\.C - S\.O",
            r"الشخص الواحد",
            r"شركة ذات مسؤولية محدودة - الشخص الواحد",
        ]

        for pattern in single_owner_patterns:
            if re.search(pattern, raw_text, re.IGNORECASE):
                logger.info("Detected: Single Owner Trade License")
                return "Single Owner"

        logger.info("Detected: Multiple Owners Trade License")
        return "Multiple Owners"

    def _build_regex_patterns(self) -> Dict[str, List[str]]:
        """Build comprehensive regex patterns for all fields"""
        return {
            # ===== LICENSE INFORMATION =====
            "license_number": [
                r"License No[.:]?\s*(\d+)",
                r"Lic\. No[.:]?\s*(\d+)",
                r"License Number[.:]?\s*(\d+)",
                r"رقم الرخصة\s*[\):=]\s*(\d+)",
                r"Lic\.No\s*(\d+)",
            ],
            "main_license_number": [
                r"Main License No[.:]?\s*(\d+)",
                r"Main Lic[.:]?\s*(\d+)",
                r"Primary License[.:]?\s*(\d+)",
                r"رقم الرخصة الأم\s*[\):=]\s*(\d+)",
            ],
            "commercial_register_number": [
                r"(?:Commercial\s+)?Register No[.:]?\s*(\d+)",
                r"Reg\. No[.:]?\s*(\d+)",
                r"Registration Number[.:]?\s*(\d+)",
                r"Commercial Register[.:]?\s*(\d+)",
                r"رقم السجل التجاري\s*[\):=]\s*(\d+)",
            ],
            "issue_date": [
                r"(?:Date\s+)?Issue[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"Issue Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"Issued?(?:\s+on)?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"تاريخ الإصدار\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            ],
            "expiry_date": [
                r"(?:Date\s+)?Expiry[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"Expiry Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"Expires?(?:\s+on)?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"تاريخ الانتهاء\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            ],
            "receipt_number": [
                r"Receipt No[.:]?\s*(\d+)",
                r"Receipt Number[.:]?\s*(\d+)",
                r"Rec\. No[.:]?\s*(\d+)",
                r"رقم الإيصال\s*[\):=]\s*(\d+)",
            ],
            "print_date": [
                r"Print Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+\d{1,2}:\d{2})",
                r"Printed?(?:\s+on)?[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+\d{1,2}:\d{2})",
                r"تاريخ الطباعة\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}\s+\d{1,2}:\d{2})",
            ],
            
            # ===== COMPANY DETAILS =====
            "company_name_english": [
                r"Company Name\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|Arabic|Trade|$)",
                r"Legal Name\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|Arabic|$)",
                r"Registered\s+as\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|$)",
            ],
            "company_name_arabic": [
                r"اسم الشركة\s*[\):=]\s*([^\n]+?)(?:\n|$)",
                r"الاسم بالعربية\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "trade_name_english": [
                r"(?:Trade\s+)?Name\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|Commercial|$)",
                r"Business Name[:\s]+([A-Z\s&\-\.]+?)(?:\n|$)",
                r"Commercial Name[:\s]+([A-Z\s&\-\.]+?)(?:\n|$)",
            ],
            "trade_name_arabic": [
                r"الاسم التجاري\s*[\):=]\s*([^\n]+?)(?:\n|$)",
                r"اسم العمل\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "legal_type": [
                r"Legal Type\s*[:\s]+([A-Z\s\-()]+?)(?:\n|$)",
                r"(?:Company\s+)?Form\s*[:\s]+([A-Z\s\-()]+?)(?:\n|$)",
                r"الشكل القانوني\s*[\):=]\s*([^\n]+?)(?:\n|$)",
                r"(LLC|Limited Liability|Partnership|Sole Proprietor|Single Owner)",
            ],
            "duns_number": [
                r"DUNS(?:\s+Number)?\s*[:\s]+(\d+)",
                r"DUNS[:\s]+(\d{9})",
                r"رقم دنز\s*[\):=]\s*(\d+)",
            ],
            "dcci_number": [
                r"DCCI\s+(?:No|Number)?[.:]?\s*(\d+)",
                r"Chamber(?:\s+Number)?[.:]?\s*(\d+)",
                r"رقم عضوية الغرفة\s*[\):=]\s*(\d+)",
            ],
            
            # ===== BUSINESS ACTIVITIES =====
            "activity_1": [
                r"Activity\s*1[.:]?\s*([^\n]+?)(?:\n|Activity|$)",
                r"Main Activity[.:]?\s*([^\n]+?)(?:\n|$)",
                r"النشاط\s*1\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "activity_2": [
                r"Activity\s*2[.:]?\s*([^\n]+?)(?:\n|Activity|$)",
                r"Secondary Activity[.:]?\s*([^\n]+?)(?:\n|$)",
                r"النشاط\s*2\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "activity_3": [
                r"Activity\s*3[.:]?\s*([^\n]+?)(?:\n|Activity|$)",
                r"النشاط\s*3\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "activity_4": [
                r"Activity\s*4[.:]?\s*([^\n]+?)(?:\n|$)",
                r"النشاط\s*4\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            
            # ===== CONTACT INFORMATION =====
            "phone": [
                r"(?:Tel|Phone)(?:\s+No)?[.:\s]+(\+?971[\s\-]?\d[\s\-]?\d{7}|\d{2,3}[\s\-]\d{6,7})",
                r"هاتف\s*[\):=]\s*(\+?971[\s\-]?\d[\s\-]?\d{7}|\d{2,3}[\s\-]\d{6,7})",
                r"Telephone[.:\s]+([0-9\-\+\s()]+)",
            ],
            "fax": [
                r"Fax(?:\s+No)?[.:\s]+([0-9\-\+\s()]+)",
                r"فاكس\s*[\):=]\s*([0-9\-\+\s()]+)",
                r"Facsimile[.:\s]+([0-9\-\+\s()]+)",
            ],
            "mobile": [
                r"(?:Mobile|Cell|Cellular)(?:\s+No)?[.:\s]+(\+?971[\s\-]?\d{2}[\s\-]?\d{7}|[0-9\-\+\s()]+)",
                r"هاتف متحرك\s*[\):=]\s*(\+?971[\s\-]?\d{2}[\s\-]?\d{7}|[0-9\-\+\s()]+)",
                r"Mobile Phone[.:\s]+([0-9\-\+\s()]+)",
            ],
            "po_box": [
                r"P\.?O\.?\s+Box[.:]?\s*(\d+)",
                r"PO\s+Box[.:]?\s*(\d+)",
                r"صندوق بريد\s*[\):=]\s*(\d+)",
            ],
            "email": [
                r"E?mail[.:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"البريد الإلكتروني\s*[\):=]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            ],
            
            # ===== ADDRESS INFORMATION =====
            "license_address": [
                r"License Address[.:]?\s*([^\n]+?)(?:\n|$)",
                r"عنوان الرخصة\s*[\):=]\s*([^\n]+?)(?:\n|$)",
                r"Address(?:\s+\(License\))?[.:]?\s*([^\n]+?)(?:\n|Commerce|$)",
            ],
            "commerce_address": [
                r"Commerce Address[.:]?\s*([^\n]+?)(?:\n|$)",
                r"عنوان السجل التجاري\s*[\):=]\s*([^\n]+?)(?:\n|$)",
                r"Commercial Address[.:]?\s*([^\n]+?)(?:\n|$)",
            ],
            "parcel_id": [
                r"Parcel\s+(?:ID|No)[.:]?\s*([\d\-]+)",
                r"Plot\s+(?:No|ID)[.:]?\s*([\d\-]+)",
                r"رقم القطعة\s*[\):=]\s*([\d\-]+)",
            ],
            
            # ===== CAPITAL DETAILS =====
            "nominated_capital": [
                r"Nominated\s+Capital[.:]?\s*([0-9,]+)",
                r"رأس المال الاسمي\s*[\):=]\s*([0-9,]+)",
                r"Authorized Capital[.:]?\s*([0-9,]+)",
            ],
            "paid_capital": [
                r"Paid(?:\s+up)?\s+Capital[.:]?\s*([0-9,]+)",
                r"رأس المال المدفوع\s*[\):=]\s*([0-9,]+)",
                r"Capital Paid[.:]?\s*([0-9,]+)",
                r"Paid\s+[.:]?\s*([0-9,]+)",
            ],
            "currency": [
                r"Currency[.:]?\s*(AED|USD|EUR|GBP|درهم|دولار)",
                r"العملة\s*[\):=]\s*(AED|USD|EUR|GBP|درهم إماراتي)",
            ],
            "number_of_shares": [
                r"(?:No|Number)\.?\s+of\s+Shares[.:]?\s*(\d+)",
                r"عدد الأسهم\s*[\):=]\s*(\d+)",
                r"Shares[.:]?\s*(\d+)",
            ],
            
            # ===== PAYMENT INFORMATION =====
            "payment_voucher_number": [
                r"P\.?V\.?\s+(?:No|Number|Voucher)[.:]?\s*(\d+)",
                r"Payment\s+Voucher[.:]?\s*(\d+)",
                r"رقم إذن الدفع\s*[\):=]\s*(\d+)",
            ],
            "payment_mode": [
                r"Payment\s+(?:Mode|Method)[.:]?\s*([^\n]+?)(?:\n|$)",
                r"كيفية الدفع\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ],
            "payment_amount": [
                r"Total(?:\s+Amount)?(?:\s+Paid)?[.:]?\s*([0-9,]+)",
                r"مبلغ الدفع\s*[\):=]\s*([0-9,]+)",
                r"Amount Paid[.:]?\s*([0-9,]+)",
            ],
            
            # ===== CONTRACT INFORMATION (Single Owner Only) =====
            "contract_number": [
                r"Contract\s+(?:No|Number)[.:]?\s*(\d+)",
                r"Memorandum\s+(?:No|Number)[.:]?\s*(\d+)",
                r"رقم العقد\s*[\):=]\s*(\d+)",
            ],
            "contract_date": [
                r"Contract\s+Date[.:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"تاريخ العقد\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
                r"Memorandum\s+Date[.:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
            ],
        }

    def _normalize_date(self, date_str: str) -> str:
        """Normalize various date formats to DD/MM/YYYY"""
        if not date_str:
            return ""
        
        date_patterns = [
            (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", lambda m: f"{m.group(3):0>2}/{m.group(2):0>2}/{m.group(1)}"),
            (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", lambda m: f"{m.group(1):0>2}/{m.group(2):0>2}/{m.group(3)}"),
        ]
        
        for pattern, formatter in date_patterns:
            match = re.search(pattern, str(date_str))
            if match:
                return formatter(match)
        
        return str(date_str)

    def _normalize_phone(self, phone_str: str) -> str:
        """Normalize phone numbers to consistent format"""
        if not phone_str:
            return ""
        
        normalized = re.sub(r'\s+', '-', str(phone_str).strip())
        normalized = re.sub(r'[()]+', '', normalized)
        
        return normalized

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """
        Fix incomplete or missing values using comprehensive regex fallback patterns.
        This provides dual-layer extraction: AI + Regex for maximum reliability.
        """
        incomplete_patterns = self._build_regex_patterns()
        fallback_count = 0
        
        for field, patterns in incomplete_patterns.items():
            if field in data:
                current_value = data[field]
                if not current_value or len(str(current_value).strip()) < 2:
                    for pattern in patterns:
                        try:
                            match = re.search(pattern, raw_text, re.IGNORECASE)
                            if match:
                                extracted_value = match.group(1).strip()
                                if extracted_value and len(extracted_value) > 1:
                                    data[field] = extracted_value
                                    fallback_count += 1
                                    logger.debug(f"Fallback recovery for {field}: {extracted_value[:50]}")
                                    break
                        except Exception as e:
                            logger.warning(f"Regex pattern error for {field}: {str(e)}")
                            continue
        
        # Normalize date formats to DD/MM/YYYY
        date_fields = ["issue_date", "expiry_date", "print_date", "contract_date", "date_of_birth"]
        for field in date_fields:
            if field in data and data[field]:
                data[field] = self._normalize_date(data[field])
        
        # Normalize phone numbers
        phone_fields = ["phone", "fax", "mobile"]
        for field in phone_fields:
            if field in data and data[field]:
                data[field] = self._normalize_phone(data[field])
        
        # Normalize capital amounts (remove commas)
        capital_fields = ["nominated_capital", "paid_capital", "payment_amount"]
        for field in capital_fields:
            if field in data and data[field]:
                data[field] = str(data[field]).replace(",", "").strip()
        
        self.extraction_metrics.regex_recovered = fallback_count
        logger.info(f"Regex fallback recovered {fallback_count} fields")
        return data

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def extract_single_owner_with_ai(self, raw_text: str) -> Tuple[Dict, Dict, Dict]:
        """Extract Single Owner Trade License fields using AI with retry logic"""

        EXPECTED_FIELD_COUNT = len(SINGLE_OWNER_ENGLISH_FIELDS)

        prompt = f"""You are an expert at extracting information from UAE Dubai Trade License (Commercial License) documents for SINGLE OWNER companies.

Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic from this bilingual Trade License certificate.

CRITICAL EXTRACTION RULES:
1. Extract values EXACTLY as they appear in the document
2. For dates, use format: DD/MM/YYYY
3. For activities, extract up to 4 business activities listed
4. This is a SINGLE OWNER company - extract the owner information separately
5. Preserve all Arabic text exactly as shown
6. If a field is not found, set it as empty string ""
7. Extract ALL {EXPECTED_FIELD_COUNT} base fields plus owner information

FIELD MAPPING GUIDE:
- "license_number": License No./رقم الرخصة
- "main_license_number": Main License No./رقم الرخصة الأم
- "commercial_register_number": Register No./رقم السجل التجاري
- "issue_date": Issue Date/تاريخ الإصدار (DD/MM/YYYY)
- "expiry_date": Expiry Date/تاريخ الانتهاء (DD/MM/YYYY)
- "company_name_english": Company Name in English
- "company_name_arabic": اسم الشركة in Arabic
- "trade_name_english": Business Name in English
- "trade_name_arabic": الاسم التجاري in Arabic
- "legal_type": Legal Type (e.g., "Limited Liability Company - Single Owner(LLC - SO)")
- "duns_number": DUNS Number
- "dcci_number": DCCI No./عضوية الغرفة
- "activity_1" to "activity_4": Business activities listed
- "phone": Phone No/تليفون
- "fax": Fax No/فاكس
- "mobile": Mobile No/هاتف متحرك
- "email": Email/البريد الإلكتروني
- "po_box": P.O. Box/صندوق بريد
- "license_address": License Address/عنوان الرخصة
- "parcel_id": Parcel ID/رقم القطعة
- "commerce_address": Commerce Address/عنوان السجل التجاري
- "paid_capital": Paid Capital/المدفوع
- "nominated_capital": Nominated Capital/الاسمي
- "currency": Currency/العملة
- "number_of_shares": No. of Shares/عدد الأسهم
- "payment_voucher_number": P.V.Nr./رقم إذن الدفع
- "payment_amount": Total amount paid
- "payment_mode": Payment Mode/كيفية الدفع
- "contract_number": Contract Number from Memorandum of Association
- "contract_date": Contract Date (DD/MM/YYYY)
- "receipt_number": Receipt Number
- "print_date": Print Date

English Fields (ALL {EXPECTED_FIELD_COUNT} required):
{json.dumps(SINGLE_OWNER_ENGLISH_FIELDS, indent=2)}

Arabic Fields (ALL {EXPECTED_FIELD_COUNT} required):
{json.dumps(SINGLE_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

Document Text (first 25,000 characters):
{raw_text[:25000]}

OWNER EXTRACTION (SINGLE OWNER ONLY):
Extract the single owner information with these exact fields:
- person_number: Unique identifier/Person No.
- name_english: Owner name in English
- name_arabic: Owner name in Arabic
- nationality_english: Nationality in English
- nationality_arabic: Nationality in Arabic
- passport_number: Passport number
- date_of_birth: Date of birth (DD/MM/YYYY)
- share_percentage: Ownership percentage (should be "100%" for single owner)
- role: Role (e.g., "Shares Owner", "Manager", "Shares Owner & Manager")

Example JSON structure:
{{
"english": {{
    "license_number": "123456",
    "company_name_english": "EXAMPLE TRADING COMPANY L.L.C",
    "trade_name_english": "EXAMPLE TRADING CO",
    "legal_type": "Limited Liability Company - Single Owner(LLC - SO)",
    "issue_date": "01/01/2024",
    "expiry_date": "31/12/2025"
}},
"arabic": {{
    "رقم_الرخصة": "123456",
    "اسم_الشركة_بالإنجليزية": "EXAMPLE TRADING COMPANY L.L.C",
    "الاسم_التجاري_بالإنجليزية": "EXAMPLE TRADING CO"
}},
"owner": {{
    "person_number": "7654321",
    "name_english": "JOHN SMITH",
    "name_arabic": "جون سميث",
    "nationality_english": "United Kingdom",
    "nationality_arabic": "المملكة المتحدة",
    "share_percentage": "100.00%",
    "role": "Shares Owner & Manager"
}}
}}

CRITICAL: Return ONLY valid JSON with ALL {EXPECTED_FIELD_COUNT} base fields populated, plus owner information.
"""

        try:
            response = self.call_ai_api(prompt)

            if response and not response.startswith("API"):
                try:
                    json_match = re.search(r"\{.*\}", response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group()
                        json_str = re.sub(r",\s*}", "}", json_str)
                        json_str = re.sub(r",\s*]", "]", json_str)

                        data = json.loads(json_str)
                        english_data = data.get("english", {})
                        arabic_data = data.get("arabic", {})
                        owner = data.get("owner", {})

                        english_data = self.ensure_all_fields(
                            english_data, SINGLE_OWNER_ENGLISH_FIELDS
                        )
                        arabic_data = self.ensure_all_fields(
                            arabic_data, SINGLE_OWNER_ARABIC_FIELDS
                        )

                        english_data = self.post_process_data(english_data, raw_text)
                        arabic_data = self.post_process_data(arabic_data, raw_text)

                        logger.info("Single Owner extraction complete")
                        self.extraction_metrics.ai_extracted = len([v for v in english_data.values() if v])
                        return english_data, arabic_data, owner

                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing error: {e}")
                except Exception as e:
                    logger.error(f"Extraction failed: {e}")

        except Exception as e:
            logger.error(f"API call failed: {e}")

        logger.warning("Single Owner extraction failed, returning empty data")
        return (
            {field: "" for field in SINGLE_OWNER_ENGLISH_FIELDS},
            {field: "" for field in SINGLE_OWNER_ARABIC_FIELDS},
            {},
        )

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def extract_multi_owner_with_ai(
        self, raw_text: str
    ) -> Tuple[Dict, Dict, List[Dict], List[Dict]]:
        """Extract Multiple Owner Trade License fields using AI with retry logic"""

        EXPECTED_FIELD_COUNT = len(MULTI_OWNER_ENGLISH_FIELDS)

        prompt = f"""You are an expert at extracting information from UAE Dubai Trade License (Commercial License) documents for MULTIPLE OWNER/PARTNERSHIP companies.

    Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic from this bilingual Trade License certificate.

    CRITICAL EXTRACTION RULES:
    1. Extract values EXACTLY as they appear in the document
    2. For dates, use format: DD/MM/YYYY
    3. For activities, extract up to 3 business activities listed
    4. This is a MULTIPLE OWNER company - extract ALL managers AND ALL partners/shareholders separately
    5. Preserve all Arabic text exactly as shown
    6. If a field is not found, set it as empty string ""
    7. Extract ALL {EXPECTED_FIELD_COUNT} base fields plus ALL managers and ALL partners

    FIELD MAPPING GUIDE (Base Information):
    - "license_number": License No./رقم الرخصة
    - "main_license_number": Main License No./رقم الرخصة الأم
    - "commercial_register_number": Register No./رقم السجل التجاري
    - "issue_date": Issue Date/تاريخ الإصدار (DD/MM/YYYY)
    - "expiry_date": Expiry Date/تاريخ الانتهاء (DD/MM/YYYY)
    - "company_name_english": Company Name in English
    - "company_name_arabic": اسم الشركة in Arabic
    - "trade_name_english": Business Name in English
    - "trade_name_arabic": الاسم التجاري in Arabic
    - "legal_type": Legal Type (e.g., "Limited Liability Company(LLC)", "Partnership", "Joint Venture")
    - "duns_number": DUNS Number/D-U-N-S
    - "activity_1" to "activity_3": Business activities listed (up to 3)
    - "phone": Phone No/تليفون
    - "fax": Fax No/فاكس
    - "mobile": Mobile No/هاتف متحرك
    - "po_box": P.O. Box/صندوق بريد
    - "license_address": License Address/عنوان الرخصة
    - "parcel_id": Parcel ID/رقم القطعة
    - "commerce_address": Commerce Address/عنوان السجل التجاري
    - "nominated_capital": Nominated Capital/رأس المال الاسمي
    - "paid_capital": Paid Capital/رأس المال المدفوع
    - "currency": Currency/العملة (e.g., "UAE Dirhams", "دولار أمريكي")
    - "number_of_shares": No. of Shares/عدد الأسهم
    - "payment_voucher_number": P.V.Nr./رقم إذن الدفع
    - "payment_amount": Total amount paid/مبلغ الدفع
    - "payment_mode": Payment Mode/كيفية الدفع

    English Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(MULTI_OWNER_ENGLISH_FIELDS, indent=2)}

    Arabic Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(MULTI_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

    Document Text (first 25,000 characters):
    {raw_text[:25000]}

    CRITICAL: MANAGERS EXTRACTION
    Extract ALL managers/officers/board members listed in the License Members or Board section.
    For EACH manager, extract these exact fields:
    - person_number: Unique identifier/Person No./رقم الشخص (required)
    - name_english: Manager name in English (required)
    - name_arabic: Manager name in Arabic/الاسم بالعربية (required)
    - nationality_english: Nationality in English (required)
    - nationality_arabic: Nationality in Arabic/الجنسية (required)
    - role: Position/role (e.g., "Manager", "Director", "Managing Director", "Board Member", "Authorized Signatory")

    Example managers structure:
    "managers": [
    {{
        "person_number": "468949",
        "name_english": "AZAT DAGDANOV",
        "name_arabic": "ازاد دفدانوف",
        "nationality_english": "Turkmenistan",
        "nationality_arabic": "تركمنستان",
        "role": "Manager"
    }},
    {{
        "person_number": "757112",
        "name_english": "JEYHUN BABAYEV",
        "name_arabic": "جيهون بابايف",
        "nationality_english": "Turkmenistan",
        "nationality_arabic": "تركمنستان",
        "role": "Manager"
    }}
    ]

    CRITICAL: PARTNERS/SHAREHOLDERS EXTRACTION
    Extract ALL partners/shareholders/members listed in the License Members or Shareholders section.
    For EACH partner, extract these exact fields:
    - person_number: Unique identifier/Person No./رقم الشخص (required)
    - name_english: Partner name in English (required)
    - name_arabic: Partner name in Arabic/الاسم بالعربية (required)
    - nationality_english: Nationality in English (required)
    - nationality_arabic: Nationality in Arabic/الجنسية (required)
    - share_percentage: Ownership percentage with % symbol (e.g., "51.00%", "25.00%", "1.00%")

    IMPORTANT: 
    - Do NOT include managers in the partners list if they only have manager role
    - Include partners who are also managers ONLY if they have explicit shareholding percentage
    - Sum of all partner percentages should equal 100%

    Example partners structure:
    "partners": [
    {{
        "person_number": "525795",
        "name_english": "IBRAHIM AHMED MUHAMMAD SAQER AL HAMADI",
        "name_arabic": "ابراهيم احمد محمد صقر الحمادي",
        "nationality_english": "United Arab Emirates",
        "nationality_arabic": "الإمارات العربية المتحدة",
        "share_percentage": "51.00%"
    }},
    {{
        "person_number": "696127",
        "name_english": "HALMURAT HALMYRADOV",
        "name_arabic": "هلمورات حلميرادوف",
        "nationality_english": "Turkmenistan",
        "nationality_arabic": "تركمنستان",
        "share_percentage": "49.00%"
    }}
    ]

    EXTRACTION QUALITY CHECKLIST:
    1. ✓ All person_number fields are populated (unique identifiers)
    2. ✓ All names are in correct language (English in name_english, Arabic in name_arabic)
    3. ✓ All nationalities match the person (check consistency between English and Arabic)
    4. ✓ Share percentages sum to approximately 100% for partners
    5. ✓ All base fields ({EXPECTED_FIELD_COUNT}) are attempted even if empty
    6. ✓ Dates are in DD/MM/YYYY format
    7. ✓ No mixing of roles - managers separate from shareholders
    8. ✓ Arabic text preserved exactly as shown in document

    Complete JSON Response Structure:
    {{
    "english": {{
        "license_number": "789137",
        "main_license_number": "696658",
        "commercial_register_number": "1123411",
        "issue_date": "22/08/2019",
        "expiry_date": "23/08/2027",
        "company_name_english": "KAFTAN RESTAURANT & CAFE L.L.C",
        "company_name_arabic": "مطعم و كافيه قفطان ش.ذ.م.م",
        "trade_name_english": "KAFTAN RESTAURANT & CAFE",
        "trade_name_arabic": "قفطان",
        "legal_type": "Limited Liability Company(LLC)",
        "duns_number": "123456789",
        "activity_1": "Restaurant",
        "activity_2": "Coffee Shop",
        "activity_3": "Cafe",
        "phone": "971-4-3389688",
        "fax": "971-4-3389687",
        "mobile": "971-52-8875650",
        "po_box": "72820",
        "license_address": "Street Name - Building No - Dubai",
        "parcel_id": "332-4033",
        "commerce_address": "Street Name - Building No - Dubai",
        "nominated_capital": "500000",
        "paid_capital": "500000",
        "currency": "UAE Dirhams",
        "number_of_shares": "500",
        "payment_voucher_number": "16841527",
        "payment_mode": "eGovernment Online Payment",
        "payment_amount": "1090"
    }},
    "arabic": {{
        "رقم_الرخصة": "789137",
        "رقم_الرخصة_الأم": "696658",
        "رقم_السجل_التجاري": "1123411",
        "تاريخ_الإصدار": "22/08/2019",
        "تاريخ_الانتهاء": "23/08/2027",
        "اسم_الشركة_بالإنجليزية": "KAFTAN RESTAURANT & CAFE L.L.C",
        "اسم_الشركة_بالعربية": "مطعم و كافيه قفطان ش.ذ.م.م",
        "الاسم_التجاري_بالإنجليزية": "KAFTAN RESTAURANT & CAFE",
        "الاسم_التجاري_بالعربية": "قفطان",
        "الشكل_القانوني": "شركة ذات مسئولية محدودة",
        "رقم_دنز": "123456789",
        "النشاط_1": "مطعم",
        "النشاط_2": "مقهى",
        "النشاط_3": "كافيه",
        "هاتف": "971-4-3389688",
        "فاكس": "971-4-3389687",
        "هاتف_متحرك": "971-52-8875650",
        "صندوق_بريد": "72820",
        "عنوان_الرخصة": "اسم الشارع - رقم البناء - دبي",
        "رقم_القطعة": "332-4033",
        "عنوان_السجل_التجاري": "اسم الشارع - رقم البناء - دبي",
        "رأس_المال_الاسمي": "500000",
        "رأس_المال_المدفوع": "500000",
        "العملة": "درهم امارات",
        "عدد_الأسهم": "500",
        "رقم_إذن_الدفع": "16841527",
        "كيفية_الدفع": "دفع إلكتروني",
        "مبلغ_الدفع": "ألف وتسعون درهما"
    }},
    "managers": [
        {{
        "person_number": "468949",
        "name_english": "AZAT DAGDANOV",
        "name_arabic": "ازاد دفدانوف",
        "nationality_english": "Turkmenistan",
        "nationality_arabic": "تركمنستان",
        "role": "Manager"
        }}
    ],
    "partners": [
        {{
        "person_number": "525795",
        "name_english": "IBRAHIM AHMED MUHAMMAD SAQER AL HAMADI",
        "name_arabic": "ابراهيم احمد محمد صقر الحمادي",
        "nationality_english": "United Arab Emirates",
        "nationality_arabic": "الإمارات العربية المتحدة",
        "share_percentage": "51.00%"
        }}
    ]
    }}

    CRITICAL REQUIREMENTS:
    1. Return ONLY valid JSON - no explanations or markdown
    2. ALL {EXPECTED_FIELD_COUNT} base fields must be present (use empty string if not found)
    3. managers array must contain ALL managers/board members (can be empty array [])
    4. partners array must contain ALL partners/shareholders (can be empty array [])
    5. No duplicate entries in managers or partners
    6. Each person_number should be unique within their category
    7. Preserve exact formatting of names and nationalities as they appear in document
    8. Share percentages must include the % symbol
    """

        try:
            response = self.call_ai_api(prompt)

            if response and not response.startswith("API"):
                logger.debug(f"Raw AI response length: {len(response)} characters")

                try:
                    json_str = None

                    try:
                        data = json.loads(response)
                        logger.debug("Direct JSON parse successful")
                        json_str = response
                    except:
                        pass

                    if not json_str:
                        first_brace = response.find("{")
                        last_brace = response.rfind("}")
                        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                            json_str = response[first_brace : last_brace + 1]
                            logger.debug(f"Extracted JSON from position {first_brace} to {last_brace}")

                    if json_str:
                        json_str = re.sub(r",\s*}", "}", json_str)
                        json_str = re.sub(r",\s*]", "]", json_str)
                        json_str = re.sub(r"}\s*{", "},{", json_str)
                        json_str = json_str.strip()

                        logger.debug(f"Cleaned JSON length: {len(json_str)} characters")

                        data = json.loads(json_str)

                        english_data = data.get("english", {})
                        arabic_data = data.get("arabic", {})
                        managers = data.get("managers", [])
                        partners = data.get("partners", [])

                        if not isinstance(managers, list):
                            logger.warning(f"managers is not a list, converting: {type(managers)}")
                            managers = []
                        if not isinstance(partners, list):
                            logger.warning(f"partners is not a list, converting: {type(partners)}")
                            partners = []

                        logger.debug(
                            f"Parsed JSON - English: {len(english_data)}, Arabic: {len(arabic_data)}, "
                            f"Managers: {len(managers)}, Partners: {len(partners)}"
                        )

                        english_data = self.ensure_all_fields(
                            english_data, MULTI_OWNER_ENGLISH_FIELDS
                        )
                        arabic_data = self.ensure_all_fields(
                            arabic_data, MULTI_OWNER_ARABIC_FIELDS
                        )

                        english_data = self.post_process_data(english_data, raw_text)
                        arabic_data = self.post_process_data(arabic_data, raw_text)

                        logger.info(
                            f"[SUCCESS] Multiple Owner extraction complete: {len(partners)} partners, {len(managers)} managers"
                        )
                        self.extraction_metrics.ai_extracted = len([v for v in english_data.values() if v])
                        return english_data, arabic_data, managers, partners
                    else:
                        logger.error("No valid JSON found in response")

                except json.JSONDecodeError as e:
                    logger.error(f"JSON parsing error: {e}")
                except Exception as e:
                    logger.error(f"Extraction failed: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"API call failed: {e}", exc_info=True)

        logger.warning("Multiple Owner extraction failed, returning empty data")
        return (
            {field: "" for field in MULTI_OWNER_ENGLISH_FIELDS},
            {field: "" for field in MULTI_OWNER_ARABIC_FIELDS},
            [],
            [],
        )

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def extract_with_ai(self, raw_text: str, ownership_type: Optional[str] = None):
        """
        Main extraction method with conditional logic based on ownership type

        Args:
            raw_text: Extracted text from document
            ownership_type: "Single Owner" or "Multiple Owners" (if None, auto-detect)

        Returns:
            For Single Owner: (english_data, arabic_data, owner)
            For Multiple Owners: (english_data, arabic_data, managers, partners)
        """
        if ownership_type is None:
            ownership_type = self.ownership_type or self.detect_ownership_type(raw_text)

        logger.debug(f"Raw text length: {len(raw_text)}, Ownership type: {ownership_type}")

        if ownership_type == "Single Owner":
            logger.info("Using Single Owner extraction logic")
            return self.extract_single_owner_with_ai(raw_text)
        elif ownership_type in ["Multiple Owners", "Partnership", "Multiple Owner"]:
            logger.info("Using Multiple Owners extraction logic")
            return self.extract_multi_owner_with_ai(raw_text)
        else:
            logger.warning(f"Unknown ownership type '{ownership_type}', defaulting to Multiple Owners")
            return self.extract_multi_owner_with_ai(raw_text)

    def ensure_all_fields(self, data: Dict, required_fields: List[str]) -> Dict:
        """Ensure all required fields exist in the dictionary"""
        return {field: data.get(field, "") for field in required_fields}

    def validate_single_owner_extraction(
        self, english_data: Dict, arabic_data: Dict, owner: Dict
    ) -> Dict:
        """Validate Single Owner extraction with relaxed thresholds"""
        
        # ✅ CRITICAL: Only 6 fields are absolutely required
        CRITICAL_FIELDS = [
            "license_number", "company_name_english", "trade_name_english",
            "issue_date", "expiry_date", "legal_type",
        ]
        
        # ✅ IMPORTANT: These improve quality but aren't deal-breakers
        IMPORTANT_FIELDS = [
            "commercial_register_number", "activity_1", "mobile", "email"
        ]
        
        non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        
        validation = {
            "english_field_count": non_empty_english,
            "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
            "has_owner": bool(owner and owner.get("name_english")),
            "is_valid": False,
            "issues": [],
            "required_fields": SINGLE_OWNER_ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": [],
            "critical_missing": [],
            "important_missing": [],
            "critical_count": 0,
            "important_count": 0,
            "completeness_percentage": 0.0,
        }

        # Check critical fields
        for field in CRITICAL_FIELDS:
            if field not in english_data or not english_data[field]:
                validation["critical_missing"].append(field)
                validation["missing_fields"].append(field)
        
        # Check important fields
        for field in IMPORTANT_FIELDS:
            if field not in english_data or not english_data[field]:
                validation["important_missing"].append(field)

        validation["critical_count"] = len(CRITICAL_FIELDS) - len(validation["critical_missing"])
        validation["important_count"] = len(IMPORTANT_FIELDS) - len(validation["important_missing"])

        # ✅ RELAXED VALIDATION LOGIC
        if validation["critical_missing"]:
            validation["is_valid"] = False
            validation["issues"].append(
                f"Missing critical fields: {', '.join(validation['critical_missing'])}"
            )
            logger.error(f"Single Owner INVALID: Missing critical: {validation['critical_missing']}")
        
        elif non_empty_english < 15:  # ✅ REDUCED from 25 to 15
            validation["is_valid"] = False
            validation["issues"].append(
                f"Insufficient total fields: {non_empty_english}/39 (need 15+)"
            )
            logger.error(f"Single Owner INVALID: Only {non_empty_english}/39 fields")
        
        elif not validation["has_owner"]:
            validation["is_valid"] = False
            validation["issues"].append("No owner information extracted")
            logger.error("Single Owner INVALID: No owner info")
        
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            logger.info(
                f"Single Owner VALID: {non_empty_english}/39 fields, "
                f"Critical: {validation['critical_count']}/6 ✓"
            )

        validation["completeness_percentage"] = round((non_empty_english / 39) * 100, 1)
        return validation

    # def validate_single_owner_extraction(
    #     self, english_data: Dict, arabic_data: Dict, owner: Dict
    # ) -> Dict:
    #     """Validate Single Owner extraction completeness with importance-based thresholds"""
        
    #     CRITICAL_FIELDS = [
    #         "license_number", "company_name_english", "trade_name_english",
    #         "issue_date", "expiry_date", "legal_type",
    #     ]
        
    #     IMPORTANT_FIELDS = [
    #         "commercial_register_number", "company_name_arabic", "trade_name_arabic",
    #         "activity_1", "license_address", "nominated_capital", "paid_capital", "currency",
    #     ]
        
    #     non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        
    #     validation = {
    #         "english_field_count": non_empty_english,
    #         "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
    #         "has_owner": bool(owner and owner.get("name_english")),
    #         "is_valid": False,
    #         "issues": [],
    #         "required_fields": SINGLE_OWNER_ENGLISH_FIELDS,
    #         "present_fields": [k for k, v in english_data.items() if v],
    #         "missing_fields": [],
    #         "critical_missing": [],
    #         "important_missing": [],
    #         "critical_count": 0,
    #         "important_count": 0,
    #         "completeness_percentage": 0.0,
    #     }

    #     # Categorize missing fields
    #     for field in CRITICAL_FIELDS:
    #         if field not in english_data or not english_data[field]:
    #             validation["critical_missing"].append(field)
    #             validation["missing_fields"].append(field)
        
    #     for field in IMPORTANT_FIELDS:
    #         if field not in english_data or not english_data[field]:
    #             validation["important_missing"].append(field)

    #     validation["critical_count"] = len(CRITICAL_FIELDS) - len(validation["critical_missing"])
    #     validation["important_count"] = len(IMPORTANT_FIELDS) - len(validation["important_missing"])

    #     # Validation logic
    #     if validation["critical_missing"]:
    #         validation["is_valid"] = False
    #         validation["issues"].append(
    #             f"Missing critical fields: {', '.join(validation['critical_missing'])}"
    #         )
    #         logger.error(f"Single Owner INVALID: Missing critical: {validation['critical_missing']}")
    #     elif validation["important_count"] < 5:
    #         validation["is_valid"] = False
    #         validation["issues"].append(
    #             f"Insufficient important fields: {validation['important_count']}/8 (need 5+)"
    #         )
    #         logger.error(f"Single Owner INVALID: Only {validation['important_count']}/8 important fields")
    #     elif non_empty_english < 25:
    #         validation["is_valid"] = False
    #         validation["issues"].append(
    #             f"Insufficient total fields: {non_empty_english}/39 (need 25+)"
    #         )
    #         logger.error(f"Single Owner INVALID: Only {non_empty_english}/39 fields")
    #     elif not validation["has_owner"]:
    #         validation["is_valid"] = False
    #         validation["issues"].append("No owner information extracted")
    #         logger.error("Single Owner INVALID: No owner info")
    #     else:
    #         validation["is_valid"] = True
    #         validation["issues"] = []
    #         logger.info(
    #             f"Single Owner VALID: {non_empty_english}/39 fields, "
    #             f"Critical: {validation['critical_count']}/6, Owner: ✓"
    #         )

    #     validation["completeness_percentage"] = round((non_empty_english / 39) * 100, 1)
    #     return validation

    def validate_multi_owner_extraction(
        self,
        english_data: Dict,
        arabic_data: Dict,
        managers: List[Dict],
        partners: List[Dict],
    ) -> Dict:
        """Validate Multiple Owner extraction completeness"""
        
        non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        
        validation = {
            "english_field_count": non_empty_english,
            "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
            "managers_count": len(managers),
            "partners_count": len(partners),
            "is_valid": False,
            "issues": [],
            "required_fields": MULTI_OWNER_ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": [],
        }

        logger.info(
            f"Trade License: {non_empty_english}/33 fields, {len(partners)} partners, {len(managers)} managers"
        )

        critical_fields = [
            "license_number", "company_name_english", "trade_name_english",
            "issue_date", "expiry_date", "legal_type",
        ]

        for f in critical_fields:
            if f not in english_data or not english_data[f]:
                validation["issues"].append(f"Missing critical field: {f}")
                validation["missing_fields"].append(f)

        has_members = len(partners) > 0 or len(managers) > 0

        if validation["missing_fields"]:
            validation["is_valid"] = False
            logger.error(f"Multiple Owner INVALID: Missing critical: {validation['missing_fields']}")
        elif non_empty_english < 20:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/33 (need 20+)")
            logger.error(f"Multiple Owner INVALID: Only {non_empty_english}/33 fields")
        elif not has_members:
            validation["is_valid"] = False
            validation["issues"].append("No partners or managers extracted")
            logger.error("Multiple Owner INVALID: No partners/managers found")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            logger.info(f"Multiple Owner VALID: {non_empty_english}/33 fields, {len(partners)} partners ✓")

        return validation

    def validate_extraction(self, *args, ownership_type: Optional[str] = None) -> Dict:
        """
        Validate extraction based on ownership type

        Args:
            For Single Owner: english_data, arabic_data, owner
            For Multiple Owners: english_data, arabic_data, managers, partners
            ownership_type: "Single Owner" or "Multiple Owners"

        Returns:
            Validation dictionary with is_valid, issues, and field counts
        """
        ownership_type = ownership_type or self.ownership_type

        if ownership_type == "Single Owner" and len(args) == 3:
            return self.validate_single_owner_extraction(*args)
        elif len(args) == 4:
            return self.validate_multi_owner_extraction(*args)
        else:
            raise ValueError(
                f"Invalid arguments for validation with ownership_type={ownership_type}"
            )

    def get_extraction_report(self, *args, ownership_type: Optional[str] = None) -> Dict:
        """Generate a comprehensive extraction report with metrics and validation"""
        validation = self.validate_extraction(*args, ownership_type=ownership_type)
        
        report = {
            "extraction_metrics": asdict(self.extraction_metrics),
            "validation": validation,
            "quality_score": self._calculate_quality_score(validation),
            "recommendations": self._generate_recommendations(validation),
            "timestamp": datetime.now().isoformat(),
        }
        
        return report

    def _calculate_quality_score(self, validation: Dict) -> float:
        """Calculate quality score (0-100) based on validation"""
        english_count = validation.get("english_field_count", 0)
        required_count = len(validation.get("required_fields", []))
        completeness = (english_count / required_count) * 100 if required_count > 0 else 0
        
        if validation.get("is_valid"):
            return min(100, completeness)
        else:
            return max(0, completeness - 20)

    def _generate_recommendations(self, validation: Dict) -> List[str]:
        """Generate recommendations based on validation results"""
        recommendations = []
        
        if not validation.get("is_valid"):
            if validation.get("missing_fields"):
                recommendations.append(
                    f"Verify missing critical fields: {', '.join(validation['missing_fields'])}"
                )
            if validation.get("critical_missing"):
                recommendations.append(
                    f"Critical information missing: {', '.join(validation['critical_missing'])}"
                )
            if validation.get("issues"):
                recommendations.extend([f"Issue: {issue}" for issue in validation["issues"]])
        else:
            if validation.get("important_missing"):
                recommendations.append(
                    f"Optional: {len(validation['important_missing'])} important fields missing"
                )
            recommendations.append("Extraction is valid and ready for use")
        
        return recommendations

    def process_trade_license(self, pdf_bytes: bytes, ownership_type: Optional[str] = None) -> Dict:
        """
        Complete pipeline: Extract PDF → Detect Type → Extract Fields → Validate → Report

        Args:
            pdf_bytes: PDF file content as bytes
            ownership_type: Optional override for ownership type detection

        Returns:
            Complete processing result with extracted data and validation
        """
        self.start_time = time.time()
        
        logger.info(f"Processing Trade License Document - Size: {len(pdf_bytes)} bytes")
        
        # Step 1: Extract text from PDF
        logger.info("Step 1: Extracting text from PDF...")
        raw_text = self.extract_text_from_pdf(pdf_bytes)
        
        if raw_text.startswith("[PDF EXTRACTION ERROR]"):
            logger.error(f"PDF extraction failed: {raw_text}")
            return {
                "success": False,
                "error": raw_text,
                "timestamp": datetime.now().isoformat(),
            }
        
        logger.info(f"Successfully extracted {len(raw_text)} characters from PDF")
        
        # Step 2: Detect ownership type
        logger.info("Step 2: Detecting ownership type...")
        detected_type = ownership_type or self.detect_ownership_type(raw_text)
        logger.info(f"Detected ownership type: {detected_type}")
        
        # Step 3: Extract fields using AI + Regex
        logger.info("Step 3: Extracting fields with AI and regex fallback...")
        extraction_result = self.extract_with_ai(raw_text, detected_type)
        
        # Step 4: Validate extraction
        logger.info("Step 4: Validating extraction...")
        validation = self.validate_extraction(*extraction_result, ownership_type=detected_type)
        
        # Step 5: Generate report
        logger.info("Step 5: Generating quality report...")
        report = self.get_extraction_report(*extraction_result, ownership_type=detected_type)
        
        # Calculate processing time
        self.extraction_metrics.processing_time = time.time() - self.start_time
        
        # Step 6: Format result
        if detected_type == "Single Owner":
            english_data, arabic_data, owner = extraction_result
            result = {
                "success": validation["is_valid"],
                "ownership_type": detected_type,
                "english_data": english_data,
                "arabic_data": arabic_data,
                "owner": owner,
                "validation": validation,
                "quality_report": report,
                "timestamp": datetime.now().isoformat(),
            }
        else:
            english_data, arabic_data, managers, partners = extraction_result
            result = {
                "success": validation["is_valid"],
                "ownership_type": detected_type,
                "english_data": english_data,
                "arabic_data": arabic_data,
                "managers": managers,
                "partners": partners,
                "validation": validation,
                "quality_report": report,
                "timestamp": datetime.now().isoformat(),
            }
        
        logger.info(
            f"Processing complete - Valid: {result['success']}, "
            f"Quality: {report['quality_score']:.1f}%, Time: {self.extraction_metrics.processing_time:.2f}s"
        )
        
        return result


# ===========================
# UTILITY FUNCTIONS
# ===========================

def process_pdf_file(file_path: str, api_key: Optional[str] = None) -> Dict:
    """Process a PDF file and return extracted trade license data"""
    logger.info(f"Processing PDF file: {file_path}")
    
    try:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        
        extractor = TradeLicenseExtractor(api_key=api_key)
        result = extractor.process_trade_license(pdf_bytes)
        
        return result
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return {"success": False, "error": f"File not found: {file_path}"}
    except Exception as e:
        logger.error(f"Error processing file: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def export_results_to_json(result: Dict, output_path: str) -> bool:
    """Export extraction results to JSON file"""
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"Results exported to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error exporting results: {e}")
        return False
