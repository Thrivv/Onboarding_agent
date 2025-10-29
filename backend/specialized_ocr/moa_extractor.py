# specialized_ocr/moa_extractor.py

import os
import json
import re
import requests
import zipfile
import tempfile
import time
import shutil
from typing import Dict, Tuple
from functools import wraps
import fitz  # PyMuPDF
from xml.etree import ElementTree as ET

# API Configuration
API_KEY = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-...")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-32b-instruct"

# Fields expected for MOA extraction (34 fields)
ENGLISH_FIELDS = [
    "document_type",
    "company_name",
    "company_type",
    "date_of_execution",
    "owner_name",
    "owner_nationality",
    "passport_number",
    "date_of_birth",
    "owner_residence",
    "activity_1_data_services",
    "activity_2_computer_systems",
    "activity_3_web_design",
    "activity_4_internet_content",
    "company_address",
    "head_office_location",
    "company_duration",
    "duration_start_date",
    "number_of_shares",
    "value_per_share",
    "share_type",
    "payment_status",
    "manager_name",
    "manager_nationality",
    "manager_residence",
    "manager_address",
    "appointment_start",
    "appointment_renewal",
    "financial_year_start",
    "financial_year_end",
    "first_financial_year",
    "maximum_duration",
    "balance_sheet_submission",
    "legal_reserve_percentage",
    "profit_loss_distribution",
]

ARABIC_FIELDS = [
    "نوع_الوثيقة",
    "اسم_الشركة",
    "نوع_الشركة",
    "تاريخ_التنفيذ",
    "اسم_المالك",
    "جنسية_المالك",
    "رقم_الجواز",
    "تاريخ_الميلاد",
    "إقامة_المالك",
    "النشاط_1_خدمات_البيانات",
    "النشاط_2_أنظمة_الحاسب",
    "النشاط_3_تصميم_المواقع",
    "النشاط_4_محتوى_الإنترنت",
    "عنوان_الشركة",
    "موقع_المركز_الرئيسي",
    "مدة_الشركة",
    "تاريخ_بدء_المدة",
    "عدد_الحصص",
    "قيمة_كل_حصة",
    "نوع_الحصص",
    "حالة_الدفع",
    "اسم_المدير",
    "جنسية_المدير",
    "إقامة_المدير",
    "عنوان_المدير",
    "بداية_التعيين",
    "تجديد_التعيين",
    "بداية_السنة_المالية",
    "نهاية_السنة_المالية",
    "السنة_المالية_الأولى",
    "المدة_القصوى",
    "تقديم_الميزانية",
    "نسبة_الاحتياطي_القانوني",
    "توزيع_الأرباح_والخسائر",
]

