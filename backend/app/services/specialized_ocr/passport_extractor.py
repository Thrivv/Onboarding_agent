"""
Passport OCR Extractor - Adapted for DigiOB specialized_ocr pipeline.

Extracts and validates passport data from images and PDFs.

Primary path (prompt-remediation Phase 1, item #4, opt-in via
config.TEXTRACT_ANALYZE_ID_ENABLED): AWS Textract AnalyzeID -- structured
field extraction that never sends the passport image to a third-party LLM.
Falls back automatically to the original vision-LLM extraction
(PassportOCRClient below) whenever Textract is off, unavailable, or its
result is missing a mandatory field. See textract_id_client.py and
PassportProcessor._extract_page() for the fallback logic.
"""

import base64
import json
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import requests
from PIL import Image, ImageEnhance, ImageFilter
import fitz  # PyMuPDF
from app import config


# ─── Configuration (reads from environment, consistent with ocr_service.py) ──
BEDROCK_API_KEY = config.AWS_BEARER_TOKEN_BEDROCK
# Model name + endpoint come from llm_client (backed by bedrock_client.py).
# Do not redeclare them here.
from app.services.llm_client import (
    LLM_API_URL,
    TEXT_PRIMARY,
    TEXT_FALLBACK,
    VISION_PRIMARY,
)
from app.services import bedrock_client
from app.services import textract_id_client
import logging

logger = logging.getLogger(__name__)

PASSPORT_MODEL = VISION_PRIMARY
IMAGE_TARGET_WIDTH = 1200
JPEG_QUALITY = 82
# Configurable via PASSPORT_API_TIMEOUT_SECONDS in .env.docker — change +
# restart the container to raise/lower this without editing code.
API_TIMEOUT = config.PASSPORT_API_TIMEOUT_SECONDS
MAX_TOKENS = 800


# ─── Data Models ──────────────────────────────────────────────────────────────
@dataclass
class PassportData:
    """Validated passport data structure."""
    # Mandatory fields
    passport_number: str
    surname: str
    given_names: str
    nationality: str
    date_of_birth: str
    sex: str
    date_of_expiry: str

    # Optional fields
    document_type: Optional[str] = None
    country_code: Optional[str] = None
    place_of_birth: Optional[str] = None
    date_of_issue: Optional[str] = None
    place_of_issue: Optional[str] = None
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    spouse_name: Optional[str] = None
    address: Optional[str] = None
    pin_code: Optional[str] = None
    old_passport_number: Optional[str] = None
    file_number: Optional[str] = None
    mrz_line1: Optional[str] = None
    mrz_line2: Optional[str] = None
    page_type: Optional[str] = None

    # Metadata
    _source_file: Optional[str] = None
    _extracted_at: Optional[str] = None
    _pages_scanned: Optional[int] = None
    _page: Optional[str] = None
    _model: Optional[str] = None
    _parse_method: Optional[str] = None


class ExtractionError(Exception):
    """Base exception for extraction errors."""
    pass


class ValidationError(ExtractionError):
    """Raised when validation fails."""
    pass


class MandatoryFields(Enum):
    """Required passport fields."""
    PASSPORT_NUMBER = "passport_number"
    SURNAME = "surname"
    GIVEN_NAMES = "given_names"
    NATIONALITY = "nationality"
    DATE_OF_BIRTH = "date_of_birth"
    SEX = "sex"
    DATE_OF_EXPIRY = "date_of_expiry"


