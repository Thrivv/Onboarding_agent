# specialized_ocr/trade_extractor.py

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
from dotenv import load_dotenv
from app import config

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
# This module deliberately does NOT call logging.basicConfig(). It used to, and
# because a library module is imported long before an application configures
# anything, that call was silently configuring root logging for the ENTIRE
# application — logging.basicConfig() is a no-op once root already has
# handlers, so whoever calls it first wins, and this module kept winning.
#
# The visible symptom: every log line in production rendered as
# "[INFO] <message>" with no timestamp, no logger name and no [request_id],
# rather than the format set up in app/logging_config.py — so the request-id
# correlation the API middleware provides was never actually visible. It also
# quietly attached a FileHandler writing trade_license_extraction.log into the
# process working directory.
#
# Configuration belongs to the entrypoint (app/main.py and
# app/services/reply_loop.py, both via app.logging_config.setup_logging()).
# Modules should only ever take a logger, which is all this now does.
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# API Configuration — from .env only, no hard-coded secrets
# ─────────────────────────────────────────────────────────────────────────────
API_KEY       = config.AWS_BEARER_TOKEN_BEDROCK or ""
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
from app.utils.retry import retry_with_backoff

API_URL       = LLM_API_URL
# Model tiering (prompt-remediation Phase 2, opt-in via
# config.MODEL_TIERING_ENABLED): Trade License extraction is one of the
# two tasks dumps/docs/bedrock-final-recommendation.md singles out for a
# stronger model, given its multi-step UBO/ownership-structure reasoning
# (single-owner, multi-owner, corporate-shareholder chains). Falls back
# to the default model automatically at the bedrock_client.post() level
# if the reasoning-tier model call itself fails -- see that module's
# _resolve_invoke_url().
LLAMA_MODEL   = config.BEDROCK_REASONING_MODEL_ID if config.MODEL_TIERING_ENABLED else TEXT_PRIMARY
QWEN_MODEL    = TEXT_FALLBACK

# Configurable via TRADE_LICENSE_API_TIMEOUT_SECONDS / DOC_EXTRACTION_MAX_RETRIES
# in .env.docker — change + restart the container to raise/lower without
# editing code.
REQUEST_TIMEOUT  = config.TRADE_LICENSE_API_TIMEOUT_SECONDS
MAX_RETRIES      = config.DOC_EXTRACTION_MAX_RETRIES
BASE_RETRY_DELAY = 5

# ─────────────────────────────────────────────────────────────────────────────
# Field lists
# ─────────────────────────────────────────────────────────────────────────────
MAX_ACTIVITIES = 15

def _build_activity_fields_en(prefix: str = "activity") -> List[str]:
    return [f"{prefix}_{i}" for i in range(1, MAX_ACTIVITIES + 1)]

def _build_activity_fields_ar(prefix: str = "النشاط") -> List[str]:
    return [f"{prefix}_{i}" for i in range(1, MAX_ACTIVITIES + 1)]

# ── Fixed fields ──────────────────────────────────────────────────────────────
_MO_FIXED_EN_PRE  = ["license_number", "main_license_number", "commercial_register_number",
                      "issue_date", "expiry_date", "receipt_number", "print_date",
                      "company_name_english", "company_name_arabic", "trade_name_english",
                      "trade_name_arabic", "legal_type", "duns_number"]
_MO_FIXED_EN_POST = ["phone", "fax", "mobile", "po_box",
                      "license_address", "parcel_id", "commerce_address",
                      "nominated_capital", "paid_capital", "currency", "number_of_shares",
                      "payment_voucher_number", "payment_mode", "payment_amount"]

_MO_FIXED_AR_PRE  = ["رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
                      "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
                      "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية",
                      "الاسم_التجاري_بالإنجليزية", "الاسم_التجاري_بالعربية",
                      "الشكل_القانوني", "رقم_دنز"]
_MO_FIXED_AR_POST = ["هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد",
                      "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
                      "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
                      "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع"]

MULTI_OWNER_ENGLISH_FIELDS = (
    _MO_FIXED_EN_PRE +
    _build_activity_fields_en() +
    _MO_FIXED_EN_POST
)
MULTI_OWNER_ARABIC_FIELDS = (
    _MO_FIXED_AR_PRE +
    _build_activity_fields_ar() +
    _MO_FIXED_AR_POST
)

# ── Single Owner ──────────────────────────────────────────────────────────────
_SO_FIXED_EN_PRE  = ["license_number", "main_license_number", "commercial_register_number",
                      "issue_date", "expiry_date", "receipt_number", "print_date",
                      "company_name_english", "company_name_arabic", "trade_name_english",
                      "trade_name_arabic", "legal_type", "duns_number", "dcci_number"]
_SO_FIXED_EN_POST = ["phone", "fax", "mobile", "po_box", "email",
                      "license_address", "parcel_id", "commerce_address",
                      "nominated_capital", "paid_capital", "currency", "number_of_shares",
                      "payment_voucher_number", "payment_mode", "payment_amount",
                      "contract_number", "contract_date"]

_SO_FIXED_AR_PRE  = ["رقم_الرخصة", "رقم_الرخصة_الأم", "رقم_السجل_التجاري",
                      "تاريخ_الإصدار", "تاريخ_الانتهاء", "رقم_الإيصال", "تاريخ_الطباعة",
                      "اسم_الشركة_بالإنجليزية", "اسم_الشركة_بالعربية",
                      "الاسم_التجاري_بالإنجليزية", "الاسم_التجاري_بالعربية",
                      "الشكل_القانوني", "رقم_دنز", "رقم_عضوية_الغرفة"]
_SO_FIXED_AR_POST = ["هاتف", "فاكس", "هاتف_متحرك", "صندوق_بريد", "البريد_الإلكتروني",
                      "عنوان_الرخصة", "رقم_القطعة", "عنوان_السجل_التجاري",
                      "رأس_المال_الاسمي", "رأس_المال_المدفوع", "العملة", "عدد_الأسهم",
                      "رقم_إذن_الدفع", "كيفية_الدفع", "مبلغ_الدفع",
                      "رقم_العقد", "تاريخ_العقد"]

SINGLE_OWNER_ENGLISH_FIELDS = (
    _SO_FIXED_EN_PRE +
    _build_activity_fields_en() +
    _SO_FIXED_EN_POST
)
SINGLE_OWNER_ARABIC_FIELDS = (
    _SO_FIXED_AR_PRE +
    _build_activity_fields_ar() +
    _SO_FIXED_AR_POST
)

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Owner:
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
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    role: str = ""

@dataclass
class Partner:
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    share_percentage: str = ""
    share_source: str = ""
    role: str = ""
    is_agent: bool = False

@dataclass
class UBO:
    person_number: str = ""
    name_english: str = ""
    name_arabic: str = ""
    nationality_english: str = ""
    nationality_arabic: str = ""
    share_percentage: str = ""
    ubo_basis: str = ""         # Why this person qualifies as UBO
    source_role: str = ""       # "Partner", "Owner", "Manager+Partner", etc.
    is_direct_ubo: bool = True  # True = direct shareholder, False = indirect/controller
    passport_number: str = ""   # from Owner (Single Owner case)
    date_of_birth: str = ""     # from Owner (Single Owner case)

@dataclass
class ExtractionMetrics:
    ai_extracted: int = 0
    regex_recovered: int = 0
    final_completeness: int = 0
    processing_time: float = 0.0
    api_calls: int = 0
    api_errors: int = 0

# ─────────────────────────────────────────────────────────────────────────────
# UBO threshold — standard AML/KYC
# ─────────────────────────────────────────────────────────────────────────────
UBO_SHARE_THRESHOLD = 25.0


# ─────────────────────────────────────────────────────────────────────────────
# Retry decorator
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Prompt helpers — dummy example data only
# ─────────────────────────────────────────────────────────────────────────────

_SO_EXAMPLE = {
    "license_number":            "XXXXXXX",
    "commercial_register_number":"XXXXXXX",
    "issue_date":                "DD/MM/YYYY",
    "expiry_date":               "DD/MM/YYYY",
    "company_name_english":      "SAMPLE COMPANY NAME L.L.C",
    "company_name_arabic":       "اسم الشركة النموذجية ش.ذ.م.م",
    "trade_name_english":        "SAMPLE TRADE NAME",
    "trade_name_arabic":         "الاسم التجاري النموذجي",
    "legal_type":                "Limited Liability Company - Single Owner(LLC - SO)",
    "activity_1":                "Primary Business Activity Description",
    "activity_2":                "Secondary Business Activity Description",
    "mobile":                    "971XXXXXXXXX",
    "email":                     "contact@samplecompany.ae",
    "po_box":                    "XXXXX",
    "license_address":           "Area Name, Street Name, Building Name, Dubai",
    "paid_capital":              "XXXXXX",
    "currency":                  "AED",
}