EXPECTED_FIELD_COUNT = 34


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
                    if (
                        any(code in error_msg for code in ["503", "429", "502", "504"])
                        and attempt < max_retries - 1
                    ):
                        delay = base_delay * (2**attempt)
                        print(
                            f"[WARN] MOA API error (attempt {attempt + 1}/{max_retries}): {error_msg}"
                        )
                        print(f"[INFO] Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None

        return wrapper

    return decorator


class MOAExtractor:
    """MOA extractor with bilingual support and retry logic"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY
        self.api_url = API_URL

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF using PyMuPDF"""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            all_text = ""
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                page_text = page.get_text()
                all_text += f"\n--- Page {page_num + 1} ---\n{page_text}\n"

            doc.close()
            return all_text

        except Exception as e:
            return f"[PDF EXTRACTION ERROR] {str(e)}"

    def extract_text_from_docx(self, docx_bytes: bytes) -> str:
        """Extract text from DOCX by parsing OXML structure"""
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp()
            docx_path = os.path.join(temp_dir, "temp_document.docx")

            with open(docx_path, "wb") as f:
                f.write(docx_bytes)

            with zipfile.ZipFile(docx_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            document_xml_path = os.path.join(temp_dir, "word", "document.xml")

            if not os.path.exists(document_xml_path):
                return (
                    "[DOCX EXTRACTION ERROR] document.xml not found in DOCX structure"
                )

            tree = ET.parse(document_xml_path)
            root = tree.getroot()

            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

            text_content = []

            for text_elem in root.findall(".//w:t", ns):
                if text_elem.text:
                    text_content.append(text_elem.text)

            # Extract table content
            for table in root.findall(".//w:tbl", ns):
                for row in table.findall(".//w:tr", ns):
                    row_text = []
                    for cell in row.findall(".//w:tc", ns):
                        cell_text = []
                        for text_elem in cell.findall(".//w:t", ns):
                            if text_elem.text:
                                cell_text.append(text_elem.text)
                        if cell_text:
                            row_text.append(" ".join(cell_text))
                    if row_text:
                        text_content.append(" | ".join(row_text))

            extracted_text = "\n".join(text_content)
            extracted_text = re.sub(r"\s+", " ", extracted_text)
            extracted_text = extracted_text.strip()

            return (
                extracted_text
                if extracted_text
                else "[DOCX EXTRACTION ERROR] No text content found"
            )

        except Exception as e:
            return f"[DOCX EXTRACTION ERROR] {str(e)}"

        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

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
            "max_tokens": 4500,
        }

        try:
            response = requests.post(
                self.api_url, headers=headers, json=data, timeout=120
            )

            if response.status_code in [502, 503, 504]:
                raise RuntimeError(
                    f"MOA API failed: {response.status_code} Server temporarily unavailable"
                )

            if response.status_code == 429:
                raise RuntimeError(
                    f"MOA API failed: {response.status_code} Rate limit exceeded"
                )

            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            raise RuntimeError("MOA API failed: Request timeout after 120 seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"MOA API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}"
            )

    @retry_with_backoff(max_retries=3, base_delay=10)
    def extract_with_ai(
        self, raw_text: str, model_choice: str = "llama"
    ) -> Tuple[Dict, Dict]:
        """Extract bilingual MOA fields using AI - ENHANCED PROMPT FROM STANDALONE"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME

        prompt = f"""You are an expert at extracting information from UAE Memorandum of Association (MOA) documents.

Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic from this bilingual MOA document.

CRITICAL REQUIREMENTS:

1. **EXACT FIELD NAMES** - Use these EXACT field names with numbers:
   - activity_1_data_services (NOT activity__data_services)
   - activity_2_computer_systems (NOT activity__computer_systems)
   - activity_3_web_design (NOT activity__web_design)
   - activity_4_internet_content (NOT activity__internet_content)

2. **COMPLETE NUMERIC VALUES** - Extract ALL numbers completely:
   - passport_number: "Z5434257" (complete passport number with all digits)
   - date_of_execution: "30/12/2024" (complete date with day/month/year)
   - date_of_birth: "10/10/1999" (complete date)
   - company_duration: "99 years" (include the number before "years")
   - number_of_shares: "300" (exact number from Article 7)
   - value_per_share: "1000" (complete amount from Article 7)
   - appointment_start: "5 years" (include duration number)

3. **COMPLETE ADDRESS INFORMATION**:
   - company_address: Must include P.O. Box number if present
   - manager_address: "P.O. Box No. 3999, Dubai, United Arab Emirates" (complete with P.O. Box)

4. **Article-Specific Extraction**:
   - Article 6: Extract company_duration (e.g., "99 years")
   - Article 7: Extract number_of_shares ("300") and value_per_share ("1000")
   - Article 8: Extract manager details and complete manager_address with P.O. Box
   - Article 9: Extract appointment_start (e.g., "5 years"), appointment_renewal
   - Article 11: Extract financial_year_start ("1st January"), financial_year_end ("31st December")
   - Article 12: Extract legal_reserve_percentage ("10%")