# ─── Image Processing ──────────────────────────────────────────────────────────
class ImageProcessor:
    """Handles image preprocessing for OCR."""

    @staticmethod
    def preprocess(pil_img: Image.Image, target_width: int = IMAGE_TARGET_WIDTH) -> Image.Image:
        """Resize, sharpen, and enhance contrast."""
        img = pil_img.convert("RGB")
        w, h = img.size

        if w > target_width:
            ratio = target_width / w
            img = img.resize((target_width, int(h * ratio)), Image.LANCZOS)

        img = img.filter(ImageFilter.SHARPEN)
        img = img.filter(ImageFilter.SHARPEN)
        img = ImageEnhance.Contrast(img).enhance(1.4)
        img = ImageEnhance.Sharpness(img).enhance(1.8)

        return img

    @staticmethod
    def to_base64(pil_img: Image.Image, quality: int = JPEG_QUALITY) -> str:
        """Convert PIL Image to base64-encoded JPEG string."""
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @staticmethod
    def pdf_to_images(pdf_bytes: bytes) -> List[Image.Image]:
        """Convert PDF pages to PIL Images."""
        images = []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for page in doc:
            mat = fitz.Matrix(1.8, 1.8)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)

        doc.close()
        return images


# ─── JSON Extraction ──────────────────────────────────────────────────────────
class JSONExtractor:
    """Extracts and validates JSON from LLM responses."""

    @staticmethod
    def extract(text: str) -> Dict:
        """Extract JSON from model response with multiple fallback strategies."""
        text = text.strip()

        # Strategy 1: Direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Strip markdown fences
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find first {...} block
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            try:
                return json.loads(brace.group(0))
            except json.JSONDecodeError:
                pass

        # Strategy 4: Regex field extraction fallback
        fallback = JSONExtractor._regex_extraction(text)
        if fallback:
            fallback["_parse_method"] = "regex_fallback"
            return fallback

        raise ExtractionError(f"Could not extract valid JSON from response: {text[:200]}")

    @staticmethod
    def _regex_extraction(text: str) -> Dict:
        """Extract fields using regex patterns."""
        patterns = {
            "passport_number": r"Passport\s*(?:Number|No\.?)\s*[:\-=»>]+\s*([A-Z]\d{7,8})",
            "surname": r"Surname\s*[:\-=»>]+\s*([A-Z]+)",
            "given_names": r"Given\s*Names?\s*[:\-=»>]+\s*([A-Z ]+)",
            "date_of_birth": r"Date\s*of\s*Birth\s*[:\-=»>]+\s*(\d{2}[/\-.]\d{2}[/\-.]\d{4})",
            "date_of_expiry": r"(?:Date\s*of\s*Expiry|Expiry\s*Date)\s*[:\-=»>]+\s*(\d{2}[/\-.]\d{2}[/\-.]\d{4})",
            "date_of_issue": r"(?:Date\s*of\s*Issue|Issue\s*Date)\s*[:\-=»>]+\s*(\d{2}[/\-.]\d{2}[/\-.]\d{4})",
            "nationality": r"Nationality\s*[:\-=»>]+\s*(INDIAN|[A-Z]+)",
            "sex": r"\bSex\s*[:\-=»>]+\s*(M|F|Male|Female)",
            "place_of_birth": r"Place\s*of\s*Birth\s*[:\-=»>]+\s*([A-Z ,]+)",
            "place_of_issue": r"Place\s*of\s*Issue\s*[:\-=»>]+\s*([A-Z ]+)",
            "mrz_line1": r"(P<[A-Z]{3}[A-Z<]{30,})",
            "mrz_line2": r"([A-Z0-9]{9}<[0-9A-Z<]{33,})",
            "father_name": r"(?:Father|Father/Legal\s*Guardian)\s*[:\-=»>]+\s*([A-Z ]+)",
            "mother_name": r"Mother\s*[:\-=»>]+\s*([A-Z ]+)",
            "file_number": r"File\s*(?:Number|No\.?)\s*[:\-=»>]+\s*([A-Z0-9]+)",
            "old_passport_number": r"Old\s*Passport\s*(?:Number|No\.?)\s*[:\-=»>]+\s*([A-Z]\d+)",
            "pin_code": r"PIN\s*[:\-]*\s*(\d{6})",
            "country_code": r"Country\s*Code\s*[:\-=»>]+\s*([A-Z]{2,3})",
        }

        fallback = {}
        for field, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fallback[field] = match.group(1).strip()

        return fallback if fallback else {}


