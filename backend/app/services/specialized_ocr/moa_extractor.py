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
from app import config

# API Configuration
API_KEY = config.AWS_BEARER_TOKEN_BEDROCK or ""
# Model names + endpoint come from llm_client (env-driven via .env.docker).
# Do not redeclare them here — see the LLM MODEL ROUTING block in .env.docker.
from app.services.llm_client import (
    LLM_API_URL,
    TEXT_PRIMARY,
    TEXT_FALLBACK,
    VISION_PRIMARY,
)
from app.services import bedrock_client
from app.services.specialized_ocr.extraction_schema import validate_and_coerce
import logging
from app.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

API_URL = LLM_API_URL
# Configurable via MOA_API_TIMEOUT_SECONDS in .env.docker — change + restart
# the container to raise/lower this without editing code.
API_TIMEOUT_SECONDS = config.MOA_API_TIMEOUT_SECONDS
# Model tiering (prompt-remediation Phase 2, opt-in via
# config.MODEL_TIERING_ENABLED): MOA extraction is the other task
# dumps/docs/bedrock-final-recommendation.md singles out for a stronger
# model -- bilingual EN/AR structured extraction with an explicit
# validation pass, same reasoning-load tier as trade license. Both
# LLAMA_MODEL_NAME and QWEN_MODEL_NAME below move to the reasoning tier
# together so the double-pass extraction (see extract_with_ai) doesn't
# end up comparing a stronger-model pass against a weaker-model pass --
# both names already resolve to the same single Bedrock model today
# regardless (see llm_client.py's module docstring), a leftover from the
# pre-Bedrock multi-provider era. Falls back to the default model
# automatically at the bedrock_client.post() level if the reasoning-tier
# call itself fails -- see that module's _resolve_invoke_url().
LLAMA_MODEL_NAME = config.BEDROCK_REASONING_MODEL_ID if config.MODEL_TIERING_ENABLED else TEXT_PRIMARY
QWEN_MODEL_NAME = config.BEDROCK_REASONING_MODEL_ID if config.MODEL_TIERING_ENABLED else TEXT_FALLBACK
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

    # PROMPT CACHING (prompt-remediation Phase 3): static instructions/schema/
    # field-reference/validation-rules moved here as a system prompt so
    # bedrock_client.py's existing ephemeral prompt caching (see
    # _to_bedrock_payload) applies to them instead of being re-sent and
    # re-processed as fresh input tokens on every single MOA extraction call.
    # Content is UNCHANGED, character-for-character, from the previous
    # extract_with_ai() prompt -- only its position moved (still an f-string,
    # so the ENGLISH_FIELDS/ARABIC_FIELDS json.dumps() calls still interpolate
    # correctly since those are module-level constants), so extraction
    # behaviour is not expected to change.
    _SYSTEM_PROMPT = f"""You are an expert AI specialized in extracting information from UAE Memorandum of Association (MOA) documents.

    🔴 CRITICAL INSTRUCTION: ARTICLE-BY-ARTICLE + DOCUMENT-WIDE DUAL EXTRACTION

    You MUST perform extraction using TWO INDEPENDENT METHODS to ensure 100% accuracy:

    **METHOD 1: ARTICLE-BY-ARTICLE EXTRACTION (FIRST PASS)**
    Systematically extract fields by reading each article:
    - Article 1: Company name, type, execution date, owner details
    - Article 2: Owner passport, nationality, date of birth
    - Articles 3-5: Business activities (activity_1 through activity_4)
    - Article 6: Company duration (must include NUMBER + "years")
    - Article 7: Share details (number_of_shares, value_per_share)
    - Article 8: Manager details with complete address
    - Article 9: Manager appointment duration (must include NUMBER + "years")
    - Article 11: Financial year details (with ordinals: 1st, 31st)
    - Article 12: Legal reserve percentage (must include NUMBER + "%")
    Store internally as ARTICLE_BASED_EXTRACTION.

    **METHOD 2: DOCUMENT-WIDE EXTRACTION (SECOND PASS - INDEPENDENT)**
    Re-read the ENTIRE document from start to finish.
    Extract ALL {EXPECTED_FIELD_COUNT} fields WITHOUT referring to article-specific extractions.
    Store internally as DOCUMENT_WIDE_EXTRACTION.

    **CROSS-VALIDATION BETWEEN METHODS:**
    For EACH of the 34 fields:
    - Compare ARTICLE_BASED vs DOCUMENT_WIDE extractions
    - If values MATCH exactly → Accept the value ✓
    - If values DIFFER → Re-extract from the specific article with maximum precision
    - If BOTH are empty → Mark as CRITICAL_FAILURE for that field
    - If ONE is empty and OTHER has value → Verify the non-empty value against document

    **FOCUSED RE-EXTRACTION:**
    For any field where METHOD_1 ≠ METHOD_2:
    1. Locate the exact article/section containing that field
    2. Re-read that article with maximum attention to detail
    3. Look for numbers, dates, names with extreme precision
    4. Extract the complete value (including units like "years", "%", "months")
    5. Validate against format requirements
    6. If still uncertain → Return the most complete and format-valid value

    📋 MANDATORY FIELD-BY-FIELD FORMAT VALIDATION

    Before accepting ANY field value, it MUST pass these validation rules:

    ✅ **passport_number** (رقم_الجواز):
    ▪ MUST match format: [A-Z]\\d{{6,9}}
    ▪ MUST start with LETTER, followed by 6-9 DIGITS
    ▪ Example: "Z5434257" NOT "Z" alone or "5434257" alone
    ▪ Location: Article 1 or Article 2 owner details
    ▪ Pattern: "passport No. Z5434257" or "holder of passport (Z5434257)"
    ▪ Validation: ^[A-Z]\\d{{6,9}}$
    ▪ If invalid: Re-scan for "passport" keyword and extract letter+digits

    ✅ **date_of_execution** (تاريخ_التنفيذ):
    ▪ MUST match format: DD/MM/YYYY
    ▪ MUST be complete date (e.g., "30/12/2024")
    ▪ Example: "30/12/2024" NOT "2024-12-30" or "12/30/2024"
    ▪ Location: Opening paragraph "entered into on" or Article 1
    ▪ Validation: ^\\d{{2}}/\\d{{2}}/\\d{{4}}$
    ▪ If invalid: Re-extract from opening date mention and convert to DD/MM/YYYY

    ✅ **company_name** (اسم_الشركة):
    ▪ MUST be complete legal company name
    ▪ MUST be at least 5 characters
    ▪ MUST appear consistently across articles
    ▪ Example: "SAMPLE COMPANY NAME L.L.C"
    ▪ Location: Article 1 "company name" clause
    ▪ If invalid: Re-extract from Article 1 opening statement

    ✅ **owner_name** (اسم_المالك):
    ▪ MUST be complete full name with title
    ▪ MUST be at least 3 characters
    ▪ Example: "Ms. SAMPLE OWNER NAME"
    ▪ Location: Article 1, Article 2, or owner section
    ▪ Include title if present: Mr., Ms., Mrs., Dr.
    ▪ If invalid: Re-extract from owner/shareholder clause

    ✅ **manager_name** (اسم_المدير):
    ▪ MUST be complete full name with title
    ▪ MUST be at least 3 characters
    ▪ Often same as owner_name in single-owner companies
    ▪ Example: "Ms. SAMPLE OWNER NAME"
    ▪ Location: Article 8 manager appointment
    ▪ If invalid: Re-extract from Article 8

    ✅ **company_type** (نوع_الشركة):
    ▪ Common values: "ONE PERSON LIMITED LIABILITY COMPANY", "LIMITED LIABILITY COMPANY"
    ▪ Arabic: "شركة الشخص الواحد ذات مسؤولية محدودة"
    ▪ Location: Article 1
    ▪ If invalid: Re-extract company type/form from Article 1

    ✅ **date_of_birth** (تاريخ_الميلاد):
    ▪ MUST match format: DD/MM/YYYY
    ▪ MUST be valid birth date (year between 1950-2010 typically)
    ▪ Example: "11/11/1999"
    ▪ Location: Article 2 or owner details
    ▪ Validation: ^\\d{{2}}/\\d{{2}}/\\d{{4}}$
    ▪ If invalid: Re-extract from "born on" or date of birth mention

    ✅ **company_duration** (مدة_الشركة):
    ▪ MUST be format: "XX years" (e.g., "99 years")
    ▪ MUST include NUMBER + space + "years"
    ▪ NOT just "years" alone or "Z" or "//"
    ▪ Example: "99 years"
    ▪ Location: Article 6 company duration clause
    ▪ Pattern: "(99) Ninety Nine years" → Extract "99 years"
    ▪ Validation: ^\\d+\\s+years?$
    ▪ If invalid: Look in Article 6 for number BEFORE "years" keyword

    ✅ **number_of_shares** (عدد_الحصص):
    ▪ MUST be complete integer (1-6 digits)
    ▪ MUST be NUMBER ONLY (no "shares", no "DHS", no text)
    ▪ Example: "300" NOT "300 shares" or "DHS 300"
    ▪ Location: Article 7 "divided into (300) shares"
    ▪ Validation: ^\\d{{1,6}}$
    ▪ If invalid: Extract number from "divided into (XXX) shares" clause

    ✅ **value_per_share** (قيمة_كل_حصة):
    ▪ MUST be complete amount (3-7 digits)
    ▪ MUST be NUMBER ONLY (no "DHS", no currency symbol)
    ▪ Example: "1000" NOT "DHS 1000" or "1000 Dirhams"
    ▪ Location: Article 7 "value of each share (DHS 1000)"
    ▪ Validation: ^\\d{{3,7}}$
    ▪ If invalid: Extract number after "DHS" or "value" keyword

    ✅ **appointment_start** (بداية_التعيين):
    ▪ MUST be format: "X years" (e.g., "5 years")
    ▪ MUST include NUMBER + space + "years"
    ▪ Example: "5 years"
    ▪ Location: Article 9 manager appointment
    ▪ Pattern: "appointed for (5) Five years" → Extract "5 years"
    ▪ Validation: ^\\d+\\s+years?$
    ▪ If invalid: Look in Article 9 for appointment period number

    ✅ **legal_reserve_percentage** (نسبة_الاحتياطي_القانوني):
    ▪ MUST be format: "X%" (e.g., "10%")
    ▪ MUST include NUMBER + "%" symbol
    ▪ NOT just "%" alone
    ▪ Example: "10%"
    ▪ Location: Article 12 legal reserve allocation
    ▪ Pattern: "allocate (10)%" → Extract "10%"
    ▪ Validation: ^\\d+%$
    ▪ If invalid: Look in Article 12 for percentage before "%" symbol

    ✅ **maximum_duration** (المدة_القصوى):
    ▪ MUST be format: "X months" (e.g., "18 months")
    ▪ MUST include NUMBER + space + "months"
    ▪ Example: "18 months"
    ▪ Location: Balance sheet submission clause
    ▪ Pattern: "(18) eighteen months" → Extract "18 months"
    ▪ Validation: ^\\d+\\s+months?$
    ▪ If invalid: Look for number BEFORE "months" keyword

    ✅ **financial_year_start** (بداية_السنة_المالية):
    ▪ MUST include ordinal: "1st January"
    ▪ NOT just "January" or "1 January"
    ▪ MUST have "st", "nd", "rd", or "th"
    ▪ Example: "1st January"
    ▪ Location: Article 11 financial year
    ▪ Pattern: "commence on 1st January" → Extract "1st January"
    ▪ If invalid: Add ordinal to make "1st January"

    ✅ **financial_year_end** (نهاية_السنة_المالية):
    ▪ MUST include ordinal: "31st December"
    ▪ NOT just "December" or "31 December"
    ▪ Example: "31st December"
    ▪ Location: Article 11 financial year
    ▪ Pattern: "end on 31st December" → Extract "31st December"
    ▪ If invalid: Add ordinal to make "31st December"

    ✅ **company_address** (عنوان_الشركة):
    ▪ MUST include P.O. Box number
    ▪ Format: "P.O. Box No. XXXX, Dubai, United Arab Emirates"
    ▪ MUST NOT be "P.O. Box No. , Dubai" (missing number)
    ▪ Example: "P.O. Box No. 3999, Dubai, United Arab Emirates"
    ▪ Location: Company address clause
    ▪ Extraction: Find P.O. Box number (e.g., "3999"), then construct full address
    ▪ If invalid: Re-scan for "P.O. Box" or "ص.ب" and extract number

    ✅ **manager_address** (عنوان_المدير):
    ▪ Same format as company_address
    ▪ MUST include P.O. Box number
    ▪ Format: "P.O. Box No. XXXX, Dubai, United Arab Emirates"
    ▪ Location: Article 8 manager details
    ▪ If invalid: Re-extract P.O. Box number and construct address

    ✅ **owner_nationality** (جنسية_المالك):
    ▪ MUST be complete country name
    ▪ Example: "India", "United Arab Emirates", "United Kingdom"
    ▪ Location: Article 2 or owner details
    ▪ If invalid: Re-extract from nationality mention

    ✅ **manager_nationality** (جنسية_المدير):
    ▪ MUST be complete country name
    ▪ Often same as owner_nationality
    ▪ Example: "India"
    ▪ Location: Article 8
    ▪ If invalid: Re-extract or use owner_nationality if same person

    ✅ **activity_1_data_services** through **activity_4_internet_content**:
    ▪ MUST use EXACT field names (check underscore placement!)
    ▪ activity_1_data_services (NOT activity__data_services)
    ▪ activity_2_computer_systems
    ▪ activity_3_web_design
    ▪ activity_4_internet_content
    ▪ Each MUST be complete activity description (≥10 characters)
    ▪ Location: Articles 3, 4, 5
    ▪ If invalid: Re-extract from activities section with exact field names

    ✅ **owner_residence** (إقامة_المالك):
    ▪ Usually: "Dubai, United Arab Emirates"
    ▪ Location: Owner details section
    ▪ If invalid: Extract city and country

    ✅ **manager_residence** (إقامة_المدير):
    ▪ Usually: "Dubai, United Arab Emirates"
    ▪ Location: Article 8
    ▪ If invalid: Extract city and country

    ✅ **head_office_location** (موقع_المركز_الرئيسي):
    ▪ Usually: "Dubai, United Arab Emirates"
    ▪ Location: Head office clause
    ▪ If invalid: Extract emirate and country

    ✅ **share_type** (نوع_الحصص):
    ▪ Common values: "cash shares", "in-kind shares"
    ▪ Arabic: "حصة نقدية"
    ▪ Location: Article 7
    ▪ If invalid: Extract share type from Article 7

    ✅ **payment_status** (حالة_الدفع):
    ▪ Common values: "fully paid up in cash", "partially paid"
    ▪ Arabic: "دفعت بالكامل"
    ▪ Location: Article 7
    ▪ If invalid: Extract payment status

    ✅ **appointment_renewal** (تجديد_التعيين):
    ▪ Complete text about renewal
    ▪ Example: "automatically renewed for similar periods"
    ▪ Location: Article 9
    ▪ If invalid: Extract renewal clause text

    ✅ **first_financial_year** (السنة_المالية_الأولى):
    ▪ Complete description
    ▪ Example: "from date of registration to 31st December"
    ▪ Location: Article 11
    ▪ If invalid: Extract first year description

    ✅ **balance_sheet_submission** (تقديم_الميزانية):
    ▪ Complete submission requirement
    ▪ Example: "within 3 months from end of financial year"
    ▪ Location: Balance sheet article
    ▪ If invalid: Extract submission timeframe

    ✅ **profit_loss_distribution** (توزيع_الأرباح_والخسائر):
    ▪ Complete distribution rule
    ▪ Example: "distributed according to shareholding percentage"
    ▪ Location: Profit distribution article
    ▪ If invalid: Extract distribution mechanism

    ✅ **duration_start_date** (تاريخ_بدء_المدة):
    ▪ Usually: "date of registration in Commercial Register"
    ▪ Location: Article 6
    ▪ If invalid: Extract start date reference

    ✅ **document_type** (نوع_الوثيقة):
    ▪ Should be: "MEMORANDUM OF ASSOCIATION" or "Memorandum of Association"
    ▪ Arabic: "عقد تأسيس"
    ▪ Location: Document header
    ▪ If invalid: Use standard value

    🎯 ARTICLE-SPECIFIC EXTRACTION GUIDE

    **Article 1 - Company Formation:**
    → company_name, company_type, date_of_execution, owner_name

    **Article 2 - Owner Details:**
    → passport_number, owner_nationality, date_of_birth, owner_residence

    **Articles 3-5 - Business Activities:**
    → activity_1_data_services
    → activity_2_computer_systems
    → activity_3_web_design
    → activity_4_internet_content

    **Article 6 - Company Duration:**
    → company_duration (MUST extract: "XX years")
    → duration_start_date

    **Article 7 - Share Capital:**
    → number_of_shares (extract NUMBER only)
    → value_per_share (extract AMOUNT only)
    → share_type
    → payment_status

    **Article 8 - Manager Appointment:**
    → manager_name
    → manager_nationality
    → manager_residence
    → manager_address (MUST include P.O. Box)

    **Article 9 - Manager Term:**
    → appointment_start (MUST extract: "X years")
    → appointment_renewal

    **Article 11 - Financial Year:**
    → financial_year_start (MUST have ordinal: "1st January")
    → financial_year_end (MUST have ordinal: "31st December")
    → first_financial_year

    **Article 12 - Legal Reserve:**
    → legal_reserve_percentage (MUST extract: "X%")

    **Other Clauses:**
    → company_address (with P.O. Box)
    → head_office_location
    → maximum_duration ("X months")
    → balance_sheet_submission
    → profit_loss_distribution

    📚 FIELD REFERENCE (USE EXACT NAMES):

    ENGLISH FIELDS (ALL 34 REQUIRED):
    {json.dumps(ENGLISH_FIELDS, indent=2)}

    ARABIC FIELDS (ALL 34 REQUIRED):
    {json.dumps(ARABIC_FIELDS, ensure_ascii=False, indent=2)}

    ✅ VALIDATION REQUIREMENTS BEFORE OUTPUT

    Your extraction is ONLY valid if ALL of these conditions are met:

    🔴 CRITICAL FIELDS (ALL 5 MUST BE COMPLETE):
    1. ✓ passport_number: Format [A-Z]\\d{{6,9}} (e.g., "Z5434257")
    2. ✓ date_of_execution: Format DD/MM/YYYY (e.g., "30/12/2024")
    3. ✓ company_name: Complete name, ≥5 characters
    4. ✓ owner_name: Complete name, ≥3 characters
    5. ✓ manager_name: Complete name, ≥3 characters

    🟡 MINIMUM THRESHOLD:
    ✓ At least 22 out of 34 fields MUST be complete in BOTH English and Arabic

    🟢 FORMAT VALIDATIONS:
    ✓ passport_number: ^[A-Z]\\d{{6,9}}$
    ✓ date_of_execution: DD/MM/YYYY format
    ✓ date_of_birth: DD/MM/YYYY format
    ✓ company_duration: "XX years" (includes number)
    ✓ number_of_shares: Integer only (1-6 digits)
    ✓ value_per_share: Integer only (3-7 digits)
    ✓ appointment_start: "X years" (includes number)
    ✓ legal_reserve_percentage: "X%" (includes number and %)
    ✓ maximum_duration: "X months" (includes number)
    ✓ financial_year_start: "1st January" (with ordinal)
    ✓ financial_year_end: "31st December" (with ordinal)
    ✓ company_address: Includes "P.O. Box No. XXXX"
    ✓ manager_address: Includes "P.O. Box No. XXXX"

    🚫 FORBIDDEN VALUES (NOT ALLOWED):
    ✗ Empty strings: ""
    ✗ Null values: null
    ✗ Incomplete values: "Z" alone, "//" alone, "years" alone, "%" alone, "DHS " alone
    ✗ Placeholder text: "N/A", "Not Available", "TBD"
    ✗ Wrong formats: "2024-12-30" (for dates), "1 January" (missing ordinal)
    ✗ Partial addresses: "P.O. Box No. , Dubai" (missing number)

    📤 OUTPUT FORMAT (STRICT JSON)

    {{
    "english": {{
        "document_type": "MEMORANDUM OF ASSOCIATION",
        "company_name": "SAMPLE COMPANY NAME L.L.C",
        "company_type": "ONE PERSON LIMITED LIABILITY COMPANY",
        "date_of_execution": "30/12/2024",
        "owner_name": "Ms. SAMPLE OWNER NAME",
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
        "manager_name": "Ms. SAMPLE OWNER NAME",
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
        "اسم_الشركة": "اسم الشركة النموذجية ش.ذ.م.م",
        "نوع_الشركة": "شركة الشخص الواحد ذات مسؤولية محدودة",
        "تاريخ_التنفيذ": "30/12/2024",
        "اسم_المالك": "السيدة. الاسم النموذجي للمالك",
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
        "اسم_المدير": "السيدة. الاسم النموذجي للمالك",
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
    }},
    "extraction_metadata": {{
        "dual_method_validation": "completed",
        "article_based_document_wide_matches": 30,
        "re_extracted_fields": ["company_duration", "number_of_shares", "passport_number"],
        "critical_fields_status": "all_valid",
        "total_fields_completed": 34,
        "extraction_confidence": "high",
        "format_validation_passed": true,
        "minimum_threshold_met": true,
        "p_o_box_extracted": true
    }}
    }}

    ❌ FAILURE RESPONSE (If Extraction Fails After All Attempts)

    If you CANNOT extract all 5 CRITICAL fields after re-extraction attempts, return:

    {{
    "extraction_status": "FAILED",
    "failed_critical_fields": ["passport_number", "date_of_execution"],
    "reason": "Passport number incomplete after 3 attempts. Date format unclear in document.",
    "partial_data_available": true,
    "fields_successfully_extracted": 28,
    "recommendation": "Document may require manual review for critical fields"
    }}

    🚀 FINAL INSTRUCTIONS

    EXTRACTION SEQUENCE:
    1. Perform ARTICLE-BY-ARTICLE extraction → Store all 34 fields
    2. Perform DOCUMENT-WIDE extraction → Store all 34 fields independently
    3. Compare both methods → Identify mismatches (should be <15%)
    4. Re-extract mismatched fields from specific articles → Validate format
    5. Verify ALL 5 critical fields are complete and format-valid
    6. Verify at least 22/34 fields are complete
    7. Verify numeric fields have complete values (not just units)
    8. Verify addresses include P.O. Box numbers
    9. Verify financial year fields have ordinals
    10. Return JSON ONLY when ALL validations pass

    CRITICAL REMINDERS:
    ⚠️ passport_number: Must be "Z5434257" format (letter + 6-9 digits), NOT "Z" alone
    ⚠️ company_duration: Must be "99 years" (number + years), NOT just "years"
    ⚠️ number_of_shares: Must be "300" (integer only), NOT "300 shares"
    ⚠️ value_per_share: Must be "1000" (integer only), NOT "DHS 1000"
    ⚠️ legal_reserve_percentage: Must be "10%" (number + %), NOT just "%"
    ⚠️ appointment_start: Must be "5 years" (number + years), NOT just "years"
    ⚠️ financial_year_start: Must be "1st January" (with ordinal), NOT just "January"
    ⚠️ company_address: Must be "P.O. Box No. 3999, Dubai, UAE", NOT "P.O. Box No. , Dubai"

    ⚠️ IMPORTANT: Return ONLY the JSON object. NO markdown formatting, NO ```json blocks, NO explanatory text before or after the JSON.

    BEGIN DUAL-METHOD EXTRACTION NOW."""

    @retry_with_backoff(max_retries=3, base_delay=5, label="MOA API")
    def call_ai_api(self, prompt: str, model_name: str = None) -> str:
        """Call the Bedrock API with retry logic"""
        if not self.api_key:
            return "API key not configured"

        model = model_name or LLAMA_MODEL_NAME

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,  # Changed to 0.0 for maximum consistency
            "max_tokens": 4500,
        }

        try:
            response = bedrock_client.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUT_SECONDS)

            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"MOA API failed: {response.status_code} Server temporarily unavailable")

            if response.status_code == 429:
                raise RuntimeError(f"MOA API failed: {response.status_code} Rate limit exceeded")

            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            raise RuntimeError(f"MOA API failed: Request timeout after {API_TIMEOUT_SECONDS} seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"MOA API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")

    @retry_with_backoff(max_retries=3, base_delay=5, label="MOA API")
    def extract_with_ai(self, raw_text: str, model_choice: str = "llama") -> Tuple[Dict, Dict]:
        """Extract bilingual MOA fields using AI - DOUBLE-PASS EXTRACTION WITH VALIDATION"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME

        prompt = f"Document Text:\n{raw_text[:20000]}"

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
                        logger.error(f"MOA JSON decode error: {e}")
                        # Try fixing common issues
                        json_str = re.sub(r"//.*?\n", "", json_str)
                        json_str = re.sub(r"/\*.*?\*/", "", json_str, flags=re.DOTALL)
                        json_str = re.sub(r"(\w+):", r'"\1":', json_str)

                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError as e2:
                            logger.error(f"MOA JSON still invalid: {e2}")
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
                logger.error(f"MOA extraction failed: {e}")
                import traceback
                logger.error(traceback.format_exc())

        return self.get_empty_fields()

    def get_empty_fields(self) -> Tuple[Dict, Dict]:
        """Return empty dictionaries with all fields"""
        return (
            {field: "" for field in ENGLISH_FIELDS},
            {field: "" for field in ARABIC_FIELDS},
        )

    def ensure_all_fields(self, data: Dict, required_fields: list) -> Dict:
        """Ensure all required fields exist in the dictionary, string-valued.

        prompt-remediation Phase 4: delegates to extraction_schema.validate_and_coerce
        (pydantic-backed) instead of a bare dict comprehension -- same shape in/out,
        but a non-string field value now gets coerced and logged instead of
        silently flowing downstream untyped.
        """
        return validate_and_coerce(data, required_fields, "MOAFields")

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
                    logger.warning(f"{field} format issue: '{data[field]}' - {desc}")

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
                                    logger.info(f"[REGEX FIX] company_duration: {data[field]}")
                                elif field == "appointment_start":
                                    data[field] = f"{extracted} years"
                                    logger.info(f"[REGEX FIX] appointment_start: {data[field]}")
                                elif field == "maximum_duration":
                                    data[field] = f"{extracted} months"
                                    logger.info(f"[REGEX FIX] maximum_duration: {data[field]}")
                                elif field == "legal_reserve_percentage":
                                    data[field] = f"{extracted}%"
                                    logger.info(f"[REGEX FIX] legal_reserve_percentage: {data[field]}")
                                elif field in ["company_address", "manager_address"]:
                                    # Reconstruct full address with P.O. Box
                                    data[field] = f"P.O. Box No. {extracted}, Dubai, United Arab Emirates"
                                    logger.info(f"[REGEX FIX] {field}: {data[field]}")
                                else:
                                    data[field] = extracted
                                    logger.info(f"[REGEX FIX] {field}: {extracted}")
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
                logger.info(f"[FIX] financial_year_start: {data['financial_year_start']}")

        if "financial_year_end" in data:
            val = str(data["financial_year_end"]).strip()
            if val in ["st December", " December", "December", "31 December", ""]:
                match = re.search(r"end\s+on\s+(31st\s+December)", raw_text, re.IGNORECASE)
                if match:
                    data["financial_year_end"] = match.group(1)
                else:
                    data["financial_year_end"] = "31st December"
                logger.info(f"[FIX] financial_year_end: {data['financial_year_end']}")

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
                            logger.info(f"[FIX] {addr_field} P.O. Box: {po_box}")
                            break

        # Fix activity field names if AI used wrong format
        fields_to_rename = {}
        for key in list(data.keys()):
            # Check for wrong formats like "activity__" or "activity_"
            if "activity_" in key and key not in ENGLISH_FIELDS:
                logger.warning(f"Found incorrect activity field name: {key}")
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
                logger.info(f"[FIX] Renamed {old_key} → {new_key}")

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
                        logger.info(f"[FIX] passport_number: {data['passport_number']}")
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

        logger.info(f"[VALIDATION] MOA: {non_empty_count}/34 fields populated")

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
            logger.info(f"[VALIDATION] Format issues: {format_issues}")

        # Validation rules - THRESHOLD: 22 out of 34 fields (65%)
        # 1. All critical fields must be present
        # 2. At least 22 fields must have valid values
        if missing_critical:
            validation["is_valid"] = False
            validation["issues"].append(f"Missing critical fields: {', '.join(missing_critical)}")
            logger.info(f"[VALIDATION] MOA INVALID: Missing critical: {missing_critical}")
        elif non_empty_count < 22:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_count}/34 (need 22+)")
            logger.info(f"[VALIDATION] MOA INVALID: Only {non_empty_count}/34 fields (need 22+)")
        else:
            validation["is_valid"] = True
            # Clear format issues if we have enough fields
            if not missing_critical:
                validation["issues"] = []
            logger.info(f"[VALIDATION] MOA VALID: {non_empty_count}/34 fields")

        return validation