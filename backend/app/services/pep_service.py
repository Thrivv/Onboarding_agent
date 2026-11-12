"""
pep_service.py — PEP (Politically Exposed Person) Declaration Service
Handles saving, loading, and checking PEP data for MyBank onboarding v4.

PEP data structure:
  domestic_pep:
    - status (bool)
    - name   (str, required if status=True)
    - position (str, required if status=True)
  foreign_pep:
    - status (bool)
    - country (str, required if status=True)
    - name    (str, required if status=True)
    - position (str, required if status=True)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from app.services.supabase_client import supabase_service
from app.repositories.compliance_repository import PepRepository
from app.services.chatupload_helpers import user_docs_path
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PATH HELPERS
# ============================================================================

def pep_json_path(email: str) -> Path:
    """Return the path for the PEP JSON file for this user."""
    return user_docs_path(email) / "pep.json"


# ============================================================================
# SAVE PEP
# ============================================================================

def save_pep(email: str, user_id: str, pep_data: Dict) -> Dict:
    """
    Save PEP declaration — both to disk (JSON) and Supabase DB.

    Args:
        email:     User's email address
        user_id:   User's UUID from the users table
        pep_data:  Dict with domestic_pep and foreign_pep sections

    Returns:
        Dict with success status and saved record
    """
    now = datetime.now(timezone.utc).isoformat()

    domestic = pep_data.get("domestic_pep", {})
    foreign = pep_data.get("foreign_pep", {})

    record = {
        "user_email":           email,
        "user_id":              user_id,
        "saved_at":             now,
        # Domestic PEP
        "domestic_pep":         _to_bool(domestic.get("status", False)),
        "domestic_pep_name":    domestic.get("name", ""),
        "domestic_pep_position": domestic.get("position", ""),
        # Foreign PEP
        "foreign_pep":          _to_bool(foreign.get("status", False)),
        "foreign_pep_country":  foreign.get("country", ""),
        "foreign_pep_name":     foreign.get("name", ""),
        "foreign_pep_position": foreign.get("position", ""),
    }

    # ── Write to disk ────────────────────────────────────────────────────────
    try:
        path = pep_json_path(email)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        logger.info(f"[PEP] Saved to disk: {path}")
    except Exception as e:
        logger.warning(f"[PEP] Disk write failed: {e}")

    # ── Write to Supabase ────────────────────────────────────────────────────
    try:
        db_record = {k: v for k, v in record.items() if k != "saved_at"}
        # Upsert: delete existing then insert
        PepRepository.delete_for_user(email)
        PepRepository.insert(db_record)
        logger.info(f"[PEP] Saved to Supabase for: {email}")
    except Exception as e:
        logger.warning(f"[PEP] Supabase write failed (non-fatal): {e}")

    return {"success": True, "record": record}


# ============================================================================
# LOAD PEP
# ============================================================================

def load_pep(email: str) -> Optional[Dict]:
    """
    Load PEP record for this user.
    1. Try disk first (fast path).
    2. Fall back to Supabase if disk file missing or empty.
    3. Re-sync Supabase data to disk so next call is fast.
    Returns None if no PEP data exists anywhere.
    """
    path = pep_json_path(email)

    # ── 1. Try disk ───────────────────────────────────────────────────────────
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"[PEP] Disk load failed: {e}")

    # ── 2. Fall back to Supabase ──────────────────────────────────────────────
    try:
        res = PepRepository.get_for_user(email)
        rows = res.data if res and res.data else []
        if rows:
            record = rows[0]
            logger.info(f"[PEP] Loaded from Supabase for: {email}")
            # Re-sync to disk
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2, ensure_ascii=False)
                logger.info(f"[PEP] Re-synced to disk: {path}")
            except Exception as we:
                logger.warning(f"[PEP] Re-sync to disk failed: {we}")
            return record
    except Exception as e:
        logger.warning(f"[PEP] Supabase fallback failed: {e}")

    return None


# ============================================================================
# CHECK STATUS
# ============================================================================

def get_pep_status(email: str) -> str:
    """
    Returns:
        'not_started' — no PEP record on disk or Supabase
        'completed'   — PEP form submitted and saved
    """
    data = load_pep(email)
    if data is None:
        return "not_started"
    return "completed"


def get_pep_status_disk_only(email: str) -> str:
    """
    Like get_pep_status() but ONLY checks the local disk file.
    Used for trigger logic so stale Supabase records don't suppress the form.

    Returns:
        'not_started' — pep.json does not exist on disk
        'completed'   — pep.json exists and has valid data
    """
    path = pep_json_path(email)
    if not path.exists():
        return "not_started"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data or not isinstance(data, dict):
            return "not_started"
        return "completed"
    except Exception:
        return "not_started"


# ============================================================================
# VALIDATE PEP DATA
# ============================================================================

def validate_pep_data(pep_data: Dict) -> Dict:
    """
    Validate PEP form data against business rules:
      - If domestic_pep.status = True → name and position are required
      - If foreign_pep.status = True  → country, name, and position are required

    Returns:
        { "valid": bool, "missing_fields": [str], "message": str }
    """
    missing = []
    domestic = pep_data.get("domestic_pep", {})
    foreign = pep_data.get("foreign_pep", {})

    if _to_bool(domestic.get("status")):
        if not domestic.get("name", "").strip():
            missing.append("domestic_pep.name")
        if not domestic.get("position", "").strip():
            missing.append("domestic_pep.position")

    if _to_bool(foreign.get("status")):
        if not foreign.get("country", "").strip():
            missing.append("foreign_pep.country")
        if not foreign.get("name", "").strip():
            missing.append("foreign_pep.name")
        if not foreign.get("position", "").strip():
            missing.append("foreign_pep.position")

    if missing:
        return {
            "valid": False,
            "missing_fields": missing,
            "message": "Please complete all required PEP fields before submitting."
        }
    return {"valid": True, "missing_fields": [], "message": ""}


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _to_bool(val) -> Optional[bool]:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("yes", "true", "1")
    return bool(val)