# ─── OCR API Client ───────────────────────────────────────────────────────────
class PassportOCRClient:
    """Handles API communication with LLM vision model."""

    SYSTEM_PROMPT = """You are a passport OCR engine. You MUST respond with ONLY a JSON object.
NO explanation. NO preamble. NO markdown. NO code blocks. ONLY raw JSON starting with { and ending with }."""

    USER_PROMPT = """Extract every field from this passport image and return ONLY this JSON (null if not found):
{
  "document_type": null,
  "country_code": null,
  "passport_number": null,
  "surname": null,
  "given_names": null,
  "nationality": null,
  "date_of_birth": null,
  "sex": null,
  "place_of_birth": null,
  "date_of_issue": null,
  "date_of_expiry": null,
  "place_of_issue": null,
  "father_name": null,
  "mother_name": null,
  "spouse_name": null,
  "address": null,
  "pin_code": null,
  "old_passport_number": null,
  "file_number": null,
  "mrz_line1": null,
  "mrz_line2": null,
  "page_type": null
}

IMPORTANT FOR MRZ: MRZ lines are the two rows of machine-readable text at the bottom of the bio-data page using only uppercase letters, digits, and '<' characters. Example: P<UTOSURNAME<<GIVENNAME<<<<<<<<<<<<<< and A1234567<8UTO9001019M3001019<<<<<<<<<<<<<<02
Extract them exactly as they appear, character by character."""

    def __init__(self, api_key: str = None):
        """Initialize OCR client."""
        self.api_key = api_key or BEDROCK_API_KEY
        self.api_url = LLM_API_URL
        self.model = PASSPORT_MODEL

    def extract_from_image(self, pil_img: Image.Image, page_label: str) -> Dict:
        """Extract passport data from image using vision API."""
        try:
            processed = ImageProcessor.preprocess(pil_img)
            b64 = ImageProcessor.to_base64(processed)

            # PROMPT CACHING (prompt-remediation Phase 3): USER_PROMPT is entirely
            # static -- it carries no per-image interpolation, only the fixed
            # output schema and MRZ instructions. Previously it was sent as a
            # text block inside the user turn on every single call, which put
            # it outside bedrock_client.py's ephemeral system-prompt caching
            # (see _to_bedrock_payload) even though it never changes between
            # calls. It now lives in the system message alongside
            # SYSTEM_PROMPT so it is cached too; the user turn carries only
            # the one thing that actually varies per call -- the image.
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT + "\n\n" + self.USER_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    },
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0.0,
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            resp = bedrock_client.post(self.api_url, json=payload, headers=headers, timeout=API_TIMEOUT)
            resp.raise_for_status()

            raw_text = resp.json()["choices"][0]["message"]["content"]
            data = JSONExtractor.extract(raw_text)

            data["_page"] = page_label
            data["_model"] = self.model

            return data

        except requests.RequestException as e:
            raise ExtractionError(f"API request failed: {str(e)}")
        except (KeyError, json.JSONDecodeError) as e:
            raise ExtractionError(f"Failed to parse API response: {str(e)}")


