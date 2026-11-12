# specialized_ocr/bvi_extractor.py
"""
Certificate of Incorporation (CoI) Extractor
=============================================
Handles extraction from Certificate of Incorporation documents issued by
offshore / international jurisdictions (BVI, Cayman, DIFC, ADGM, etc.)
as well as onshore UAE free-zone certificates.

The extractor focuses on:
  - Registered company information (name, registration number, jurisdiction)
  - Incorporation date
  - Directors and Shareholders list with share percentages

Output matches the same extractor contract used by MOAExtractor / TradeLicenseExtractor:
    extract() → dict with document_type, is_valid, extracted_fields, ...
"""

import os
import re
import json
import time
import requests
import fitz          # PyMuPDF
from functools import wraps
from typing import Dict, List, Optional, Tuple
from app import config

# ============================================================================
# API CONFIGURATION
# ============================================================================

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
import logging
from app.utils.retry import retry_with_backoff as _retry_with_backoff

logger = logging.getLogger(__name__)

API_URL = LLM_API_URL
# Configurable via BVI_API_TIMEOUT_SECONDS in .env.docker — change + restart
# the container to raise/lower this without editing code.
API_TIMEOUT_SECONDS = config.BVI_API_TIMEOUT_SECONDS

LLAMA_MODEL_NAME = TEXT_PRIMARY
QWEN_MODEL_NAME  = TEXT_FALLBACK

# ============================================================================
# EXPECTED FIELDS
# ============================================================================

COI_FIELDS = [
    "company_name",
    "registration_number",
    "jurisdiction",
    "incorporation_date",
    "company_type",
    "registered_agent",
    "registered_office",
    "directors_and_shareholders",   # list of dicts
    "share_capital",
    "currency",
]

# Minimum required fields for the document to be considered valid
REQUIRED_FIELDS = {
    "company_name",
    "registration_number",
    "incorporation_date",
    "directors_and_shareholders",
}


# ============================================================================
# RETRY DECORATOR  (same pattern as MOAExtractor)
# ============================================================================



# ============================================================================
# EXTRACTOR CLASS
# ============================================================================

class BVIExtractor:
    """
    Certificate of Incorporation extractor.

    Usage
    -----
    extractor = BVIExtractor(api_key=config.AWS_BEARER_TOKEN_BEDROCK)

    with open("certificate.pdf", "rb") as f:
        file_bytes = f.read()

    result = extractor.extract(file_bytes, filename="certificate.pdf")
    # result["is_valid"]           → bool
    # result["extracted_fields"]   → dict with COI_FIELDS
    # result["directors_and_shareholders"] → list of {name, role, share_percentage}
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY
        self.api_url = API_URL

    # ------------------------------------------------------------------ #
    #  TEXT EXTRACTION                                                     #
    # ------------------------------------------------------------------ #

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = ""
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                text += f"\n--- Page {page_num + 1} ---\n{page.get_text()}\n"
            doc.close()
            return text
        except Exception as e:
            return f"[PDF EXTRACTION ERROR] {e}"

    # ------------------------------------------------------------------ #
    #  AI CALL                                                             #
    # ------------------------------------------------------------------ #

    @_retry_with_backoff(max_retries=3, base_delay=5, label="CoI API")
    def _call_api(self, prompt: str, model_name: str = None) -> str:
        """Call the Bedrock API with retry logic."""
        if not self.api_key:
            raise RuntimeError("Bedrock API key not configured")

        model = model_name or LLAMA_MODEL_NAME
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 3000,
        }

        response = bedrock_client.post(self.api_url, headers=headers, json=payload, timeout=API_TIMEOUT_SECONDS)

        if response.status_code in [502, 503, 504]:
            raise RuntimeError(f"CoI API server error: {response.status_code}")
        if response.status_code == 429:
            raise RuntimeError(f"CoI API rate limit exceeded")

        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------ #
    #  AI EXTRACTION                                                       #
    # ------------------------------------------------------------------ #

    # PROMPT CACHING (prompt-remediation Phase 3): everything that does not
    # change between calls -- role, JSON schema, extraction rules -- lives
    # here as a system prompt instead of being re-sent as part of the user
    # turn on every single call. bedrock_client.py already applies
    # ephemeral prompt caching to any system-role text automatically (see
    # _to_bedrock_payload); moving this here is what makes that caching
    # apply to CoI extraction, where before it was baked directly into the
    # user prompt and reprocessed as fresh input tokens every time. The
    # instruction text itself is UNCHANGED, character-for-character, from
    # the previous _build_extraction_prompt -- only its position moved, so
    # extraction behaviour is not expected to change.
    _SYSTEM_PROMPT = """You are a specialist in extracting structured data from Certificate of Incorporation documents from any jurisdiction (BVI, Cayman, DIFC, ADGM, UAE mainland, etc.).

