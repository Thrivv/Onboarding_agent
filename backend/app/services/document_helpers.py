# app/services/document_helpers.py
"""
Document Version Tracking Helper Functions
✅ UPDATED: Atomic transactions, proper failure handling, standardized data flow
✅ v2: ref_no-based folder structure, document prefix naming convention
"""

import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re
from app import config

logger = logging.getLogger(__name__)

# ============================================================================
# PATH CONFIGURATION
# ============================================================================

def get_documents_base_path() -> Path:
    """
    Get the base documents directory path.

    Priority:
      1. DOCUMENTS_PATH env var — set via docker-compose.yml (the existing
         YAML config for this service) for both the backend and reply-loop
         services. This is the supported way to change the upload location
         for a new build: edit the value in docker-compose.yml and
         rebuild/redeploy, no code change needed. Avoids the fragile
         file-relative computation that resolves to /app/documents/ inside
         Docker instead of the mounted /app/backend/documents/.
      2. Relative fallback — works correctly in local development where the
         file lives at backend/app/services/document_helpers.py (3 levels up
         = backend/).
    """
    docs_env = config.DOCUMENTS_PATH
    if docs_env:
        return Path(docs_env) / "id"

    # Local-dev fallback: 3 levels up from this file = backend/
    # Must match the Docker-configured DOCUMENTS_PATH convention
    # (docker-compose.yml / Dockerfile: DOCUMENTS_PATH=/app/backend/documents/sme,
    # then "id" is appended above) — i.e. backend/documents/sme/id — otherwise
    # local runs look in backend/documents/id, which doesn't exist.
    current_file = Path(__file__).resolve()
    backend_dir = current_file.parent.parent.parent
    return backend_dir / "documents" / "sme" / "id"


def get_external_file_path() -> Optional[Path]:
    """
    Optional secondary/mirror save location, set via EXTERNAL_FILE_PATH
    (docker-compose.yml, same pattern as DOCUMENTS_PATH).

    Returns None if the env var isn't set — callers must treat that as
    "mirroring is disabled" and skip silently. This is purely additive: it
    never replaces the primary DOCUMENTS_PATH save, and a missing/unwritable
    external path must never break the primary upload.
    """
    ext_env = config.EXTERNAL_FILE_PATH
    return Path(ext_env) if ext_env else None


def mirror_to_external_path(saved_folder: Path) -> None:
    """
    Best-effort mirror of a finalized document folder to EXTERNAL_FILE_PATH,
    flattened to just {ref_no}/{filename} — no {DOC}-{ref_no}/ or members/
    nesting, and no output.json (external copy is file-only).

    e.g. .../documents/sme/id/{ref_no}/EID-{ref_no}/EID-{ref_no}.png     →
         {EXTERNAL_FILE_PATH}/{ref_no}/EID-{ref_no}.png
         .../documents/sme/id/{ref_no}/members/MEID-{ref_no}-1/MEID-{ref_no}-1.png →
         {EXTERNAL_FILE_PATH}/{ref_no}/MEID-{ref_no}-1.png

    No-op if EXTERNAL_FILE_PATH isn't set. Never raises — any failure (path
    not mounted, permissions, disk full, etc.) is logged and swallowed so the
    primary save is never affected by this being unavailable.
    """
    ext_base = get_external_file_path()
    if not ext_base:
        return

    try:
        if not saved_folder.exists():
            logger.warning(f"[MIRROR] Source folder missing, skipping mirror: {saved_folder}")
            return

        docs_base = get_documents_base_path()
        try:
            rel = saved_folder.resolve().relative_to(docs_base.resolve())
            ref_no_part = rel.parts[0]
        except (ValueError, IndexError):
            # Folder isn't under the documents base path (unexpected layout) —
            # fall back to the folder's own name so we still mirror *something*.
            ref_no_part = saved_folder.name

        dest_folder = ext_base / ref_no_part
        dest_folder.mkdir(parents=True, exist_ok=True)

        for item in saved_folder.iterdir():
            if item.is_file() and item.name != "output.json":
                shutil.copy2(item, dest_folder / item.name)

        logger.info(f"[MIRROR] Mirrored (flat) to external path: {dest_folder}")
    except Exception as e:
        logger.warning(f"[MIRROR] Could not mirror {saved_folder} to external path: {e}")


# ── ref_no resolution cache (process-scoped, avoids repeated DB hits) ────────
_ref_no_cache: Dict[str, str] = {}


def get_document_ref_no(email: str) -> str:
    """
    Resolve the ref_no for a user by email.
    Uses an in-process cache so each email is only looked up once per worker.
    Falls back to email itself if ref_no is missing (backward-compat for old rows).
    """
    if email in _ref_no_cache:
        return _ref_no_cache[email]

    try:
        from app.repositories.user_repository import UserRepository
        result = UserRepository.get_ref_no(email)
        ref_no = (result.data or {}).get("ref_no") or email
    except Exception as e:
        logger.warning(f"get_document_ref_no lookup failed for {email}: {e}")
        ref_no = email  # safe fallback

    _ref_no_cache[email] = ref_no
    return ref_no