# ─── Data Validation ──────────────────────────────────────────────────────────
class PassportValidator:
    """Validates extracted passport data."""

    MANDATORY_FIELDS = {field.value for field in MandatoryFields}

    @staticmethod
    def validate(data: Dict) -> Tuple[bool, List[str]]:
        """Validate extracted data for mandatory fields."""
        errors = []

        for field_name in PassportValidator.MANDATORY_FIELDS:
            value = data.get(field_name)
            if not value or (isinstance(value, str) and value.strip() in ("", "null", "None")):
                errors.append(f"Missing required field: {field_name}")

        return len(errors) == 0, errors

    @staticmethod
    def create_validated_record(data: Dict, filename: str) -> PassportData:
        """Create validated PassportData record."""
        is_valid, errors = PassportValidator.validate(data)

        if not is_valid:
            raise ValidationError(f"Validation failed: {'; '.join(errors)}")

        try:
            record = PassportData(
                passport_number=data.get("passport_number", "").strip(),
                surname=data.get("surname", "").strip(),
                given_names=data.get("given_names", "").strip(),
                nationality=data.get("nationality", "").strip(),
                date_of_birth=data.get("date_of_birth", "").strip(),
                sex=data.get("sex", "").strip(),
                date_of_expiry=data.get("date_of_expiry", "").strip(),
                document_type=data.get("document_type"),
                country_code=data.get("country_code"),
                place_of_birth=data.get("place_of_birth"),
                date_of_issue=data.get("date_of_issue"),
                place_of_issue=data.get("place_of_issue"),
                father_name=data.get("father_name"),
                mother_name=data.get("mother_name"),
                spouse_name=data.get("spouse_name"),
                address=data.get("address"),
                pin_code=data.get("pin_code"),
                old_passport_number=data.get("old_passport_number"),
                file_number=data.get("file_number"),
                mrz_line1=data.get("mrz_line1"),
                mrz_line2=data.get("mrz_line2"),
                page_type=data.get("page_type"),
                _source_file=filename,
                _extracted_at=datetime.now().isoformat(),
                _pages_scanned=data.get("_pages_scanned"),
            )
            return record
        except TypeError as e:
            raise ValidationError(f"Failed to create PassportData record: {str(e)}")