Extract ALL available information from the document text you are given.
Pay special attention to the list of directors and shareholders with their ownership percentages.

Return ONLY a valid JSON object with this exact structure (use empty string "" for missing fields, empty list [] for missing lists):

{
  "company_name": "<full registered company name>",
  "registration_number": "<company registration / incorporation number>",
  "jurisdiction": "<country or territory of incorporation e.g. British Virgin Islands>",
  "incorporation_date": "<date in DD/MM/YYYY or as-found>",
  "company_type": "<e.g. Business Company, Private Limited, etc.>",
  "registered_agent": "<name of registered agent if present>",
  "registered_office": "<registered office address>",
  "share_capital": "<authorised / issued share capital amount>",
  "currency": "<currency of share capital e.g. USD>",
  "directors_and_shareholders": [
    {
      "name": "<full name of individual or entity>",
      "role": "<Director | Shareholder | Director & Shareholder>",
      "nationality": "<nationality if stated>",
      "share_percentage": <numeric percentage as number e.g. 70 — use 0 if not stated or is a director only>,
      "number_of_shares": "<number of shares if stated>"
    }
  ]
}

IMPORTANT RULES:
1. Return ONLY the JSON object — no preamble, no explanation, no markdown fences.
2. share_percentage must be a NUMBER (not a string with % symbol).
3. If percentage is not explicitly stated but shares are, compute percentage from total shares.
4. Include ALL directors and ALL shareholders even if they are the same person.
5. Do NOT invent data — use empty string or 0 for unknown fields."""

    def _build_extraction_prompt(self, raw_text: str) -> str:
        return f"Document Text:\n{raw_text[:6000]}"

    def _extract_with_ai(self, raw_text: str, model_name: str = None) -> Dict:
        """Call AI to extract CoI fields. Returns parsed dict."""
        prompt = self._build_extraction_prompt(raw_text)

        try:
            response_text = self._call_api(prompt, model_name)
        except Exception as e:
            logger.error(f"CoI AI extraction failed: {e}")
            return {}

        # Parse JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if not json_match:
            logger.warning(f"No JSON found in CoI AI response. Raw: {response_text[:300]}")
            return {}

        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError as e:
            logger.warning(f"CoI JSON parse failed: {e}. Attempting cleanup...")
            # Light cleanup
            json_str = json_match.group(0)
            json_str = re.sub(r',\s*}', '}', json_str)   # trailing commas
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                return json.loads(json_str)
            except Exception:
                logger.error(f"CoI JSON parse failed after cleanup")
                return {}

    # ------------------------------------------------------------------ #
    #  VALIDATION                                                          #
    # ------------------------------------------------------------------ #

    def _validate(self, data: Dict) -> Dict:
        """
        Validate extracted CoI data.
        Returns a validation dict with is_valid, present_fields, missing_fields, issues.
        """
        issues = []
        present = []
        missing = []

        for field in REQUIRED_FIELDS:
            value = data.get(field)
            if value and value != "" and value != [] and value != 0:
                present.append(field)
            else:
                missing.append(field)
                issues.append(f"Missing required field: {field}")

        # Additional check: directors_and_shareholders must be a non-empty list
        das = data.get("directors_and_shareholders", [])
        if not isinstance(das, list) or len(das) == 0:
            if "directors_and_shareholders" not in missing:
                missing.append("directors_and_shareholders")
                issues.append("directors_and_shareholders is empty or invalid")

        # Check share percentages sum reasonably (warn if not ~100%)
        shareholders = [p for p in das if isinstance(p, dict) and p.get("share_percentage", 0) > 0]
        if shareholders:
            total_pct = sum(float(p.get("share_percentage", 0)) for p in shareholders)
            if not (95 <= total_pct <= 105):
                issues.append(
                    f"Share percentages sum to {total_pct:.1f}% (expected ~100%)"
                )
                logger.warning(f"CoI share percentages sum = {total_pct:.1f}%")

        return {
            "is_valid": len(missing) == 0,
            "present_fields": present,
            "missing_fields": missing,
            "issues": issues,
        }

    # ------------------------------------------------------------------ #
    #  PUBLIC API  — main entry point                                      #
    # ------------------------------------------------------------------ #

    def extract(
        self,
        file_bytes: bytes,
        filename: str = "certificate.pdf",
        model_name: str = None,
    ) -> Dict:
        """
        Full extraction pipeline for a Certificate of Incorporation.

        Returns
        -------
        {
            "document_type": "certificate_of_incorporation",
            "filename": str,
            "is_valid": bool,
            "extracted_fields": {
                "company_name": str,
                "registration_number": str,
                "jurisdiction": str,
                "incorporation_date": str,
                "company_type": str,
                "registered_agent": str,
                "registered_office": str,
                "share_capital": str,
                "currency": str,
                "directors_and_shareholders": [ {name, role, nationality, share_percentage, number_of_shares} ]
            },
            "validation": { is_valid, present_fields, missing_fields, issues },
            "status_message": str,
            "raw_text": str (first 1000 chars),
        }
        """
        logger.info(f"\n[CoI EXTRACTOR] Processing: {filename}")

        # 1. Extract raw text
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            raw_text = self.extract_text_from_pdf(file_bytes)
        else:
            # For images — caller should have converted to text via OCR first.
            # Accept raw bytes interpreted as UTF-8 text fallback.
            try:
                raw_text = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                raw_text = ""

        if raw_text.startswith("[PDF EXTRACTION ERROR]") or len(raw_text.strip()) < 50:
            logger.error(f"CoI text extraction failed or returned insufficient text")
            return {
                "document_type": "certificate_of_incorporation",
                "filename": filename,
                "is_valid": False,
                "extracted_fields": {},
                "validation": {
                    "is_valid": False,
                    "present_fields": [],
                    "missing_fields": list(REQUIRED_FIELDS),
                    "issues": ["Text extraction failed"],
                },
                "status_message": "❌ FAILED: Could not extract text from CoI document",
                "raw_text": raw_text[:500],
            }

        logger.info(f"[CoI EXTRACTOR] Extracted {len(raw_text)} characters of text")

        # 2. AI extraction
        data = self._extract_with_ai(raw_text, model_name)

        # 3. Validate
        validation = self._validate(data)

        # 4. Build result
        is_valid = validation["is_valid"]
        if is_valid:
            n_shareholders = len([
                p for p in data.get("directors_and_shareholders", [])
                if p.get("share_percentage", 0) > 0
            ])
            status_msg = (
                f"✅ VALID: Certificate of Incorporation extracted — "
                f"{data.get('company_name', '')} | "
                f"{data.get('jurisdiction', '')} | "
                f"{n_shareholders} shareholder(s)"
            )
        else:
            status_msg = f"❌ INCOMPLETE: {', '.join(validation['issues'][:3])}"

        logger.info(f"[CoI EXTRACTOR] {status_msg}")

        return {
            "document_type": "certificate_of_incorporation",
            "filename": filename,
            "is_valid": is_valid,
            "extracted_fields": data,
            "validation": validation,
            "status_message": status_msg,
            "raw_text": raw_text[:1000],
        }