def get_user_documents_path(email: str) -> Path:
    """
    Get user-specific documents root directory.
    Path is now keyed by ref_no (unique per onboarding), not email.
    Structure: documents/id/{ref_no}/
    """
    ref_no = get_document_ref_no(email)
    base_path = get_documents_base_path()
    user_path = base_path / ref_no
    user_path.mkdir(parents=True, exist_ok=True)
    return user_path


def get_user_documents_path_by_ref(ref_no: str) -> Path:
    """
    Get user-specific documents root directory directly by ref_no.
    Use this when ref_no is already known (avoids a DB lookup).
    Structure: documents/id/{ref_no}/
    """
    base_path = get_documents_base_path()
    user_path = base_path / ref_no
    user_path.mkdir(parents=True, exist_ok=True)
    return user_path


def get_member_documents_path(email: str, member_name: str) -> Path:
    """
    Get the members/ root under the user's ref_no folder.
    Structure: documents/id/{ref_no}/members/
    Individual member document folders live directly under members/:
      members/{PREFIX}-{ref_no}-{index}/
    member_name is kept for legacy callers but the actual folder is members/ —
    individual member doc folders are resolved via build_document_id.
    """
    user_path = get_user_documents_path(email)
    members_path = user_path / "members"
    members_path.mkdir(parents=True, exist_ok=True)
    return members_path


# ============================================================================
# DOCUMENT PREFIX AND ID HELPERS
# ============================================================================

# Prefix map: (doc_type_lower, is_member) → prefix string
_DOC_PREFIX_MAP = {
    ("commercial", False):       "TL-",
    ("trade_license", False):    "TL-",
    ("commercial_license", False): "TL-",
    ("eid", False):              "EID-",
    ("passport", False):         "PP-",
    ("ejari", False):            "POS-",
    ("tenancy", False):          "POS-",
    ("moa", False):              "MOA-",
    ("memorandum", False):       "MOA-",
    # Member documents
    ("eid", True):               "MEID-",
    ("passport", True):          "MPP-",
}

_DEFAULT_PREFIX = "DOC-"


def get_document_prefix(doc_type: str, is_member: bool = False) -> str:
    """
    Return the file/folder prefix for a given document type.

    | doc_type              | is_member | prefix  |
    |-----------------------|-----------|---------|
    | commercial / trade_license | False | TL-    |
    | eid                   | False     | EID-    |
    | passport              | False     | PP-     |
    | ejari / tenancy       | False     | POS-    |
    | moa / memorandum      | False     | MOA-    |
    | eid                   | True      | MEID-   |
    | passport              | True      | MPP-    |

    Single Owner accounts never pass is_member=True for their own EID/
    Passport (see get_member_index's docstring) — the owner's own identity
    document always stays at the document root as EID-{ref_no}/PP-{ref_no},
    same as today. MPP- only applies to a Partnership/Multiple Owner
    member's passport, saved under members/.
    """
    key = (doc_type.lower().strip(), bool(is_member))
    return _DOC_PREFIX_MAP.get(key, _DEFAULT_PREFIX)


def get_member_index(email: str, member_name: str) -> int:
    """
    Return the 1-based index of member_name among this ref_no's Key
    Individuals, ordered by created_at ascending — EXCLUDING the account
    owner (source "SO_OWNER"), whose own EID/Passport is saved at the
    document root (EID-{ref_no}/, PP-{ref_no}/), not under members/. This
    keeps MEID- numbering aligned with what's actually under members/: 1 for
    the first added Key Individual, 2 for the second, and so on.

    Reads the local, ref_no-scoped key_individuals.json (via
    key_individual_service.load_key_individuals) rather than querying
    Supabase by email — the Supabase key_individuals table isn't scoped by
    ref_no, so rows from earlier onboarding attempts under the same email
    were bleeding into the ordering and inflating the index (e.g. landing on
    3 for what should have been the first added member).

    Returns 1 if not found (safe fallback).
    """
    try:
        from app.services.key_individual_service import load_key_individuals

        all_kis = load_key_individuals(email)
        non_owner_kis = [k for k in all_kis if k.get("source") != "SO_OWNER"]
        non_owner_kis.sort(key=lambda k: k.get("created_at") or "")

        for idx, m in enumerate(non_owner_kis, start=1):
            display = (m.get("display_name") or
                       f"{m.get('first_name', '')} {m.get('last_name', '')}".strip())
            if display.lower() == member_name.lower():
                return idx
        # Not found — count existing member document folders as fallback
        members_dir = get_member_documents_path(email, member_name)
        existing = [d for d in members_dir.iterdir() if d.is_dir()]
        return len(existing) + 1
    except Exception as e:
        logger.warning(f"get_member_index failed for {email}/{member_name}: {e}")
        return 1


def build_document_id(
    doc_type: str,
    ref_no: str,
    is_member: bool = False,
    member_index: Optional[int] = None,
) -> str:
    """
    Build the canonical document_id (= folder name = file stem) for a document.

    Examples:
      build_document_id("commercial", "abc-123")       → "TL-abc-123"
      build_document_id("eid",        "abc-123")       → "EID-abc-123"
      build_document_id("eid",        "abc-123", True, 1) → "MEID-abc-123-1"
      build_document_id("passport",   "abc-123", True, 2) → "PP-abc-123-2"
    """
    prefix = get_document_prefix(doc_type, is_member)
    base = f"{prefix}{ref_no}"
    if is_member and member_index is not None:
        base = f"{base}-{member_index}"
    return base

