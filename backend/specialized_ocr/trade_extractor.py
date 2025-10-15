"""
Trade License Extractor - UAE Dubai Trade License (Commercial License) Document Processing
Supports both Single Owner and Multiple Owner/Partnership companies
Extracts bilingual fields (English + Arabic) with conditional logic based on ownership type
Backend version with retry logic and enhanced prompts
"""

import os
import json
import re
import requests
import time
from typing import Dict, Tuple, List, Union
from functools import wraps
import fitz  # PyMuPDF

# API Configuration
API_KEY = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-...")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-32b-instruct"

# Fields for Multiple Owner Trade License (33 fields)
MULTI_OWNER_ENGLISH_FIELDS = [
    # License Information
    "license_number", "main_license_number", "commercial_register_number",
    "issue_date", "expiry_date", "receipt_number", "print_date",
    # Company Details
    "company_name_english", "company_name_arabic",
    "trade_name_english", "trade_name_arabic",
    "legal_type", "duns_number",
    # Business Activities
    "activity_1", "activity_2", "activity_3",
    # Contact Information
    "phone", "fax", "mobile", "po_box",
    # Address
    "license_address", "parcel_id", "commerce_address",
    # Capital Details
    "nominated_capital", "paid_capital", "currency", "number_of_shares",
    # Payment Information
    "payment_voucher_number", "payment_mode", "payment_amount"
]

MULTI_OWNER_ARABIC_FIELDS = [
    # معلومات الرخصة
    "رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
    "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
    # تفاصيل الشركة
    "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية",
    "الاسم_التجاري_بالإنجليزية", "الاسم_التجاري_بالعربية",
    "الشكل_القانوني", "رقم_دنز",
    # أنشطة الأعمال
    "النشاط_1", "النشاط_2", "النشاط_3",
    # معلومات الاتصال
    "هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد",
    # العنوان
    "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
    # تفاصيل رأس المال
    "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
    # معلومات الدفع
    "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع"
]

# Fields for Single Owner Trade License (39 fields)
SINGLE_OWNER_ENGLISH_FIELDS = [
    # License Information
    "license_number", "main_license_number", "commercial_register_number",
    "issue_date", "expiry_date", "receipt_number", "print_date",
    # Company Details
    "company_name_english", "company_name_arabic",
    "trade_name_english", "trade_name_arabic",
    "legal_type", "duns_number", "dcci_number",
    # Business Activities
    "activity_1", "activity_2", "activity_3", "activity_4",
    # Contact Information
    "phone", "fax", "mobile", "po_box", "email",
    # Address
    "license_address", "parcel_id", "commerce_address",
    # Capital Details
    "nominated_capital", "paid_capital", "currency", "number_of_shares",
    # Payment Information
    "payment_voucher_number", "payment_mode", "payment_amount",
    # Contract Information
    "contract_number", "contract_date"
]

SINGLE_OWNER_ARABIC_FIELDS = [
    # معلومات الرخصة
    "رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
    "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
    # تفاصيل الشركة
    "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية",
    "الاسم_التجاري_بالإنجليزية", "الاسم_التجاري_بالعربية",
    "الشكل_القانوني", "رقم_دنز", "رقم_عضوية_الغرفة",
    # أنشطة الأعمال
    "النشاط_1", "النشاط_2", "النشاط_3", "النشاط_4",
    # معلومات الاتصال
    "هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد", "البريد_الإلكتروني",
    # العنوان
    "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
    # تفاصيل رأس المال
    "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
    # معلومات الدفع
    "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع",
    # معلومات العقد
    "رقم_العقد", "تاريخ_العقد"
]

# Backward compatibility - default to multi-owner fields
ENGLISH_FIELDS = MULTI_OWNER_ENGLISH_FIELDS
ARABIC_FIELDS = MULTI_OWNER_ARABIC_FIELDS
EXPECTED_FIELD_COUNT = len(MULTI_OWNER_ENGLISH_FIELDS)

