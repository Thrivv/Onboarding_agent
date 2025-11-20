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
                    if any(code in error_msg for code in ["503", "429", "502", "504"]) and attempt < max_retries - 1:
                        delay = base_delay * (2**attempt)
                        print(f"[WARN] MOA API error (attempt {attempt + 1}/{max_retries}): {error_msg}")
                        print(f"[INFO] Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None
        return wrapper
    return decorator


class MOAExtractor:
    """MOA extractor with bilingual support and enhanced regex"""

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
                return "[DOCX EXTRACTION ERROR] document.xml not found in DOCX structure"

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

            return extracted_text if extracted_text else "[DOCX EXTRACTION ERROR] No text content found"

        except Exception as e:
            return f"[DOCX EXTRACTION ERROR] {str(e)}"
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    @retry_with_backoff(max_retries=3, base_delay=5)
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
            "temperature": 0.0,  # Changed to 0.0 for maximum consistency
            "max_tokens": 4500,
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=60)

            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"MOA API failed: {response.status_code} Server temporarily unavailable")

            if response.status_code == 429:
                raise RuntimeError(f"MOA API failed: {response.status_code} Rate limit exceeded")

            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            raise RuntimeError("MOA API failed: Request timeout after 60 seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"MOA API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")

    @retry_with_backoff(max_retries=3, base_delay=5)
    def extract_with_ai(self, raw_text: str, model_choice: str = "llama") -> Tuple[Dict, Dict]:
        """Extract bilingual MOA fields using AI - ENHANCED PROMPT WITH STRICTER RULES"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME

        prompt = f"""You are an expert AI specialized in extracting information from UAE Memorandum of Association (MOA) documents. Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic with COMPLETE values.

**CRITICAL EXTRACTION RULES:**

1. **EXACT FIELD NAMES** - Use these EXACT field names (NEVER change them):
   - activity_1_data_services (NOT activity__data_services or activity_data_services)
   - activity_2_computer_systems (format: activity_NUMBER_descriptor)
   - activity_3_web_design
   - activity_4_internet_content

2. **COMPLETE NUMERIC VALUES** - Extract ALL numbers completely:
   - passport_number: "Z5434257" (complete passport with letter + digits)
   - date_of_execution: "30/12/2024" (format: DD/MM/YYYY)
   - date_of_birth: "10/10/1999" (format: DD/MM/YYYY)
   - company_duration: "99 years" (INCLUDE the number before "years")
   - number_of_shares: "300" (exact integer from Article 7)
   - value_per_share: "1000" (exact amount in DHS from Article 7)
   - appointment_start: "5 years" (INCLUDE the number)

3. **FIELD LENGTH VALIDATION**:
   - Passport: 7-10 characters (e.g., "Z5434257")
   - Dates: 10 characters in DD/MM/YYYY format
   - Duration/Time periods: Must include number + unit (e.g., "99 years", "5 years", "18 months")
   - Percentages: Number + % symbol (e.g., "10%")
   - Share count: 1-6 digits (e.g., "300")
   - Share value: 3-7 digits (e.g., "1000")

4. **COMPLETE ADDRESS INFORMATION**:
   - company_address: "P.O. Box No. 3999, Dubai, United Arab Emirates" (COMPLETE with P.O. Box)
   - manager_address: Same format - MUST include P.O. Box number
   - head_office_location: "Dubai, United Arab Emirates"

5. **Article-Specific Extraction Rules**:
   - **Article 6**: company_duration (e.g., "99 years") - MUST include number
   - **Article 7**: 
     * number_of_shares: Extract the NUMBER of shares (e.g., "300")
     * value_per_share: Extract the VALUE per share (e.g., "1000")
   - **Article 8**: manager details with COMPLETE address including P.O. Box
   - **Article 9**: 
     * appointment_start: Duration (e.g., "5 years")
     * appointment_renewal: Full text about renewal
   - **Article 11**: 
     * financial_year_start: "1st January" (WITH ordinal)
     * financial_year_end: "31st December" (WITH ordinal)
     * first_financial_year: Complete description
   - **Article 12**: legal_reserve_percentage: "10%" (WITH percentage sign)

6. **NO PARTIAL VALUES** - NEVER extract incomplete values:
   - ❌ WRONG: "//" or " years" or "DHS " or "%" or "Z" alone
   - ✓ CORRECT: "30/12/2024", "99 years", "DHS 300000", "10%", "Z5434257"
   - If you find " years", look BACKWARD for the NUMBER before it
   - If you find "DHS ", look FORWARD for the AMOUNT after it

7. **Date Format Consistency**: ALL dates MUST be DD/MM/YYYY (NOT MM/DD/YYYY or YYYY-MM-DD)

8. **Financial Year Format**: Must include ordinal numbers
   - financial_year_start: "1st January" (NOT just "January")
   - financial_year_end: "31st December" (NOT just "December")

Document Text (EXTENDED to 30000 chars for better coverage):
{raw_text[:30000]}

ENGLISH FIELDS (use these EXACT names - DO NOT MODIFY):
{json.dumps(ENGLISH_FIELDS, indent=2)}

ARABIC FIELDS (use these EXACT names - DO NOT MODIFY):
{json.dumps(ARABIC_FIELDS, ensure_ascii=False, indent=2)}

**EXAMPLE OF CORRECT FORMAT WITH COMPLETE VALUES:**

{{
  "english": {{
    "document_type": "MEMORANDUM OF ASSOCIATION",
    "company_name": "THRIVV GROWTH TECHNOLOGY SERVICES L.L.C",
    "company_type": "ONE PERSON LIMITED LIABILITY COMPANY",
    "date_of_execution": "30/12/2024",
    "owner_name": "Ms. VARSHA BALAJI BALAJI",
    "owner_nationality": "India",
    "passport_number": "Z5434257",
    "date_of_birth": "10/10/1999",
    "owner_residence": "Dubai, United Arab Emirates",
    "activity_1_data_services": "Data Classification & Analysis Services",
    "activity_2_computer_systems": "Computer Systems & Communication Equipment Software Design",
    "activity_3_web_design": "Web-Design",
    "activity_4_internet_content": "Internet Content Provider",
    "company_address": "P.O. Box No. 3999, Dubai, United Arab Emirates",
    "head_office_location": "Dubai, United Arab Emirates",
    "company_duration": "99 years",
    "duration_start_date": "date of registration in Commercial Register",
    "number_of_shares": "300",
    "value_per_share": "1000",
    "share_type": "cash shares",
    "payment_status": "fully paid up in cash",
    "manager_name": "Ms. VARSHA BALAJI BALAJI",
    "manager_nationality": "India",
    "manager_residence": "Dubai, United Arab Emirates",
    "manager_address": "P.O. Box No. 3999, Dubai, United Arab Emirates",
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
    "اسم_الشركة": "ثريف جروث لخدمات التقنية ش.ذ.م.م",
    "نوع_الشركة": "شركة الشخص الواحد ذات مسؤولية محدودة",
    "تاريخ_التنفيذ": "30/12/2024",
    "اسم_المالك": "السيدة. فارشا بالجى بالجى",
    "جنسية_المالك": "الهند",
    "رقم_الجواز": "Z5434257",
    "تاريخ_الميلاد": "10/10/1999",
    "إقامة_المالك": "دبي، الإمارات العربية المتحدة",
    "النشاط_1_خدمات_البيانات": "خدمات تصنيف وتحليل البيانات",
    "النشاط_2_أنظمة_الحاسب": "تصميم نظم الحاسب الآلي وأجهزة الاتصال",
    "النشاط_3_تصميم_المواقع": "تصميم مواقع الشبكة المعلوماتية",
    "النشاط_4_محتوى_الإنترنت": "امداد مواقع الشبكة المعلوماتية بالمحتويات",
    "عنوان_الشركة": "ص.ب. 3999، دبي، الإمارات العربية المتحدة",
    "موقع_المركز_الرئيسي": "دبي، الإمارات العربية المتحدة",
    "مدة_الشركة": "99 سنة",
    "تاريخ_بدء_المدة": "تاريخ التسجيل في السجل التجاري",
    "عدد_الحصص": "300",
    "قيمة_كل_حصة": "1000",
    "نوع_الحصص": "حصة نقدية",
    "حالة_الدفع": "دفعت بالكامل",
    "اسم_المدير": "السيدة. فارشا بالجى بالجى",
    "جنسية_المدير": "الهند",
    "إقامة_المدير": "دبي، الإمارات العربية المتحدة",
    "عنوان_المدير": "ص.ب. 3999، دبي، الإمارات العربية المتحدة",
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

**VALIDATION CHECKLIST BEFORE RETURNING:**
✓ All 34 fields present in both English and Arabic
✓ Passport number is complete (e.g., "Z5434257", not just "Z")
✓ All dates are DD/MM/YYYY format with complete values
✓ company_duration includes number (e.g., "99 years", not just "years")
✓ number_of_shares is a complete number (e.g., "300")
✓ value_per_share is a complete number (e.g., "1000")
✓ All addresses include P.O. Box numbers
✓ appointment_start includes number (e.g., "5 years")
✓ financial_year_start has ordinal (e.g., "1st January")
✓ financial_year_end has ordinal (e.g., "31st December")
✓ legal_reserve_percentage includes % (e.g., "10%")
✓ maximum_duration includes number and unit (e.g., "18 months")

Return ONLY the JSON object with NO additional text, explanations, or markdown formatting. ALL 34 fields MUST have complete actual values from the document."""

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

                    # Post-process with enhanced regex
                    english_data = self.post_process_data(english_data, raw_text)
                    arabic_data = self.post_process_data(arabic_data, raw_text)

                    # Validate field lengths
                    english_data = self.validate_field_formats(english_data)

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

    def validate_field_formats(self, data: Dict) -> Dict:
        """Validate and warn about field format issues"""
        validations = {
            'passport_number': (r'^[A-Z]\d{6,9}$', 'Should be letter + 6-9 digits'),
            'date_of_execution': (r'^\d{2}/\d{2}/\d{4}$', 'Should be DD/MM/YYYY'),
            'date_of_birth': (r'^\d{2}/\d{2}/\d{4}$', 'Should be DD/MM/YYYY'),
            'company_duration': (r'^\d+\s+years?$', 'Should be "X years"'),
            'number_of_shares': (r'^\d{1,6}$', 'Should be 1-6 digits'),
            'value_per_share': (r'^\d{3,7}$', 'Should be 3-7 digits'),
            'appointment_start': (r'^\d+\s+years?$', 'Should be "X years"'),
            'maximum_duration': (r'^\d+\s+months?$', 'Should be "X months"'),
            'legal_reserve_percentage': (r'^\d+%$', 'Should be "X%"'),
        }

        for field, (pattern, desc) in validations.items():
            if field in data and data[field]:
                if not re.match(pattern, str(data[field])):
                    print(f"[WARN] {field} format issue: '{data[field]}' - {desc}")

        return data

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """Fix incomplete or missing values using ENHANCED regex fallback"""

        # Enhanced patterns with multiple alternatives and bilingual support
        incomplete_patterns = {
            "date_of_execution": [
                r"entered into on.*?(\d{2}/\d{2}/\d{4})",
                r"day of\s+(\d{2}/\d{2}/\d{4})",
                r"الموافق\s+(\d{2}/\d{2}/\d{4})",
                r"Monday.*?(\d{2}/\d{2}/\d{4})",
            ],
            "date_of_birth": [
                r"born on[:\s]+(\d{2}/\d{2}/\d{4})",
                r"Date of Birth[:\s]+(\d{2}/\d{2}/\d{4})",
                r"تاريخ الميلاد\s+(\d{2}/\d{2}/\d{4})",
            ],
            "passport_number": [
                r"passport\s+No\.?\s*([A-Z]\d{6,9})",
                r"holder of passport.*?([A-Z]\d{6,9})",
                r"جواز سفر رقم\s+\((\d+[A-Z])\)",  # Arabic format
                r"No\.\s+([A-Z]\d{6,9})",
            ],
            "company_duration": [
                r"\((\d+)\)\s*(?:Ninety|Eighty|Seventy).*?years?",
                r"duration.*?be\s+\((\d+)\).*?years?",
                r"مدة.*?\((\d+)\).*?(?:سنة|سنوات)",
                r"shall be\s+\((\d+)\).*?year",
            ],
            "number_of_shares": [
                r"divided into\s+\((\d+)\)\s+shares",
                r"موزعة على\s+\((\d+)\)\s+حصة",
                r"\((\d+)\)\s+shares.*?value",
                r"Article 7.*?(\d+)\s+shares",
            ],
            "value_per_share": [
                r"value of each share.*?\((?:DHS\s*)?(\d+)\)",
                r"قيمة كل حصة\s+\((\d+)\)",
                r"each share.*?Dirhams.*?\((?:DHS\s*)?(\d+)\)",
                r"per share.*?\((\d+)\)",
            ],
            "appointment_start": [
                r"appointed for.*?period of\s+\((\d+)\).*?years?",
                r"لمدة\s+\((\d+)\).*?(?:سنة|سنوات)",
                r"period of\s+\((\d+)\)\s+(?:Five|five).*?year",
            ],
            "maximum_duration": [
                r"not.*?exceed\s+\((\d+)\).*?months?",
                r"لا.*?تجاوز.*?\((\d+)\).*?(?:شهر|أشهر)",
                r"\((\d+)\).*?(?:eighteen|Eighteen).*?month",
            ],
            "legal_reserve_percentage": [
                r"allocate\s+(\d+)%.*?reserve",
                r"تخصيص نسبة\s+%(\d+)",
                r"(\d+)%.*?statutory reserve",
                r"احتياطي.*?(\d+)%",
            ],
            "company_address": [
                r"P\.O\.\s*Box\s*No\.\s*(\d+),\s*Dubai",
                r"ص\.?\s*ب\.?\s*(\d+).*?دبي",
            ],
            "manager_address": [
                r"Address:\s*P\.O\.\s*Box\s*No\.\s*(\d+)",
                r"العنوان.*?ص\.?\s*ب\.?\s*(\d+)",
            ],
        }

        # Check and fix incomplete values
        incomplete_indicators = ["", "//", "Z", " years", " months", "DHS ", "% ", "st ", "/", ""]

        for field, patterns in incomplete_patterns.items():
            if field in data:
                value = str(data[field]).strip()
                # Check if value is incomplete or empty
                if not value or value in incomplete_indicators or len(value) < 2:
                    # Try each pattern
                    for pattern in patterns:
                        match = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
                        if match:
                            extracted = match.group(1).strip()
                            if extracted and len(extracted) > 0:
                                # Format based on field type
                                if field == "company_duration":
                                    data[field] = f"{extracted} years"
                                    print(f"[REGEX FIX] company_duration: {data[field]}")
                                elif field == "appointment_start":
                                    data[field] = f"{extracted} years"
                                    print(f"[REGEX FIX] appointment_start: {data[field]}")
                                elif field == "maximum_duration":
                                    data[field] = f"{extracted} months"
                                    print(f"[REGEX FIX] maximum_duration: {data[field]}")
                                elif field == "legal_reserve_percentage":
                                    data[field] = f"{extracted}%"
                                    print(f"[REGEX FIX] legal_reserve_percentage: {data[field]}")
                                elif field in ["company_address", "manager_address"]:
                                    # Reconstruct full address with P.O. Box
                                    data[field] = f"P.O. Box No. {extracted}, Dubai, United Arab Emirates"
                                    print(f"[REGEX FIX] {field}: {data[field]}")
                                else:
                                    data[field] = extracted
                                    print(f"[REGEX FIX] {field}: {extracted}")
                                break

        # Fix financial year fields with ordinals
        if "financial_year_start" in data:
            val = str(data["financial_year_start"]).strip()
            if val in ["st January", " January", "January", "1 January", ""]:
                # Look for the proper text
                match = re.search(r"commence\s+on\s+(1st\s+January)", raw_text, re.IGNORECASE)
                if match:
                    data["financial_year_start"] = match.group(1)
                else:
                    data["financial_year_start"] = "1st January"
                print(f"[FIX] financial_year_start: {data['financial_year_start']}")

        if "financial_year_end" in data:
            val = str(data["financial_year_end"]).strip()
            if val in ["st December", " December", "December", "31 December", ""]:
                match = re.search(r"end\s+on\s+(31st\s+December)", raw_text, re.IGNORECASE)
                if match:
                    data["financial_year_end"] = match.group(1)
                else:
                    data["financial_year_end"] = "31st December"
                print(f"[FIX] financial_year_end: {data['financial_year_end']}")

        # Fix P.O. Box in addresses if still incomplete
        for addr_field in ["company_address", "manager_address"]:
            if addr_field in data:
                value = str(data[addr_field])
                # Check if address is incomplete or missing P.O. Box number
                if not value or "P.O. Box No. ," in value or not re.search(r'\d', value):
                    # Try to find P.O. Box number in document
                    po_patterns = [
                        r"P\.O\.\s*Box\s*No\.\s*(\d+)",
                        r"ص\.?\s*ب\.?\s*:?\s*(\d+)",
                    ]
                    for pattern in po_patterns:
                        po_match = re.search(pattern, raw_text, re.IGNORECASE)
                        if po_match:
                            po_box = po_match.group(1)
                            data[addr_field] = f"P.O. Box No. {po_box}, Dubai, United Arab Emirates"
                            print(f"[FIX] {addr_field} P.O. Box: {po_box}")
                            break

        # Fix activity field names if AI used wrong format
        fields_to_rename = {}
        for key in list(data.keys()):
            # Check for wrong formats like "activity__" or "activity_"
            if "activity_" in key and key not in ENGLISH_FIELDS:
                print(f"[WARN] Found incorrect activity field name: {key}")
                # Try to map to correct field based on content
                value = str(data[key]).lower()
                if "data" in value or "classification" in value:
                    fields_to_rename[key] = "activity_1_data_services"
                elif "computer" in value or "system" in value:
                    fields_to_rename[key] = "activity_2_computer_systems"
                elif "web" in value or "design" in value:
                    fields_to_rename[key] = "activity_3_web_design"
                elif "internet" in value or "content" in value:
                    fields_to_rename[key] = "activity_4_internet_content"

        # Perform renaming
        for old_key, new_key in fields_to_rename.items():
            if new_key not in data or not data[new_key]:
                data[new_key] = data.pop(old_key)
                print(f"[FIX] Renamed {old_key} → {new_key}")

        # Validate passport format and fix if needed
        if "passport_number" in data:
            passport = str(data["passport_number"]).strip()
            # If passport is just a letter or incomplete
            if len(passport) < 4:
                # Try to find complete passport
                passport_patterns = [
                    r"passport.*?No\.?\s*([A-Z]\d{6,9})",
                    r"holder of passport.*?No\.?\s*([A-Z]\d{6,9})",
                    r"\((\d{7}[A-Z])\)",  # Some passports end with letter
                ]
                for pattern in passport_patterns:
                    match = re.search(pattern, raw_text, re.IGNORECASE)
                    if match:
                        data["passport_number"] = match.group(1)
                        print(f"[FIX] passport_number: {data['passport_number']}")
                        break

        return data

    def validate_extraction(self, english_data: Dict, arabic_data: Dict) -> Dict:
        """Validate extracted fields with enhanced checks"""
        validation = {
            "english_field_count": len([v for v in english_data.values() if v and str(v).strip()]),
            "arabic_field_count": len([v for v in arabic_data.values() if v and str(v).strip()]),
            "english_missing": [f for f in ENGLISH_FIELDS if f not in english_data or not english_data[f]],
            "arabic_missing": [f for f in ARABIC_FIELDS if f not in arabic_data or not arabic_data[f]],
            "is_valid": False,
            "issues": [],
            "required_fields": ENGLISH_FIELDS,
            "present_fields": [k for k, v in english_data.items() if v],
            "missing_fields": [],
        }

        # Count non-empty fields (excluding obvious incomplete values)
        incomplete_values = ["--", "Z", "", "//", " ", "years", "months", "%", "DHS"]
        non_empty_count = len([
            v for v in english_data.values()
            if v and str(v).strip() and str(v).strip() not in incomplete_values
        ])

        print(f"[VALIDATION] MOA: {non_empty_count}/34 fields populated")

        # Check critical fields
        critical_fields = [
            "company_name",
            "owner_name", 
            "manager_name",
            "date_of_execution",
            "passport_number",
        ]
        missing_critical = []

        for f in critical_fields:
            value = str(english_data.get(f, "")).strip()
            if not value or value in incomplete_values or len(value) < 3:
                missing_critical.append(f)
                validation["missing_fields"].append(f)
                validation["issues"].append(f"Missing or incomplete critical field: {f}")

        # Additional validation: Check field formats
        format_issues = []
        
        # Validate dates
        for date_field in ["date_of_execution", "date_of_birth"]:
            if date_field in english_data and english_data[date_field]:
                if not re.match(r'^\d{2}/\d{2}/\d{4}$', str(english_data[date_field])):
                    format_issues.append(f"{date_field} format incorrect")
        
        # Validate passport
        if "passport_number" in english_data and english_data["passport_number"]:
            if not re.match(r'^[A-Z]\d{6,9}$', str(english_data["passport_number"])):
                format_issues.append("passport_number format incorrect")

        # Validate numeric fields
        if "number_of_shares" in english_data and english_data["number_of_shares"]:
            if not re.match(r'^\d{1,6}$', str(english_data["number_of_shares"])):
                format_issues.append("number_of_shares should be numeric")

        if "value_per_share" in english_data and english_data["value_per_share"]:
            if not re.match(r'^\d{3,7}$', str(english_data["value_per_share"])):
                format_issues.append("value_per_share should be numeric")

        if format_issues:
            validation["issues"].extend(format_issues)
            print(f"[VALIDATION] Format issues: {format_issues}")

        # Validation rules - THRESHOLD: 22 out of 34 fields (65%)
        # 1. All critical fields must be present
        # 2. At least 22 fields must have valid values
        if missing_critical:
            validation["is_valid"] = False
            validation["issues"].append(f"Missing critical fields: {', '.join(missing_critical)}")
            print(f"[VALIDATION] MOA INVALID: Missing critical: {missing_critical}")
        elif non_empty_count < 22:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_count}/34 (need 22+)")
            print(f"[VALIDATION] MOA INVALID: Only {non_empty_count}/34 fields (need 22+)")
        else:
            validation["is_valid"] = True
            # Clear format issues if we have enough fields
            if not missing_critical:
                validation["issues"] = []
            print(f"[VALIDATION] MOA VALID: {non_empty_count}/34 fields ✅")

        return validation