# ============================================================================
# ✅ NEW: EXTRACTED DATA NORMALIZATION
# ============================================================================

def normalize_and_validate_extracted_data(raw_data: dict, doc_type: str) -> dict:
    """
    ✅ NEW: Single source of truth for data normalization
    Called immediately after OCR, before saving
    
    Args:
        raw_data: Raw extracted data from OCR
        doc_type: Document type (eid, commercial, ejari, moa)
        
    Returns:
        Normalized, flattened dictionary
        
    Raises:
        ValueError: If extraction produced no valid data
    """
    if not raw_data or not isinstance(raw_data, dict):
        logger.warning(f"[NORMALIZE] Empty or invalid data for {doc_type}")
        raise ValueError(f"No data extracted for {doc_type}")
    
    logger.info(f"[NORMALIZE] Processing {doc_type} data...")
    logger.info(f"[NORMALIZE] Input keys: {list(raw_data.keys())}")
    
    # Step 1: Flatten nested structures
    if doc_type.lower() in ["commercial", "ejari", "tenancy", "moa", "memorandum"]:
        # Check for nested "english" key
        if "english" in raw_data and isinstance(raw_data["english"], dict):
            data = raw_data["english"]
            logger.info(f"[NORMALIZE] Extracted from 'english' key")
        # Check for nested "result" key
        elif "result" in raw_data and isinstance(raw_data["result"], dict):
            if "english" in raw_data["result"]:
                data = raw_data["result"]["english"]
                logger.info(f"[NORMALIZE] Extracted from 'result.english' key")
            else:
                data = raw_data["result"]
                logger.info(f"[NORMALIZE] Extracted from 'result' key")
        else:
            data = raw_data
            logger.info(f"[NORMALIZE] Using flat structure")
    else:
        # EID is already flat
        data = raw_data
        logger.info(f"[NORMALIZE] EID flat structure")
    
    # Step 2: Remove empty/null values
    cleaned = {}
    for key, value in data.items():
        # Skip nested objects
        if isinstance(value, dict):
            continue
        # Skip empty values
        if value is None or value == "" or value == "N/A" or value == "Not found":
            continue
        cleaned[key] = value
    
    # Step 3: Validate minimum fields
    if len(cleaned) == 0:
        logger.error(f"[NORMALIZE] No valid fields extracted for {doc_type}")
        raise ValueError(f"Extraction produced no valid data for {doc_type}")
    
    logger.info(f"[NORMALIZE] Normalized {len(cleaned)} fields for {doc_type}")
    logger.info(f"[NORMALIZE] Output keys: {list(cleaned.keys())[:5]}")
    
    return cleaned


# ============================================================================
# VERSION TRACKING FUNCTIONS
# ============================================================================