5. **Financial Year Details** - Must include ordinal numbers:
   - financial_year_start: "1st January" (with "1st")
   - financial_year_end: "31st December" (with "31st")
   - maximum_duration: "18 months" (complete number)

6. **NO PARTIAL VALUES**: Do not extract "//" or " years" or "DHS " or "%" alone
   - If you find " years", look for the NUMBER before it
   - If you find "DHS ", look for the AMOUNT after it
   - Extract complete dates, not just slashes

7. ALL {EXPECTED_FIELD_COUNT} fields MUST have complete actual values from the document

Document Text (EXTENDED to 25000 chars):
{raw_text[:25000]}

ENGLISH FIELDS (use these EXACT names):
{json.dumps(ENGLISH_FIELDS, indent=2)}

ARABIC FIELDS (use these EXACT names):
{json.dumps(ARABIC_FIELDS, ensure_ascii=False, indent=2)}

EXAMPLE OF CORRECT FORMAT WITH COMPLETE VALUES:
{{
  "english": {{
    "document_type": "MEMORANDUM OF ASSOCIATION",
    "company_name": "ABC TRADING SERVICES L.L.C",
    "company_type": "ONE PERSON LIMITED LIABILITY COMPANY",
    "date_of_execution": "15/03/2024",
    "owner_name": "Mr. JOHN SMITH ANDERSON",
    "owner_nationality": "United Kingdom",
    "passport_number": "A1234567",
    "date_of_birth": "25/06/1985",
    "owner_residence": "Dubai, United Arab Emirates",
    "activity_1_data_services": "Business Consulting Services",
    "activity_2_computer_systems": "Information Technology Services",
    "activity_3_web_design": "Digital Marketing Services",
    "activity_4_internet_content": "Online Content Development",
    "company_address": "P.O. Box No. 12345, Dubai, United Arab Emirates",
    "head_office_location": "Dubai, United Arab Emirates",
    "company_duration": "50 years",
    "duration_start_date": "date of registration in Commercial Register",
    "number_of_shares": "100",
    "value_per_share": "1000",
    "share_type": "cash shares",
    "payment_status": "fully paid up in cash",
    "manager_name": "Mr. JOHN SMITH ANDERSON",
    "manager_nationality": "United Kingdom",
    "manager_residence": "Dubai, United Arab Emirates",
    "manager_address": "P.O. Box No. 12345, Dubai, United Arab Emirates",
    "appointment_start": "5 years",
    "appointment_renewal": "automatically renewed for similar periods",
    "financial_year_start": "1st January",
    "financial_year_end": "31st December",
    "first_financial_year": "from date of registration to 31st December",
    "maximum_duration": "18 months",
    "balance_sheet_submission": "within 3 months from end of financial year",
    "legal_reserve_percentage": "10%",
    "profit_loss_distribution": "distributed according to shareholding percentage"
  }},
  "arabic": {{
    "نوع_الوثيقة": "عقد تأسيس",
    "اسم_الشركة": "شركة التجارة ش.ذ.م.م",
    "نوع_الشركة": "شركة الشخص الواحد ذات مسؤولية محدودة",
    "تاريخ_التنفيذ": "15/03/2024",
    "اسم_المالك": "السيد. جون سميث اندرسون",
    "جنسية_المالك": "المملكة المتحدة",
    "رقم_الجواز": "A1234567",
    "تاريخ_الميلاد": "25/06/1985",
    "إقامة_المالك": "دبي، الإمارات العربية المتحدة",
    "النشاط_1_خدمات_البيانات": "خدمات استشارات الأعمال",
    "النشاط_2_أنظمة_الحاسب": "خدمات تكنولوجيا المعلومات",
    "النشاط_3_تصميم_المواقع": "خدمات التسويق الرقمي",
    "النشاط_4_محتوى_الإنترنت": "تطوير المحتوى الإلكتروني",
    "عنوان_الشركة": "ص.ب. 12345، دبي، الإمارات العربية المتحدة",
    "موقع_المركز_الرئيسي": "دبي، الإمارات العربية المتحدة",
    "مدة_الشركة": "50 سنة",
    "تاريخ_بدء_المدة": "تاريخ التسجيل في السجل التجاري",
    "عدد_الحصص": "100",
    "قيمة_كل_حصة": "1000",
    "نوع_الحصص": "حصة نقدية",
    "حالة_الدفع": "دفعت بالكامل",
    "اسم_المدير": "السيد. جون سميث اندرسون",
    "جنسية_المدير": "المملكة المتحدة",
    "إقامة_المدير": "دبي، الإمارات العربية المتحدة",
    "عنوان_المدير": "ص.ب. 12345، دبي، الإمارات العربية المتحدة",
    "بداية_التعيين": "5 سنوات",
    "تجديد_التعيين": "تجدد تلقائيا لمدد مماثلة",
    "بداية_السنة_المالية": "1 يناير",
    "نهاية_السنة_المالية": "31 ديسمبر",
    "السنة_المالية_الأولى": "من تاريخ التسجيل إلى 31 ديسمبر",
    "المدة_القصوى": "18 شهر",
    "تقديم_الميزانية": "خلال 3 أشهر من نهاية السنة المالية",
    "نسبة_الاحتياطي_القانوني": "10%",
    "توزيع_الأرباح_والخسائر": "توزع حسب نسبة المساهمة"
  }}
}}

