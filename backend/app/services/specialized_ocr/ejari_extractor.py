# # specialized_ocr/ejari_extractor.py

import os
import json
import re
import requests
import zipfile
import tempfile
import shutil
import time
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
# Configurable via EJARI_API_TIMEOUT_SECONDS in .env.docker — change + restart
# the container to raise/lower this without editing code.
API_TIMEOUT_SECONDS = config.EJARI_API_TIMEOUT_SECONDS
LLAMA_MODEL_NAME = TEXT_PRIMARY
QWEN_MODEL_NAME = TEXT_FALLBACK
ENGLISH_FIELDS = [
    "contract_number", "registration_date", 
    "owner_name", "owner_number", "owner_nationality",
    "lessor_company", "lessor_license_number", "lessor_license_issuer", "lessor_phone", "lessor_email",
    "tenant_company", "tenant_number", "tenant_license", "tenant_license_issuer",
    "start_date", "end_date",
    "building_name", "area", "plot_number", "makani_number", "property_number",
    "property_type", "property_subtype", "usage", "size"
]

ARABIC_FIELDS = [
    "رقم_العقد", "تاريخ_التسجيل",
    "اسم_المالك", "رقم_المالك", "جنسية_المالك",
    "اسم_المؤجر", "رقم_رخصة_المؤجر", "جهة_إصدار_رخصة_المؤجر", "هاتف_المؤجر", "بريد_المؤجر",
    "اسم_المستأجر", "رقم_المستأجر", "رخصة_المستأجر", "جهة_إصدار_رخصة_المستأجر",
    "تاريخ_البدء", "تاريخ_الإنتهاء",
    "اسم_المبنى", "المنطقة", "رقم_الأرض", "رقم_مكاني", "رقم_العقار",
    "نوع_العقار", "نوع_العقار_الفرعي", "الإستخدام", "المساحة"
]

EXPECTED_FIELD_COUNT = 25