def get_document_version_info(
    user_email: str,
    document_type: str,
    member_name: Optional[str] = None
) -> Dict:
    """Get version information for a document type"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        if not base_path.exists():
            return {
                "has_existing": False,
                "next_version": 1,
                "previous_document_id": None,
                "previous_count": 0
            }
        
        existing_docs = []
        
        logger.info(f"[VERSION] Searching for existing '{document_type}' documents...")
        
        for item in base_path.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            
            output_json = item / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                doc_type = data.get("document_type", "").lower()
                
                if doc_type == document_type.lower():
                    is_current = data.get("is_current", True)
                    
                    if is_current:
                        doc_info = {
                            "document_id": item.name,
                            "version": data.get("version", 1),
                            "is_valid": data.get("is_valid", False),
                            "uploaded_at": data.get("uploaded_at", ""),
                            "path": str(item)
                        }
                        existing_docs.append(doc_info)
                        logger.info(f"[VERSION] Found current {document_type}: {item.name} (v{doc_info['version']})")
                        
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        if not existing_docs:
            logger.info(f"[VERSION] No existing {document_type} documents found")
            return {
                "has_existing": False,
                "next_version": 1,
                "previous_document_id": None,
                "previous_count": 0
            }
        
        # Sort by version (highest first)
        existing_docs.sort(key=lambda x: x["version"], reverse=True)
        latest_doc = existing_docs[0]
        
        logger.info(f"[VERSION] Found {len(existing_docs)} current {document_type} document(s)")
        logger.info(f"[VERSION] Latest version: v{latest_doc['version']} in {latest_doc['document_id']}")
        
        if len(existing_docs) > 1:
            logger.warning(f"[VERSION] WARNING: Found {len(existing_docs)} current documents!")
        
        return {
            "has_existing": True,
            "next_version": latest_doc["version"] + 1,
            "previous_document_id": latest_doc["document_id"],
            "previous_count": len(existing_docs),
            "all_current_documents": existing_docs
        }
        
    except Exception as e:
        logger.error(f"get_document_version_info failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "has_existing": False,
            "next_version": 1,
            "previous_document_id": None,
            "previous_count": 0
        }


def _document_types_match(type1: str, type2: str) -> bool:
    """Check if two document types match (considering aliases)"""
    if type1 == type2:
        return True
    
    if type1 in ["ejari", "tenancy"] and type2 in ["ejari", "tenancy"]:
        return True
    
    if type1 in ["moa", "memorandum"] and type2 in ["moa", "memorandum"]:
        return True
    
    if type1 in ["commercial", "commercial_license", "trade_license"] and type2 in ["commercial", "commercial_license", "trade_license"]:
        return True
    
    return False


def mark_previous_version_superseded(
    user_email: str,
    document_type: str,
    previous_document_id: str,
    new_document_id: str,
    member_name: Optional[str] = None
) -> bool:
    """Mark previous version as superseded by new upload"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        old_doc_path = base_path / previous_document_id / "output.json"
        
        if not old_doc_path.exists():
            error_msg = f"Previous document output.json not found: {old_doc_path}"
            logger.error(f"{error_msg}")
            raise FileNotFoundError(error_msg)
        
        try:
            with open(old_doc_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            error_msg = f"Failed to read previous document: {old_doc_path}"
            logger.error(f"{error_msg}: {e}")
            raise IOError(error_msg) from e
        
        data["is_current"] = False
        data["superseded_by"] = new_document_id
        data["superseded_at"] = datetime.now(timezone.utc).isoformat()
        
        try:
            with open(old_doc_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            error_msg = f"Failed to write supersession to: {old_doc_path}"
            logger.error(f"{error_msg}: {e}")
            raise IOError(error_msg) from e
        
        logger.info(f"[SUCCESS] Marked {previous_document_id} as superseded by {new_document_id}")
        return True
        
    except (FileNotFoundError, IOError, PermissionError):
        raise
    except Exception as e:
        error_msg = f"Unexpected error marking document as superseded: {str(e)}"
        logger.error(f"{error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        raise Exception(error_msg) from e


def mark_all_previous_versions_superseded(
    user_email: str,
    document_type: str,
    new_document_id: str,
    member_name: Optional[str] = None
) -> Tuple[int, int]:
    """Mark ALL current documents of a type as superseded by the new upload"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        if not base_path.exists():
            return (0, 0)
        
        documents_to_supersede = []
        
        for item in base_path.iterdir():
            if not item.is_dir() or item.name == "members" or item.name == new_document_id:
                continue
            
            output_json = item / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if (data.get("document_type", "").lower() == document_type.lower() and
                    data.get("is_current", True)):
                    documents_to_supersede.append(item.name)
                    
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        if not documents_to_supersede:
            logger.info(f"[SUPERSEDE] No documents to supersede")
            return (0, 0)
        
        logger.info(f"[SUPERSEDE] Superseding {len(documents_to_supersede)} document(s): {documents_to_supersede}")
        
        success_count = 0
        
        for old_doc_id in documents_to_supersede:
            try:
                mark_previous_version_superseded(
                    user_email,
                    document_type,
                    old_doc_id,
                    new_document_id,
                    member_name
                )
                success_count += 1
            except Exception as e:
                logger.error(f"[SUPERSEDE] Failed to supersede {old_doc_id}: {e}")
        
        logger.info(f"[SUPERSEDE] Successfully superseded {success_count}/{len(documents_to_supersede)} documents")
        
        return (len(documents_to_supersede), success_count)
        
    except Exception as e:
        logger.error(f"mark_all_previous_versions_superseded failed: {e}")
        return (0, 0)


def get_current_documents_only(
    user_email: str,
    member_name: Optional[str] = None
) -> List[Dict]:
    """Get only current (non-superseded) documents"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        if not base_path.exists():
            return []
        
        current_docs = []
        
        for item in base_path.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            
            output_json = item / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data.get("is_current", True):
                    current_docs.append({
                        "document_id": item.name,
                        "document_type": data.get("document_type"),
                        "version": data.get("version", 1),
                        "filename": data.get("filename"),
                        "is_valid": data.get("is_valid", False),
                        "uploaded_at": data.get("uploaded_at"),
                        "extracted_data": data.get("extracted_fields") or data.get("extracted_data"),
                        "member_name": data.get("member_name")
                    })
                    
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        return current_docs
        
    except Exception as e:
        logger.error(f"get_current_documents_only failed: {e}")
        return []


def detect_and_repair_version_conflicts(
    user_email: str,
    member_name: Optional[str] = None,
    auto_repair: bool = True
) -> Dict:
    """Detect and optionally repair documents where multiple versions are marked as current"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        if not base_path.exists():
            return {"conflicts_found": 0, "conflicts_repaired": 0}
        
        documents_by_type = {}
        
        for item in base_path.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            
            output_json = item / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                doc_type = data.get("document_type", "").lower()
                is_current = data.get("is_current", True)
                version = data.get("version", 1)
                
                if doc_type not in documents_by_type:
                    documents_by_type[doc_type] = []
                
                documents_by_type[doc_type].append({
                    "document_id": item.name,
                    "version": version,
                    "is_current": is_current,
                    "path": output_json,
                    "uploaded_at": data.get("uploaded_at")
                })
                
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        conflicts = []
        
        for doc_type, docs in documents_by_type.items():
            current_docs = [d for d in docs if d["is_current"]]
            
            if len(current_docs) > 1:
                logger.warning(f"[CONFLICT] Found {len(current_docs)} current versions of {doc_type}")
                conflicts.append({
                    "document_type": doc_type,
                    "current_count": len(current_docs),
                    "documents": current_docs
                })
        
        repaired_count = 0
        
        if auto_repair and conflicts:
            logger.info(f"[REPAIR] Auto-repairing {len(conflicts)} conflicts...")
            
            for conflict in conflicts:
                docs = sorted(conflict["documents"], key=lambda x: x["version"], reverse=True)
                
                latest = docs[0]
                older_docs = docs[1:]
                
                logger.info(f"[REPAIR] {conflict['document_type']}: Keeping v{latest['version']}, marking {len(older_docs)} older versions as superseded")
                
                for old_doc in older_docs:
                    try:
                        with open(old_doc["path"], 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        data["is_current"] = False
                        data["superseded_by"] = latest["document_id"]
                        data["superseded_at"] = datetime.now(timezone.utc).isoformat()
                        data["auto_repaired"] = True
                        data["repaired_at"] = datetime.now(timezone.utc).isoformat()
                        
                        with open(old_doc["path"], 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        
                        repaired_count += 1
                        logger.info(f"[REPAIR] Repaired: {old_doc['document_id']}")
                        
                    except Exception as e:
                        logger.error(f"[REPAIR] Failed to repair {old_doc['document_id']}: {e}")
        
        return {
            "conflicts_found": len(conflicts),
            "conflicts_repaired": repaired_count,
            "conflicts": conflicts,
            "success": repaired_count == sum(len(c["documents"]) - 1 for c in conflicts)
        }
        
    except Exception as e:
        logger.error(f"detect_and_repair_version_conflicts failed: {e}")
        return {
            "conflicts_found": 0,
            "conflicts_repaired": 0,
            "error": str(e)
        }


def calculate_document_status(user_email: str, required_doc_types: list, documents: list, member_name: str = None):
    """
    Calculate document submission status for required document types
    
    ✅ SMART LOGIC: Only checks if at least ONE approved version exists per type
    - Ignores rejected/tampered documents if an approved replacement exists
    - Handles multiple versions of the same document type correctly
    
    Args:
        user_email: User's email
        required_doc_types: List of required document types (e.g., ['eid', 'ejari'])
        documents: List of document dicts (from get_submitted_documents)
        member_name: Optional member name for filtering member-specific documents
    
    Returns:
        dict with keys:
        - can_confirm: bool - Whether user can confirm (all required docs approved)
        - all_submitted: bool - Whether all required types have at least one submission
        - all_approved: bool - Whether all required types have at least one approved doc
        - missing_documents: list - Document types with no submissions
        - pending_approval: list - Document types with submissions but no approvals
        - total_required: int
        - total_submitted: int
        - total_approved: int
    """
    
    # ============================================================================
    # STEP 1: Filter to CURRENT documents only
    # ============================================================================
    current_docs = [d for d in documents if d.get("is_current") == True]

    # If member_name specified, filter to that member's documents
    if member_name:
        current_docs = [d for d in current_docs if d.get("member_name") == member_name]

    # ============================================================================
    # STEP 2: Group documents by type and determine status for each type
    # ============================================================================
    # Normalize required doc types (handle aliases)
    normalized_required = set()
    for doc_type in required_doc_types:
        doc_type_lower = doc_type.lower()
        normalized_required.add(doc_type_lower)

        # Add aliases
        if doc_type_lower in ["tenancy", "ejari"]:
            normalized_required.update(["ejari", "tenancy"])
        elif doc_type_lower in ["moa", "memorandum"]:
            normalized_required.update(["moa", "memorandum"])
        elif doc_type_lower in ["commercial", "commercial_license", "trade_license"]:
            normalized_required.update(["commercial", "commercial_license", "trade_license"])

    # Group current documents by type
    docs_by_type = {}
    for doc in current_docs:
        doc_type = doc["document_type"].lower()

        if doc_type not in docs_by_type:
            docs_by_type[doc_type] = []
        docs_by_type[doc_type].append(doc)

    logger.debug(
        f"[calculate_document_status] {user_email} member={member_name} "
        f"required={normalized_required} have_types={list(docs_by_type.keys())}"
    )
    
    # ============================================================================
    # STEP 3: Check status for each required document type
    # ============================================================================
    approved_types = set()  # Types that have at least one approved document
    submitted_types = set()  # Types that have at least one submission
    pending_types = []      # Types with submissions but no approvals
    missing_types = []      # Types with no submissions at all
    
    for required_type in normalized_required:
        # Check if this type has any current documents
        has_submission = False
        has_approval = False
        
        # Check all possible aliases for this type
        check_types = [required_type]
        if required_type in ["tenancy", "ejari"]:
            check_types = ["ejari", "tenancy"]
        elif required_type in ["moa", "memorandum"]:
            check_types = ["moa", "memorandum"]
        elif required_type in ["commercial", "commercial_license", "trade_license"]:
            check_types = ["commercial", "commercial_license", "trade_license"]
        
        # Look through all aliases
        for check_type in check_types:
            if check_type in docs_by_type:
                docs_of_this_type = docs_by_type[check_type]
                has_submission = True
                submitted_types.add(required_type)
                
                # Check if ANY document of this type is approved
                for doc in docs_of_this_type:
                    if doc["status_category"] == "approved":
                        has_approval = True
                        approved_types.add(required_type)
                        break

                if has_approval:
                    break  # Found approval, no need to check other aliases

        # Determine status for this type
        if not has_submission:
            missing_types.append(required_type)
        elif not has_approval:
            pending_types.append(required_type)

    # ============================================================================
    # STEP 4: Calculate final status
    # ============================================================================
    total_required = len(required_doc_types)
    total_submitted = len(submitted_types)
    total_approved = len(approved_types)

    all_submitted = len(missing_types) == 0
    all_approved = len(approved_types) >= len(required_doc_types)
    can_confirm = all_approved  # Can confirm if all required types have approvals

    logger.debug(
        f"[calculate_document_status] {user_email} required={total_required} submitted={total_submitted} "
        f"approved={total_approved} missing={missing_types} pending={pending_types} can_confirm={can_confirm}"
    )

    return {
        "can_confirm": can_confirm,
        "all_submitted": all_submitted,
        "all_approved": all_approved,
        "missing_documents": missing_types,
        "pending_approval": pending_types,
        "total_required": total_required,
        "total_submitted": total_submitted,
        "total_approved": total_approved
    }

def get_document_history(
    user_email: str,
    document_type: str,
    member_name: Optional[str] = None
) -> List[Dict]:
    """Get complete version history for a document type"""
    try:
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        if not base_path.exists():
            return []
        
        versions = []
        
        for item in base_path.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            
            output_json = item / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_type = data.get("document_type", "").lower()
                
                if not _document_types_match(stored_type, document_type.lower()):
                    continue
                
                versions.append({
                    "document_id": item.name,
                    "version": data.get("version", 1),
                    "filename": data.get("filename"),
                    "is_valid": data.get("is_valid", False),
                    "is_current": data.get("is_current", True),
                    "uploaded_at": data.get("uploaded_at"),
                    "superseded_by": data.get("superseded_by"),
                    "superseded_at": data.get("superseded_at"),
                    "extracted_data": data.get("extracted_fields") or data.get("extracted_data"),
                    "validation": data.get("validation"),
                    "ai_reasoning": data.get("ai_reasoning"),
                    "status_message": data.get("status_message")
                })
                
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        versions.sort(key=lambda x: x["version"], reverse=True)
        
        return versions
        
    except Exception as e:
        logger.error(f"get_document_history failed: {e}")
        return []


# ============================================================================
# ✅ UPDATED: ATOMIC SAVE WITH TRANSACTION-LIKE BEHAVIOR
# ============================================================================

def save_document_with_version(
    user_email: str,
    document_type: str,
    document_id: str,
    filename: str,
    file_content: bytes,
    extracted_data: Dict,
    is_valid: bool,
    validation_result: Dict,
    member_name: Optional[str] = None,
    additional_data: Optional[Dict] = None
) -> Tuple[bool, str, Dict]:
    """
    ✅ UPDATED: Save document with atomic transaction-like behavior
    
    Changes:
    - Pre-validation: Detect and repair conflicts BEFORE saving
    - Atomic writes: Save to temp location, then commit
    - Proper rollback: Clean up on any failure
    - Post-validation: Verify consistency after save
    """
    
    temp_folder = None
    
    try:
        logger.info(f"\n{'='*80}")
        logger.info(f"[SAVE] ATOMIC DOCUMENT SAVE")
        logger.info(f"[SAVE] Type: {document_type}")
        logger.info(f"[SAVE] Document ID: {document_id}")
        logger.info(f"[SAVE] User: {user_email}")
        if member_name:
            logger.info(f"[SAVE] Member: {member_name}")
        logger.info(f"{'='*80}\n")
        
        # ========================================================================
        # ✅ PHASE 1: PRE-VALIDATION (Detect and repair conflicts)
        # ========================================================================
        logger.info(f"[SAVE] PHASE 1: Pre-validation...")
        
        conflict_check = detect_and_repair_version_conflicts(
            user_email, member_name, auto_repair=True
        )
        
        if conflict_check["conflicts_found"] > 0:
            logger.warning(f"[SAVE] Found {conflict_check['conflicts_found']} conflicts")
            logger.info(f"[SAVE] Repaired {conflict_check['conflicts_repaired']} conflicts")
            
            if conflict_check["conflicts_repaired"] != conflict_check["conflicts_found"]:
                error_msg = f"Could not repair all conflicts: {conflict_check['conflicts_repaired']}/{conflict_check['conflicts_found']}"
                logger.error(f"[SAVE] {error_msg}")
                return False, error_msg, {}
        
        logger.info(f"[SAVE] Pre-validation passed\n")
        
        # ========================================================================
        # PHASE 2: GET VERSION INFO (Now guaranteed conflict-free)
        # ========================================================================
        logger.info(f"[SAVE] PHASE 2: Get version info...")
        version_info = get_document_version_info(user_email, document_type, member_name)
        
        logger.info(f"[SAVE] Version info:")
        logger.info(f"  - Has existing: {version_info['has_existing']}")
        logger.info(f"  - Next version: {version_info['next_version']}")
        logger.info(f"  - Previous document: {version_info.get('previous_document_id')}")
        logger.info(f"  - Current documents found: {version_info.get('previous_count', 0)}\n")
        
        # ========================================================================
        # PHASE 3: PREPARE TEMP LOCATION
        # ========================================================================
        logger.info(f"[SAVE] PHASE 3: Prepare temp location...")
        
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        # Create temp folder with .tmp suffix
        temp_folder = base_path / f"{document_id}.tmp"
        
        if temp_folder.exists():
            shutil.rmtree(temp_folder)
        
        temp_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"[SAVE] Temp folder created: {temp_folder}")
        
        # Save file to temp location
        temp_file_path = temp_folder / filename
        with open(temp_file_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"[SAVE] File written to temp location")
        
        # Prepare output.json data
        output_data = {
            "document_type": document_type,
            "filename": filename,
            "document_id": document_id,
            "version": version_info["next_version"],
            "is_current": True,
            "is_valid": is_valid,
            "extracted_fields": extracted_data,  # ✅ Standardized field name
            "validation": validation_result,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "member_name": member_name,
            "supersedes": version_info.get("previous_document_id"),
            "superseded_by": None,
            "superseded_at": None,
            "superseded_count": version_info.get("previous_count", 0)
        }
        
        if additional_data:
            output_data.update(additional_data)
        
        # Save output.json to temp location
        temp_output_path = temp_folder / "output.json"
        with open(temp_output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[SAVE] output.json written to temp location\n")
        
        # ========================================================================
        # ✅ PHASE 4: MARK SUPERSESSIONS (While still in temp)
        # ========================================================================
        logger.info(f"[SAVE] PHASE 4: Mark supersessions...")
        
        if version_info["has_existing"]:
            try:
                attempted, succeeded = mark_all_previous_versions_superseded(
                    user_email,
                    document_type,
                    document_id,
                    member_name
                )
                
                if attempted > 0 and succeeded != attempted:
                    error_msg = f"Failed to supersede {attempted - succeeded}/{attempted} previous documents"
                    logger.error(f"[SAVE] {error_msg}")
                    
                    # Rollback: Delete temp folder
                    if temp_folder and temp_folder.exists():
                        shutil.rmtree(temp_folder)
                        logger.info(f"[SAVE] Rolled back temp folder")
                    
                    return False, error_msg, {}
                
                if succeeded > 0:
                    logger.info(f"[SAVE] Successfully superseded {succeeded} previous version(s)")
                
            except Exception as supersede_error:
                logger.error(f"[SAVE] Supersession failed: {supersede_error}")
                
                # Rollback: Delete temp folder
                if temp_folder and temp_folder.exists():
                    shutil.rmtree(temp_folder)
                    logger.info(f"[SAVE] Rolled back temp folder")
                
                error_msg = f"Supersession failed: {str(supersede_error)}"
                return False, error_msg, {}
        
        logger.info(f"[SAVE] Supersession phase complete\n")
        
        # ========================================================================
        # ✅ PHASE 5: ATOMIC COMMIT (Rename temp to final)
        # ========================================================================
        logger.info(f"[SAVE] PHASE 5: Atomic commit...")
        
        final_folder = base_path / document_id
        
        # Delete old version if exists (same document_id - re-upload case)
        if final_folder.exists():
            shutil.rmtree(final_folder)
            logger.info(f"[SAVE] Deleted old version in same folder: {document_id}")
        
        # Atomic rename (this is the commit point)
        temp_folder.rename(final_folder)
        temp_folder = None  # Prevent rollback now that commit succeeded

        logger.info(f"[SAVE] Upload committed atomically: {final_folder}\n")

        # ✅ Best-effort mirror to EXTERNAL_FILE_PATH (no-op if unset; never
        # raises — a mirror failure must not affect the primary save above).
        mirror_to_external_path(final_folder)

        # ========================================================================
        # PHASE 6: POST-COMMIT VERIFICATION
        # ========================================================================
        logger.info(f"[SAVE] PHASE 6: Post-commit verification...")
        
        verify_info = get_document_version_info(user_email, document_type, member_name)
        
        if verify_info.get("previous_count", 0) > 0:
            logger.warning(f"[SAVE] WARNING: Found {verify_info['previous_count']} other current documents after save!")
        else:
            logger.info(f"[SAVE] Verification passed: This is the only current document")
        
        logger.info(f"\n{'='*80}")
        logger.info(f"[SAVE] DOCUMENT SAVED SUCCESSFULLY")
        logger.info(f"[SAVE] Version: {version_info['next_version']}")
        logger.info(f"[SAVE] Conflicts repaired: {conflict_check['conflicts_repaired']}")
        logger.info(f"{'='*80}\n")
        
        return True, "Document saved successfully", version_info
        
    except Exception as e:
        logger.error(f"[SAVE] Save failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Rollback: Clean up temp folder
        if temp_folder and temp_folder.exists():
            try:
                shutil.rmtree(temp_folder)
                logger.info(f"[SAVE] Cleaned up temp folder after error")
            except Exception as rollback_error:
                logger.error(f"[SAVE] Failed to clean up temp folder: {rollback_error}")
        
        return False, f"Failed to save document: {str(e)}", {}

# ============================================================================
# ✅ NEW: SAVE FAILED UPLOAD AS HISTORICAL RECORD
# ============================================================================

def save_failed_upload_as_history(
    user_email: str,
    document_type: str,
    filename: str,
    file_content: bytes,
    error_reason: str,
    extracted_data: Optional[Dict] = None,
    validation_result: Optional[Dict] = None,
    member_name: Optional[str] = None,
    additional_data: Optional[Dict] = None
) -> Tuple[bool, str, str]:
    """
    ✅ NEW: Save failed uploads as historical records immediately
    
    Args:
        user_email: User email
        document_type: Document type
        filename: Original filename
        file_content: File bytes
        error_reason: Why the upload failed
        extracted_data: Extracted data (if any)
        validation_result: Validation details (if any)
        member_name: Optional member name
        additional_data: Optional additional data
        
    Returns:
        Tuple of (success, message, document_id)
    """
    try:
        logger.info(f"\n{'='*80}")
        logger.info(f"[HISTORY] SAVING FAILED UPLOAD AS HISTORY")
        logger.info(f"[HISTORY] Type: {document_type}")
        logger.info(f"[HISTORY] Reason: {error_reason}")
        logger.info(f"{'='*80}\n")
        
        # Get version info
        version_info = get_document_version_info(user_email, document_type, member_name)
        
        # Create unique document ID with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        document_id = f"{document_type}_failed_{timestamp}"
        
        # Get base path
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        # Create folder
        doc_folder = base_path / document_id
        doc_folder.mkdir(parents=True, exist_ok=True)
        
        # Save file
        file_path = doc_folder / filename
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"[HISTORY] File saved: {file_path}")
        
        # Prepare metadata
        output_data = {
            "document_type": document_type,
            "filename": filename,
            "document_id": document_id,
            "version": version_info["next_version"],
            "is_current": False,  # ✅ NEVER current!
            "is_valid": False,
            "status_category": "rejected",
            "ai_reasoning": error_reason,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "member_name": member_name,
            "failure_type": "validation_failed",
            "archived_immediately": True,
            "extracted_fields": extracted_data or {},
            "validation": validation_result or {}
        }
        
        if additional_data:
            output_data.update(additional_data)
        
        # Save output.json
        output_json_path = doc_folder / "output.json"
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[HISTORY] Metadata saved")
        logger.info(f"[HISTORY] Failed upload saved as v{version_info['next_version']} (historical)\n")
        
        return True, "Failed upload saved to history", document_id
        
    except Exception as e:
        logger.error(f"[HISTORY] Failed to save history: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, f"Failed to save history: {str(e)}", ""


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_display_document_name(doc_type: str) -> str:
    """Convert internal document type to user-friendly display name"""
    display_names = {
        "identity": "Identity Document (Emirates ID or Passport)",
        "eid": "Emirates ID (EID)",
        "eid_or_passport": "Emirates ID or Passport",
        "passport": "Passport",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)"
    }
    return display_names.get(doc_type.lower(), doc_type.upper())


def normalize_document_type(doc_type: str) -> str:
    """Normalize document type to canonical form"""
    doc_type_lower = doc_type.lower().strip()
    
    if doc_type_lower in ["eid", "emirates_id", "emiratesid"]:
        return "eid"

    if doc_type_lower in ["passport", "travel_document", "travel document", "intl_id"]:
        return "passport"

    if doc_type_lower in ["ejari", "tenancy", "tenancy_contract"]:
        return "ejari"
    
    if doc_type_lower in ["commercial", "commercial_license", "trade_license"]:
        return "commercial"
    
    if doc_type_lower in ["moa", "memorandum", "memorandum_of_association"]:
        return "moa"
    
    return doc_type_lower


def cleanup_old_versions(
    user_email: str,
    document_type: str,
    keep_count: int = 3,
    member_name: Optional[str] = None
) -> int:
    """Clean up old document versions (keep only recent N versions)"""
    try:
        versions = get_document_history(user_email, document_type, member_name)
        
        if len(versions) <= keep_count:
            logger.info(f"No cleanup needed - only {len(versions)} versions")
            return 0
        
        versions_to_delete = versions[keep_count:]
        
        if member_name:
            base_path = get_member_documents_path(user_email, member_name)
        else:
            base_path = get_user_documents_path(user_email)
        
        deleted_count = 0
        
        for version in versions_to_delete:
            doc_folder = base_path / version["document_id"]
            
            if doc_folder.exists():
                shutil.rmtree(doc_folder)
                deleted_count += 1
                logger.info(f"Deleted old version: {version['document_id']} (v{version['version']})")
        
        logger.info(f"[SUCCESS] Cleaned up {deleted_count} old versions")
        return deleted_count
        
    except Exception as e:
        logger.error(f"cleanup_old_versions failed: {e}")
        return 0


# ============================================================================
# EXPORT
# ============================================================================

__all__ = ["router"]