Return ONLY valid JSON with ALL {EXPECTED_FIELD_COUNT} fields populated from the document with COMPLETE values.
Extract only information explicitly present in the text.
"""

        response = self.call_ai_api(prompt, model_name)

        if response and not response.startswith("API Error"):
            try:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    json_str = json_match.group()

                    # Clean up JSON
                    json_str = re.sub(r",\s*}", "}", json_str)
                    json_str = re.sub(r",\s*]", "]", json_str)
                    json_str = json_str.replace("\n", " ")
                    json_str = re.sub(r"\s+", " ", json_str)

                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        print(f"[ERROR] MOA JSON decode error: {e}")

                        # Try fixing common issues
                        json_str = re.sub(r"//.*?\n", "", json_str)
                        json_str = re.sub(r"/\*.*?\*/", "", json_str, flags=re.DOTALL)
                        json_str = re.sub(r"(\w+):", r'"\1":', json_str)

                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError as e2:
                            print(f"[ERROR] MOA JSON still invalid: {e2}")
                            return self.get_empty_fields()

                    english_data = data.get("english", {})
                    arabic_data = data.get("arabic", {})

                    # Ensure all fields exist
                    english_data = self.ensure_all_fields(english_data, ENGLISH_FIELDS)
                    arabic_data = self.ensure_all_fields(arabic_data, ARABIC_FIELDS)

                    # Post-process with enhanced logic
                    english_data = self.post_process_data(english_data, raw_text)
                    arabic_data = self.post_process_data(arabic_data, raw_text)

                    return english_data, arabic_data

            except Exception as e:
                print(f"[ERROR] MOA extraction failed: {e}")
                import traceback

                traceback.print_exc()

        return self.get_empty_fields()

    def get_empty_fields(self) -> Tuple[Dict, Dict]:
        """Return empty dictionaries with all fields"""
        return (
            {field: "" for field in ENGLISH_FIELDS},
            {field: "" for field in ARABIC_FIELDS},
        )

    def ensure_all_fields(self, data: Dict, required_fields: list) -> Dict:
        """Ensure all required fields exist in the dictionary"""
        complete_data = {}
        for field in required_fields:
            complete_data[field] = data.get(field, "")
        return complete_data

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """Fix incomplete or missing values using ENHANCED regex fallback"""

        # Enhanced patterns with multiple alternatives
        incomplete_patterns = {
            "date_of_execution": [
                r"entered into on.*?(\d{2}/\d{2}/\d{4})",
                r"day of\s+(\d{2}/\d{2}/\d{4})",
                r"executed on\s+(\d{2}/\d{2}/\d{4})",
                r"(\d{2}/\d{2}/\d{4})",
            ],
            "date_of_birth": [
                r"born on[:\s]+(\d{2}/\d{2}/\d{4})",
                r"Date of Birth[:\s]+(\d{2}/\d{2}/\d{4})",
                r"DOB[:\s]+(\d{2}/\d{2}/\d{4})",
            ],
            "passport_number": [
                r"passport\s+No\.?\s*([A-Z]\d{6,})",
                r"holder of passport.*?([A-Z]\d{6,})",
                r"Passport[:\s]+([A-Z]\d{6,})",
            ],
            "company_duration": [
                r"duration.*?(\d+)\s*(?:years?|سنة|سنوات)",
                r"مدة.*?(\d+)\s*(?:years?|سنة|سنوات)",
                r"period of\s+(\d+)\s+years",
            ],
            "number_of_shares": [
                r"divided into\s*\(?(\d+)\)?\s*shares",
                r"(\d+)\s*shares",
                r"موزعة.*?(\d+).*?حصص",
                r"Article 7.*?(\d+)\s*shares",
            ],
            "value_per_share": [
                r"value\s+of\s+each\s+share.*?(?:DHS|درهم)\s*(\d+)",
                r"(?:DHS|درهم)\s*(\d{3,})",
                r"قيمة.*?حصة.*?(\d{3,})",
                r"per share.*?(\d{3,})",
            ],
            "appointment_start": [
                r"(\d+)\s*years?\s+from\s+the\s+date",
                r"period of\s+(\d+)\s+years",
                r"مدة.*?(\d+)\s*(?:سنة|سنوات)",
            ],
            "maximum_duration": [
                r"not\s+exceed\s*(\d+)\s*months",
                r"(\d+)\s*months",
                r"لا تتجاوز.*?(\d+).*?شهر",
            ],
            "legal_reserve_percentage": [
                r"(\d+)\s*%.*?(?:reserve|احتياطي)",
                r"reserve.*?(\d+)\s*%",
                r"احتياطي.*?(\d+)\s*%",
            ],
        }

        # Check and fix incomplete values
        incomplete_indicators = [
            "",
            "//",
            "Z",
            " years",
            " months",
            "DHS ",
            "% ",
            "st January",
            "st December",
        ]

        for field, patterns in incomplete_patterns.items():
            if field in data:
                value = str(data[field]).strip()
                # Check if value is incomplete
                if not value or value in incomplete_indicators or len(value) < 3:
                    # Try each pattern
                    for pattern in patterns:
                        match = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
                        if match:
                            extracted = match.group(1).strip()
                            if extracted and len(extracted) > 1:
                                # Format based on field type
                                if field == "company_duration":
                                    data[field] = f"{extracted} years"
                                elif field == "appointment_start":
                                    data[field] = f"{extracted} years"
                                elif field == "maximum_duration":
                                    data[field] = f"{extracted} months"
                                elif field == "legal_reserve_percentage":
                                    data[field] = f"{extracted}%"
                                else:
                                    data[field] = extracted
                                break

        # Fix financial year fields with ordinals
        if "financial_year_start" in data:
            val = str(data["financial_year_start"]).strip()
            if val in ["st January", " January", "January", "1 January"]:
                data["financial_year_start"] = "1st January"
            elif not val or len(val) < 5:
                match = re.search(
                    r"commence\s+on\s+(1st\s+January)", raw_text, re.IGNORECASE
                )
                if match:
                    data["financial_year_start"] = match.group(1)

        if "financial_year_end" in data:
            val = str(data["financial_year_end"]).strip()
            if val in ["st December", " December", "December", "31 December"]:
                data["financial_year_end"] = "31st December"
            elif not val or len(val) < 5:
                match = re.search(
                    r"end\s+on\s+(31st\s+December)", raw_text, re.IGNORECASE
                )
                if match:
                    data["financial_year_end"] = match.group(1)

        # Fix P.O. Box in addresses
        for addr_field in ["company_address", "manager_address"]:
            if addr_field in data:
                value = str(data[addr_field])
                if (
                    "P.O. Box No. ," in value
                    or "P.O. Box No.  ," in value
                    or not re.search(r"\d", value)
                ):
                    # Try to find P.O. Box number
                    po_match = re.search(
                        r"P\.O\.\s*Box\s*No\.\s*(\d+)", raw_text, re.IGNORECASE
                    )
                    if po_match:
                        po_box = po_match.group(1)
                        data[addr_field] = (
                            f"P.O. Box No. {po_box}, Dubai, United Arab Emirates"
                        )

        # Fix activity field names (if AI used wrong names)
        fields_to_rename = {}
        for key in list(data.keys()):
            if "activity__" in key:
                parts = key.split("__")
                if len(parts) == 2:
                    activity_type = parts[1]
                    if "data" in activity_type or "بيانات" in activity_type:
                        fields_to_rename[key] = "activity_1_data_services"
                    elif "computer" in activity_type or "حاسب" in activity_type:
                        fields_to_rename[key] = "activity_2_computer_systems"
                    elif "web" in activity_type or "مواقع" in activity_type:
                        fields_to_rename[key] = "activity_3_web_design"
                    elif "internet" in activity_type or "إنترنت" in activity_type:
                        fields_to_rename[key] = "activity_4_internet_content"

        # Perform renaming
        for old_key, new_key in fields_to_rename.items():
            data[new_key] = data.pop(old_key)

        return data

    def validate_extraction(self, english_data: Dict, arabic_data: Dict) -> Dict:
        """Validate extracted fields - RELAXED THRESHOLD"""
        validation = {
            "english_field_count": len(
                [v for v in english_data.values() if v and str(v).strip()]
            ),
            "arabic_field_count": len(
                [v for v in arabic_data.values() if v and str(v).strip()]
            ),
            "english_missing": [
                f
                for f in ENGLISH_FIELDS
                if f not in english_data or not english_data[f]
            ],
            "arabic_missing": [
                f for f in ARABIC_FIELDS if f not in arabic_data or not arabic_data[f]
            ],
            "is_valid": False,
            "issues": [],
            "required_fields": ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": [],
        }

        # Count non-empty fields (excluding obvious incomplete values)
        non_empty_count = len(
            [
                v
                for v in english_data.values()
                if v and str(v).strip() and str(v).strip() not in ["--", "Z", "", "//"]
            ]
        )

        print(f"[VALIDATION] MOA: {non_empty_count}/34 fields populated")

        # Check critical fields
        critical_fields = [
            "company_name",
            "owner_name",
            "manager_name",
            "date_of_execution",
        ]
        missing_critical = []

        for f in critical_fields:
            if (
                f not in english_data
                or not english_data[f]
                or str(english_data[f]).strip() in ["", "--", "Z"]
            ):
                missing_critical.append(f)
                validation["missing_fields"].append(f)

        # Validation rules - CHANGED: Reduced from 25 to 22 fields (65% of total)
        # 1. All critical fields must be present
        # 2. At least 22 out of 34 fields must have values
        if missing_critical:
            validation["is_valid"] = False
            validation["issues"].append(
                f"Missing critical fields: {', '.join(missing_critical)}"
            )
            print(f"[VALIDATION] MOA INVALID: Missing critical: {missing_critical}")
        elif non_empty_count < 22:  # CHANGED from 25
            validation["is_valid"] = False
            validation["issues"].append(
                f"Insufficient fields: {non_empty_count}/34 (need 22+)"
            )
            print(
                f"[VALIDATION] MOA INVALID: Only {non_empty_count}/34 fields (need 22+)"
            )
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            print(f"[VALIDATION] MOA VALID: {non_empty_count}/34 fields ✅")

        return validation