_SO_OWNER_EXAMPLE = {
    "person_number":      "XXXXXXX",
    "name_english":       "FIRST MIDDLE LAST NAME",
    "name_arabic":        "الاسم الأول الأوسط الأخير",
    "nationality_english":"Country Name",
    "nationality_arabic": "اسم الدولة",
    "passport_number":    "XXXXXXXXX",
    "date_of_birth":      "DD/MM/YYYY",
    "share_percentage":   "100.00%",
    "role":               "Shares Owner & Manager",
}

_MO_EXAMPLE = {
    "license_number":            "XXXXXXX",
    "main_license_number":       "XXXXXXX",
    "commercial_register_number":"XXXXXXX",
    "issue_date":                "DD/MM/YYYY",
    "expiry_date":               "DD/MM/YYYY",
    "company_name_english":      "SAMPLE PARTNERSHIP COMPANY L.L.C",
    "company_name_arabic":       "شركة النموذج للشراكة ش.ذ.م.م",
    "trade_name_english":        "SAMPLE TRADE NAME",
    "trade_name_arabic":         "الاسم التجاري النموذجي",
    "legal_type":                "Limited Liability Company(LLC)",
    "activity_1":                "Primary Business Activity",
    "phone":                     "971-4-XXXXXXX",
    "mobile":                    "971-5X-XXXXXXX",
    "nominated_capital":         "XXXXXX",
    "paid_capital":              "XXXXXX",
    "currency":                  "UAE Dirhams",
    "number_of_shares":          "XXX",
}

_MO_MANAGER_EXAMPLE = {
    "person_number":      "XXXXXXX",
    "name_english":       "MANAGER FULL NAME",
    "name_arabic":        "اسم المدير الكامل",
    "nationality_english":"Country Name",
    "nationality_arabic": "اسم الدولة",
    "role":               "Manager",
}

_MO_PARTNER_EXAMPLE_T2 = {
    "person_number":      "XXXXXXX",
    "name_english":       "PARTNER FULL NAME",
    "name_arabic":        "اسم الشريك الكامل",
    "nationality_english":"Country Name",
    "nationality_arabic": "اسم الدولة",
    "share_percentage":   "51.0000000%",
    "share_source":       "Table 2 - Partners Annex",
    "role":               "Partner",
    "is_agent":           False,
}

_MO_PARTNER_EXAMPLE_T2_B = {
    "person_number":      "YYYYYYY",
    "name_english":       "SECOND PARTNER FULL NAME",
    "name_arabic":        "اسم الشريك الثاني الكامل",
    "nationality_english":"Country Name",
    "nationality_arabic": "اسم الدولة",
    "share_percentage":   "49.0000000%",
    "share_source":       "Table 2 - Partners Annex",
    "role":               "Partner",
    "is_agent":           False,
}

_MO_PARTNER_EXAMPLE_T1 = {
    **_MO_PARTNER_EXAMPLE_T2,
    "share_percentage": "60.0000000%",
    "share_source":     "Table 1 - License Members",
}

_MO_PARTNER_EXAMPLE_NULL = {
    **_MO_PARTNER_EXAMPLE_T2,
    "share_percentage": None,
    "share_source":     None,
}

# Agent example — included in partners array with is_agent=True
_MO_AGENT_EXAMPLE = {
    "person_number":      "ZZZZZZZ",
    "name_english":       "SERVICE AGENT FULL NAME",
    "name_arabic":        "اسم وكيل الخدمات الكامل",
    "nationality_english":"Country Name",
    "nationality_arabic": "اسم الدولة",
    "share_percentage":   None,
    "share_source":       None,
    "role":               "Service Agent",
    "is_agent":           True,
}


# ─────────────────────────────────────────────────────────────────────────────
# MANAGERS & PARTNERS BLOCK (revised — agents INCLUDED)
# ─────────────────────────────────────────────────────────────────────────────
MANAGERS_PARTNERS_BLOCK = f"""
📋 TWO-TABLE EXTRACTION PROTOCOL (CRITICAL - READ CAREFULLY)

UAE Trade Licenses may contain ONE or TWO separate member/partner tables.
Determine which tables are present BEFORE extracting any data.

┌─────────────────────────────────────────────────────────────────────────┐
│ TABLE 1: "License Members / الأطراف"  ← typically PAGE 1               │
│ Columns: رقم الشخص | الاسم | الجنسية | الصفة/Role | الحصص/Share        │
│                                                                         │
│ The الحصص (Share) column in Table 1 may be:                            │
│   (a) BLANK for all rows    → shares are in Table 2 (if it exists)     │
│   (b) POPULATED             → use ONLY if Table 2 is absent            │
│                                                                         │
│ Role classification — process EVERY ROW independently:                 │
│   "مدير / Manager"              → managers array                       │
│   "شريك / Partner"              → partners array, is_agent: false      │
│   "مالك مؤسسة / Est. Owner"     → partners array, is_agent: false      │
│   "وكيل خدمات / Service Agent"  → partners array, is_agent: TRUE      │
│                                   share_percentage: null                │
│                                                                         │
│ ⚠⚠ CRITICAL: EVERY ROW IN TABLE 1 MUST APPEAR IN THE OUTPUT.          │
│ ⚠⚠ DO NOT DROP or SKIP any row for ANY reason.                         │
│ ⚠⚠ Service Agents are INCLUDED in partners[] with is_agent: true       │
│ ⚠⚠ ONE ROW = ONE ARRAY ENTRY, always.                                  │
│ ⚠ Same person_number with TWO different roles = TWO separate entries:  │
│     Row 1: role=Manager   → managers[]                                 │
│     Row 2: role=Partner   → partners[]                                 │
│   Do NOT merge rows before role-splitting.                             │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ TABLE 2: "Partners Annex / ملحق الشركاء"  ← SEPARATE PAGE (pg 2+)     │
│ Columns: الاسم | الجنسية | مسلسل الشخص/Sr.No. | الحصص/Share           │
│                                                                         │
│ ⚠ When present, THIS is the ONLY authoritative source for shares       │
│ ⚠ Extract EVERY ROW — tables can have 2 to 10+ partners               │
└─────────────────────────────────────────────────────────────────────────┘

🔄 SHARE SOURCE DECISION TREE (FOLLOW EXACTLY)

STEP 1 — Detect Table 2:
    Search for heading "ملحق الشركاء" or "Partners Annex".

    IF FOUND   → Table 2 EXISTS  → STEP 2a
    IF MISSING → Table 2 ABSENT  → STEP 2b

STEP 2a — Table 2 EXISTS:
    → Collect ALL person entries from Table 1 (names, roles, nationalities).
    → Collect ALL person entries from Table 2 (names, shares).
    → MERGE by person_number:
        • Person in BOTH tables → one entry: names/nationality from Table 1,
          share_percentage from Table 2.
        • Person ONLY in Table 1 → include them, share_percentage from Table 1
          الحصص column if present, else null.
        • Person ONLY in Table 2 → include them with share from Table 2.
    → Result: ALL unique persons across both tables are present.
    → metadata: "partners_annex_present": true
    → metadata: "share_source": "Merged Table 1 + Table 2"
    → metadata: "total_members_count": <Table1 count + Table2 unique additions>

STEP 2b — Table 2 ABSENT:
    → Extract ALL persons from Table 1 only.
    IF Table 1 الحصص column has values:
        → Use those values as share_percentage.
        → metadata: "share_source": "Table 1 - License Members"
    IF Table 1 الحصص column is blank:
        → Set share_percentage: null for each person.
        → metadata: "share_source": null
        → metadata: "share_data_available": false
    → metadata: "partners_annex_present": false

DEDUPLICATION RULE:
    Deduplication happens AFTER role-splitting, WITHIN each array separately.
    - Same person_number appearing as Manager AND Partner → one entry in each array ✓
    - Same person_number appearing as Manager TWICE → deduplicate to one in managers[]
    - Same person_number appearing as Partner TWICE  → deduplicate to one in partners[]
    - Agent rows → go to partners[] with is_agent=true, NEVER dropped

NEVER drop any person found in either table.
NEVER deduplicate across arrays (managers vs partners).
NEVER use "" (empty string) — use null when share is unavailable.

🔢 SHARE PERCENTAGE — NON-NEGOTIABLE RULES

RULE 1 — EXACT COPY: Copy character-by-character from source table.
    "80.0000000%" → output "80.0000000%"   ✓
    "50.00%"      → output "50.00%"         ✓
    "50%"         → output "50%"            ✓
    NEVER round: "80%" ✗  "80.00%" ✗  "80.0000000%" ✓

RULE 2 — ALWAYS END WITH %: share_percentage must end with "%".

RULE 3 — COUNT BEFORE EXTRACTING:
    Step 1: Count total partner rows in source table → N
    Step 2: Extract all N partners
    Step 3: Verify partners array has exactly N entries
    Step 4: Sum all percentages for non-agent, non-manager entries
            → must equal 100% (±0.01%)
    If sum ≠ 100%: at least one row is missing. Re-read the table.

RULE 4 — AGENTS HAVE NULL SHARE: Service Agents always get share_percentage: null

RULE 5 — FULL NAMES: Copy the complete name. Arabic names can be 4–6 words long.

🟢 MANAGERS ARRAY — REQUIRED FIELDS

Source: Table 1 rows where role = مدير / Manager

Example:
{json.dumps(_MO_MANAGER_EXAMPLE, indent=4, ensure_ascii=False)}

Validation per manager:
    ✓ person_number       : not empty, from رقم الشخص column
    ✓ name_english        : full name, not truncated
    ✓ name_arabic         : full Arabic name
    ✓ nationality_english : complete country name
    ✓ nationality_arabic  : country in Arabic
    ✓ role                : "Manager" or exact printed role

🔵 PARTNERS ARRAY — REQUIRED FIELDS (ALL MEMBERS INCL. AGENTS)

Source: ALL non-Manager rows from Table 1, plus Table 2 shares if present.
This includes: Partners, Est. Owners, AND Service Agents.

Example — Table 2 present (partner):
{json.dumps(_MO_PARTNER_EXAMPLE_T2, indent=4, ensure_ascii=False)}

Example — Table 2 absent, share in Table 1:
{json.dumps(_MO_PARTNER_EXAMPLE_T1, indent=4, ensure_ascii=False)}

Example — Service Agent (always is_agent: true, share always null):
{json.dumps(_MO_AGENT_EXAMPLE, indent=4, ensure_ascii=False)}

Example — No share data available:
{json.dumps(_MO_PARTNER_EXAMPLE_NULL, indent=4, ensure_ascii=False)}

Validation per partner / agent entry:
    ✓ person_number       : not empty
    ✓ name_english        : complete full name (4–6 words possible)
    ✓ name_arabic         : complete full Arabic name
    ✓ nationality_english : complete country name
    ✓ nationality_arabic  : country in Arabic
    ✓ share_percentage    : EXACT value with % OR null (null for agents always)
    ✓ share_source        : one of the label strings, or null for agents
    ✓ role                : exact role as printed (e.g. "Partner", "Est. Owner",
                            "Service Agent", "Shares Owner")
    ✓ is_agent            : true ONLY for وكيل خدمات / Service Agent rows,
                            false for all others

🔁 CROSS-REFERENCE RULE

If person X appears in Table 1 as Manager AND Table 2 as Partner:
    → Add to managers[]  using role from Table 1
    → Add to partners[]  using share_percentage from Table 2
    → Same person in both arrays is CORRECT — do NOT deduplicate across arrays.

📤 EXTRACTION METADATA — PARTNER/MANAGER FIELDS

"partners_annex_present":    true | false,
"share_source":              "Merged Table 1 + Table 2"
                           | "Table 1 - License Members"
                           | null,
"share_data_available":      true | false,
"table1_member_count":       <int>,   ← total rows in License Members table
"table2_member_count":       <int>,   ← total rows in Partners Annex (0 if absent)
"total_unique_members":      <int>,   ← final count after merge & dedup
"partners_array_count":      <int>,   ← must include agents too
"share_percentage_sum":      "100.0000000%" | null,
"managers_count":            <int>,
"agents_count":              <int>,   ← number of is_agent=true entries
"cross_reference_persons":   ["<person_number>", ...],
"members_only_in_table1":    ["<person_number>", ...],
"members_only_in_table2":    ["<person_number>", ...],
"members_source":            "License Members table page 1",
"partners_source":           "Merged: License Members page 1 + Partners Annex page 2"
                           | "License Members table page 1 (no annex found)"
                           | "N/A - no share data available"
"""


