"""
fatca_service.py — FATCA Declaration Service
Handles saving, loading, and checking FATCA data for MyBank onboarding v3.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from app.services.supabase_client import supabase_service
from app.repositories.compliance_repository import FatcaRepository
from app.services.chatupload_helpers import user_docs_path
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PATH HELPERS
# ============================================================================

def fatca_json_path(email: str) -> Path:
    """Return the path for the FATCA JSON file for this user."""
    return user_docs_path(email) / "fatca.json"


# ============================================================================
# SAVE FATCA
# ============================================================================

def save_fatca(email: str, user_id: str, fatca_applicable: bool, form_data: Optional[Dict] = None) -> Dict:
    """
    Save FATCA declaration — both to disk (JSON) and Supabase DB.

    Args:
        email:             User's email address
        user_id:           User's UUID from the users table
        fatca_applicable:  True if FATCA applies, False = "Not Applicable"
        form_data:         11-field form dict (only when fatca_applicable=True)

    Returns:
        Dict with success status and saved record
    """
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "user_email":                email,
        "user_id":                   user_id,
        "fatca_applicable":          fatca_applicable,
        "saved_at":                  now,
    }

    if fatca_applicable and form_data:
        record.update({
            "entity_type":               form_data.get("entity_type"),
            "country_of_tax_residence":  form_data.get("country_of_tax_residence", "UAE"),
            "passive_nffe_us_ownership": form_data.get("passive_nffe_us_ownership"),
            "entity_incorporated_in_usa": _to_bool(form_data.get("entity_incorporated_in_usa")),
            "entity_has_us_ownership":    _to_bool(form_data.get("entity_has_us_ownership")),
            "address_or_phone_in_usa":    _to_bool(form_data.get("address_or_phone_in_usa")),
            "payment_instruction_to_usa": _to_bool(form_data.get("payment_instruction_to_usa")),
            "income_from_us_sources":     _to_bool(form_data.get("income_from_us_sources")),
            "irs_form_obtained":          _to_bool(form_data.get("irs_form_obtained")),
            "us_tax_id":                 form_data.get("us_tax_id"),
        })

    # ── Write to disk ────────────────────────────────────────────────────────
    try:
        path = fatca_json_path(email)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        logger.info(f"[FATCA] Saved to disk: {path}")
    except Exception as e:
        logger.warning(f"[FATCA] Disk write failed: {e}")

    # ── Write to Supabase ────────────────────────────────────────────────────
    try:
        db_record = {k: v for k, v in record.items()
                     if k not in ("saved_at",)}
        # Upsert: delete existing then insert (Supabase anon key has no upsert conflict)
        FatcaRepository.delete_for_user(email)
        FatcaRepository.insert(db_record)
        logger.info(f"[FATCA] Saved to Supabase for: {email}")
    except Exception as e:
        logger.warning(f"[FATCA] Supabase write failed: {e}")

    return {"success": True, "record": record}


# ============================================================================
# LOAD FATCA
# ============================================================================

def load_fatca(email: str) -> Optional[Dict]:
    """
    Load FATCA record for this user.
    1. Try disk first (fast path).
    2. Fall back to Supabase if disk file missing or empty.
    3. Re-sync Supabase data to disk so next call is fast.
    Returns None if no FATCA data exists anywhere.
    """
    path = fatca_json_path(email)

    # ── 1. Try disk ───────────────────────────────────────────────────────────
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"[FATCA] Disk load failed: {e}")

    # ── 2. Fall back to Supabase ──────────────────────────────────────────────
    try:
        res = FatcaRepository.get_for_user(email)
        rows = res.data if res and res.data else []
        if rows:
            record = rows[0]
            logger.info(f"[FATCA] Loaded from Supabase for: {email}")
            # Re-sync to disk
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2, ensure_ascii=False)
                logger.info(f"[FATCA] Re-synced to disk: {path}")
            except Exception as we:
                logger.warning(f"[FATCA] Re-sync to disk failed: {we}")
            return record
    except Exception as e:
        logger.warning(f"[FATCA] Supabase fallback failed: {e}")

    return None


# ============================================================================
# CHECK STATUS
# ============================================================================

def get_fatca_status(email: str) -> str:
    """
    Returns:
        'not_started'   — no FATCA record on disk
        'not_applicable' — recorded as not applicable
        'completed'     — form submitted and saved
    """
    data = load_fatca(email)
    if data is None:
        return "not_started"
    if not data.get("fatca_applicable", False):
        return "not_applicable"
    return "completed"


def get_fatca_status_disk_only(email: str) -> str:
    """
    Like get_fatca_status() but ONLY checks the local disk file — does NOT
    fall back to Supabase.  Use this for trigger logic (e.g. deciding whether
    to show the FATCA modal after commercial-license upload) so that a stale
    Supabase record from a previous onboarding session doesn't suppress the
    modal for a new session whose disk folder was cleared.

    Returns:
        'not_started'    — fatca.json does not exist on disk
        'not_applicable' — fatca.json exists and fatca_applicable is falsy
        'completed'      — fatca.json exists and fatca_applicable is truthy
    """
    path = fatca_json_path(email)
    if not path.exists():
        return "not_started"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data or not isinstance(data, dict):
            return "not_started"
        if not data.get("fatca_applicable", False):
            return "not_applicable"
        return "completed"
    except Exception:
        return "not_started"


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _to_bool(val) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("yes", "true", "1")
    return bool(val)
