"""
key_individual_service.py — Key Individual (KI / Authorised Signatory) Service
Handles saving, loading, and updating KI records for MyBank onboarding v3.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any

from app.services.supabase_client import supabase_service
from app.repositories.key_individual_repository import KeyIndividualRepository
from app.services.chatupload_helpers import user_docs_path
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# PATH HELPERS
# ============================================================================

def ki_json_path(email: str) -> Path:
    """Return the path for the key_individuals JSON file for this user."""
    return user_docs_path(email) / "key_individuals.json"


# ============================================================================
# LOAD ALL KIs
# ============================================================================

def load_key_individuals(email: str) -> List[Dict]:
    """
    Load all key individuals for this user from disk.
    Returns [] if no file exists.
    """
    path = ki_json_path(email)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[KI] Load failed: {e}")
        return []


# ============================================================================
# ACCOUNT OWNER IDENTIFICATION
# ============================================================================
# The Single-Owner conversational loop tracks the account owner as its first
# "member" internally (member_progress.json, member_eids/so_member_eids stage
# machinery) to drive the KiLoopCard / role-assignment UI. But the owner's own
# EID/Passport must be saved at the document root (EID-{ref_no}/, PP-{ref_no}/
# — same as TL-/POS-), never under members/MEID-{ref_no}-{n}/ like an
# additionally-added Key Individual. These two helpers let upload-handling
# code detect "is this upload actually the owner's own document?" so it can
# route storage correctly regardless of what the loop's internal state thinks.

def get_owner_display_name(email: str) -> Optional[str]:
    """
    Return the display_name of this ref_no's SO_OWNER key individual record,
    or None if it hasn't been created yet (created by POST /ki/so-as-selection
    once Ejari is verified).
    """
    for ki in load_key_individuals(email):
        if ki.get("source") == "SO_OWNER":
            return ki.get("display_name")
    return None


def is_account_owner(email: str, name: Optional[str]) -> bool:
    """
    True if `name` matches this account's SO_OWNER key individual record
    (case-insensitive). Used to keep the owner's own identity document out of
    members/ even while the conversational loop still tracks them as a member.
    """
    if not name or not name.strip():
        return False
    owner_name = get_owner_display_name(email)
    return bool(owner_name) and owner_name.strip().upper() == name.strip().upper()


# ============================================================================
# SAVE / UPSERT ONE KI
# ============================================================================

def _to_iso_date(value):
    """'' / None / unparseable -> None; DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD -> 'YYYY-MM-DD'."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def save_key_individual(email: str, ki_data: Dict) -> Dict:
    """
    Save or update a Key Individual record.
    ki_data must contain at least: first_name, last_name, mobile_number, id_number, id_type.

    Sets display_name automatically from first + last.
    Assigns a UUID id if not already present.

    Returns the saved KI dict.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Auto-fill display_name
    ki_data["display_name"] = (
        f"{ki_data.get('first_name', '')} {ki_data.get('last_name', '')}".strip()
    )

    if "id" not in ki_data:
        import uuid as _uuid
        ki_data["id"] = str(_uuid.uuid4())

    ki_data["user_email"] = email
    ki_data["updated_at"] = now
    if "created_at" not in ki_data:
        ki_data["created_at"] = now

    # ── Read existing list ───────────────────────────────────────────────────
    all_kis = load_key_individuals(email)

    # Replace if same id, else append
    idx = next((i for i, k in enumerate(all_kis) if k.get("id") == ki_data["id"]), None)
    if idx is not None:
        all_kis[idx] = ki_data
    else:
        all_kis.append(ki_data)

    # ── Write to disk ────────────────────────────────────────────────────────
    try:
        path = ki_json_path(email)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_kis, f, indent=2, ensure_ascii=False)
        logger.info(f"[KI] Saved to disk: {ki_data['display_name']}")
    except Exception as e:
        logger.warning(f"[KI] Disk write failed: {e}")

    # ── Write to Supabase ────────────────────────────────────────────────────
    try:
        db_record = {k: v for k, v in ki_data.items()
                     if k not in ("created_at", "updated_at")}
        # DATE columns: OCR gives "" when missing and DD/MM/YYYY otherwise.
        # Postgres rejects "" (failing the whole upsert) and would read
        # 07/11/2026 as July 11 — normalize to ISO or NULL.
        for _date_col in ("id_expiry_date", "date_of_birth"):
            if _date_col in db_record:
                db_record[_date_col] = _to_iso_date(db_record[_date_col])
        # Upsert by id
        KeyIndividualRepository.upsert(db_record)
        logger.info(f"[KI] Saved to Supabase: {ki_data['display_name']}")
    except Exception as e:
        logger.warning(f"[KI] Supabase write failed: {e}")

    return ki_data


# ============================================================================
# UPDATE KI VERIFICATION STATUS
# ============================================================================

def update_ki_verification(email: str, ki_id: str, document_id: str, status: str = "verified") -> bool:
    """
    Mark a KI as verified after their ID document has been uploaded and OCR'd.
    """
    all_kis = load_key_individuals(email)
    updated = False
    for ki in all_kis:
        if ki.get("id") == ki_id:
            ki["document_id"] = document_id
            ki["verification_status"] = status
            ki["updated_at"] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if updated:
        path = ki_json_path(email)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(all_kis, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[KI] Verification update disk write failed: {e}")
        try:
            KeyIndividualRepository.attach_document(ki_id, document_id, status)
        except Exception as e:
            logger.warning(f"[KI] Supabase verification update failed: {e}")

    return updated


def update_ki_verification_by_name(
    email: str,
    member_name: str,
    document_id: str = "",
    status: str = "verified",
) -> bool:
    """
    Mark a KI as verified by matching on display_name (case-insensitive).

    Used when member EIDs are verified in the so_member_eids / member_eids
    stage, where only the member's name is known (no ki_id is available).
    Keeps key_individuals.json in sync with member_progress.json so that
    both MOA_EXTRACTED and AI_ADDED members show the correct status in the
    final registered-individuals summary.
    """
    all_kis = load_key_individuals(email)
    updated = False
    matched_id = None

    for ki in all_kis:
        if ki.get("display_name", "").upper() == member_name.strip().upper():
            ki["verification_status"] = status
            ki["updated_at"] = datetime.now(timezone.utc).isoformat()
            if document_id:
                ki["document_id"] = document_id
            matched_id = ki.get("id")
            updated = True
            break

    if updated:
        path = ki_json_path(email)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(all_kis, f, indent=2, ensure_ascii=False)
            logger.info(f"[KI] verification_status='{status}' written for '{member_name}'")
        except Exception as e:
            logger.warning(f"[KI] Verification-by-name disk write failed: {e}")
        try:
            update_payload: dict = {"verification_status": status}
            if document_id:
                update_payload["document_id"] = document_id
            if matched_id:
                KeyIndividualRepository.update_by_id(matched_id, update_payload)
        except Exception as e:
            logger.warning(f"[KI] Supabase verification-by-name update failed: {e}")
    else:
        logger.warning(f"[KI] update_ki_verification_by_name: no KI matched '{member_name}' for {email}")

    return updated


# ============================================================================
# UPDATE KI CONTACT INFO (System Role / Email / Phone — AI_ADDED KIs only)
# ============================================================================

def update_ki_contact_info(
    email: str,
    ki_name: str,
    system_role: str,
    contact_email: str,
    phone_number: str,
    share_percentage: Optional[float] = None,
) -> bool:
    """
    Patch a KI record (matched by display_name, case-insensitive) with the
    contact-info fields collected after role assignment in the KI loop:
      - system_role      : "Self Admin" | "Maker" | "Approver"
      - contact_email    : validated email address
      - phone_number     : with country code, e.g. +971501234567
      - share_percentage : ownership % (e.g. 25.0)

    Also writes a contact_info block into the KI's EID/Passport output.json
    so the raw OCR document record is enriched with the collected details.

    Returns True if a matching record was found and updated.
    """
    all_kis = load_key_individuals(email)
    updated = False
    updated_ki_id = None
    ki_document_id = None

    for ki in all_kis:
        if ki.get("display_name", "").upper() == ki_name.strip().upper():
            ki["system_role"]   = system_role.strip()
            ki["contact_email"] = contact_email.strip()
            ki["phone_number"]  = phone_number.strip()
            if share_percentage is not None:
                ki["share_percentage"] = share_percentage
            ki["updated_at"]    = datetime.now(timezone.utc).isoformat()
            updated_ki_id       = ki.get("id")
            ki_document_id      = ki.get("document_id")
            updated = True
            break

    if updated:
        # ── 1. Write key_individuals.json ───────────────────────────────────
        path = ki_json_path(email)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(all_kis, f, indent=2, ensure_ascii=False)
            logger.info(f"[KI] Contact info saved for: {ki_name}")
        except Exception as e:
            logger.warning(f"[KI] Contact info disk write failed: {e}")

        # ── 2. Sync to Supabase ─────────────────────────────────────────────
        try:
            if updated_ki_id:
                supabase_payload = {
                    "system_role":   system_role.strip(),
                    "contact_email": contact_email.strip(),
                    "phone_number":  phone_number.strip(),
                }
                if share_percentage is not None:
                    supabase_payload["share_percentage"] = share_percentage
                KeyIndividualRepository.update_by_id(updated_ki_id, supabase_payload)
                logger.info(f"[KI] Contact info synced to Supabase for: {ki_name}")
        except Exception as e:
            logger.warning(f"[KI] Supabase contact info sync failed (non-fatal): {e}")

        # ── 3. Patch EID/Passport output.json with contact_info block ───────
        if ki_document_id:
            try:
                docs_root = user_docs_path(email)
                output_json_path = docs_root / ki_document_id / "output.json"
                if output_json_path.exists():
                    with open(output_json_path, "r", encoding="utf-8") as f:
                        ocr_data = json.load(f)
                    ocr_data["contact_info"] = {
                        "contact_email":    contact_email.strip(),
                        "phone_number":     phone_number.strip(),
                        "share_percentage": share_percentage,
                        "collected_at":     datetime.now(timezone.utc).isoformat(),
                    }
                    with open(output_json_path, "w", encoding="utf-8") as f:
                        json.dump(ocr_data, f, indent=2, ensure_ascii=False)
                    logger.info(f"[KI] contact_info written to output.json for doc_id={ki_document_id}")
                else:
                    logger.warning(f"[KI] output.json not found at {output_json_path} — skipping patch")
            except Exception as e:
                logger.warning(f"[KI] output.json patch failed (non-fatal): {e}")

    return updated


# ============================================================================
# UPDATE AS STATUS FOR MOA MEMBERS (Part A checkbox)
# ============================================================================

def save_moa_member_as_status(email: str, member_role_map: Dict[str, Any]) -> None:
    """
    Save role assignment for MOA-extracted members.
    member_role_map: { "MEMBER NAME": "AS" | "MEMBER", ... }
                  OR (legacy) { "MEMBER NAME": True/False, ... }

    Creates or updates KI records with source=MOA_EXTRACTED.
    Non-AS members are still saved so Stage 2 can reference them.
    """
    for name, role_value in member_role_map.items():
        # Accept both new string roles ("AS"/"MEMBER") and legacy booleans
        if isinstance(role_value, bool):
            is_as = role_value
        else:
            is_as = str(role_value).strip().upper() == "AS"

        parts = name.strip().split()
        first = parts[0] if parts else name
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

        existing = next(
            (k for k in load_key_individuals(email)
             if k.get("display_name", "").upper() == name.upper()
             and k.get("source") == "MOA_EXTRACTED"),
            None
        )

        ki_data = existing or {
            "first_name":   first,
            "last_name":    last,
            "mobile_number": "",
            "id_number":    "",
            "id_type":      "EID",
            "source":       "MOA_EXTRACTED",
            "verification_status": "pending",
        }

        ki_data["is_authorised_signatory"] = is_as
        ki_data["role"] = _compute_role(is_as, ki_data.get("is_ubo", False))
        ki_data["display_name"] = name
        save_key_individual(email, ki_data)

    logger.info(f"[KI] MOA member role assignments saved for: {email}")


# ============================================================================
# SAVE AI-ADDED KI (Conversational Loop — EID-first approach)
# ============================================================================

def save_ai_added_ki(
    email: str,
    extracted_data: Dict,
    role: str,
    document_id: str,
) -> Dict:
    """
    Save a Key Individual who was added via the conversational loop (AI_ADDED source).
    The EID/Passport was already uploaded and OCR'd — extracted_data contains the
    fields extracted from the document.  We mark the KI as 'verified' immediately
    since the ID document already exists on disk.

    Args:
        email:          User email.
        extracted_data: OCR output dict (name_english, id_number, expiry_date, etc.).
        role:           "AS" | "MEMBER" — role selected by user after OCR.
        document_id:    The doc folder ID under which the uploaded EID was saved.

    Returns:
        The saved KI dict (includes auto-generated id).
    """
    is_as = str(role).strip().upper() == "AS"

    # ── Extract name from OCR fields ────────────────────────────────────────
    # EID-style fields first
    name_en = (
        extracted_data.get("name_english")
        or extracted_data.get("full_name")
        or extracted_data.get("name")
        or ""
    ).strip()
    # Passport OCR uses given_names + surname instead of name_english
    if not name_en:
        _given   = (extracted_data.get("given_names") or "").strip()
        _surname = (extracted_data.get("surname") or "").strip()
        if _given or _surname:
            name_en = f"{_given} {_surname}".strip()
    parts     = name_en.split()
    first     = parts[0] if parts else ""
    last      = " ".join(parts[1:]) if len(parts) > 1 else ""
    display   = f"{first} {last}".strip() or name_en or "Unknown"

    # ── Build KI record ──────────────────────────────────────────────────────
    id_number = (
        extracted_data.get("id_number")
        or extracted_data.get("emirates_id_number")
        or extracted_data.get("passport_number")
        or ""
    )
    doc_type_raw = extracted_data.get("document_type", "eid").lower()
    id_type = "PASSPORT" if "passport" in doc_type_raw else "EID"

    ki_data = {
        "first_name":          first,
        "last_name":           last,
        "display_name":        display,
        "mobile_number":       "",
        "id_number":           id_number,
        "id_type":             id_type,
        "id_expiry_date":      extracted_data.get("expiry_date") or extracted_data.get("id_expiry") or "",
        "nationality":         extracted_data.get("nationality") or extracted_data.get("nationality_english") or "",
        "source":              "AI_ADDED",
        "verification_status": "verified",          # Already uploaded + OCR'd
        "is_authorised_signatory": is_as,
        "is_ubo":              False,
        "role":                _compute_role(is_as, False),
        "document_id":         document_id,
    }

    # ── Name-based deduplication ─────────────────────────────────────────────
    # If a KI record already exists for this person (created earlier from the
    # commercial extraction or /ki/so-as-selection with verification_status:
    # "pending"), carry forward its `id` so save_key_individual() REPLACES that
    # record instead of appending a duplicate.  Also preserve any fields that
    # weren't captured in the OCR output (share_percentage, is_ubo, etc.).
    try:
        _existing_ki = next(
            (k for k in load_key_individuals(email)
             if (k.get("display_name") or "").strip().upper() == display.upper()),
            None
        )
        if _existing_ki:
            ki_data["id"]         = _existing_ki["id"]
            ki_data["created_at"] = _existing_ki.get("created_at")
            # Preserve compliance fields that aren't in OCR output
            if _existing_ki.get("share_percentage"):
                ki_data["share_percentage"] = _existing_ki["share_percentage"]
            if _existing_ki.get("is_ubo"):
                ki_data["is_ubo"] = _existing_ki["is_ubo"]
            logger.info(
                f"[KI] Matched existing KI '{display}' "
                f"(id={_existing_ki['id']}, source={_existing_ki.get('source')}) "
                f"— updating in-place with verified status"
            )
    except Exception as _dedup_err:
        logger.warning(f"[KI] Name-dedup lookup failed (non-fatal): {_dedup_err}")

    saved = save_key_individual(email, ki_data)
    logger.info(f"[KI] AI_ADDED KI saved: {display} | role={role} | doc_id={document_id}")
    return saved


# ============================================================================
# UPDATE UBO STATUS FOR MEMBER (Stage 2)
# ============================================================================

def update_member_ubo_status(email: str, member_name: str, is_ubo: bool) -> None:
    """
    Set the UBO flag for a specific member (Stage 2 UBO confirmation).
    Looks up by display_name (case-insensitive).
    """
    all_kis = load_key_individuals(email)
    found = False
    for ki in all_kis:
        if ki.get("display_name", "").upper() == member_name.upper():
            ki["is_ubo"] = is_ubo
            ki["role"] = _compute_role(ki.get("is_authorised_signatory", False), is_ubo)
            ki["updated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        # Member not yet in KI list — create minimal record
        parts = member_name.strip().split()
        ki = {
            "first_name":            parts[0] if parts else member_name,
            "last_name":             " ".join(parts[1:]) if len(parts) > 1 else "",
            "mobile_number":         "",
            "id_number":             "",
            "id_type":               "EID",
            "source":                "MOA_EXTRACTED",
            "verification_status":   "pending",
            "is_authorised_signatory": False,
            "is_ubo":                is_ubo,
            "role":                  _compute_role(False, is_ubo),
        }
        all_kis.append(ki)

    path = ki_json_path(email)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(all_kis, f, indent=2, ensure_ascii=False)
        logger.info(f"[KI] UBO status updated for: {member_name}")
    except Exception as e:
        logger.warning(f"[KI] UBO update disk write failed: {e}")


# ============================================================================
# SELF-DECLARATION SUMMARY DATA
# ============================================================================

def get_ki_summary(email: str) -> List[Dict]:
    """
    Return a clean summary list of KIs suitable for the Self-Declaration card.
    Each item: display_name, id_type, id_number, role, is_authorised_signatory,
               is_ubo, verification_status, source.
    """
    all_kis = load_key_individuals(email)
    return [
        {
            "display_name":          k.get("display_name", ""),
            "id_type":               k.get("id_type", ""),
            "id_number":             k.get("id_number", ""),
            "role":                  k.get("role", _compute_role(
                                         k.get("is_authorised_signatory", False),
                                         k.get("is_ubo", False))),
            "is_authorised_signatory": k.get("is_authorised_signatory", False),
            "is_ubo":                k.get("is_ubo", False),
            "verification_status":   k.get("verification_status", "pending"),
            "source":                k.get("source", "MANUALLY_ADDED"),
        }
        for k in all_kis
    ]


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _compute_role(is_as: bool, is_ubo: bool) -> str:
    if is_ubo and is_as:
        return "UBO & Authorised Signatory"
    if is_ubo:
        return "UBO"
    if is_as:
        return "Authorised Signatory"
    return "Member"