class TradeLicenseExtractor:
    """
    Unified Trade License extractor with bilingual support,
    retry logic, and comprehensive regex fallback.
    Supports Single Owner and Multiple Owner/Partnership companies.

    Key behaviours (v2):
      - Service Agents are ALWAYS included in partners[] with is_agent=True
        and share_percentage=None.  They are never silently dropped.
      - A post-extraction member-count verification cross-checks extracted
        totals against raw-text person-number counts in Table 1.
      - Share percentages are preserved with exact decimal formatting.
      - UBO identification is run automatically on every successful extraction
        and included as a "ubos" key in the result dict.
    """

    def __init__(self, api_key: Optional[str] = None, ownership_type: Optional[str] = None):
        self.api_key = api_key or API_KEY
        self.api_url = API_URL
        self.ownership_type = ownership_type
        self.extraction_metrics = ExtractionMetrics()
        self.start_time = None
        logger.info("TradeLicenseExtractor initialized")

    # ─────────────────────────────────────────────────────────────────────────
    # PDF extraction
    # ─────────────────────────────────────────────────────────────────────────
    def extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        doc = None
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count == 0:
                return "[PDF EXTRACTION ERROR] PDF has no pages"
            text = ""
            for i in range(doc.page_count):
                try:
                    text += doc[i].get_text() + "\n"
                except Exception as e:
                    logger.warning(f"Error extracting page {i}: {e}")
            if not text or len(text.strip()) < 100:
                return "[PDF EXTRACTION ERROR] PDF appears to be empty or contains very little text"
            logger.info(f"Extracted {len(text)} chars from {doc.page_count} pages")
            return text
        except Exception as e:
            return f"[PDF EXTRACTION ERROR] {e}"
        finally:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # Dynamic token budget
    # ─────────────────────────────────────────────────────────────────────────
    def get_dynamic_max_tokens(self, raw_text: str) -> int:
        """
        Scale token budget by document complexity.
        Checks Table 2 first, then falls back to Table 1 share hits.

        Tiers:
          ≥6 share hits → 8000
          ≥3 share hits → 6000
          ≥1 share hit  → 4500
          0 share hits  → 4000
        """
        def _count_hits(section: str) -> int:
            return len(re.findall(r"\d{1,3}\.\d+%?", section))

        annex = re.search(
            r"(?:ملحق\s*الشركاء|Partners\s*Annex)(.*?)(?:Receipt\s*No|رقم\s*الإيصال|$)",
            raw_text, re.DOTALL | re.IGNORECASE
        )
        if annex:
            hits   = _count_hits(annex.group(1))
            source = "Table 2 (Partners Annex)"
        else:
            members = re.search(
                r"(?:License\s*Members|اصحاب\s*الرخصة|الأطراف)(.*?)(?:ملحق\s*الشركاء|Partners\s*Annex|Receipt\s*No|رقم\s*الإيصال|$)",
                raw_text, re.DOTALL | re.IGNORECASE
            )
            hits   = _count_hits(members.group(1)) if members else 0
            source = "Table 1 (License Members)" if members else "none"

        if hits >= 6:
            tokens = 8000
        elif hits >= 3:
            tokens = 6000
        elif hits >= 1:
            tokens = 4500
        else:
            tokens = 4000

        logger.info(f"Token budget: {tokens} (share_hits={hits}, source={source})")
        return tokens

    # ─────────────────────────────────────────────────────────────────────────
    # Member-count verification
    # ─────────────────────────────────────────────────────────────────────────
    def _verify_member_count(self, raw_text: str, managers: list, partners: list) -> dict:
        """
        Count distinct person-number occurrences inside Table 1 from raw text
        and compare against the total extracted across managers + partners.
        Returns a dict with verification status and any gap details.
        """
        table1_m = re.search(
            r"(?:License\s*Members|الأطراف|اصحاب\s*الرخصة)"
            r"(.*?)"
            r"(?:License\s*Activities|نشاط\s*الرخصة|ملحق\s*الشركاء|Partners\s*Annex|Receipt\s*No|رقم\s*الإيصال|$)",
            raw_text, re.DOTALL | re.IGNORECASE
        )
        if not table1_m:
            return {"verified": False, "reason": "Table 1 section not found in raw text"}

        t1_block = table1_m.group(1)
        # 6–7 digit person numbers
        raw_ids = re.findall(r"\b(\d{6,7})\b", t1_block)
        unique_raw = set(raw_ids)

        extracted_ids = set(
            str(m.get("person_number", "")).strip()
            for m in (managers + partners)
            if m.get("person_number")
        )

        missing = unique_raw - extracted_ids
        extra   = extracted_ids - unique_raw

        result = {
            "table1_raw_person_count":  len(unique_raw),
            "extracted_total":          len(extracted_ids),
            "missing_person_numbers":   list(missing),
            "extra_person_numbers":     list(extra),
            "verified":                 len(missing) == 0,
        }
        if missing:
            logger.warning(f"Member count mismatch — missing from extraction: {missing}")
        else:
            logger.info(f"Member count verified: {len(extracted_ids)} members extracted")
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # validate_and_fix_partners  (v2 — agents INCLUDED)
    # ─────────────────────────────────────────────────────────────────────────
    def validate_and_fix_partners(self, partners: list, raw_text: str) -> list:
        """
        Post-process partners array:
          - Agents are KEPT with is_agent=True, share_percentage=None
          - Merges Table 1 + Table 2 entries so ALL members are preserved
          - Deduplicates by person_number WITHIN partners only
          - Enforces exact decimal preservation via regex fallback
          - Sets share_percentage to None when genuinely unavailable
          - Logs share sum validation
        Returns: fixed list (agents included, tagged)
        """
        if not partners:
            return partners

        has_annex = bool(re.search(
            r"ملحق\s*الشركاء|Partners\s*Annex",
            raw_text, re.IGNORECASE
        ))

        if has_annex:
            annex_m = re.search(
                r"(?:ملحق\s*الشركاء|Partners\s*Annex)(.*?)(?:Receipt\s*No|رقم\s*الإيصال|$)",
                raw_text, re.DOTALL | re.IGNORECASE
            )
            annex_scope     = annex_m.group(1) if annex_m else ""
            declared_source = "Merged Table 1 + Table 2"
        else:
            annex_scope     = ""
            declared_source = "Table 1 - License Members"

        # ── Role classification sets ──────────────────────────────────────
        AGENT_ROLES   = {"agent", "وكيل", "وكيل خدمات", "service agent",
                         "وكيل الخدمات", "خدمات وكيل"}
        PARTNER_ROLES = {"partner", "شريك", "est. owner", "مالك مؤسسة",
                         "est owner", "owner", "مالك", "shares owner",
                         "مالك حصص"}

        # ── STEP 1: tag every entry (agents stay, just flagged) ───────────
        tagged: list[dict] = []
        for p in partners:
            role_raw = str(p.get("role", "") or "").strip()
            role_lc  = role_raw.lower()
            is_agent = any(a in role_lc for a in AGENT_ROLES)

            p = dict(p)   # shallow copy — avoid mutating caller's list
            p["is_agent"] = is_agent or bool(p.get("is_agent", False))

            # Agents always have null share
            if p["is_agent"]:
                p["share_percentage"] = None
                p["share_source"]     = None
                if not p.get("role"):
                    p["role"] = "Service Agent"

            tagged.append(p)

        logger.info(f"Partners tagged — total: {len(tagged)}, "
                    f"agents: {sum(1 for p in tagged if p['is_agent'])}")

        # ── STEP 2: deduplicate WITHIN partners (by person_number) ────────
        merged: dict[str, dict] = {}
        for p in tagged:
            pid = str(p.get("person_number", "")).strip()
            if not pid:
                pid = f"__no_id_{len(merged)}"
            if pid not in merged:
                merged[pid] = p.copy()
            else:
                # Keep whichever has a share value (agents always keep null)
                existing_share = merged[pid].get("share_percentage") or ""
                new_share      = p.get("share_percentage") or ""
                if new_share and not existing_share and not merged[pid].get("is_agent"):
                    merged[pid]["share_percentage"] = new_share
                # Keep longer names
                for nf in ("name_english", "name_arabic"):
                    if len(str(p.get(nf, ""))) > len(str(merged[pid].get(nf, ""))):
                        merged[pid][nf] = p[nf]

        deduped = list(merged.values())
        logger.info(f"Partners after dedup: {len(deduped)} (from {len(tagged)} tagged rows)")

        # ── STEP 3: fix / recover share percentages (skip agents) ─────────
        fixed = []
        for p in deduped:
            if p.get("is_agent"):
                # Agents always null — no regex recovery attempted
                p["share_percentage"] = None
                p["share_source"]     = None
                fixed.append(p)
                continue

            share     = str(p.get("share_percentage", "") or "").strip()
            person_no = p.get("person_number", "")

            if share.lower() in ("", "none", "null"):
                share = ""

            # Priority 1: regex against Table 2 section (exact decimals)
            if person_no and not share and annex_scope:
                m = re.search(
                    rf"{re.escape(person_no)}[^\n]{{0,300}}?(\d{{1,3}}\.\d+%)",
                    annex_scope
                )
                if m:
                    share = m.group(1)
                else:
                    m2 = re.search(
                        rf"(\d{{1,3}}\.\d+%)[^\n]{{0,300}}?{re.escape(person_no)}",
                        annex_scope
                    )
                    if m2:
                        share = m2.group(1)

            # Priority 2: regex against full raw text
            if person_no and not share:
                m3 = re.search(
                    rf"{re.escape(person_no)}[^\n]{{0,300}}?(\d{{1,3}}\.\d+%)",
                    raw_text
                )
                if m3:
                    share = m3.group(1)

            # Priority 3: bare integer percentage
            if person_no and not share:
                m4 = re.search(
                    rf"{re.escape(person_no)}[^\n]{{0,200}}?(\b\d{{1,3}}\b)(?!\.\d)",
                    raw_text
                )
                if m4:
                    share = m4.group(1) + "%"

            # Ensure % suffix
            if share and not share.endswith("%"):
                share += "%"

            p["share_percentage"] = share if share else None
            p["share_source"]     = declared_source if p["share_percentage"] else None
            fixed.append(p)

        # ── STEP 4: sum validation (exclude agents) ────────────────────────
        try:
            values = [
                float(p["share_percentage"].replace("%", ""))
                for p in fixed
                if p.get("share_percentage") and not p.get("is_agent")
            ]
            if values:
                total = sum(values)
                if abs(total - 100.0) > 0.1:
                    logger.warning(
                        f"Share sum = {total:.7f}% — expected 100.0%. "
                        f"May indicate a missing partner row."
                    )
                else:
                    logger.info(f"Share sum = {total:.7f}% (valid)")
            else:
                logger.warning("No share percentages found — share_data_available = false")
        except Exception as e:
            logger.warning(f"Share sum check failed: {e}")

        # ── STEP 5: log agent summary ─────────────────────────────────────
        agents    = [p for p in fixed if p.get("is_agent")]
        partners_ = [p for p in fixed if not p.get("is_agent")]
        logger.info(
            f"Final partners array: {len(fixed)} total "
            f"({len(partners_)} non-agents, {len(agents)} agents)"
        )
        for a in agents:
            logger.info(
                f"  → Agent included: {a.get('name_english','?')} "
                f"({a.get('person_number','?')}) — {a.get('nationality_english','?')}"
            )

        return fixed

    # ─────────────────────────────────────────────────────────────────────────
    # UBO identification
    # ─────────────────────────────────────────────────────────────────────────
    def identify_ubos(
        self,
        ownership_type: str,
        partners: list,         # validated partners list (non-agents + agents)
        managers: list,
        owner: dict = None,     # Single Owner case
    ) -> list:
        """
        Identify Ultimate Beneficial Owners (UBOs) from extracted trade license data.

        Rules applied (standard AML/KYC):
          1. Single Owner  → the owner is always the sole UBO (100%).
          2. Multi-Owner   → any partner with share_percentage ≥ UBO_SHARE_THRESHOLD.
          3. Fallback      → if no partner meets the threshold (e.g. corporate layering
                             or share data unavailable), ALL non-agent partners qualify
                             so no real person is omitted.
          4. Managers who ALSO appear as partners are included via their partner entry.
          5. Pure managers (no shares) are NOT UBOs unless they are the sole controller
                             and no partners exist at all.
          6. Service Agents (is_agent=True) are NEVER UBOs.

        Returns a list of UBO dicts (serialisable).
        """
        ubos: list[dict] = []

        # ── Case 1: Single Owner ──────────────────────────────────────────
        if ownership_type == "Single Owner" and owner:
            ubo = UBO(
                person_number       = str(owner.get("person_number", "") or ""),
                name_english        = str(owner.get("name_english", "") or ""),
                name_arabic         = str(owner.get("name_arabic", "") or ""),
                nationality_english = str(owner.get("nationality_english", "") or ""),
                nationality_arabic  = str(owner.get("nationality_arabic", "") or ""),
                share_percentage    = str(owner.get("share_percentage", "100%") or "100%"),
                ubo_basis           = "Sole owner — 100% beneficial ownership",
                source_role         = owner.get("role", "Shares Owner"),
                is_direct_ubo       = True,
                passport_number     = str(owner.get("passport_number", "") or ""),
                date_of_birth       = str(owner.get("date_of_birth", "") or ""),
            )
            ubos.append(asdict(ubo))
            logger.info(f"UBO identified (Single Owner): {ubo.name_english}")
            return ubos

        # ── Case 2: Multi-Owner — filter out agents ───────────────────────
        non_agents = [p for p in partners if not p.get("is_agent", False)]

        if not non_agents:
            logger.warning("UBO identification: no non-agent partners found.")
            return ubos

        # ── Parse share percentages ───────────────────────────────────────
        def _parse_share(p: dict) -> float:
            raw = str(p.get("share_percentage", "") or "").replace("%", "").strip()
            try:
                return float(raw) if raw else 0.0
            except ValueError:
                return 0.0

        # ── Identify threshold-based UBOs ─────────────────────────────────
        threshold_ubos = [p for p in non_agents if _parse_share(p) >= UBO_SHARE_THRESHOLD]

        # ── Fallback: no threshold met → all non-agent partners are UBOs ──
        candidates = threshold_ubos if threshold_ubos else non_agents

        if not threshold_ubos:
            logger.warning(
                f"No partner meets {UBO_SHARE_THRESHOLD}% threshold — "
                f"all {len(non_agents)} non-agent partners flagged as UBOs (fallback)."
            )

        # ── Build manager lookup (person_number → manager entry) ──────────
        mgr_lookup = {
            str(m.get("person_number", "")).strip(): m
            for m in managers
            if m.get("person_number")
        }

        for p in candidates:
            share_val  = _parse_share(p)
            person_no  = str(p.get("person_number", "") or "")
            is_manager = person_no in mgr_lookup

            if share_val >= UBO_SHARE_THRESHOLD:
                basis = (
                    f"Direct shareholder — {p.get('share_percentage', '')} ownership "
                    f"(≥{UBO_SHARE_THRESHOLD}% threshold)"
                )
            else:
                basis = (
                    f"Included as UBO — share percentage below threshold or unavailable "
                    f"(fallback: no single partner holds ≥{UBO_SHARE_THRESHOLD}%)"
                )

            if is_manager:
                basis  += "; also holds Manager role"
                source  = "Manager + Partner"
            else:
                source  = p.get("role", "Partner")

            ubo = UBO(
                person_number       = person_no,
                name_english        = str(p.get("name_english", "") or ""),
                name_arabic         = str(p.get("name_arabic", "") or ""),
                nationality_english = str(p.get("nationality_english", "") or ""),
                nationality_arabic  = str(p.get("nationality_arabic", "") or ""),
                share_percentage    = str(p.get("share_percentage", "") or ""),
                ubo_basis           = basis,
                source_role         = source,
                is_direct_ubo       = True,
            )
            ubos.append(asdict(ubo))
            logger.info(
                f"UBO identified: {ubo.name_english} | "
                f"share={ubo.share_percentage} | basis={ubo.ubo_basis[:60]}"
            )

        # ── Pure managers (no partner entry) as controller fallback ───────
        if not ubos and managers:
            logger.warning("No partner UBOs found — adding all managers as controlling-person UBOs.")
            for m in managers:
                ubo = UBO(
                    person_number       = str(m.get("person_number", "") or ""),
                    name_english        = str(m.get("name_english", "") or ""),
                    name_arabic         = str(m.get("name_arabic", "") or ""),
                    nationality_english = str(m.get("nationality_english", "") or ""),
                    nationality_arabic  = str(m.get("nationality_arabic", "") or ""),
                    share_percentage    = "",
                    ubo_basis           = "Controlling person — manager with no identified shareholder above threshold",
                    source_role         = m.get("role", "Manager"),
                    is_direct_ubo       = False,
                )
                ubos.append(asdict(ubo))
                logger.info(f"UBO (controller fallback): {ubo.name_english}")

        logger.info(
            f"UBO identification complete — {len(ubos)} UBO(s) identified "
            f"out of {len(non_agents)} non-agent partner(s)."
        )
        return ubos

    # ─────────────────────────────────────────────────────────────────────────
    # API call
    # ─────────────────────────────────────────────────────────────────────────
    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def call_ai_api(self, prompt: str, model_name: Optional[str] = None, max_tokens: int = 4000, system_prompt: Optional[str] = None) -> str:
        if not self.api_key:
            logger.error("API key not configured")
            return "API key not configured"

        model   = model_name or LLAMA_MODEL
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model":       model,
            "messages":    ([{"role": "system", "content": system_prompt}] if system_prompt else [])
                           + [{"role": "user", "content": prompt}],
            # Standardized to 0.0 (prompt-remediation Phase 2) -- this was the
            # only one of the five specialized extractors running at 0.1;
            # every other extractor (bvi, moa, ejari, passport) already uses
            # 0.0 for the same reason extraction wants it: deterministic,
            # repeatable field values, not creative variation. tests/
            # ocr_corpus.py's Layer 2 baseline (requests.json) was
            # re-recorded to match after this change -- see the Phase 2 note
            # in prompt-remediation-plan.html for what changed and why.
            "temperature": 0.0,
            "max_tokens":  max_tokens,
        }

        try:
            self.extraction_metrics.api_calls += 1
            resp = bedrock_client.post(self.api_url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)

            if resp.status_code in [502, 503, 504]:
                self.extraction_metrics.api_errors += 1
                raise RuntimeError(f"Trade License API failed: {resp.status_code} Server temporarily unavailable")
            if resp.status_code == 429:
                self.extraction_metrics.api_errors += 1
                raise RuntimeError(f"Trade License API failed: {resp.status_code} Rate limit exceeded")

            resp.raise_for_status()
            result = resp.json()
            logger.info(f"API call successful — Model: {model}, max_tokens: {max_tokens}")
            return result["choices"][0]["message"]["content"]

        except requests.exceptions.Timeout:
            self.extraction_metrics.api_errors += 1
            raise RuntimeError(f"Trade License API failed: Request timeout after {REQUEST_TIMEOUT} seconds")
        except requests.exceptions.RequestException as e:
            self.extraction_metrics.api_errors += 1
            sc = resp.status_code if 'resp' in locals() else 'Unknown'
            raise RuntimeError(f"Trade License API failed: {sc} {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Ownership detection
    # ─────────────────────────────────────────────────────────────────────────
    def detect_ownership_type(self, raw_text: str) -> str:
        for p in [r"Single Owner", r"LLC - SO", r"L\.L\.C - S\.O",
                  r"الشخص الواحد", r"شركة ذات مسؤولية محدودة - الشخص الواحد"]:
            if re.search(p, raw_text, re.IGNORECASE):
                logger.info("Detected: Single Owner")
                return "Single Owner"
        logger.info("Detected: Multiple Owners")
        return "Multiple Owners"

    # ─────────────────────────────────────────────────────────────────────────
    # Regex patterns
    # ─────────────────────────────────────────────────────────────────────────
    def _build_regex_patterns(self) -> Dict[str, List[str]]:
        patterns = {
            "license_number": [r"License No[.:]?\s*(\d+)", r"رقم الرخصة\s*[\):=]\s*(\d+)"],
            "main_license_number": [r"Main License No[.:]?\s*(\d+)", r"رقم الرخصة الأم\s*[\):=]\s*(\d+)"],
            "commercial_register_number": [r"(?:Commercial\s+)?Register No[.:]?\s*(\d+)", r"رقم السجل التجاري\s*[\):=]\s*(\d+)"],
            "issue_date":   [r"Issue Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})", r"تاريخ الإصدار\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})"],
            "expiry_date":  [r"Expiry Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})", r"تاريخ الانتهاء\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})"],
            "receipt_number":  [r"Receipt No[.:]?\s*(\d+)", r"رقم الإيصال\s*[\):=]\s*(\d+)"],
            "print_date":      [r"Print Date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})", r"تاريخ الطباعة\s*[\):=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})"],
            "company_name_english": [r"Company Name\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|Arabic|Trade|$)"],
            "company_name_arabic":  [r"اسم الشركة\s*[\):=]\s*([^\n]+?)(?:\n|$)"],
            "trade_name_english":   [r"(?:Trade\s+)?Name\s*[:\s]+([A-Z\s&\-\.]+?)(?:\n|Commercial|$)", r"Commercial Name[:\s]+([A-Z\s&\-\.]+?)(?:\n|$)"],
            "trade_name_arabic":    [r"الاسم التجاري\s*[\):=]\s*([^\n]+?)(?:\n|$)"],
            "legal_type":  [r"Legal Type\s*[:\s]+([A-Z\s\-()]+?)(?:\n|$)", r"الشكل القانوني\s*[\):=]\s*([^\n]+?)(?:\n|$)"],
            "duns_number": [r"DUNS(?:\s+Number)?\s*[:\s]+(\d+)", r"رقم دنز\s*[\):=]\s*(\d+)"],
            "dcci_number": [r"DCCI\s+(?:No|Number)?[.:]?\s*(\d+)", r"رقم عضوية الغرفة\s*[\):=]\s*(\d+)"],
            "phone":  [r"(?:Tel|Phone)(?:\s+No)?[.:\s]+(\+?971[\s\-]?\d[\s\-]?\d{7}|\d{2,3}[\s\-]\d{6,7})"],
            "fax":    [r"Fax(?:\s+No)?[.:\s]+([0-9\-\+\s()]+)"],
            "mobile": [r"(?:Mobile|Cell)(?:\s+No)?[.:\s]+(\+?971[\s\-]?\d{2}[\s\-]?\d{7})"],
            "po_box": [r"P\.?O\.?\s+Box[.:]?\s*(\d+)", r"صندوق بريد\s*[\):=]\s*(\d+)"],
            "email":  [r"E?mail[.:\s]+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"],
            "license_address":  [r"License Address[.:]?\s*([^\n]+?)(?:\n|$)"],
            "commerce_address": [r"Commerce Address[.:]?\s*([^\n]+?)(?:\n|$)"],
            "parcel_id":        [r"Parcel\s+(?:ID|No)[.:]?\s*([\d\-]+)"],
            "nominated_capital":[r"Nominated\s+Capital[.:]?\s*([0-9,]+)"],
            "paid_capital":     [r"Paid(?:\s+up)?\s+Capital[.:]?\s*([0-9,]+)"],
            "currency":         [r"Currency[.:]?\s*(AED|USD|EUR|درهم)"],
            "number_of_shares": [r"(?:No|Number)\.?\s+of\s+Shares[.:]?\s*(\d+)"],
            "payment_voucher_number": [r"P\.?V\.?\s+(?:No|Number)[.:]?\s*(\d+)"],
            "payment_mode":   [r"Payment\s+(?:Mode|Method)[.:]?\s*([^\n]+?)(?:\n|$)"],
            "payment_amount": [r"Total(?:\s+Amount)?[.:]?\s*([0-9,]+)"],
            "contract_number":[r"Contract\s+(?:No|Number)[.:]?\s*(\d+)"],
            "contract_date":  [r"Contract\s+Date[.:]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})"],
        }
        for i in range(1, MAX_ACTIVITIES + 1):
            patterns[f"activity_{i}"] = [
                rf"Activity\s*{i}[.:]?\s*([^\n]+?)(?:\n|Activity|$)",
                rf"النشاط\s*{i}\s*[\):=]\s*([^\n]+?)(?:\n|$)",
            ]
        return patterns

    def _normalize_date(self, d: str) -> str:
        if not d:
            return ""
        for pat, fmt in [
            (r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", lambda m: f"{m.group(3):0>2}/{m.group(2):0>2}/{m.group(1)}"),
            (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",  lambda m: f"{m.group(1):0>2}/{m.group(2):0>2}/{m.group(3)}"),
        ]:
            m = re.search(pat, str(d))
            if m:
                return fmt(m)
        return str(d)

    def _normalize_phone(self, p: str) -> str:
        if not p:
            return ""
        return re.sub(r'[()]+', '', re.sub(r'\s+', '-', str(p).strip()))

    def _extract_activities_from_raw(self, raw_text: str) -> Dict[str, str]:
        """
        Dedicated activity extractor.
        Handles three document layouts:
          Layout A — labelled:  "Activity 1  Floor & Wall Tiling Works"
          Layout B — section:   "License Activities / نشاط الرخصة التجارية"
                                followed by unlabelled lines, one per activity
          Layout C — Arabic:    "النشاط 1  أعمال تبليط الأرضيات"
        """
        result: Dict[str, str] = {}

        # Layout A: explicitly labelled activities
        for i in range(1, MAX_ACTIVITIES + 1):
            for pat in [
                rf"Activity\s*{i}\s*[.:\-]?\s*([^\n]+)",
                rf"النشاط\s*{i}\s*[\):=\-]?\s*([^\n]+)",
            ]:
                m = re.search(pat, raw_text, re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    if val and len(val) > 3:
                        result[f"activity_{i}"] = val
                        break

        # Layout B: section block (unlabelled lines)
        if len(result) < 2:
            section_match = re.search(
                r"(?:License\s*Activities|نشاط\s*الرخصة\s*التجارية|Activities\s*License)"
                r"(.*?)"
                r"(?:Receipt\s*No|رقم\s*الإيصال|Address\s*/\s*العنوان|Phone\s*No|$)",
                raw_text, re.DOTALL | re.IGNORECASE
            )
            if section_match:
                block    = section_match.group(1)
                lines    = [ln.strip() for ln in block.splitlines() if ln.strip()]
                en_lines = [ln for ln in lines if re.search(r"[A-Za-z]", ln)]
                for idx, activity in enumerate(en_lines[:MAX_ACTIVITIES], start=1):
                    key = f"activity_{idx}"
                    if key not in result:
                        result[key] = activity

        logger.info(f"Activities extracted: {len(result)} ({list(result.keys())})")
        return result

    def post_process_data(self, data: Dict, raw_text: str) -> Dict:
        patterns  = self._build_regex_patterns()
        recovered = 0
        for field, pats in patterns.items():
            if field in data and not (data[field] and len(str(data[field]).strip()) >= 2):
                for pat in pats:
                    try:
                        m = re.search(pat, raw_text, re.IGNORECASE)
                        if m:
                            val = m.group(1).strip()
                            if val and len(val) > 1:
                                data[field] = val
                                recovered += 1
                                break
                    except Exception as e:
                        logger.warning(f"Regex error for {field}: {e}")
        for f in ["issue_date","expiry_date","print_date","contract_date","date_of_birth"]:
            if f in data and data[f]:
                data[f] = self._normalize_date(data[f])
        for f in ["phone","fax","mobile"]:
            if f in data and data[f]:
                data[f] = self._normalize_phone(data[f])
        for f in ["nominated_capital","paid_capital","payment_amount"]:
            if f in data and data[f]:
                data[f] = str(data[f]).replace(",","").strip()
        self.extraction_metrics.regex_recovered = recovered
        logger.info(f"Regex fallback recovered {recovered} fields")

        # Activity-specific pass
        raw_activities = self._extract_activities_from_raw(raw_text)
        for key, val in raw_activities.items():
            if key in data and not data[key]:
                data[key] = val
                logger.debug(f"Activity fallback filled {key}: {val[:60]}")

        return data

    def ensure_all_fields(self, data: Dict, required: List[str]) -> Dict:
        # prompt-remediation Phase 4: delegates to extraction_schema.validate_and_coerce
        # (pydantic-backed) instead of a bare dict comprehension -- same shape in/out,
        # but a non-string field value now gets coerced and logged instead of
        # silently flowing downstream untyped.
        return validate_and_coerce(data, required, "TradeLicenseFields")

    # ─────────────────────────────────────────────────────────────────────────
    # Single Owner extraction
    # ─────────────────────────────────────────────────────────────────────────
    # PROMPT CACHING (prompt-remediation Phase 3): static instructions/field
    # lists/output-schema for the single- and multi-owner extraction prompts
    # moved here as system prompts so bedrock_client.py's existing ephemeral
    # prompt caching (see _to_bedrock_payload) applies to them instead of being
    # re-sent and re-processed as fresh input tokens on every Trade License
    # extraction call. Content is UNCHANGED, character-for-character, from the
    # previous extract_single_owner_with_ai()/extract_multi_owner_with_ai()
    # prompts -- only their position moved (still f-strings, so the
    # json.dumps(...) example blocks and MANAGERS_PARTNERS_BLOCK still
    # interpolate correctly against module-level constants; the local `N`
    # count is now spelled out as len(...) since a class attribute can't see a
    # method's local variable), so extraction behaviour is not expected to
    # change.
    _SYSTEM_PROMPT_SINGLE = f"""You are an expert AI extracting UAE Dubai Trade License data for a SINGLE OWNER company.

🔴 DOUBLE-PASS EXTRACTION PROTOCOL
Perform TWO independent passes. Compare results. Re-extract mismatches.

📋 FIELDS TO EXTRACT
ENGLISH fields ({len(SINGLE_OWNER_ENGLISH_FIELDS)} total):
{json.dumps(SINGLE_OWNER_ENGLISH_FIELDS, indent=2)}

ARABIC fields ({len(SINGLE_OWNER_ENGLISH_FIELDS)} total):
{json.dumps(SINGLE_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

🟢 CRITICAL FIELDS (all 6 must be populated):
  license_number, company_name_english, trade_name_english,
  issue_date (DD/MM/YYYY), expiry_date (DD/MM/YYYY), legal_type

🟡 MINIMUM THRESHOLD: At least 15/{len(SINGLE_OWNER_ENGLISH_FIELDS)} base fields complete.

🟢 OWNER OBJECT (required):
  name_english, name_arabic, nationality_english, nationality_arabic,
  share_percentage ("100%" or "100.00%"), role

📤 OUTPUT FORMAT (JSON only — no markdown):
{{
  "english": {json.dumps({f: _SO_EXAMPLE.get(f, "") for f in SINGLE_OWNER_ENGLISH_FIELDS}, indent=4)},
  "arabic":  {json.dumps({f: "" for f in SINGLE_OWNER_ARABIC_FIELDS}, indent=4, ensure_ascii=False)},
  "owner":   {json.dumps(_SO_OWNER_EXAMPLE, indent=4, ensure_ascii=False)},
  "extraction_metadata": {{
    "double_pass_validation": "completed",
    "critical_fields_status": "all_valid",
    "total_fields_completed": 0,
    "owner_extracted": true
  }}
}}

Return ONLY the JSON object. No markdown. No explanation.
BEGIN EXTRACTION NOW."""

    _SYSTEM_PROMPT_MULTI = f"""You are an expert AI extracting UAE Dubai Trade License data for a MULTIPLE OWNER company.

🔴 DOUBLE-PASS EXTRACTION PROTOCOL
Perform TWO independent passes. Compare results. Re-extract mismatches.

📋 FIELDS TO EXTRACT
ENGLISH fields ({len(MULTI_OWNER_ENGLISH_FIELDS)} total):
{json.dumps(MULTI_OWNER_ENGLISH_FIELDS, indent=2)}

ARABIC fields ({len(MULTI_OWNER_ENGLISH_FIELDS)} total):
{json.dumps(MULTI_OWNER_ARABIC_FIELDS, ensure_ascii=False, indent=2)}

🟢 CRITICAL FIELDS (all 6 must be populated):
  license_number, company_name_english, trade_name_english,
  issue_date (DD/MM/YYYY), expiry_date (DD/MM/YYYY), legal_type

🟡 MINIMUM THRESHOLD: At least 20/{len(MULTI_OWNER_ENGLISH_FIELDS)} base fields complete.

{MANAGERS_PARTNERS_BLOCK}

📤 OUTPUT FORMAT (JSON only — no markdown):
{{
  "english": {json.dumps({f: _MO_EXAMPLE.get(f, "") for f in MULTI_OWNER_ENGLISH_FIELDS}, indent=4)},
  "arabic":  {json.dumps({f: "" for f in MULTI_OWNER_ARABIC_FIELDS}, indent=4, ensure_ascii=False)},
  "managers": [{json.dumps(_MO_MANAGER_EXAMPLE, indent=6, ensure_ascii=False)}],
  "partners": [
    {json.dumps(_MO_PARTNER_EXAMPLE_T2,   indent=6, ensure_ascii=False)},
    {json.dumps(_MO_PARTNER_EXAMPLE_T2_B, indent=6, ensure_ascii=False)},
    {json.dumps(_MO_AGENT_EXAMPLE,        indent=6, ensure_ascii=False)}
  ],
  "extraction_metadata": {{
    "double_pass_validation": "completed",
    "partners_annex_present": true,
    "share_source": "Table 2 - Partners Annex",
    "share_data_available": true,
    "table1_member_count": 3,
    "partners_table_row_count": 2,
    "partners_array_count": 3,
    "share_percentage_sum": "100.0000000%",
    "managers_count": 1,
    "agents_count": 1,
    "cross_reference_persons": [],
    "members_source": "License Members table page 1",
    "partners_source": "Partners Annex ملحق الشركاء page 2"
  }}
}}

Return ONLY the JSON object. No markdown. No explanation.
BEGIN EXTRACTION NOW."""

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def extract_single_owner_with_ai(self, raw_text: str) -> Tuple[Dict, Dict, Dict]:
        N = len(SINGLE_OWNER_ENGLISH_FIELDS)
        prompt = f"Document Text:\n{raw_text[:20000]}"

        return self._run_single_owner_extraction(prompt, raw_text, N)

    def _run_single_owner_extraction(self, prompt, raw_text, N):
        try:
            resp = self.call_ai_api(
                prompt,
                max_tokens=self.get_dynamic_max_tokens(raw_text),
                system_prompt=self._SYSTEM_PROMPT_SINGLE,
            )
            if resp and not resp.startswith("API"):
                data = self._parse_json_response(resp)
                if data:
                    en  = self.ensure_all_fields(data.get("english", {}), SINGLE_OWNER_ENGLISH_FIELDS)
                    ar  = self.ensure_all_fields(data.get("arabic",  {}), SINGLE_OWNER_ARABIC_FIELDS)
                    own = data.get("owner", {})
                    en  = self.post_process_data(en, raw_text)
                    ar  = self.post_process_data(ar, raw_text)
                    self.extraction_metrics.ai_extracted = len([v for v in en.values() if v])
                    logger.info("Single Owner extraction complete")
                    return en, ar, own
        except Exception as e:
            logger.error(f"Single Owner extraction failed: {e}", exc_info=True)
        logger.warning("Single Owner extraction failed, returning empty data")
        return ({f:"" for f in SINGLE_OWNER_ENGLISH_FIELDS},
                {f:"" for f in SINGLE_OWNER_ARABIC_FIELDS}, {})

    # ─────────────────────────────────────────────────────────────────────────
    # Multi Owner extraction
    # ─────────────────────────────────────────────────────────────────────────
    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_RETRY_DELAY)
    def extract_multi_owner_with_ai(self, raw_text: str) -> Tuple[Dict, Dict, List[Dict], List[Dict]]:
        N = len(MULTI_OWNER_ENGLISH_FIELDS)
        prompt = f"Document Text:\n{raw_text[:25000]}"

        return self._run_multi_owner_extraction(prompt, raw_text)

    def _run_multi_owner_extraction(self, prompt, raw_text):
        try:
            resp = self.call_ai_api(
                prompt,
                max_tokens=self.get_dynamic_max_tokens(raw_text),
                system_prompt=self._SYSTEM_PROMPT_MULTI,
            )
            if resp and not resp.startswith("API"):
                data = self._parse_json_response(resp)
                if data:
                    en  = self.ensure_all_fields(data.get("english",   {}), MULTI_OWNER_ENGLISH_FIELDS)
                    ar  = self.ensure_all_fields(data.get("arabic",    {}), MULTI_OWNER_ARABIC_FIELDS)
                    mgr = data.get("managers", []) if isinstance(data.get("managers"), list) else []
                    prt = data.get("partners", []) if isinstance(data.get("partners"), list) else []
                    en  = self.post_process_data(en, raw_text)
                    ar  = self.post_process_data(ar, raw_text)
                    prt = self.validate_and_fix_partners(prt, raw_text)

                    # Member-count verification
                    count_check = self._verify_member_count(raw_text, mgr, prt)
                    if not count_check.get("verified"):
                        logger.warning(
                            f"Member count verification FAILED: "
                            f"{count_check.get('missing_person_numbers')} may be missing"
                        )

                    agents     = [p for p in prt if p.get("is_agent")]
                    non_agents = [p for p in prt if not p.get("is_agent")]
                    self.extraction_metrics.ai_extracted = len([v for v in en.values() if v])
                    logger.info(
                        f"Multi Owner extraction: {len(non_agents)} partners, "
                        f"{len(mgr)} managers, {len(agents)} agents"
                    )
                    return en, ar, mgr, prt, count_check
        except Exception as e:
            logger.error(f"Multi Owner extraction failed: {e}", exc_info=True)
        logger.warning("Multi Owner extraction failed, returning empty data")
        empty_check = {"verified": False, "reason": "Extraction failed"}
        return ({f:"" for f in MULTI_OWNER_ENGLISH_FIELDS},
                {f:"" for f in MULTI_OWNER_ARABIC_FIELDS}, [], [], empty_check)

    # ─────────────────────────────────────────────────────────────────────────
    # JSON parser helper
    # ─────────────────────────────────────────────────────────────────────────
    def _parse_json_response(self, resp: str) -> Optional[Dict]:
        try:
            return json.loads(resp)
        except Exception:
            pass
        fb = resp.find("{"); lb = resp.rfind("}")
        if fb != -1 and lb > fb:
            chunk = resp[fb:lb+1]
            chunk = re.sub(r",\s*}", "}", chunk)
            chunk = re.sub(r",\s*]", "]", chunk)
            chunk = re.sub(r"}\s*{",  "},{", chunk)
            try:
                return json.loads(chunk)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse failed: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Public extraction router
    # ─────────────────────────────────────────────────────────────────────────
    def extract_with_ai(self, raw_text: str, ownership_type: Optional[str] = None):
        ot = ownership_type or self.ownership_type or self.detect_ownership_type(raw_text)
        if ot == "Single Owner":
            return self.extract_single_owner_with_ai(raw_text)
        return self.extract_multi_owner_with_ai(raw_text)

    # ─────────────────────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────────────────────
    def validate_single_owner_extraction(self, en: Dict, ar: Dict, owner: Dict) -> Dict:
        CRITICAL = ["license_number","company_name_english","trade_name_english",
                    "issue_date","expiry_date","legal_type"]
        ne = len([v for v in en.values() if v and str(v).strip()])
        v  = {
            "english_field_count": ne,
            "arabic_field_count":  len([x for x in ar.values() if x and str(x).strip()]),
            "has_owner":           bool(owner and owner.get("name_english")),
            "is_valid":            False,
            "issues":              [],
            "critical_missing":    [],
            "completeness_percentage": round(ne/len(SINGLE_OWNER_ENGLISH_FIELDS)*100, 1),
        }
        for f in CRITICAL:
            if not en.get(f):
                v["critical_missing"].append(f)
        if v["critical_missing"]:
            v["issues"].append(f"Missing critical: {v['critical_missing']}")
        elif ne < 15:
            v["issues"].append(f"Only {ne}/{len(SINGLE_OWNER_ENGLISH_FIELDS)} fields")
        elif not v["has_owner"]:
            v["issues"].append("No owner extracted")
        else:
            v["is_valid"] = True
        return v

    def validate_multi_owner_extraction(self, en: Dict, ar: Dict,
                                         managers: List, partners: List,
                                         count_check: Optional[Dict] = None) -> Dict:
        CRITICAL = ["license_number","company_name_english","trade_name_english",
                    "issue_date","expiry_date","legal_type"]
        ne      = len([v for v in en.values() if v and str(v).strip()])
        agents  = [p for p in partners if p.get("is_agent")]
        non_ag  = [p for p in partners if not p.get("is_agent")]
        v = {
            "english_field_count":  ne,
            "arabic_field_count":   len([x for x in ar.values() if x and str(x).strip()]),
            "managers_count":       len(managers),
            "partners_count":       len(non_ag),
            "agents_count":         len(agents),
            "total_members_count":  len(managers) + len(partners),
            "is_valid":             False,
            "issues":               [],
            "missing_fields":       [f for f in CRITICAL if not en.get(f)],
            "member_count_check":   count_check or {},
        }
        if v["missing_fields"]:
            v["issues"].append(f"Missing critical: {v['missing_fields']}")
        elif ne < 20:
            v["issues"].append(f"Only {ne}/{len(MULTI_OWNER_ENGLISH_FIELDS)} fields")
        elif not (non_ag or managers):
            v["issues"].append("No partners or managers extracted")
        else:
            v["is_valid"] = True
        if count_check and not count_check.get("verified"):
            v["issues"].append(
                f"Member count mismatch — possibly missing: "
                f"{count_check.get('missing_person_numbers', [])}"
            )
        return v

    def validate_extraction(self, *args, ownership_type: Optional[str] = None) -> Dict:
        ot = ownership_type or self.ownership_type
        if ot == "Single Owner" and len(args) == 3:
            return self.validate_single_owner_extraction(*args)
        elif len(args) in (4, 5):
            cc = args[4] if len(args) == 5 else None
            return self.validate_multi_owner_extraction(args[0], args[1], args[2], args[3], cc)
        raise ValueError(f"Invalid args for ownership_type={ot}")

    # ─────────────────────────────────────────────────────────────────────────
    # Quality report
    # ─────────────────────────────────────────────────────────────────────────
    def _calculate_quality_score(self, v: Dict) -> float:
        total = len(SINGLE_OWNER_ENGLISH_FIELDS if v.get("has_owner") is not None
                    else MULTI_OWNER_ENGLISH_FIELDS)
        score = (v.get("english_field_count", 0) / total) * 100 if total else 0
        return min(100, score) if v.get("is_valid") else max(0, score - 20)

    def _generate_recommendations(self, v: Dict) -> List[str]:
        recs = []
        if not v.get("is_valid"):
            for issue in v.get("issues", []):
                recs.append(f"Fix: {issue}")
        else:
            recs.append("Extraction valid and ready for use.")
        cc = v.get("member_count_check", {})
        if cc and not cc.get("verified"):
            missing = cc.get("missing_person_numbers", [])
            if missing:
                recs.append(f"⚠ Check raw PDF for person numbers: {missing}")
        return recs

    def get_extraction_report(self, *args, ownership_type: Optional[str] = None) -> Dict:
        v = self.validate_extraction(*args, ownership_type=ownership_type)
        return {
            "extraction_metrics":  asdict(self.extraction_metrics),
            "validation":          v,
            "quality_score":       self._calculate_quality_score(v),
            "recommendations":     self._generate_recommendations(v),
            "timestamp":           datetime.now().isoformat(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Main pipeline
    # ─────────────────────────────────────────────────────────────────────────
    def process_trade_license(self, pdf_bytes: bytes, ownership_type: Optional[str] = None) -> Dict:
        self.start_time = time.time()
        logger.info(f"Processing Trade License — size: {len(pdf_bytes)} bytes")

        raw_text = self.extract_text_from_pdf(pdf_bytes)
        if raw_text.startswith("[PDF EXTRACTION ERROR]"):
            return {"success": False, "error": raw_text, "timestamp": datetime.now().isoformat()}

        detected   = ownership_type or self.detect_ownership_type(raw_text)
        extraction = self.extract_with_ai(raw_text, detected)
        validation = self.validate_extraction(*extraction, ownership_type=detected)
        report     = self.get_extraction_report(*extraction, ownership_type=detected)
        self.extraction_metrics.processing_time = time.time() - self.start_time

        base = {
            "success":        validation["is_valid"],
            "ownership_type": detected,
            "validation":     validation,
            "quality_report": report,
            "timestamp":      datetime.now().isoformat(),
        }

        if detected == "Single Owner":
            en, ar, owner = extraction

            ubos = self.identify_ubos(
                ownership_type = "Single Owner",
                partners       = [],
                managers       = [],
                owner          = owner,
            )

            return {
                **base,
                "english_data": en,
                "arabic_data":  ar,
                "owner":        owner,
                "ubos":         ubos,
            }

        else:
            en, ar, mgr, prt, count_check = extraction

            agents     = [p for p in prt if p.get("is_agent")]
            non_agents = [p for p in prt if not p.get("is_agent")]

            ubos = self.identify_ubos(
                ownership_type = detected,
                partners       = prt,       # full list (agents filtered inside)
                managers       = mgr,
                owner          = None,
            )

            return {
                **base,
                "english_data":       en,
                "arabic_data":        ar,
                "managers":           mgr,
                "partners":           non_agents,
                "agents":             agents,
                "all_members":        prt,
                "ubos":               ubos,
                "member_count_check": count_check,
            }


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────
def process_pdf_file(file_path: str, api_key: Optional[str] = None) -> Dict:
    try:
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        return TradeLicenseExtractor(api_key=api_key).process_trade_license(pdf_bytes)
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def export_results_to_json(result: Dict, output_path: str) -> bool:
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"Results exported → {output_path}")
        return True
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return False


def get_ubo_names(result: dict) -> list:
    """
    Return a flat list of UBO name strings from a process_trade_license result.
    Useful for feeding directly into the members/stage-transition list in the
    frontend (same format as the existing membersList).

    Format: "FULL NAME (XX.XX%) — Nationality"
    """
    ubos  = result.get("ubos", [])
    names = []
    for u in ubos:
        name  = u.get("name_english", "").strip()
        share = u.get("share_percentage", "")
        nat   = u.get("nationality_english", "")

        label = name
        if share:
            label += f" ({share})"
        if nat:
            label += f" — {nat}"
        if name:
            names.append(label)
    return names