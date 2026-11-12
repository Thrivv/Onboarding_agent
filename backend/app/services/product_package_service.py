"""
product_package_service.py — Product Package Selection Service
Handles saving, loading, and checking product package selections during onboarding.
Packages are predefined — Essential / Plus / Advanced.
AI recommendation is provided via call_text_llm based on the user's nature_of_business.
"""

import json
import uuid
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

from app.services.supabase_client import supabase_service
from app.repositories.compliance_repository import ProductPackageRepository
from app.services.chatupload_helpers import user_docs_path

logger = logging.getLogger(__name__)


# ============================================================================
# PACKAGE DEFINITIONS (matches UI exactly)
# ============================================================================

OFFERED_PRODUCTS: List[str] = [
    "CASA Accounts",
    "Deposit Accounts",
    "Loan Accounts",
    "Cards",
    "Beneficiary",
    "Own Account Transfers",
    "Within Bank Transfers",
    "Domestic Transfers",
    "Instant Transfers",
    "International Transfers",
    "Bill Payments",
    "Card Payments",
    "Loan Payments",
    "Bulk Payments",
    "Payroll",
    "Non WPS",
    "Request To Pay",
    "EIPP",
    "Checkbook Request",
    "Balance Confirmation",
    "Payer",
    "Tally",
    "Zoho",
    "RFM Loyalty",
    "Stripe",
    "RewardX",
    "HRMS",
]

PACKAGE_DEFINITIONS: Dict[str, List[str]] = {
    "Essential": [
        "CASA Accounts",
        "Deposit Accounts",
        "Loan Accounts",
        "Cards",
        "Beneficiary",
        "Own Account Transfers",
        "Within Bank Transfers",
        "Domestic Transfers",
        "Instant Transfers",
        "International Transfers",
        "Bill Payments",
        "Card Payments",
        "Loan Payments",
        "Bulk Payments",
        "Payroll",
        "Non WPS",
    ],
    "Plus": [
        "CASA Accounts",
        "Deposit Accounts",
        "Loan Accounts",
        "Cards",
        "Beneficiary",
        "Own Account Transfers",
        "Within Bank Transfers",
        "Domestic Transfers",
        "Instant Transfers",
        "International Transfers",
        "Bill Payments",
        "Card Payments",
        "Loan Payments",
        "Bulk Payments",
        "Payroll",
        "Non WPS",
        "Request To Pay",
        "EIPP",
        "Checkbook Request",
        "Balance Confirmation",
        "Payer",
    ],
    "Advanced": [
        "CASA Accounts",
        "Deposit Accounts",
        "Loan Accounts",
        "Cards",
        "Beneficiary",
        "Own Account Transfers",
        "Within Bank Transfers",
        "Domestic Transfers",
        "Instant Transfers",
        "International Transfers",
        "Bill Payments",
        "Card Payments",
        "Loan Payments",
        "Bulk Payments",
        "Payroll",
        "Non WPS",
        "Request To Pay",
        "EIPP",
        "Checkbook Request",
        "Balance Confirmation",
        "Payer",
        "Tally",
        "Zoho",
        "RFM Loyalty",
        "Stripe",
        "RewardX",
        "HRMS",
    ],
}



# ============================================================================
# PATH HELPER
# ============================================================================

def package_json_path(email: str) -> Path:
    """Return the disk path for this user's product package selection."""
    return user_docs_path(email) / "product_package.json"


# ============================================================================
# CHECK — has the user already completed package selection?
# ============================================================================

def is_package_done(email: str) -> bool:
    """Return True if product_package.json exists for this user."""
    return package_json_path(email).exists()


# ============================================================================
# SAVE PACKAGE SELECTION
# ============================================================================

def save_package_selection(
    email: str,
    selected_package: str,
    availed_products: List[str],
) -> Dict[str, Any]:
    """
    Persist the user's product package choice to disk (product_package.json)
    and upsert into Supabase product_packages table.

    Args:
        email:             User's email
        selected_package:  "Essential" | "Plus" | "Advanced"
        availed_products:  Final list of chosen product strings

    Returns:
        Dict with success flag and saved record
    """
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "id":                str(uuid.uuid4()),
        "user_email":        email,
        "selected_package":  selected_package,
        "availed_products":  availed_products,
        "saved_at":          now,
    }

    # ── Write to disk ──────────────────────────────────────────────────────
    pkg_path = package_json_path(email)
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    logger.info(f"[PKG] Package saved to disk: {pkg_path}")

    # ── Upsert to Supabase ─────────────────────────────────────────────────
    try:
        supabase_record = {
            "user_email":       email,
            "selected_package": selected_package,
            "availed_products": availed_products,
            "updated_at":       now,
        }
        ProductPackageRepository.upsert(supabase_record)
        logger.info(f"[PKG] Package upserted to Supabase for {email}")
    except Exception as e:
        logger.warning(f"[PKG]  Supabase upsert failed (disk save succeeded): {e}")

    return {"success": True, "record": record}


