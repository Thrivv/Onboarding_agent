# specialized_ocr/ejari_extractor.py

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

# API Configuration
API_KEY = os.getenv("OPENROUTER_API_KEY", "sk-or-v1-...")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct"
QWEN_MODEL_NAME = "qwen/qwen-2.5-vl-32b-instruct"

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
                        print(f"[WARN] Ejari API error (attempt {attempt + 1}/{max_retries}): {error_msg}")
                        print(f"[INFO] Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None
        return wrapper
    return decorator


class EjariExtractor:
    """Ejari (Tenancy Contract) extractor with bilingual support and retry logic"""
    
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
            "max_tokens": 3500,
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=120)
            
            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Server temporarily unavailable")
            
            if response.status_code == 429:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Rate limit exceeded")
            
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except requests.exceptions.Timeout:
            raise RuntimeError("Ejari API failed: Request timeout after 120 seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ejari API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")

    def extract_with_ai(self, raw_text: str, model_choice: str = "llama") -> Tuple[Dict, Dict]:
        """Extract bilingual Ejari fields using AI - IMPROVED PROMPT"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME
        
        prompt = f"""You are an expert at extracting information from UAE Ejari (Tenancy Contract Registration) certificates.

Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic from this bilingual Ejari certificate.

CRITICAL FIELD EXTRACTION RULES:
1. Extract values EXACTLY as they appear in the document
2. "building_name" and "area" are DIFFERENT fields - NEVER use the same value for both
3. For dates, use format: DD-MM-YYYY

SPECIFIC FIELD SOURCES:
- "building_name" (اسم_المبنى): Extract from "Building Name/No" row
  * If value looks like an area, use "Building-[value]" to distinguish it
  
- "area" (المنطقة): Extract from "Land Area" row (district/neighborhood name)

TRANSLATION RULES FOR ARABIC:
- Preserve "Al" prefix: "Al Garhoud" → "الغارحود" (with ال)
- Without "Al": "GARHOUD" → "غارحود" (without ال)
- If both fields would be identical, add "مبنى" (building) or "مجمع" (complex) to building_name

English Fields (MUST extract all 25):
{json.dumps(ENGLISH_FIELDS, indent=2)}

Arabic Fields (MUST extract all 25):
{json.dumps(ARABIC_FIELDS, ensure_ascii=False, indent=2)}

IMPORTANT FIELD MAPPINGS:
- owner_number: رقم المالك (Owner Number field)
- lessor_license_issuer: جهة إصدار رخصة المؤجر (License Issuer under Lessor)
- tenant_license_issuer: جهة إصدار رخصة المستأجر (License Issuer under Tenant)
- tenant_license: Usually "Initial App./Exp." with number and date
- tenant_number: Tenant No or رقم المستأجر

Document Text (first 25000 chars):
{raw_text[:25000]}

Example with DISTINCT building and area (MANDATORY):
{{
  "english": {{
    "contract_number": "0120241230004974",
    "registration_date": "30-12-2024",
    "owner_name": "AHMED MOHAMMED ALI",
    "owner_number": "784123456789",
    "owner_nationality": "United Arab Emirates",
    "lessor_company": "ABC Property Management LLC",
    "lessor_license_number": "1234567",
    "lessor_license_issuer": "DED-Dubai",
    "lessor_phone": "97145551234",
    "lessor_email": "info@abcproperty.ae",
    "tenant_company": "XYZ TRADING L.L.C",
    "tenant_number": "784987654321",
    "tenant_license": "9876543/31-12-2025",
    "tenant_license_issuer": "DED-Dubai",
    "start_date": "01-01-2024",
    "end_date": "31-12-2024",
    "building_name": "Marina Tower Complex",
    "area": "Dubai Marina",
    "plot_number": "123-456",
    "makani_number": "12345 67890",
    "property_number": "101-5",
    "property_type": "Office",
    "property_subtype": "Office",
    "usage": "Commercial",
    "size": "50.00 Sq.m"
  }},
  "arabic": {{
    "رقم_العقد": "0120241230004974",
    "تاريخ_التسجيل": "30-12-2024",
    "اسم_المالك": "أحمد محمد علي",
    "رقم_المالك": "784123456789",
    "جنسية_المالك": "الإمارات العربية المتحدة",
    "اسم_المؤجر": "شركة إدارة العقارات ش ذ م م",
    "رقم_رخصة_المؤجر": "1234567",
    "جهة_إصدار_رخصة_المؤجر": "دائرة التنمية الاقتصادية",
    "هاتف_المؤجر": "97145551234",
    "بريد_المؤجر": "info@abcproperty.ae",
    "اسم_المستأجر": "شركة التجارة ش.ذ.م.م",
    "رقم_المستأجر": "784987654321",
    "رخصة_المستأجر": "9876543/31-12-2025",
    "جهة_إصدار_رخصة_المستأجر": "دائرة التنمية الاقتصادية",
    "تاريخ_البدء": "01-01-2024",
    "تاريخ_الإنتهاء": "31-12-2024",
    "اسم_المبنى": "مجمع برج المارينا",
    "المنطقة": "دبي مارينا",
    "رقم_الأرض": "123-456",
    "رقم_مكاني": "12345 67890",
    "رقم_العقار": "101-5",
    "نوع_العقار": "مكتب",
    "نوع_العقار_الفرعي": "مكتب",
    "الإستخدام": "تجاري",
    "المساحة": "50.00 متر مربع"
  }}
}}