class EjariExtractor:
    """Ejari (Tenancy Contract) extractor with bilingual support and enhanced regex"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY
        self.api_url = API_URL

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF using PyMuPDF"""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = ""
            for i in range(doc.page_count):
                page = doc.load_page(i)
                text += page.get_text() + "\n"
            doc.close()
            return text
        except Exception as e:
            return f"[PDF EXTRACTION ERROR] {str(e)}"

    def extract_text_from_docx(self, docx_bytes: bytes) -> str:
        """Extract text from DOCX by parsing OXML structure"""
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp()
            docx_path = os.path.join(temp_dir, "temp_document.docx")
            
            with open(docx_path, 'wb') as f:
                f.write(docx_bytes)
            
            with zipfile.ZipFile(docx_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            document_xml_path = os.path.join(temp_dir, 'word', 'document.xml')
            if not os.path.exists(document_xml_path):
                return "[DOCX EXTRACTION ERROR] document.xml not found"
            
            tree = ET.parse(document_xml_path)
            root = tree.getroot()
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            text_content = []
            for text_elem in root.findall('.//w:t', ns):
                if text_elem.text:
                    text_content.append(text_elem.text)
            
            extracted_text = '\n'.join(text_content)
            extracted_text = re.sub(r'\s+', ' ', extracted_text).strip()
            
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
    # validation-rules moved here as a system prompt so bedrock_client.py's
    # existing ephemeral prompt caching (see _to_bedrock_payload) applies to
    # them instead of these ~450 lines being re-sent and re-processed as fresh
    # input tokens on every single Ejari extraction call. Content is UNCHANGED,
    # character-for-character, from the previous extract_with_ai() prompt --
    # only its position moved (and it is now an f-string so EXPECTED_FIELD_COUNT
    # still interpolates), so extraction behaviour is not expected to change.
    _SYSTEM_PROMPT = f"""You are an expert AI model specialized in extracting information from UAE Ejari (Tenancy Contract Registration) certificates.

    🔴 CRITICAL INSTRUCTION: DOUBLE-PASS EXTRACTION PROTOCOL

    You MUST perform extraction in TWO INDEPENDENT PASSES to ensure accuracy:

    **PASS 1 (FIRST EXTRACTION):**
    Read the entire document carefully and extract ALL {EXPECTED_FIELD_COUNT} fields in both English and Arabic.
    Store this internally as EXTRACTION_PASS_1.

    **PASS 2 (SECOND EXTRACTION - INDEPENDENT):**
    Re-read the SAME document from the beginning WITHOUT referring to your first extraction.
    Extract ALL {EXPECTED_FIELD_COUNT} fields again independently.
    Store this internally as EXTRACTION_PASS_2.

    **CONSISTENCY VALIDATION:**
    Compare PASS_1 and PASS_2 for EACH field:
    - If values MATCH exactly → Accept the value ✓
    - If values DIFFER → Re-extract that specific field with higher precision
    - If BOTH are empty → Mark as CRITICAL_FAILURE for that field
    - If ONE is empty and OTHER has value → Verify the non-empty value, then use it

    **RE-EXTRACTION FOR MISMATCHES:**
    For any field where PASS_1 ≠ PASS_2:
    1. Locate the exact section in the document containing that field
    2. Re-read that section with maximum attention
    3. Extract the value with 100% precision
    4. Validate against format requirements
    5. If still uncertain after 3 attempts → Return the most complete/valid value

    📋 MANDATORY FIELD-BY-FIELD FORMAT VALIDATION

    Before accepting ANY field value, it MUST pass these validation rules:

    ✅ **contract_number** (رقم_العقد):
    ▪ MUST be EXACTLY 16 digits
    ▪ MUST start with "01"
    ▪ Format: 01XXXXXXXXXXXXXX
    ▪ Regex: ^01\\d{{14}}$
    ▪ Location: "Contract No" or "رقم العقد" row
    ▪ Example: "0120241230004974"
    ▪ If invalid: Re-scan document for any 16-digit number starting with "01"

    ✅ **registration_date** (تاريخ_التسجيل):
    ▪ MUST match format: DD-MM-YYYY
    ▪ MUST have valid day (01-31), month (01-12), year (2015-2030)
    ▪ Example: "30-12-2024"
    ▪ Location: "Registration Date" or "تاريخ التسجيل"
    ▪ If invalid: Re-extract and convert any date format to DD-MM-YYYY

    ✅ **owner_name** (اسم_المالك):
    ▪ MUST be complete full name (no truncation, no "...")
    ▪ MUST be at least 3 characters
    ▪ MUST NOT contain only numbers
    ▪ Example: "SAMPLE OWNER FULL NAME"
    ▪ Location: "Owner Name" or "اسم المالك" section
    ▪ If invalid: Re-extract complete name from owner section

    ✅ **owner_number** (رقم_المالك):
    ▪ MUST be 5-7 digits
    ▪ Format: Numeric only
    ▪ Example: "171445"
    ▪ Location: "Owner Number" or "رقم المالك"
    ▪ Validation: 5 <= len(value) <= 7 AND value.isdigit()
    ▪ If invalid: Re-extract from owner number field

    ✅ **owner_nationality** (جنسية_المالك):
    ▪ MUST be complete nationality name
    ▪ Example: "United Arab Emirates", "India", "Pakistan"
    ▪ Location: "Nationality" or "الجنسية" in owner section
    ▪ If invalid: Re-extract nationality from owner row

    ✅ **lessor_company** (اسم_المؤجر):
    ▪ MUST be complete company/person name
    ▪ MUST be at least 3 characters
    ▪ Example: "SAMPLE LESSOR COMPANY LLC"
    ▪ Location: "Lessor Name" or "اسم المؤجر"
    ▪ If invalid: Re-extract from lessor section

    ✅ **lessor_license_number** (رقم_رخصة_المؤجر):
    ▪ MUST be 6-7 digits
    ▪ Example: "1326400", "1495267"
    ▪ Location: "License Number" in lessor section
    ▪ Validation: 6 <= len(value) <= 7 AND value.isdigit()
    ▪ If invalid: Re-extract license number from lessor row

    ✅ **lessor_license_issuer** (جهة_إصدار_رخصة_المؤجر):
    ▪ Common values: "DED-Dubai", "DED", "Dubai Economy"
    ▪ Arabic: "دائرة التنمية الاقتصادية"
    ▪ Location: "License Issuer" or "جهة إصدار الرخصة"
    ▪ If invalid: Re-extract issuing authority

    ✅ **lessor_phone** (هاتف_المؤجر):
    ▪ MUST include country code (971 or +971)
    ▪ MUST be 10-13 digits total
    ▪ Preserve pipe character if present: "971|0523276602"
    ▪ Example: "9710523276602" or "971|0523276602"
    ▪ Location: "Tel. No" or "رقم الهاتف" in lessor section
    ▪ Validation: "971" in value AND len(digits) >= 10
    ▪ If invalid: Re-extract full phone number with country code

    ✅ **lessor_email** (بريد_المؤجر):
    ▪ MUST be valid email format
    ▪ MUST contain "@" and domain extension
    ▪ Example: "lessor@samplecompany.ae"
    ▪ Location: "E-mail" or "البريد الإلكتروني" in lessor section
    ▪ Validation: contains "@" AND contains "." after "@"
    ▪ If invalid: Re-extract email address

    ✅ **tenant_company** (اسم_المستأجر):
    ▪ MUST be complete company/person name
    ▪ MUST be at least 3 characters
    ▪ Example: "SAMPLE TENANT COMPANY L.L.C"
    ▪ Location: "Tenant Name" or "اسم المستأجر"
    ▪ If invalid: Re-extract from tenant section

    ✅ **tenant_number** (رقم_المستأجر):
    ▪ MUST be EXACTLY 16 digits
    ▪ MUST start with "04"
    ▪ Format: 04XXXXXXXXXXXXXX
    ▪ Regex: ^04\\d{{14}}$
    ▪ Example: "0420241230004964"
    ▪ Location: "Tenant No" or "رقم المستأجر"
    ▪ If invalid: Re-scan for 16-digit number starting with "04"

    ✅ **tenant_license** (رخصة_المستأجر):
    ▪ Format: "LICENSE_NO / DD-MM-YYYY"
    ▪ Example: "1495267 / 19-06-2025"
    ▪ Location: "Initial App./Exp." or "رقم الموافقة و تاريخ الانتهاء"
    ▪ If invalid: Extract license number and date separately, then combine

    ✅ **tenant_license_issuer** (جهة_إصدار_رخصة_المستأجر):
    ▪ Common values: "DED-Dubai", "DED", "Dubai Economy"
    ▪ Arabic: "دائرة التنمية الاقتصادية"
    ▪ Location: "License Issuer" in tenant section
    ▪ If invalid: Re-extract issuing authority

    ✅ **start_date** (تاريخ_البدء):
    ▪ MUST match format: DD-MM-YYYY
    ▪ MUST be valid date
    ▪ Example: "30-12-2024"
    ▪ Location: "Start Date" or "تاريخ البدء"
    ▪ Validation: ^\\d{{2}}-\\d{{2}}-\\d{{4}}$
    ▪ If invalid: Re-extract and convert to DD-MM-YYYY

    ✅ **end_date** (تاريخ_الإنتهاء):
    ▪ MUST match format: DD-MM-YYYY
    ▪ MUST be AFTER start_date
    ▪ Example: "29-12-2025"
    ▪ Location: "End Date" or "تاريخ الإنتهاء"
    ▪ Validation: ^\\d{{2}}-\\d{{2}}-\\d{{4}}$ AND end > start
    ▪ If invalid: Re-extract and convert to DD-MM-YYYY

    ✅ **building_name** (اسم_المبنى):
    ▪ MUST be extracted from "Building Name/No" row
    ▪ MUST be DIFFERENT from "area" field
    ▪ Example: "GARHOUD", "Building-Al Garhoud"
    ▪ Location: "Building Name/No" or "إسم المبنى/رقم المبنى"
    ▪ Validation: building_name != area
    ▪ If SAME as area: Prefix with "Building-" to differentiate

    ✅ **area** (المنطقة):
    ▪ MUST be extracted from "Land Area" row
    ▪ MUST be DIFFERENT from "building_name" field
    ▪ Example: "Al Garhoud", "الغارحود"
    ▪ Location: "Land Area" or "المنطقة" row (NOT Building row!)
    ▪ Validation: area != building_name
    ▪ If SAME as building: Extract from correct "Land Area" section

    ✅ **plot_number** (رقم_الأرض):
    ▪ Format: XXX-XXX or XX-X
    ▪ Example: "214-266", "95-0"
    ▪ Location: "Plot Number" or "رقم الأرض"
    ▪ Validation: ^\\d{{1,3}}-\\d{{1,3}}$
    ▪ If invalid: Re-extract plot number with hyphen format

    ✅ **makani_number** (رقم_مكاني):
    ▪ Format: XXXXX XXXXX (5 digits space 5 digits)
    ▪ Example: "32607 94119"
    ▪ Location: "Makani No" or "رقم مكاني"
    ▪ Validation: ^\\d{{5}}\\s\\d{{5}}$
    ▪ If invalid: Re-extract ensuring space separator

    ✅ **property_number** (رقم_العقار):
    ▪ Format: XXX-XX or XX-X
    ▪ Example: "106-19"
    ▪ Location: "Property No." or "رقم العقار"
    ▪ Validation: ^\\d{{2,3}}-\\d{{1,2}}$
    ▪ If invalid: Re-extract with hyphen format

    ✅ **property_type** (نوع_العقار):
    ▪ Common values: "Office", "Apartment", "Villa", "Shop", "Warehouse"
    ▪ Arabic: "مكتب", "شقة", "فيلا", "محل", "مستودع"
    ▪ Location: "Type" or "النوع" in property section
    ▪ If invalid: Re-extract property type

    ✅ **property_subtype** (نوع_العقار_الفرعي):
    ▪ Usually same as property_type or more specific
    ▪ Example: "Office", "Residential Apartment"
    ▪ Location: "SubType" or "النوع الفرعي"
    ▪ If invalid: Re-extract or use property_type value

    ✅ **usage** (الإستخدام):
    ▪ Common values: "Commercial", "Residential", "Mixed"
    ▪ Arabic: "تجاري", "سكني", "مختلط"
    ▪ Location: "Usage" or "الإستخدام"
    ▪ If invalid: Re-extract usage category

    ✅ **size** (المساحة):
    ▪ Format: "X.XX Sq.m" (English) or "X.XX متر مربع" (Arabic)
    ▪ MUST include 2 decimal places
    ▪ MUST include unit (Sq.m or متر مربع)
    ▪ Example: "10.00 Sq.m", "10.00 متر مربع"
    ▪ Location: "Size" or "المساحة"
    ▪ Validation: \\d+\\.\\d{{2}}\\s(?:Sq\\.m|متر مربع)
    ▪ If invalid: Re-extract and ensure ".00" suffix and unit

    🎯 ARABIC TRANSLATION RULES

    **"Al" Prefix Handling:**
    ▪ If English has "Al": "Al Garhoud" → Arabic: "الغارحود" (keep ال prefix)
    ▪ If English without "Al": "GARHOUD" → Arabic: "غارحود" (no ال prefix)

    **Standard Translations:**
    ▪ "United Arab Emirates" → "الإمارات العربية المتحدة"
    ▪ "DED-Dubai" / "Dubai Economy" → "دائرة التنمية الاقتصادية"
    ▪ "Commercial" → "تجاري"
    ▪ "Residential" → "سكني"
    ▪ "Office" → "مكتب"
    ▪ "Apartment" → "شقة"
    ▪ "Villa" → "فيلا"
    ▪ "Shop" → "محل"

    📍 DOCUMENT STRUCTURE REFERENCE

    **OWNER SECTION (المالك):**
    - Owner Name / اسم المالك
    - Owner Number / رقم المالك (5-7 digits)
    - Nationality / الجنسية

    **LESSOR SECTION (المؤجر):**
    - Lessor Name / اسم المؤجر
    - License Number / رقم الرخصة (6-7 digits)
    - License Issuer / جهة إصدار الرخصة
    - Tel. No / رقم الهاتف (with 971 code)
    - E-mail / البريد الإلكتروني

    **TENANT SECTION (المستأجر):**
    - Tenant Name / اسم المستأجر
    - Tenant No / رقم المستأجر (16 digits starting with 04)
    - Initial App./Exp. / رقم الموافقة و تاريخ الانتهاء
    - License Issuer / جهة إصدار الرخصة

    **CONTRACT DETAILS (تفاصيل عقد الإيجار):**
    - Start Date / تاريخ البدء (DD-MM-YYYY)
    - End Date / تاريخ الإنتهاء (DD-MM-YYYY)

    **PROPERTY DETAILS (تفاصيل العقار):**
    - Building Name/No / إسم المبنى/رقم المبنى ⚠️ (for building_name)
    - Land Area / المنطقة ⚠️ (for area field - NOT building!)
    - Plot Number / رقم الأرض (XXX-XXX format)
    - Makani No / رقم مكاني (XXXXX XXXXX format)
    - Property No. / رقم العقار (XXX-XX format)
    - Type / النوع (property type)
    - SubType / النوع الفرعي (property subtype)
    - Usage / الإستخدام (Commercial/Residential)
    - Size / المساحة (X.XX Sq.m)

    ✅ VALIDATION REQUIREMENTS BEFORE OUTPUT

    Your extraction is ONLY valid if ALL of these conditions are met:

    🔴 CRITICAL FIELDS (MUST ALL BE COMPLETE):
    1. ✓ contract_number: Exactly 16 digits, starts with "01"
    2. ✓ owner_name: Complete name, ≥3 characters
    3. ✓ tenant_company: Complete name, ≥3 characters
    4. ✓ start_date: Format DD-MM-YYYY, valid date
    5. ✓ end_date: Format DD-MM-YYYY, valid date, after start_date

    🟡 MINIMUM THRESHOLD:
    ✓ At least 18 out of 25 fields MUST be complete in BOTH English and Arabic

    🟢 FORMAT VALIDATIONS:
    ✓ contract_number: ^01\\d{{14}}$
    ✓ tenant_number: ^04\\d{{14}}$
    ✓ owner_number: 5-7 digits
    ✓ All dates: DD-MM-YYYY format
    ✓ building_name ≠ area (must be different values)
    ✓ size: Includes ".XX Sq.m" or ".XX متر مربع"
    ✓ makani_number: XXXXX XXXXX format
    ✓ plot_number: XXX-XXX format
    ✓ lessor_phone: Contains "971" and ≥10 digits
    ✓ lessor_email: Contains "@" and valid domain

    🚫 FORBIDDEN VALUES (NOT ALLOWED):
    ✗ Empty strings: ""
    ✗ Null values: null
    ✗ Placeholder text: "N/A", "Not Available", "Unknown"
    ✗ Truncation markers: "...", single letters only
    ✗ Partial values: "97" (for phone), "01" (for contract), "Sq.m" (without number)

    📤 OUTPUT FORMAT (STRICT JSON)

    {{
    "english": {{
        "contract_number": "0120241230004974",
        "registration_date": "30-12-2024",
        "owner_name": "SAMPLE OWNER FULL NAME",
        "owner_number": "171445",
        "owner_nationality": "United Arab Emirates",
        "lessor_company": "SAMPLE LESSOR COMPANY LLC",
        "lessor_license_number": "1326400",
        "lessor_license_issuer": "DED-Dubai",
        "lessor_phone": "9710523276602",
        "lessor_email": "lessor@samplecompany.ae",
        "tenant_company": "SAMPLE TENANT COMPANY L.L.C",
        "tenant_number": "0420241230004964",
        "tenant_license": "1495267 / 19-06-2025",
        "tenant_license_issuer": "DED-Dubai",
        "start_date": "30-12-2024",
        "end_date": "29-12-2025",
        "building_name": "GARHOUD",
        "area": "Al Garhoud",
        "plot_number": "214-266",
        "makani_number": "32607 94119",
        "property_number": "106-19",
        "property_type": "Office",
        "property_subtype": "Office",
        "usage": "Commercial",
        "size": "10.00 Sq.m"
    }},
    "arabic": {{
        "رقم_العقد": "0120241230004974",
        "تاريخ_التسجيل": "30-12-2024",
        "اسم_المالك": "اسم المالك النموذجي",
        "رقم_المالك": "171445",
        "جنسية_المالك": "الإمارات العربية المتحدة",
        "اسم_المؤجر": "اسم الشركة المؤجرة النموذجية",
        "رقم_رخصة_المؤجر": "1326400",
        "جهة_إصدار_رخصة_المؤجر": "دائرة التنمية الاقتصادية",
        "هاتف_المؤجر": "9710523276602",
        "بريد_المؤجر": "lessor@samplecompany.ae",
        "اسم_المستأجر": "اسم الشركة المستأجرة النموذجية",
        "رقم_المستأجر": "0420241230004964",
        "رخصة_المستأجر": "1495267 / 19-06-2025",
        "جهة_إصدار_رخصة_المستأجر": "دائرة التنمية الاقتصادية",
        "تاريخ_البدء": "30-12-2024",
        "تاريخ_الإنتهاء": "29-12-2025",
        "اسم_المبنى": "غارحود",
        "المنطقة": "الغارحود",
        "رقم_الأرض": "214-266",
        "رقم_مكاني": "32607 94119",
        "رقم_العقار": "106-19",
        "نوع_العقار": "مكتب",
        "نوع_العقار_الفرعي": "مكتب",
        "الإستخدام": "تجاري",
        "المساحة": "10.00 متر مربع"
    }},
    "extraction_metadata": {{
        "double_pass_validation": "completed",
        "pass_1_pass_2_match_count": 23,
        "re_extracted_fields": ["building_name", "area"],
        "critical_fields_status": "all_valid",
        "total_fields_completed": 25,
        "extraction_confidence": "high",
        "format_validation_passed": true,
        "minimum_threshold_met": true
    }}
    }}

    ❌ FAILURE RESPONSE (If Extraction Fails After All Attempts)

    If you CANNOT extract all 5 CRITICAL fields after re-extraction attempts, return:

    {{
    "extraction_status": "FAILED",
    "failed_critical_fields": ["field_name1", "field_name2"],
    "reason": "Specific reason why extraction failed",
    "partial_data_available": true/false,
    "recommendation": "Document may be unclear/damaged in these sections"
    }}

    🚀 FINAL INSTRUCTIONS

    1. Perform PASS 1 extraction → Store all 25 fields
    2. Perform PASS 2 extraction → Store all 25 fields independently
    3. Compare both passes → Identify mismatches
    4. Re-extract mismatched fields → Validate format
    5. Verify ALL 5 critical fields are complete and valid
    6. Verify at least 18/25 fields are complete
    7. Verify building_name ≠ area
    8. Return JSON ONLY when ALL validations pass

    ⚠️ IMPORTANT: Return ONLY the JSON object. NO markdown formatting, NO ```json blocks, NO explanatory text before or after the JSON.

    BEGIN EXTRACTION NOW."""

    @retry_with_backoff(max_retries=3, base_delay=10, label="Ejari API")
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
            "max_tokens": 3500,
        }

        try:
            response = bedrock_client.post(self.api_url, headers=headers, json=data, timeout=API_TIMEOUT_SECONDS)

            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Server temporarily unavailable")

            if response.status_code == 429:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Rate limit exceeded")

            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            raise RuntimeError(f"Ejari API failed: Request timeout after {API_TIMEOUT_SECONDS} seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ejari API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")

    def extract_with_ai(self, raw_text: str, model_choice: str = "llama") -> Tuple[Dict, Dict]:
        """Extract bilingual Ejari fields using AI - DOUBLE-PASS EXTRACTION WITH VALIDATION"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME
        
        prompt = f"Document Text:\n{raw_text[:20000]}"

        response = self.call_ai_api(prompt, model_name)

        if response and not response.startswith("API Error"):
            try:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group()
                    
                    # Clean JSON
                    json_str = re.sub(r',\s*}', '}', json_str)
                    json_str = re.sub(r',\s*]', ']', json_str)
                    json_str = json_str.replace('\n', ' ')
                    json_str = re.sub(r'\s+', ' ', json_str)
                    
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logger.error(f"Ejari JSON decode error: {e}")
                        # Try fixing
                        json_str = re.sub(r'//.*?\n', '', json_str)
                        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                        json_str = re.sub(r'(\w+):', r'"\1":', json_str)
                        
                        try:
                            data = json.loads(json_str)
                        except:
                            return self.get_empty_fields()
                    
                    english_data = data.get("english", {})
                    arabic_data = data.get("arabic", {})
                    
                    # Ensure all fields
                    english_data = self.ensure_all_fields(english_data, ENGLISH_FIELDS)
                    arabic_data = self.ensure_all_fields(arabic_data, ARABIC_FIELDS)
                    
                    # Post-process with enhanced regex
                    english_data = self.post_process_data(english_data, raw_text)
                    arabic_data = self.post_process_data(arabic_data, raw_text)
                    
                    # Validate and fix field lengths
                    english_data = self.validate_field_lengths(english_data)
                    
                    return english_data, arabic_data
                    
            except Exception as e:
                logger.error(f"Ejari extraction failed: {e}")
                import traceback
                logger.error(traceback.format_exc())

        return self.get_empty_fields()

    def get_empty_fields(self) -> Tuple[Dict, Dict]:
        """Return empty dictionaries with all fields"""
        return (
            {field: "" for field in ENGLISH_FIELDS},
            {field: "" for field in ARABIC_FIELDS}
        )

    def ensure_all_fields(self, data: Dict, required_fields: list) -> Dict:
        """Ensure all required fields exist and are string-valued.

        prompt-remediation Phase 4: delegates to extraction_schema.validate_and_coerce
        (pydantic-backed) instead of a bare dict comprehension -- same shape in/out
        (every field present, string-valued, missing -> ""), but a field the model
        returned as a non-string now gets coerced and logged instead of silently
        flowing downstream untyped into regex-based post-processing.
        """
        return validate_and_coerce(data, required_fields, "EjariFields")

    def validate_field_lengths(self, data: Dict) -> Dict:
        """Validate and fix field lengths based on expected patterns"""
        validations = {
            'contract_number': (r'^\d{16}$', 'Should be 16 digits'),
            'tenant_number': (r'^04\d{14}$', 'Should be 16 digits starting with 04'),
            'owner_number': (r'^\d{5,7}$', 'Should be 5-7 digits'),
            'lessor_license_number': (r'^\d{6,7}$', 'Should be 6-7 digits'),
            'makani_number': (r'^\d{5}\s\d{5}$', 'Should be format XXXXX XXXXX'),
            'plot_number': (r'^\d{1,3}-\d{1,3}$', 'Should be format XXX-XXX'),
            'property_number': (r'^\d{2,3}-\d{1,2}$', 'Should be format XXX-XX'),
            'size': (r'^\d+\.\d{2}\s(?:Sq\.m|متر مربع)$', 'Should include unit'),
        }
        
        for field, (pattern, desc) in validations.items():
            if field in data and data[field]:
                if not re.match(pattern, str(data[field])):
                    logger.warning(f"{field} validation failed: {data[field]} - {desc}")
        
        return data

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """Fix incomplete values using enhanced regex fallback"""
        
        # Enhanced regex patterns with stricter matching
        incomplete_patterns = {
            "contract_number": [
                r'Contract No[:\s]+(\d{16})',
                r'رقم العقد[:\s]+(\d{16})',
                r'(?:Contract|EJARI).*?(?:No|ID)[:\s]+(\d{16})'
            ],
            "registration_date": [
                r'Registration Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'تاريخ التسجيل[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
            "owner_name": [
                r'Owner Name[:\s]+([A-Z\s]+?)(?:\n|Owner Number)',
                r'اسم المالك[:\s]+([\u0600-\u06FF\s]+?)(?:\n|رقم المالك)'
            ],
            "owner_number": [
                r'Owner Number[:\s]+(\d{5,7})',
                r'رقم المالك[:\s]*(\d{5,7})'
            ],
            "tenant_number": [
                r'Tenant No[:\s]+(04\d{14})',
                r'رقم المستأجر[:\s]+(04\d{14})'
            ],
            "lessor_phone": [
                r'Tel\.\s*No[:\s]+(971[|\d]+)',
                r'رقم الهاتف[:\s]+(971[|\d]+)'
            ],
            "lessor_email": [
                r'E-mail[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'البريد الإلكتروني[:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
            ],
            "lessor_license_number": [
                r'License Number[:\s]+(\d{6,7})',
                r'رقم الرخصة[:\s]+(\d{6,7})'
            ],
            "lessor_license_issuer": [
                r'License Issuer[:\s]+([A-Z\-]+)',
                r'جهة إصدار الرخصة[:\s]+([\u0600-\u06FF\s]+)'
            ],
            "tenant_license": [
                r'Initial App\./Exp\.[:\s]+(\d{6,7}\s*/\s*\d{2}-\d{2}-\d{4})',
                r'رقم الموافقة و تاريخ الانتهاء[:\s]+(\d{6,7}\s*/\s*\d{2}-\d{2}-\d{4})'
            ],
            "start_date": [
                r'Start Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'تاريخ البدء[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
            "end_date": [
                r'End Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'تاريخ الإنتهاء[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
            "building_name": [
                r'Building Name/No[:\s]+([A-Z\s]+?)(?:\n|Land Area)',
                r'إسم المبنى/رقم المبنى[:\s]+([\u0600-\u06FF\s]+?)(?:\n|المنطقة)'
            ],
            "area": [
                r'Land Area[:\s]+([A-Za-z\s]+?)(?:\n|Plot)',
                r'المنطقة[:\s]+([\u0600-\u06FF\s]+?)(?:\n|رقم الأرض)'
            ],
            "plot_number": [
                r'Plot Number[:\s]+(\d{1,3}-\d{1,3})',
                r'رقم الأرض[:\s]+(\d{1,3}-\d{1,3})'
            ],
            "makani_number": [
                r'Makani No[:\s]+(\d{5}\s+\d{5})',
                r'رقم مكاني[:\s]+(\d{5}\s+\d{5})'
            ],
            "property_number": [
                r'Property No\.[:\s]+(\d{2,3}-\d{1,2})',
                r'رقم العقار[:\s]+(\d{2,3}-\d{1,2})'
            ],
            "size": [
                r'Size[:\s]+(\d+\.\d{2}\s*\(Sq\.m\))',
                r'المساحة[:\s]+(\d+\.\d{2}\s*متر مربع)'
            ],
        }

        for field, patterns in incomplete_patterns.items():
            if field in data and (not data[field] or len(str(data[field])) < 2):
                for pattern in patterns:
                    match = re.search(pattern, raw_text, re.IGNORECASE | re.MULTILINE)
                    if match:
                        extracted_value = match.group(1).strip()
                        data[field] = extracted_value
                        logger.info(f"[REGEX FIX] {field}: {extracted_value}")
                        break

        # Special size formatting fix
        if 'size' in data and data['size']:
            size_val = str(data['size'])
            # Ensure proper format "X.XX Sq.m"
            size_match = re.search(r'(\d+(?:\.\d+)?)', size_val)
            if size_match:
                number = size_match.group(1)
                if '.' not in number:
                    number += '.00'
                elif len(number.split('.')[1]) == 1:
                    number += '0'
                data['size'] = f"{number} Sq.m"

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
            "missing_fields": []
        }

        non_empty_english = len([v for v in english_data.values() if v and str(v).strip()])
        
        logger.info(f"[VALIDATION] Ejari: {non_empty_english}/25 English fields")

        # Check critical fields
        critical_fields = ["contract_number", "owner_name", "tenant_company", "start_date", "end_date"]
        missing_critical = []
        
        for f in critical_fields:
            if f not in english_data or not english_data[f] or str(english_data[f]).strip() == "":
                missing_critical.append(f)
                validation["missing_fields"].append(f)
                validation["issues"].append(f"Missing critical field: {f}")

        # Threshold: 18 fields minimum (72% of 25)
        if missing_critical:
            validation["is_valid"] = False
            logger.info(f"[VALIDATION] Ejari INVALID: Missing critical: {missing_critical}")
        elif non_empty_english < 18:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/25 (need 18+)")
            logger.info(f"[VALIDATION] Ejari INVALID: Only {non_empty_english}/25 fields (need 18+)")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            logger.info(f"[VALIDATION] Ejari VALID: {non_empty_english}/25 fields")

        return validation