# ============================================================================
# LOAD PACKAGE SELECTION
# ============================================================================

def get_package_selection(email: str) -> Optional[Dict[str, Any]]:
    """
    Load the saved product package selection from disk.
    Returns None if no selection has been made yet.
    """
    path = package_json_path(email)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[PKG]  Failed to load product_package.json for {email}: {e}")
        return None


# ============================================================================
# GET PACKAGE STATUS (for sidebar / status endpoint)
# ============================================================================

def get_package_status(email: str) -> str:
    """
    Return "completed" if the user has selected a package, else "not_started".
    """
    return "completed" if is_package_done(email) else "not_started"


# ============================================================================
# AI PACKAGE RECOMMENDATION
# Reads the user's nature_of_business from Supabase, calls the LLM, and
# returns a structured recommendation for Essential / Plus / Advanced.
# Falls back to a rule-based scorer if the LLM call fails.
# ============================================================================

# Scoring table: how complex/feature-rich a domain's banking needs are (1–3)
_DOMAIN_COMPLEXITY: Dict[str, int] = {
    "Non-Profit / NGO":                   1,
    "Agriculture & Farming":              1,
    "Education & Training":               1,
    "Media & Entertainment":              2,
    "Retail":                             2,
    "Food & Beverage":                    2,
    "Hospitality & Tourism":              2,
    "Automotive":                         2,
    "Healthcare & Pharmaceuticals":       2,
    "Legal Services":                     2,
    "Financial Services & Insurance":     3,
    "Consulting & Professional Services": 2,
    "Telecommunications":                 2,
    "IT & Technology":                    3,
    "Manufacturing":                      3,
    "Logistics & Transportation":         3,
    "Import & Export / Trading":          3,
    "Energy & Utilities":                 3,
    "Mining & Natural Resources":         3,
    "Construction & Real Estate":         3,
}

_KEY_MATCHES: Dict[str, List[str]] = {
    "Essential": ["Core account management", "Domestic & international transfers", "Payroll & bulk payments"],
    "Plus":      ["Request to pay", "EIPP & checkbook services", "Balance confirmation & payer tools"],
    "Advanced":  ["ERP & accounting integrations", "Loyalty & rewards platforms", "HRMS & fintech connectors"],
}

_PACKAGE_REASONING_FALLBACK: Dict[str, str] = {
    "Essential": "Your business domains indicate standard banking requirements. Essential covers all core account, transfer, and payment needs.",
    "Plus":      "Your business profile suggests growing operational complexity. Plus adds request-to-pay, EIPP, and confirmation tools on top of core services.",
    "Advanced":  "Your selected industries typically require ERP integrations, loyalty platforms, and HRMS connectivity — all included in Advanced.",
}


def _fallback_recommendation(nature_of_business: List[str]) -> Dict[str, Any]:
    """Rule-based fallback when the LLM is unavailable."""
    if not nature_of_business:
        return {
            "recommended_package": "Plus",
            "confidence": "medium",
            "reasoning": "No specific business domains were provided. Plus is a balanced default for most corporate accounts.",
            "key_matches": _KEY_MATCHES["Plus"],
            "source": "fallback",
        }

    scores = [_DOMAIN_COMPLEXITY.get(d, 2) for d in nature_of_business]
    avg   = sum(scores) / len(scores)
    max_s = max(scores)

    if max_s == 3 or avg >= 2.5:
        pkg = "Advanced"
    elif avg >= 2:
        pkg = "Plus"
    else:
        pkg = "Essential"

    sample = ", ".join(nature_of_business[:3]) + ("…" if len(nature_of_business) > 3 else "")
    return {
        "recommended_package": pkg,
        "confidence": "medium",
        "reasoning": f"Based on your selected domains ({sample}): {_PACKAGE_REASONING_FALLBACK[pkg]}",
        "key_matches": _KEY_MATCHES[pkg],
        "source": "fallback",
    }


