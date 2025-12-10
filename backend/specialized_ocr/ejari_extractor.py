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
            "temperature": 0.0,  # Changed to 0.0 for maximum consistency
            "max_tokens": 3500,
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data, timeout=60)
            
            if response.status_code in [502, 503, 504]:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Server temporarily unavailable")
            
            if response.status_code == 429:
                raise RuntimeError(f"Ejari API failed: {response.status_code} Rate limit exceeded")
            
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except requests.exceptions.Timeout:
            raise RuntimeError("Ejari API failed: Request timeout after 60 seconds")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ejari API failed: {response.status_code if 'response' in locals() else 'Network error'} {str(e)}")

    def extract_with_ai(self, raw_text: str, model_choice: str = "llama") -> Tuple[Dict, Dict]:
        """Extract bilingual Ejari fields using AI - ENHANCED PROMPT WITH STRICTER RULES"""
        model_name = QWEN_MODEL_NAME if model_choice == "qwen" else LLAMA_MODEL_NAME
        
        prompt = f"""You are an expert AI model specialized in extracting information from UAE Ejari (Tenancy Contract Registration) certificates. Extract ALL {EXPECTED_FIELD_COUNT} fields in BOTH English and Arabic.

**CRITICAL EXTRACTION RULES:**

1. **Exact Text Preservation**: Extract values EXACTLY as written in the document - no modifications, no interpretations
2. **Field Length Validation**: 
   - Owner Number: Typically 5-7 digits (e.g., "171445")
   - Tenant Number: 16-digit format "0YYYYMMDDNNNNNNN" (e.g., "0420241230004964")
   - Contract Number: 16-digit format "01YYYYMMDDNNNNN" (e.g., "0120241230004974")
   - Phone: 10-13 digits with country code (e.g., "9710523276602" or "971|0523276602")
   - License Number: 6-7 digits (e.g., "1326400", "1495267")
   - Makani Number: Format "XXXXX XXXXX" (e.g., "32607 94119")
   - Plot Number: Format "XXX-XXX" or "XX-X" (e.g., "214-266", "95-0")
   - Size: Format "X.XX Sq.m" or "X.XX متر مربع" (e.g., "10.00 Sq.m")

3. **Date Format Consistency**: ALL dates must be DD-MM-YYYY (e.g., "30-12-2024", never "2024-12-30")

4. **Building vs Area Distinction** (MANDATORY):
   - "building_name" (اسم_المبنى): Extract from "Building Name/No" row
   - "area" (المنطقة): Extract from "Land Area" row  
   - These MUST be different values
   - If source shows same text, prefix building with "Building-" or "مبنى-"

5. **Arabic Translation Accuracy**:
   - Preserve "Al" prefix: "Al Garhoud" → "الغارحود" (keep ال)
   - Without "Al": "GARHOUD" → "غارحود" (no ال)
   - License Issuer: "DED-Dubai" → "دائرة التنمية الاقتصادية"
   - Usage: "Commercial" → "تجاري", "Residential" → "سكني"
   - Property Type: "Office" → "مكتب", "Apartment" → "شقة"

6. **Special Field Rules**:
   - tenant_license: Format "XXXXXXX / DD-MM-YYYY" (e.g., "1495267 / 19-06-2025")
   - lessor_phone & tenant_phone: Include full number with pipes preserved (e.g., "971|0523276602")
   - property_number: Format "XXX-XX" (e.g., "106-19")
   - Email: Must be valid email format

**FIELD MAPPING REFERENCE:**

English Fields (ALL 25 REQUIRED):
{json.dumps(ENGLISH_FIELDS, indent=2)}

Arabic Fields (ALL 25 REQUIRED):
{json.dumps(ARABIC_FIELDS, ensure_ascii=False, indent=2)}

**KEY FIELD LOCATIONS IN DOCUMENT:**

OWNER SECTION (المالك):
- Owner Name / اسم المالك
- Owner Number / رقم المالك (5-7 digits)
- Nationality / الجنسية

LESSOR SECTION (المؤجر):
- Lessor Name / اسم المؤجر
- License Number / رقم الرخصة
- License Issuer / جهة إصدار الرخصة
- Tel. No / رقم الهاتف
- E-mail / البريد الإلكتروني

TENANT SECTION (المستأجر):
- Tenant Name / اسم المستأجر
- Tenant No / رقم المستأجر (16 digits)
- Initial App./Exp. / رقم الموافقة و تاريخ الانتهاء
- License Issuer / جهة إصدار الرخصة

CONTRACT DETAILS (تفاصيل عقد الإيجار):
- Start Date / تاريخ البدء
- End Date / تاريخ الإنتهاء

PROPERTY DETAILS (تفاصيل العقار):
- Building Name/No / إسم المبنى/رقم المبنى
- Land Area / المنطقة (THIS IS AREA, NOT BUILDING!)
- Plot Number / رقم الأرض
- Land DM No / رقم البلدية
- Makani No / رقم مكاني
- Property No. / رقم العقار
- Type / النوع
- SubType / النوع الفرعي
- Usage / الإستخدام
- Size / المساحة

**Document Text:**
{raw_text[:28000]}

**OUTPUT FORMAT (STRICT JSON):**

{{
  "english": {{
    "contract_number": "0120241230004974",
    "registration_date": "30-12-2024",
    "owner_name": "DHAHER MOHAMMED DHAHER BIN DHAHER ALMHEIRI",
    "owner_number": "171445",
    "owner_nationality": "United Arab Emirates",
    "lessor_company": "startup router business center llc",
    "lessor_license_number": "1326400",
    "lessor_license_issuer": "DED-Dubai",
    "lessor_phone": "9710523276602",
    "lessor_email": "startuprouter.bc@gmail.com",
    "tenant_company": "THRIVV GROWTH TECHNOLOGY SERVICES L.L.C",
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
    "اسم_المالك": "ذاهر محمد ذاهر بن ذاهر المحييري",
    "رقم_المالك": "171445",
    "جنسية_المالك": "الإمارات العربية المتحدة",
    "اسم_المؤجر": "مركز ستارتاب روتر للأعمال ش ذ م م",
    "رقم_رخصة_المؤجر": "1326400",
    "جهة_إصدار_رخصة_المؤجر": "دائرة التنمية الاقتصادية",
    "هاتف_المؤجر": "9710523276602",
    "بريد_المؤجر": "startuprouter.bc@gmail.com",
    "اسم_المستأجر": "ثريف جروث للتقنية للخدمات ش.ذ.م.م",
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
  }}
}}

**VALIDATION CHECKLIST BEFORE RETURNING:**
✓ All 25 fields present in both English and Arabic
✓ Contract number is 16 digits starting with "01"
✓ Tenant number is 16 digits starting with "04"
✓ All dates are DD-MM-YYYY format
✓ building_name ≠ area (must be different)
✓ Size includes unit (Sq.m or متر مربع)
✓ Phone numbers are complete with country code
✓ Email is valid format

Return ONLY the JSON object with NO additional text, explanations, or markdown formatting."""

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
                    
                    # Post-process with enhanced regex
                    english_data = self.post_process_data(english_data, raw_text)
                    arabic_data = self.post_process_data(arabic_data, raw_text)
                    
                    # Validate and fix field lengths
                    english_data = self.validate_field_lengths(english_data)
                    
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
                    print(f"[WARN] {field} validation failed: {data[field]} - {desc}")
        
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
                        print(f"[REGEX FIX] {field}: {extracted_value}")
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
        
        print(f"[VALIDATION] Ejari: {non_empty_english}/25 English fields")

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
            print(f"[VALIDATION] Ejari INVALID: Missing critical: {missing_critical}")
        elif non_empty_english < 18:
            validation["is_valid"] = False
            validation["issues"].append(f"Insufficient fields: {non_empty_english}/25 (need 18+)")
            print(f"[VALIDATION] Ejari INVALID: Only {non_empty_english}/25 fields (need 18+)")
        else:
            validation["is_valid"] = True
            validation["issues"] = []
            print(f"[VALIDATION] Ejari VALID: {non_empty_english}/25 fields ✅")

        return validation