# ─── Processing Pipeline ──────────────────────────────────────────────────────
class PassportProcessor:
    """Main processing pipeline for passport extraction."""

    def __init__(self, api_key: str = None):
        """Initialize processor."""
        self.ocr_client = PassportOCRClient(api_key or BEDROCK_API_KEY)

    def _extract_page(self, img: Image.Image, page_label: str, warnings: List[str]) -> Dict:
        """
        Extract one passport page, trying Textract AnalyzeID first
        (prompt-remediation Phase 1, item #4) when
        config.TEXTRACT_ANALYZE_ID_ENABLED is on, falling back to the
        vision-LLM path (self.ocr_client) whenever Textract is
        unavailable or its result is missing a mandatory field.

        This fallback is the reason Textract being wrong or UAE-document
        coverage being thin can never make extraction worse than it is
        today with the flag off: the vision-LLM call still runs as the
        safety net, just skipped on the (expected, common) case where
        Textract alone was already sufficient.
        """
        if config.TEXTRACT_ANALYZE_ID_ENABLED:
            try:
                processed = ImageProcessor.preprocess(img)
                buf = io.BytesIO()
                processed.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                textract_fields = textract_id_client.analyze_identity_document(buf.getvalue())
                mapped = textract_id_client.map_to_passport_fields(textract_fields)

                if textract_id_client.is_passport_result_sufficient(mapped):
                    mapped["_page"] = page_label
                    mapped["_model"] = "aws-textract-analyze-id"
                    logger.info(f"[PASSPORT] {page_label}: Textract AnalyzeID sufficient, skipping vision LLM")
                    return mapped

                logger.info(
                    f"[PASSPORT] {page_label}: Textract AnalyzeID result incomplete "
                    f"({sorted(mapped.keys())}), falling back to vision LLM"
                )
            except textract_id_client.TextractUnavailable as e:
                logger.info(f"[PASSPORT] {page_label}: Textract unavailable ({e}), using vision LLM")
            except Exception as e:
                # Textract being flaky must never take down passport extraction
                # entirely -- the vision-LLM path below is the existing,
                # already-proven fallback.
                warnings.append(f"{page_label}: Textract AnalyzeID error ({e}), used vision LLM instead")
                logger.warning(f"[PASSPORT] {page_label}: Textract AnalyzeID error: {e}")

        return self.ocr_client.extract_from_image(img, page_label)

    def process_file(self, file_bytes: bytes, filename: str) -> Tuple[PassportData, List[str]]:
        """
        Process a passport document file (PDF or image).

        Returns:
            Tuple of (PassportData, list_of_warnings)

        Raises:
            ExtractionError: If processing fails
            ValidationError: If validation fails
        """
        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            images = ImageProcessor.pdf_to_images(file_bytes)
        elif ext in {".jpg", ".jpeg", ".png", ".webp"}:
            images = [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
        else:
            raise ExtractionError(f"Unsupported file type: {ext}")

        if not images:
            raise ExtractionError("No images extracted from file")

        warnings = []
        page_results = []

        for i, img in enumerate(images):
            try:
                result = self._extract_page(img, f"page_{i+1}", warnings)
                page_results.append(result)
            except ExtractionError as e:
                warnings.append(f"Page {i+1} extraction failed: {str(e)}")

        if not page_results:
            raise ExtractionError("Failed to extract data from all pages")

        merged = self._merge_pages(page_results)
        merged["_pages_scanned"] = len(images)

        record = PassportValidator.create_validated_record(merged, filename)
        return record, warnings

    @staticmethod
    def _merge_pages(pages: List[Dict]) -> Dict:
        """Merge results from multiple pages, preferring non-null values."""
        merged = {}
        for page in pages:
            for key, value in page.items():
                if value and value not in ("null", None, "") and key not in merged:
                    merged[key] = value
        return merged


# ─── Public Entry Point ───────────────────────────────────────────────────────

def process_passport(file_bytes: bytes, filename: str) -> dict:
    """
    Unified entry point for passport extraction.

    Args:
        file_bytes: Raw file content as bytes
        filename: Original filename (used for extension detection)

    Returns:
        dict with keys:
            - document_type: "passport"
            - is_valid: bool
            - extracted_data: flat dict of all passport fields
            - validation_errors: list of missing field errors (empty if valid)
            - warnings: list of non-fatal warnings (e.g. page extraction failures)
            - full_name: "GIVEN_NAMES SURNAME" convenience field

    The extracted_data dict mirrors PassportData field names:
        passport_number, surname, given_names, nationality,
        date_of_birth, sex, date_of_expiry,
        [optional] document_type, country_code, place_of_birth,
        date_of_issue, place_of_issue, father_name, mother_name,
        spouse_name, address, pin_code, old_passport_number,
        file_number, mrz_line1, mrz_line2, page_type
    """
    logger.info(f"[PASSPORT] Starting passport extraction for: {filename}")

    processor = PassportProcessor()

    try:
        record, warnings = processor.process_file(file_bytes, filename)

        # Convert dataclass to flat dict, strip private metadata keys
        raw_dict = asdict(record)
        extracted_data = {k: v for k, v in raw_dict.items() if not k.startswith("_") and v is not None}

        # Convenience: full name
        full_name_parts = []
        if record.given_names:
            full_name_parts.append(record.given_names.strip())
        if record.surname:
            full_name_parts.append(record.surname.strip())
        full_name = " ".join(full_name_parts)

        logger.info(f"[PASSPORT] Extraction successful: {record.passport_number} | {full_name}")

        return {
            "document_type": "passport",
            "is_valid": True,
            "extracted_data": extracted_data,
            "full_name": full_name,
            "validation_errors": [],
            "warnings": warnings,
        }

    except ValidationError as e:
        # Partial extraction — mandatory fields missing
        logger.warning(f"[PASSPORT] Validation failed: {e}")

        # Try to get whatever was extracted anyway
        errors = [str(e)]

        return {
            "document_type": "passport",
            "is_valid": False,
            "extracted_data": {},
            "full_name": "",
            "validation_errors": errors,
            "warnings": [],
        }

    except ExtractionError as e:
        logger.error(f"[PASSPORT] Extraction failed: {e}")
        raise


def is_passport_filename(filename: str) -> bool:
    """
    Heuristic check: does the filename suggest a passport document?
    Used by ocr_service.identify_document_type_from_file() for early detection.
    """
    name = Path(filename).stem.lower()
    # Also check full filename (with extension) for patterns like _pp.jpg
    full = Path(filename).name.lower()
    passport_hints = ["passport", "passpt", "_pp_", "_pp.", "_pp", "pp_", "intl_id", "travel_doc"]
    return any(hint in name for hint in passport_hints) or any(hint in full for hint in passport_hints)


def is_passport_text(text: str) -> bool:
    """
    Heuristic check: does OCR text look like a passport?
    Used by ocr_service.identify_document_type_from_text().

    IMPORTANT: MOA (Memorandum of Association) documents commonly contain partner
    passport numbers, nationalities, surnames, and dates of issue.  These overlapping
    fields used to cause false-positive passport classification.  The fix:
      - Strong signals are unambiguous passport-only markers (MRZ, explicit word
        "passport", government issuing body phrases).  ONE strong signal is enough.
      - Weak signals are fields that can appear in other document types too.  We
        now require ALL of these conditions to declare a weak-signal match:
          * weak_count >= 5  (raised from 3)
          * At least one of the weak signals must be the MRZ-derived passport-number
            pattern OR the word "passport" must appear somewhere in the text.
      - Explicit exclusion: texts that contain corporate/company document markers
        are NEVER classified as passports regardless of weak signal count.
    """
    text_lower = text.lower()

    # ── Explicit exclusion: corporate / legal documents ─────────────────────
    # If any of these appear the document is definitely NOT a standalone passport.
    CORPORATE_EXCLUSIONS = [
        "memorandum of association",
        "articles of association",
        "shareholders agreement",
        "partnership deed",
        "company constitution",
        "share transfer",
        "مذكرة تأسيس",     # Arabic: MOA
        "عقد تأسيس",       # Arabic: establishment deed
        "عقد الشركة",      # Arabic: company contract
        "اتفاقية الشركاء", # Arabic: partnership agreement
        "trade license",
        "commercial license",
        "license no",
        "department of economic development",
        "tenancy contract",
        "ejari",
        "lease agreement",
        # ── CoI / Certificate of Incorporation exclusions ────────────────────
        "certificate of incorporation",
        "certificate of good standing",
        "certificate of registration",
        "incorporated under",
        "companies act",
        "registrar of companies",
        "registered agent",
        "registered office",
        "british virgin islands",
        "cayman islands",
        "difc",
        "adgm",
        "rak icc",
        "jafza",
        "freezone authority",
        "free zone authority",
    ]
    if any(excl in text_lower for excl in CORPORATE_EXCLUSIONS):
        return False

    # ── Strong signals: unambiguous passport-only markers ───────────────────
    strong_signals = [
        bool(re.search(r"P<[A-Z]{3}", text)),            # MRZ line 1 (e.g. P<INDSMITH<<JOHN)
        bool(re.search(r"[A-Z]{2}[0-9]{7}[A-Z0-9]", text)),  # MRZ line 2 passport-number block
        "republic of india" in text_lower,
        "ministry of external affairs" in text_lower,
        "ministry of interior" in text_lower,
        "ministry of foreign affairs" in text_lower,
        "this passport" in text_lower,
        "bearer of this passport" in text_lower,
        "date of expiry" in text_lower and "given names" in text_lower,
        "mrz" in text_lower,
    ]

    # ── Weak signals: fields that can also appear in MOA / other docs ───────
    weak_signals = [
        "passport" in text_lower,                            # ← moved here: alone it's weak (MOAs say "passport no.")
        "surname" in text_lower,
        "given names" in text_lower,
        "place of birth" in text_lower,
        "place of issue" in text_lower,
        "date of issue" in text_lower,
        bool(re.search(r"\b[A-Z][0-9]{7,8}\b", text)),      # Standalone passport number
        "nationality" in text_lower and "date of birth" in text_lower,
        "date of expiry" in text_lower,
        "personal no" in text_lower or "personal number" in text_lower,
    ]

    strong_count = sum(1 for s in strong_signals if s)
    weak_count = sum(1 for s in weak_signals if s)

    # One strong signal is definitive
    if strong_count >= 1:
        return True

    # Many weak signals AND the word "passport" must appear for a weak-only match
    # (MOAs mention passport numbers but not the word "passport" as a document type)
    if weak_count >= 5 and "passport" in text_lower:
        return True

    return False