def recommend_package_from_nob(email: str) -> Dict[str, Any]:
    """
    Use call_text_llm to recommend a banking product package (Essential / Plus /
    Advanced) based on the user's nature_of_business stored in Supabase.

    Returns a dict with keys:
        recommended_package  str   — "Essential" | "Plus" | "Advanced"
        confidence           str   — "high" | "medium" | "low"
        reasoning            str   — 2–3 sentence explanation for the user
        key_matches          list  — bullet points matching NOB to package features
        source               str   — "llm" | "fallback"
        nature_of_business   list  — the domains that were used
    """
    # ── 1. Fetch user's nature_of_business from Supabase ──────────────────
    nature_of_business: List[str] = []
    annual_turnover: str = ""
    ownership_type: str = ""
    try:
        from app.repositories.user_repository import UserRepository
        result = UserRepository.get_product_profile(email)
        if result.data:
            row = result.data[0]
            nob_raw = row.get("nature_of_business") or []
            if isinstance(nob_raw, list):
                nature_of_business = nob_raw
            elif isinstance(nob_raw, str):
                try:
                    nature_of_business = json.loads(nob_raw)
                except Exception:
                    nature_of_business = [nob_raw] if nob_raw.strip() else []
            annual_turnover = str(row.get("annual_turnover") or "")
            ownership_type  = str(row.get("ownership_type") or "")
    except Exception as exc:
        logger.warning(f"[PKG-RECOMMEND] Could not fetch user data for {email}: {exc}")

    if not nature_of_business:
        logger.info(f"[PKG-RECOMMEND] No NOB found for {email} — using fallback")
        result_dict = _fallback_recommendation([])
        result_dict["nature_of_business"] = []
        return result_dict

    # ── 2. Build LLM prompt ───────────────────────────────────────────────
    pkg_desc = """
AVAILABLE BANKING PRODUCT PACKAGES:

1. Essential
   Products: CASA Accounts, Deposit Accounts, Loan Accounts, Cards, Beneficiary,
             Own Account Transfers, Within Bank Transfers, Domestic Transfers,
             Instant Transfers, International Transfers, Bill Payments, Card Payments,
             Loan Payments, Bulk Payments, Payroll, Non WPS
   Best for: Businesses with standard banking needs — core accounts, transfers, and payments.

2. Plus
   Products: Everything in Essential, plus: Request To Pay, EIPP, Checkbook Request,
             Balance Confirmation, Payer
   Best for: Growing businesses needing structured service requests, EIPP, and
             request-to-pay capabilities alongside core banking.

3. Advanced
   Products: Everything in Plus, plus: Tally, Zoho, RFM Loyalty, Stripe,
             RewardX, HRMS
   Best for: Complex corporate operations requiring ERP integrations, loyalty platforms,
             fintech connectors, and HRMS connectivity.
"""

    nob_str   = ", ".join(nature_of_business)
    extra_ctx = ""
    if annual_turnover:
        extra_ctx += f"\nAnnual Turnover: {annual_turnover}"
    if ownership_type:
        extra_ctx += f"\nOwnership Type: {ownership_type}"

    prompt = f"""You are a corporate banking advisor helping a business select the right product package.

Customer's Nature of Business: {nob_str}{extra_ctx}

{pkg_desc}

Based ONLY on the customer's nature of business and the package descriptions above,
recommend the single most suitable package.

Respond in valid JSON only — no markdown, no explanation outside the JSON:
{{
  "recommended_package": "Plus",
  "confidence": "high",
  "reasoning": "2-3 sentences explaining why this package fits the customer's business domains",
  "key_matches": ["feature 1 matched to their NOB", "feature 2", "feature 3"]
}}

Rules:
- recommended_package must be exactly one of: Essential, Plus, Advanced
- confidence must be: high, medium, or low
- reasoning must mention the customer's actual business domains
- key_matches must be 2–4 short bullet strings (10 words max each)
"""

    # ── 3. Call LLM ─────────────────────────────────────────────────────────
    # AI recommendation is temporarily disabled. Returning rule-based fallback.
    # To re-enable, uncomment the block below and remove the two lines after it.
    #
    # try:
    #     from app.services.llm_client import call_text_llm
    #     raw = call_text_llm(
    #         prompt=prompt,
    #         system_prompt=(
    #             "You are a precise banking product advisor. "
    #             "Respond ONLY with valid JSON matching the requested schema. "
    #             "No markdown fences, no extra text."
    #         ),
    #         max_tokens=400,
    #         temperature=0.2,
    #     )
    #     logger.info(f"[PKG-RECOMMEND] LLM raw response for {email}: {raw[:200]}")
    #     cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    #     parsed  = json.loads(cleaned)
    #     pkg = parsed.get("recommended_package", "")
    #     if pkg not in ("Essential", "Plus", "Advanced"):
    #         raise ValueError(f"Invalid recommended_package: {pkg!r}")
    #     return {
    #         "recommended_package": pkg,
    #         "confidence":          parsed.get("confidence", "medium"),
    #         "reasoning":           parsed.get("reasoning", ""),
    #         "key_matches":         parsed.get("key_matches", _KEY_MATCHES.get(pkg, [])),
    #         "source":              "llm",
    #         "nature_of_business":  nature_of_business,
    #     }
    # except Exception as exc:
    #     logger.warning(f"[PKG-RECOMMEND] LLM call/parse failed for {email}: {exc} — using fallback")
    #     result_dict = _fallback_recommendation(nature_of_business)
    #     result_dict["nature_of_business"] = nature_of_business
    #     return result_dict

    logger.info(f"[PKG-RECOMMEND] AI disabled — returning rule-based fallback for {email}")
    result_dict = _fallback_recommendation(nature_of_business)
    result_dict["nature_of_business"] = nature_of_business
    return result_dict