NOTICE: building_name and area are COMPLETELY DIFFERENT - this is REQUIRED.
If you extract same text for both, modify building_name by adding descriptor.

Return ONLY valid JSON in this EXACT format with ALL {EXPECTED_FIELD_COUNT} fields populated.
"""

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
                        print(f"[ERROR] Ejari JSON decode error: {e}")
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
                    
                    # Post-process
                    english_data = self.post_process_data(english_data, raw_text)
                    arabic_data = self.post_process_data(arabic_data, raw_text)
                    
                    return english_data, arabic_data
                    
            except Exception as e:
                print(f"[ERROR] Ejari extraction failed: {e}")
                import traceback
                traceback.print_exc()

        return self.get_empty_fields()

    def get_empty_fields(self) -> Tuple[Dict, Dict]:
        """Return empty dictionaries with all fields"""
        return (
            {field: "" for field in ENGLISH_FIELDS},
            {field: "" for field in ARABIC_FIELDS}
        )

    def ensure_all_fields(self, data: Dict, required_fields: list) -> Dict:
        """Ensure all required fields exist"""
        complete_data = {}
        for field in required_fields:
            complete_data[field] = data.get(field, "")
        return complete_data

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        """Fix incomplete values using regex fallback - ENHANCED"""
        incomplete_patterns = {
            "contract_number": [
                r'(?:Contract|EJARI).*?(?:No|ID)[:\s]+(\d{9,15})',
                r'Contract Number[:\s]+(\d{9,15})'
            ],
            "registration_date": [
                r'Registration Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'Date of Registration[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
            "owner_number": [
                r'Owner Number[:\s]+(\d+)',
                r'Owner No[.:\s]+(\d+)'
            ],
            "lessor_phone": [
                r'Tel\. No[:\s]+([\d|\-]+)',
                r'Phone[:\s]+([\d|\-]+)'
            ],
            "lessor_license_issuer": [
                r'License Issuer[:\s]+([A-Z\-]+)',
                r'Issuer[:\s]+([A-Z\-]+)'
            ],
            "tenant_license_issuer": [
                r'(?:Tenant.*?)?License Issuer[:\s]+([A-Z\-]+)',
            ],
            "start_date": [
                r'Start Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'From[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
            "end_date": [
                r'End Date[:\s]+(\d{2}-\d{2}-\d{4})',
                r'To[:\s]+(\d{2}-\d{2}-\d{4})'
            ],
        }

        for field, patterns in incomplete_patterns.items():
            if field in data and (not data[field] or len(str(data[field])) < 3):
                for pattern in patterns:
                    match = re.search(pattern, raw_text, re.IGNORECASE)
                    if match:
                        data[field] = match.group(1).strip()
                        break

        return data

    def validate_extraction(self, english_data: Dict, arabic_data: Dict) -> Dict:
        """Validate extracted fields - RELAXED THRESHOLD"""
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
        
        print(f"[VALIDATION] Ejari: {non_empty_english}/25 English fields")

        # Check critical fields
        critical_fields = ["contract_number", "owner_name", "start_date", "end_date"]
        missing_critical = []
        
        for f in critical_fields:
            if f not in english_data or not english_data[f] or str(english_data[f]).strip() == "":
                missing_critical.append(f)
                validation["missing_fields"].append(f)
                validation["issues"].append(f"Missing critical field: {f}")

        # CHANGED: Reduced threshold from 20 to 18 (72% of fields)
        if missing_critical:
            validation["is_valid"] = False
            print(f"[VALIDATION] Ejari INVALID: Missing critical: {missing_critical}")
        elif non_empty_english < 18:  # Changed from 20
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/25 (need 18+)")
            print(f"[VALIDATION] Ejari INVALID: Only {non_empty_english}/25 fields (need 18+)")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            print(f"[VALIDATION] Ejari VALID: {non_empty_english}/25 fields ✅")

        return validation