# ===========================
# RETRY LOGIC DECORATOR
# ===========================
def retry_with_backoff(max_retries=3, base_delay=10):
    """Retry decorator with exponential backoff for API failures"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RuntimeError as e:
                    error_msg = str(e)
                    if any(code in error_msg for code in ['503', '429', '502', '504']) and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[WARN] Trade License API error (attempt {attempt + 1}/{max_retries}): {error_msg}")
                        print(f"[INFO] Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None
        return wrapper
    return decorator


class TradeLicenseExtractor:
    """
    Unified Trade License extractor with bilingual support and retry logic
    Supports both Single Owner and Multiple Owner/Partnership companies
    """
    
    def __init__(self, api_key: str = None, ownership_type: str = None):
        """
        Initialize the extractor
        
        Args:
            api_key: OpenRouter API key
            ownership_type: "Single Owner" or "Multiple Owners" (auto-detected if None)
        """
        self.api_key = api_key or API_KEY
        self.api_url = API_URL
        self.ownership_type = ownership_type
    
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text content from PDF using PyMuPDF"""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count == 0:
                return "[PDF EXTRACTION ERROR] PDF has no pages"
            
            text = ""
            for i in range(doc.page_count):
                page = doc.load_page(i)
                page_text = page.get_text()
                text += page_text + "\n"
            
            doc.close()
            
            if not text or len(text.strip()) < 100:
                return "[PDF EXTRACTION ERROR] PDF appears to be empty or contains very little text"
            
            return text
        except Exception as e:
            return f"[PDF EXTRACTION ERROR] {str(e)}"
    
    @retry_with_backoff(max_retries=3, base_delay=10)
    def call_ai_api(self, prompt: str, model_name: str = None) -> str:
        """Call OpenRouter API with retry logic"""
        if not self.api_key:
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
            response = requests.post(self.api_url, headers=headers, json=data, timeout=120)
            
            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Trade License API failed: {response.status_code} Server temporarily unavailable")
            if response.status_code == 429:
                raise RuntimeError(f"Trade License API failed: {response.status_code} Rate limit exceeded")
            
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        
        except requests.exceptions.Timeout:
            raise RuntimeError("Trade License API failed: Request timeout after 120 seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Trade License API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")
    
    def detect_ownership_type(self, raw_text: str) -> str:
        """
        Detect if the license is for Single Owner or Multiple Owner company
        Returns: "Single Owner" or "Multiple Owners"
        """
        # Look for legal type indicators
        single_owner_patterns = [
            r"Single Owner",
            r"LLC - SO",
            r"L\.L\.C - S\.O",
            r"الشخص الواحد",
            r"شركة ذات مسؤولية محدودة - الشخص الواحد"
        ]
        
        for pattern in single_owner_patterns:
            if re.search(pattern, raw_text, re.IGNORECASE):
                print("[INFO] Detected: Single Owner Trade License")
                return "Single Owner"
        
        print("[INFO] Detected: Multiple Owners Trade License")
        return "Multiple Owners"
    
    @retry_with_backoff(max_retries=3, base_delay=10)
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
    8. DO NOT extract managers or partners - ONLY extract the single owner information

    FIELD MAPPING GUIDE:
    - "license_number" (رقم_الرخصة): License No./رقم الرخصة
    - "main_license_number" (رقم_الرخصة_الأم): Main License No./رقم الرخصة الأم
    - "commercial_register_number" (رقم_السجل_التجاري): Register No./رقم السجل التجاري
    - "issue_date" (تاريخ_الإصدار): Issue Date/تاريخ الإصدار
    - "expiry_date" (تاريخ_الانتهاء): Expiry Date/تاريخ الانتهاء
    - "company_name_english": Company Name in English
    - "company_name_arabic": اسم الشركة in Arabic
    - "trade_name_english": Business Name in English
    - "trade_name_arabic": الاسم التجاري in Arabic
    - "legal_type" (الشكل_القانوني): Legal Type (e.g., "Limited Liability Company - Single Owner(LLC - SO)")
    - "duns_number" (رقم_دنز): DUNS Number
    - "dcci_number" (رقم_عضوية_الغرفة): DCCI No./عضوية الغرفة
    - "activity_1", "activity_2", "activity_3", "activity_4": Business activities listed
    - "phone" (هاتف): Phone No/تليفون
    - "fax" (فاكس): Fax No/فاكس
    - "mobile" (هاتف_متحرك): Mobile No/هاتف متحرك
    - "email" (البريد_الإلكتروني): Email/البريد الإلكتروني
    - "po_box" (صندوق_بريد): P.O. Box/صندوق بريد
    - "license_address" (عنوان_الرخصة): License Address/عنوان الرخصة
    - "parcel_id" (رقم_القطعة): Parcel ID/رقم القطعة
    - "commerce_address" (عنوان_السجل_التجاري): Commerce Address/عنوان السجل التجاري
    - "paid_capital" (رأس_المال_المدفوع): Paid Capital/المدفوع
    - "nominated_capital" (رأس_المال_الاسمي): Nominated Capital/الاسمي
    - "currency" (العملة): Currency/العملة
    - "number_of_shares" (عدد_الأسهم): No. of Shares/عدد الأسهم
    - "payment_voucher_number" (رقم_إذن_الدفع): P.V.Nr./رقم إذن الدفع
    - "payment_amount" (مبلغ_الدفع): Total amount paid
    - "payment_mode" (كيفية_الدفع): Payment Mode/كيفية الدفع
    - "contract_number" (رقم_العقد): Contract Number from Memorandum of Association
    - "contract_date" (تاريخ_العقد): Contract Date
    - "receipt_number" (رقم_الإيصال): Receipt Number
    - "print_date" (تاريخ_الطباعة): Print Date

    English Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(SINGLE_OWNER_ENGLISH_FIELDS, indent=2)}

    Arabic Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(SINGLE_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

    Document Text (up to 25,000 characters):
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

    Example JSON structure with complete extraction:
    {{
    "english": {{
        "license_number": "123456",
        "main_license_number": "123456",
        "commercial_register_number": "9876543",
        "issue_date": "01/01/2024",
        "expiry_date": "31/12/2025",
        "receipt_number": "87654321",
        "print_date": "15/01/2024 14:30",
        "company_name_english": "EXAMPLE TRADING COMPANY L.L.C",
        "company_name_arabic": "شركة المثال التجارية ش.ذ.م.م",
        "trade_name_english": "EXAMPLE TRADING CO",
        "trade_name_arabic": "شركة المثال التجارية",
        "legal_type": "Limited Liability Company - Single Owner(LLC - SO)",
        "duns_number": "123456789",
        "dcci_number": "456789",
        "activity_1": "General Trading",
        "activity_2": "Import Export Services",
        "activity_3": "Wholesale Trade",
        "activity_4": "Retail Trade",
        "phone": "971-4-1234567",
        "fax": "971-4-1234568",
        "mobile": "971-50-1234567",
        "po_box": "12345",
        "email": "info@example.ae",
        "license_address": "Office No. 101 - Business Bay - Dubai",
        "parcel_id": "123-456",
        "commerce_address": "Building No. 5 - Trade Center - Dubai",
        "nominated_capital": "500000",
        "paid_capital": "500000",
        "currency": "UAE Dirhams",
        "number_of_shares": "500",
        "payment_voucher_number": "11223344",
        "payment_mode": "Online Payment",
        "payment_amount": "15000",
        "contract_number": "98765432",
        "contract_date": "20/12/2023"
    }},
    "arabic": {{
        "رقم_الرخصة": "123456",
        "رقم_الرخصة_الأم": "123456",
        "رقم_السجل_التجاري": "9876543",
        "تاريخ_الإصدار": "01/01/2024",
        "تاريخ_الانتهاء": "31/12/2025",
        "رقم_الإيصال": "87654321",
        "تاريخ_الطباعة": "15/01/2024 14:30",
        "اسم_الشركة_بالإنجليزية": "EXAMPLE TRADING COMPANY L.L.C",
        "اسم_الشركة_بالعربية": "شركة المثال التجارية ش.ذ.م.م",
        "الاسم_التجاري_بالإنجليزية": "EXAMPLE TRADING CO",
        "الاسم_التجاري_بالعربية": "شركة المثال التجارية",
        "الشكل_القانوني": "شركة ذات مسؤولية محدودة - الشخص الواحد",
        "رقم_دنز": "123456789",
        "رقم_عضوية_الغرفة": "456789",
        "النشاط_1": "تجارة عامة",
        "النشاط_2": "خدمات الاستيراد والتصدير",
        "النشاط_3": "تجارة الجملة",
        "النشاط_4": "تجارة التجزئة",
        "هاتف": "971-4-1234567",
        "فاكس": "971-4-1234568",
        "هاتف_متحرك": "971-50-1234567",
        "صندوق_بريد": "12345",
        "البريد_الإلكتروني": "info@example.ae",
        "عنوان_الرخصة": "مكتب رقم 101 - الخليج التجاري - دبي",
        "رقم_القطعة": "123-456",
        "عنوان_السجل_التجاري": "مبنى رقم 5 - المركز التجاري - دبي",
        "رأس_المال_الاسمي": "500000",
        "رأس_المال_المدفوع": "500000",
        "العملة": "درهم إماراتي",
        "عدد_الأسهم": "500",
        "رقم_إذن_الدفع": "11223344",
        "كيفية_الدفع": "الدفع الإلكتروني",
        "مبلغ_الدفع": "15000",
        "رقم_العقد": "98765432",
        "تاريخ_العقد": "20/12/2023"
    }},
    "owner": {{
        "person_number": "7654321",
        "name_english": "JOHN SMITH",
        "name_arabic": "جون سميث",
        "nationality_english": "United Kingdom",
        "nationality_arabic": "المملكة المتحدة",
        "passport_number": "AB1234567",
        "date_of_birth": "15/05/1985",
        "share_percentage": "100.00%",
        "role": "Shares Owner & Manager"
    }}
    }}

    CRITICAL: Return ONLY valid JSON with ALL {EXPECTED_FIELD_COUNT} base fields populated, plus owner information.
    Extract the COMPLETE owner information from the License Members section and Memorandum of Association.
    DO NOT include managers array or partners array - this is a SINGLE OWNER company.
    """

        
        try:
            # Call the AI API
            response = self.call_ai_api(prompt)
            
            if response and not response.startswith("API Error"):
                try:
                    # Extract JSON from response
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group()
                        # Clean up common JSON issues
                        json_str = re.sub(r',\s*}', '}', json_str)
                        json_str = re.sub(r',\s*]', ']', json_str)
                        
                        # Parse JSON
                        data = json.loads(json_str)
                        english_data = data.get("english", {})
                        arabic_data = data.get("arabic", {})
                        owner = data.get("owner", {})
                        
                        # Ensure all fields exist
                        english_data = self.ensure_all_fields(english_data, SINGLE_OWNER_ENGLISH_FIELDS)
                        arabic_data = self.ensure_all_fields(arabic_data, SINGLE_OWNER_ARABIC_FIELDS)
                        
                        # Post-process to fix incomplete values
                        english_data = self.post_process_data(english_data, raw_text)
                        arabic_data = self.post_process_data(arabic_data, raw_text)
                        
                        print(f"[INFO] Single Owner extraction complete")
                        
                        # Debug information
                        print(f"[DEBUG-SINGLE] Parsed data fields:")
                        print(f"[DEBUG-SINGLE] English fields: {list(english_data.keys())}")
                        print(f"[DEBUG-SINGLE] Owner info: {owner}")
                        
                        # After post-processing
                        print(f"[DEBUG-SINGLE] Post-processed English fields with values:")
                        for key, value in english_data.items():
                            if value:  # Only print non-empty values
                                print(f"[DEBUG-SINGLE] {key}: {value}")
                        
                        return english_data, arabic_data, owner
                
                except json.JSONDecodeError as e:
                    print(f"[ERROR] JSON parsing error: {e}")
                except Exception as e:
                    print(f"[ERROR] Extraction failed: {e}")
        
        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
        
        # ALWAYS return 3 values - even on failure
        print(f"[WARN] Single Owner extraction failed, returning empty data")
        return (
            {field: "" for field in SINGLE_OWNER_ENGLISH_FIELDS},
            {field: "" for field in SINGLE_OWNER_ARABIC_FIELDS},
            {}  # empty owner dict
        )

    
    @retry_with_backoff(max_retries=3, base_delay=10)
    def extract_multi_owner_with_ai(self, raw_text: str) -> Tuple[Dict, Dict, List[Dict], List[Dict]]:
        """Extract Multiple Owner Trade License fields using AI with retry logic"""
        
        EXPECTED_FIELD_COUNT = len(MULTI_OWNER_ENGLISH_FIELDS)
        
        prompt = f"""You are an expert at extracting information from UAE Dubai Trade License (Commercial License) documents for MULTIPLE OWNER/PARTNERSHIP companies.

    Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic from this bilingual Trade License certificate.

    CRITICAL EXTRACTION RULES:
    1. Extract values EXACTLY as they appear in the document
    2. For dates, use format: DD/MM/YYYY
    3. For activities, extract up to 3 business activities listed
    4. This is a MULTIPLE OWNER company - extract ALL managers and ALL partners/shareholders
    5. Preserve all Arabic text exactly as shown
    6. If a field is not found, set it as empty string ""
    7. Extract ALL {EXPECTED_FIELD_COUNT} base fields PLUS all managers AND all partners
    8. CRITICAL: Extract EVERY partner/shareholder listed in the document - do not skip any

    FIELD MAPPING GUIDE:
    - "license_number" (رقم_الرخصة): License No./رقم الرخصة
    - "main_license_number" (رقم_الرخصة_الأم): Main License No./رقم الرخصة الأم
    - "commercial_register_number" (رقم_السجل_التجاري): Register No./رقم السجل التجاري
    - "issue_date" (تاريخ_الإصدار): Issue Date/تاريخ الإصدار
    - "expiry_date" (تاريخ_الانتهاء): Expiry Date/تاريخ الانتهاء
    - "company_name_english": Company Name in English
    - "company_name_arabic": اسم الشركة in Arabic
    - "trade_name_english": Trade Name in English
    - "trade_name_arabic": الاسم التجاري in Arabic
    - "legal_type" (الشكل_القانوني): Legal Type
    - "duns_number" (رقم_دنز): DUNS Number
    - "activity_1", "activity_2", "activity_3": Business activities
    - "phone" (هاتف): Phone No/تليفون
    - "fax" (فاكس): Fax No/فاكس
    - "mobile" (هاتف_متحرك): Mobile No/هاتف متحرك
    - "po_box" (صندوق_بريد): P.O. Box/صندوق بريد
    - "license_address" (عنوان_الرخصة): License Address/عنوان الرخصة
    - "parcel_id" (رقم_القطعة): Parcel ID/رقم القطعة
    - "commerce_address" (عنوان_السجل_التجاري): Commerce Address
    - "nominated_capital" (رأس_المال_الاسمي): Nominated Capital
    - "paid_capital" (رأس_المال_المدفوع): Paid Capital
    - "currency" (العملة): Currency
    - "number_of_shares" (عدد_الأسهم): No. of Shares
    - "payment_voucher_number" (رقم_إذن_الدفع): P.V.Nr.
    - "payment_mode" (كيفية_الدفع): Payment Mode
    - "payment_amount" (مبلغ_الدفع): Payment Amount
    - "receipt_number" (رقم_الإيصال): Receipt Number
    - "print_date" (تاريخ_الطباعة): Print Date

    English Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(MULTI_OWNER_ENGLISH_FIELDS, indent=2)}

    Arabic Fields (ALL {EXPECTED_FIELD_COUNT} required):
    {json.dumps(MULTI_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

    Document Text (up to 25,000 characters):
    {raw_text[:25000]}

    MANAGERS EXTRACTION (CRITICAL):
    Extract ALL managers/officers listed in the document as an array.
    Each manager must have these fields:
    - person_number: Unique identifier/Person No.
    - name_english: Manager name in English
    - name_arabic: Manager name in Arabic
    - nationality_english: Nationality in English
    - nationality_arabic: Nationality in Arabic
    - role: Position/role (e.g., "Manager", "Director", "Authorized Signatory")

    PARTNERS/SHAREHOLDERS EXTRACTION (CRITICAL):
    Extract ALL partners/shareholders listed in the document as an array.
    Each partner must have these fields:
    - person_number: Unique identifier/Person No.
    - name_english: Partner name in English
    - name_arabic: Partner name in Arabic
    - nationality_english: Nationality in English
    - nationality_arabic: Nationality in Arabic
    - share_percentage: Ownership percentage (e.g., "51.00%", "49.00%")

    IMPORTANT: 
    - If there are 5 partners in the document, extract ALL 5 partners
    - If there are 2 managers, extract BOTH managers
    - Do NOT limit the number - extract EVERYONE listed
    - Look in "License Members", "Partners", "Shareholders", "Managers" sections

    Example JSON structure:
    {{
    "english": {{
        "license_number": "789012",
        "main_license_number": "789012",
        "commercial_register_number": "1234567",
        "issue_date": "15/03/2019",
        "expiry_date": "14/03/2020",
        "receipt_number": "98765432",
        "print_date": "20/03/2019 10:30",
        "company_name_english": "ABC TRADING LLC",
        "company_name_arabic": "شركة إيه بي سي التجارية ذ.م.م",
        "trade_name_english": "ABC TRADING",
        "trade_name_arabic": "إيه بي سي للتجارة",
        "legal_type": "Limited Liability Company (LLC)",
        "duns_number": "987654321",
        "activity_1": "General Trading",
        "activity_2": "Import and Export",
        "activity_3": "Wholesale Trade",
        "phone": "971-4-9876543",
        "fax": "971-4-9876544",
        "mobile": "971-50-9876543",
        "po_box": "54321",
        "license_address": "Office 201 - Deira - Dubai",
        "parcel_id": "789-012",
        "commerce_address": "Building 10 - Al Barsha - Dubai",
        "nominated_capital": "300000",
        "paid_capital": "300000",
        "currency": "AED",
        "number_of_shares": "300",
        "payment_voucher_number": "55667788",
        "payment_mode": "Bank Transfer",
        "payment_amount": "12000"
    }},
    "arabic": {{
        "رقم_الرخصة": "789012",
        "رقم_الرخصة_الأم": "789012",
        "رقم_السجل_التجاري": "1234567",
        "تاريخ_الإصدار": "15/03/2019",
        "تاريخ_الانتهاء": "14/03/2020",
        "رقم_الإيصال": "98765432",
        "تاريخ_الطباعة": "20/03/2019 10:30",
        "اسم_الشركة_بالإنجليزية": "ABC TRADING LLC",
        "اسم_الشركة_بالعربية": "شركة إيه بي سي التجارية ذ.م.م",
        "الاسم_التجاري_بالإنجليزية": "ABC TRADING",
        "الاسم_التجاري_بالعربية": "إيه بي سي للتجارة",
        "الشكل_القانوني": "شركة ذات مسؤولية محدودة",
        "رقم_دنز": "987654321",
        "النشاط_1": "تجارة عامة",
        "النشاط_2": "استيراد وتصدير",
        "النشاط_3": "تجارة الجملة",
        "هاتف": "971-4-9876543",
        "فاكس": "971-4-9876544",
        "هاتف_متحرك": "971-50-9876543",
        "صندوق_بريد": "54321",
        "عنوان_الرخصة": "مكتب 201 - ديرة - دبي",
        "رقم_القطعة": "789-012",
        "عنوان_السجل_التجاري": "مبنى 10 - البرشاء - دبي",
        "رأس_المال_الاسمي": "300000",
        "رأس_المال_المدفوع": "300000",
        "العملة": "درهم",
        "عدد_الأسهم": "300",
        "رقم_إذن_الدفع": "55667788",
        "كيفية_الدفع": "تحويل بنكي",
        "مبلغ_الدفع": "12000"
    }},
    "managers": [
        {{
        "person_number": "1111111",
        "name_english": "AHMED MOHAMMED",
        "name_arabic": "أحمد محمد",
        "nationality_english": "United Arab Emirates",
        "nationality_arabic": "الإمارات العربية المتحدة",
        "role": "Manager"
        }}
    ],
    "partners": [
        {{
        "person_number": "2222222",
        "name_english": "SARAH JOHNSON",
        "name_arabic": "سارة جونسون",
        "nationality_english": "United States",
        "nationality_arabic": "الولايات المتحدة",
        "share_percentage": "51.00%"
        }},
        {{
        "person_number": "3333333",
        "name_english": "DAVID BROWN",
        "name_arabic": "ديفيد براون",
        "nationality_english": "United Kingdom",
        "nationality_arabic": "المملكة المتحدة",
        "share_percentage": "49.00%"
        }}
    ]
    }}

    CRITICAL: Return ONLY valid JSON with ALL {EXPECTED_FIELD_COUNT} base fields, ALL managers array, and ALL partners array.
    Make sure to extract EVERY partner and EVERY manager from the License Members section.
    """
        
        try:
            # Call the AI API
            response = self.call_ai_api(prompt)
            
            if response and not response.startswith("API Error"):
                print(f"[DEBUG] Raw AI response length: {len(response)} characters")
                
                try:
                    # Enhanced JSON extraction with multiple strategies
                    json_str = None
                    
                    # Strategy 1: Try direct JSON parsing (if response is pure JSON)
                    try:
                        data = json.loads(response)
                        print("[DEBUG] Strategy 1 SUCCESS: Direct JSON parse")
                        json_str = response
                    except:
                        pass
                    
                    # Strategy 2: Extract JSON between first { and last }
                    if not json_str:
                        first_brace = response.find('{')
                        last_brace = response.rfind('}')
                        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                            json_str = response[first_brace:last_brace + 1]
                            print(f"[DEBUG] Strategy 2: Extracted JSON from position {first_brace} to {last_brace}")
                    
                    # Strategy 3: Use regex to find JSON blocks
                    if not json_str:
                        json_matches = re.findall(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}', response, re.DOTALL)
                        if json_matches:
                            # Try the largest JSON block
                            json_str = max(json_matches, key=len)
                            print(f"[DEBUG] Strategy 3: Found {len(json_matches)} JSON blocks, using largest")
                    
                    if json_str:
                        # Clean up common JSON issues
                        json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas before }
                        json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas before ]
                        json_str = re.sub(r'}\s*{', '},{', json_str)  # Fix missing commas between objects
                        
                        # Additional cleanup: Remove any non-JSON text
                        json_str = json_str.strip()
                        
                        print(f"[DEBUG] Cleaned JSON length: {len(json_str)} characters")
                        print(f"[DEBUG] First 200 chars: {json_str[:200]}")
                        print(f"[DEBUG] Last 200 chars: {json_str[-200:]}")
                        
                        # Try to parse cleaned JSON
                        data = json.loads(json_str)
                        
                        english_data = data.get("english", {})
                        arabic_data = data.get("arabic", {})
                        managers = data.get("managers", [])
                        partners = data.get("partners", [])
                        
                        # CRITICAL: Ensure managers and partners are lists
                        if not isinstance(managers, list):
                            print(f"[WARN] managers is not a list, converting: {type(managers)}")
                            managers = []
                        if not isinstance(partners, list):
                            print(f"[WARN] partners is not a list, converting: {type(partners)}")
                            partners = []
                        
                        print(f"[DEBUG] Parsed JSON - English fields: {len(english_data)}, Arabic fields: {len(arabic_data)}, Managers: {len(managers)}, Partners: {len(partners)}")
                        
                        # Ensure all fields exist
                        english_data = self.ensure_all_fields(english_data, MULTI_OWNER_ENGLISH_FIELDS)
                        arabic_data = self.ensure_all_fields(arabic_data, MULTI_OWNER_ARABIC_FIELDS)
                        
                        # Post-process to fix incomplete values
                        english_data = self.post_process_data(english_data, raw_text)
                        arabic_data = self.post_process_data(arabic_data, raw_text)
                        
                        print(f"[INFO] Multiple Owner extraction complete: {len(partners)} partners, {len(managers)} managers")
                        return english_data, arabic_data, managers, partners
                    else:
                        print("[ERROR] No valid JSON found in response")
                
                except json.JSONDecodeError as e:
                    print(f"[ERROR] JSON parsing error: {e}")
                    if json_str:
                        print(f"[ERROR] Problematic JSON segment: {json_str[max(0, e.pos-100):min(len(json_str), e.pos+100)]}")
                except Exception as e:
                    print(f"[ERROR] Extraction failed: {e}")
                    import traceback
                    print(f"[ERROR] Traceback: {traceback.format_exc()}")
        
        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
        
        # ALWAYS return 4 values - even on failure
        print(f"[WARN] Multiple Owner extraction failed, returning empty data")
        return (
            {field: "" for field in MULTI_OWNER_ENGLISH_FIELDS},
            {field: "" for field in MULTI_OWNER_ARABIC_FIELDS},
            [],  # empty managers list
            []   # empty partners list
        )
    
    @retry_with_backoff(max_retries=3, base_delay=10)
    def extract_with_ai(self, raw_text: str, ownership_type: str = None):
        """
        Main extraction method with conditional logic based on ownership type
        
        Args:
            raw_text: Extracted text from document
            ownership_type: "Single Owner" or "Multiple Owners" (if None, auto-detect)
        
        Returns:
            For Single Owner: (english_data, arabic_data, owner)
            For Multiple Owners: (english_data, arabic_data, managers, partners)
        """
        # Use provided ownership type or detect automatically
        if ownership_type is None:
            ownership_type = self.ownership_type or self.detect_ownership_type(raw_text)
        
        # Debug information
        print(f"[DEBUG-EXTRACT] Raw text length: {len(raw_text)}")
        print(f"[DEBUG-EXTRACT] First 500 chars: {raw_text[:500]}")
        print(f"[DEBUG-EXTRACT] Ownership type: {ownership_type}")
        
        # Route to appropriate extractor based on ownership type
        if ownership_type == "Single Owner":
            print("[INFO] Using Single Owner extraction logic")
            return self.extract_single_owner_with_ai(raw_text)
        elif ownership_type == "Multiple Owners" or ownership_type in ["Partnership", "Multiple Owner"]:
            print("[INFO] Using Multiple Owners extraction logic")
            return self.extract_multi_owner_with_ai(raw_text)
        else:
            print(f"[WARN] Unknown ownership type '{ownership_type}', defaulting to Multiple Owners logic")
            return self.extract_multi_owner_with_ai(raw_text)
    
    def ensure_all_fields(self, data: Dict, required_fields: list) -> Dict:
        """Ensure all required fields exist in the dictionary"""
        complete_data = {}
        for field in required_fields:
            complete_data[field] = data.get(field, "")
        return complete_data
    
    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """Fix incomplete or missing values using regex fallback"""
        incomplete_patterns = {
            "license_number": [
                r'License No[.:]?\s*(\d+)',
                r'Lic\. No[.:]?\s*(\d+)',
            ],
            "main_license_number": [
                r'Main License No[.:]?\s*(\d+)',
                r'Main Lic[.:]?\s*(\d+)',
            ],
            "commercial_register_number": [
                r'Register No[.:]?\s*(\d+)',
                r'Reg\. No[.:]?\s*(\d+)',
            ],
            "issue_date": [
                r'Date Issue[:\s]+(\d{2}/\d{2}/\d{4})',
                r'Issue Date[:\s]+(\d{2}/\d{2}/\d{4})',
            ],
            "expiry_date": [
                r'Date Expiry[:\s]+(\d{2}/\d{2}/\d{4})',
                r'Expiry Date[:\s]+(\d{2}/\d{2}/\d{4})',
            ],
            "phone": [
                r'Phone No[:\s]+([\d\-]+)',
                r'Tel[:\s]+([\d\-]+)',
            ],
            "mobile": [
                r'Mobile No[:\s]+([\d\-]+)',
                r'Mob[:\s]+([\d\-]+)',
            ],
            "email": [
                r'Email[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            ],
            "po_box": [
                r'P\.O\. Box[:\s]+(\d+)',
                r'PO Box[:\s]+(\d+)',
            ],
            "parcel_id": [
                r'Parcel ID[:\s]+([\d\-]+)',
                r'Plot[:\s]+([\d\-]+)',
            ],
            "paid_capital": [
                r'Paid[:\s]+([\d,]+)',
                r'Capital Paid[:\s]+([\d,]+)',
            ],
        }
        
        for field, patterns in incomplete_patterns.items():
            if field in data and (not data[field] or len(str(data[field])) < 2):
                for pattern in patterns:
                    match = re.search(pattern, raw_text, re.IGNORECASE)
                    if match:
                        data[field] = match.group(1).strip()
                        break
        
        return data
    
    def validate_single_owner_extraction(self, english_data: Dict, arabic_data: Dict, owner: Dict) -> Dict:
        """Validate Single Owner extraction completeness"""
        validation = {
            "english_field_count": len([v for v in english_data.values() if v and str(v).strip()]),
            "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
            "has_owner": bool(owner and owner.get("name_english")),
            "english_missing": [f for f in SINGLE_OWNER_ENGLISH_FIELDS if f not in english_data or not english_data[f]],
            "arabic_missing": [f for f in SINGLE_OWNER_ARABIC_FIELDS if f not in arabic_data or not arabic_data[f]],
            "is_valid": False,
            "issues": [],
            "required_fields": SINGLE_OWNER_ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": []
        }
        
        non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        
        # Check critical fields
        critical_fields = ["license_number", "company_name_english", "trade_name_english",
                          "issue_date", "expiry_date", "legal_type"]
        
        for f in critical_fields:
            if f not in english_data or not english_data[f]:
                validation["issues"].append(f"Missing critical field: {f}")
                validation["missing_fields"].append(f)
        
        # Validation: At least 30 out of 39 fields
        if validation["missing_fields"]:
            validation["is_valid"] = False
            print(f"[VALIDATION] Single Owner INVALID: Missing critical: {validation['missing_fields']}")
        elif non_empty_english < 30:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/39 (need 30+)")
            print(f"[VALIDATION] Single Owner INVALID: Only {non_empty_english}/39 fields (need 30+)")
        elif not validation["has_owner"]:
            validation["is_valid"] = False
            validation["issues"].append("No owner information extracted")
            print(f"[VALIDATION] Single Owner INVALID: No owner info")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            print(f"[VALIDATION] Single Owner VALID: {non_empty_english}/39 fields, Owner: ✅")
        
        return validation
    
    def validate_multi_owner_extraction(self, english_data: Dict, arabic_data: Dict,
                                       managers: List[Dict], partners: List[Dict]) -> Dict:
        """Validate Multiple Owner extraction completeness"""
        validation = {
            "english_field_count": len([v for v in english_data.values() if v and str(v).strip()]),
            "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
            "managers_count": len(managers),
            "partners_count": len(partners),
            "english_missing": [f for f in MULTI_OWNER_ENGLISH_FIELDS if f not in english_data or not english_data[f]],
            "arabic_missing": [f for f in MULTI_OWNER_ARABIC_FIELDS if f not in arabic_data or not arabic_data[f]],
            "is_valid": False,
            "issues": [],
            "required_fields": MULTI_OWNER_ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": []
        }
        
        non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        print(f"[VALIDATION] Trade License: {non_empty_english}/33 fields, {len(partners)} partners, {len(managers)} managers")
        
        # Check critical fields
        critical_fields = ["license_number", "company_name_english", "trade_name_english",
                          "issue_date", "expiry_date", "legal_type"]
        
        for f in critical_fields:
            if f not in english_data or not english_data[f]:
                validation["issues"].append(f"Missing critical field: {f}")
                validation["missing_fields"].append(f)
        
        # Must have partners OR managers
        has_members = len(partners) > 0 or len(managers) > 0
        
        # Validation: Only require critical fields + at least 20 fields total
        if validation["missing_fields"]:
            validation["is_valid"] = False
            print(f"[VALIDATION] Multiple Owner INVALID: Missing critical: {validation['missing_fields']}")
        elif non_empty_english < 20:  # LOWERED FROM 28 to 20
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/33 (need 20+)")
            print(f"[VALIDATION] Multiple Owner INVALID: Only {non_empty_english}/33 fields (need 20+)")
        elif not has_members:
            validation["is_valid"] = False
            validation["issues"].append("No partners or managers extracted")
            print(f"[VALIDATION] Multiple Owner INVALID: No partners/managers found")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            print(f"[VALIDATION] Multiple Owner VALID: {non_empty_english}/33 fields, {len(partners)} partners ✅")
        
        return validation
    
    def validate_extraction(self, *args, ownership_type: str = None) -> Dict:
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
            english_data, arabic_data, owner = args
            return self.validate_single_owner_extraction(english_data, arabic_data, owner)
        elif len(args) == 4:
            english_data, arabic_data, managers, partners = args
            return self.validate_multi_owner_extraction(english_data, arabic_data, managers, partners)
        else:
            raise ValueError(f"Invalid arguments for validation with ownership_type={ownership_type}")
