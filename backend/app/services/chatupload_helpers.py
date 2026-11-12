# app/services/chatupload_helpers.py

"""
Shared utility functions for document onboarding
Used by chatupload.py and document_messaging.py
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import json
from app.services.supabase_client import supabase
from app.repositories.conversation_repository import ConversationRepository
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
)

logger = logging.getLogger(__name__)

# ============================================================================
# PATH MANAGEMENT
# ============================================================================

def _resolve_ref_no(email: str) -> str:
    """
    Resolve the ref_no for a user.  Uses document_helpers cache so only one
    DB round-trip happens per worker process per email.
    """
    try:
        from app.services.document_helpers import get_document_ref_no
        return get_document_ref_no(email)
    except Exception as e:
        logger.warning(f"[_resolve_ref_no] failed for {email}: {e}")
        return email  # safe fallback


def user_docs_path(email: str) -> Path:
    """
    Get user's document root directory, keyed by ref_no.
    Delegates to get_documents_base_path() so the DOCUMENTS_PATH env var
    is honoured consistently (Docker uses /app/backend/documents,
    local dev uses the relative backend/documents path).
    """
    from app.services.document_helpers import get_documents_base_path, get_document_ref_no
    ref_no = get_document_ref_no(email)
    return get_documents_base_path() / ref_no


def members_root_path(email: str) -> Path:
    """Get members root directory: {docs_base}/{ref_no}/members/"""
    return user_docs_path(email) / "members"


def member_progress_path(email: str) -> Path:
    """Get member progress JSON file path (lives in ref_no root)"""
    return user_docs_path(email) / "member_progress.json"


def get_display_document_name(doc_type: str) -> str:
    """Convert internal document type to user-friendly display name"""
    display_names = {
        "identity": "Identity Document (Emirates ID or Passport)",
        "eid": "Emirates ID (EID)",
        "eid_or_passport": "Emirates ID or Passport",
        "passport": "Passport",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)",
        "certificate_of_incorporation": "Certificate of Incorporation (CoI)",
        "coi": "Certificate of Incorporation (CoI)",
    }
    return display_names.get(doc_type.lower(), doc_type.upper())


# ============================================================================
# DOCUMENT TYPE CONFIGURATION
# ============================================================================

def get_allowed_document_types(
    account_type: str, 
    ownership_type: str, 
    document_stage: str
) -> Dict[str, List[str]]:
    """Get allowed document types for specific account configuration and stage"""

    if account_type == ACCOUNT_CORPORATE and not ownership_type:
        # Ownership type (Single Owner vs Partnership/Multiple Owners) is no
        # longer asked upfront — it's auto-classified from the Commercial
        # License once uploaded (see the auto-classification block in
        # chatupload.py's upload_conversational()). Until that happens, only
        # the Commercial License itself is a valid upload.
        return {
            "allowed_types": ["commercial"],
            "stage_description": "Account — Ownership Detection",
            "required_docs": ["Commercial License"]
        }

    if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
        return {
            # ✅ Use "identity" virtual key (satisfied by EID OR Passport, not both)
            # Using separate "eid"/"passport" caused remaining_docs to show "Passport"
            # even after EID was already uploaded, since passport was never submitted.
            # NEW FLOW: Commercial → MOA → Ejari → EID/Passport → KI loop → FATCA
            # MOA and Ejari come before identity so post-commercial messaging says
            # "upload MOA next", then "upload Ejari next".
            "allowed_types": ["commercial", "moa", "ejari", "identity"],
            "stage_description": "Sole Proprietorship Account",
            "required_docs": [
                "Commercial License",
                "Memorandum of Association (MOA)",
                "Ejari (Tenancy Contract)",
                "Emirates ID (EID) or Passport",
            ]
        }
    
    elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:

        if document_stage == STAGE_IDENTIFICATION:
            return {
                "allowed_types": ["commercial", "ejari", "tenancy", "moa", "memorandum"],
                "stage_description": "Joint Ownership Identification Stage",
                "required_docs": ["Commercial License", "Ejari (Address Proof)", "Memorandum of Association (MOA)"]
            }

        elif document_stage == STAGE_CORPORATE_SHAREHOLDER_DOCS:
            return {
                # Also accept MOA here — the MOA may not have been uploaded yet when we
                # transitioned early (commercial detected corporate shareholders before MOA)
                "allowed_types": ["certificate_of_incorporation", "coi", "ejari", "tenancy", "moa", "memorandum"],
                "stage_description": "Corporate Shareholder CoI Collection",
                "required_docs": [
                    "Certificate of Incorporation for each corporate shareholder",
                    "Ejari (Address Proof)",
                    "Memorandum of Association (MOA)",
                ]
            }

        elif document_stage == STAGE_MEMBER_EIDS:
            return {
                "allowed_types": ["eid", "passport"],
                "stage_description": "Joint Ownership Member Identity Document Collection",
                "required_docs": ["Emirates ID (EID) or Passport for each member"]
            }
    
    return {
        "allowed_types": ["eid", "passport", "commercial", "ejari", "moa"],
        "stage_description": "General Account",
        "required_docs": ["Required documents"]
    }


def get_full_journey_document_types(
    account_type: str,
    ownership_type: str,
    email: str = "",
) -> Dict[str, List[str]]:
    """
    Return the **full** list of documents required for the entire onboarding
    journey, regardless of the user's current document_stage.

    This is used by the sidebar count so that corporate doc totals stay stable
    as the flow transitions through stages (e.g. member_eids stage no longer
    hides commercial / ejari / moa from the count).

    For Multiple Owner flows the presence of a Certificate of Incorporation
    (Type-2 journey) is determined by checking whether any CoI has been
    uploaded rather than relying on the stage field.
    """
    if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
        return {
            "allowed_types": ["commercial", "moa", "ejari", "identity"],
            "required_docs": [
                "Commercial License",
                "Memorandum of Association (MOA)",
                "Ejari (Tenancy Contract)",
                "Emirates ID (EID) or Passport",
            ],
            "stage_description": "Sole Proprietorship Account",
        }

    if account_type == ACCOUNT_CORPORATE and ownership_type in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP):
        # Detect Type-2: CoI was uploaded at any point
        _has_coi = False
        if email:
            try:
                _doc_status = check_documents_status(email)
                _has_coi = bool(
                    _doc_status.get("certificate_of_incorporation") or
                    _doc_status.get("coi")
                )
            except Exception:
                pass

        if _has_coi:
            # Type-2: corporate shareholders present → 4 corporate docs
            return {
                "allowed_types": ["commercial", "ejari", "moa", "certificate_of_incorporation", "eid", "passport"],
                "required_docs": [
                    "Commercial License",
                    "Ejari (Address Proof)",
                    "Memorandum of Association (MOA)",
                    "Certificate of Incorporation",
                    "Emirates ID (EID) or Passport for each member",
                ],
                "stage_description": "Joint Ownership Account (Type 2)",
            }
        else:
            # Type-1: no corporate shareholders → 3 corporate docs
            return {
                "allowed_types": ["commercial", "ejari", "moa", "eid", "passport"],
                "required_docs": [
                    "Commercial License",
                    "Ejari (Address Proof)",
                    "Memorandum of Association (MOA)",
                    "Emirates ID (EID) or Passport for each member",
                ],
                "stage_description": "Joint Ownership Account (Type 1)",
            }

    # Fallback
    return {
        "allowed_types": ["eid", "passport", "commercial", "ejari", "moa"],
        "stage_description": "General Account",
        "required_docs": ["Required documents"],
    }


# ============================================================================
# DOCUMENT STATUS CHECKING
# ============================================================================

def check_documents_status(email: str) -> dict:
    """Check which documents have been submitted and are valid"""
    root = user_docs_path(email)
    status = {
        "commercial": False,
        "eid": False,
        "passport": False,
        "identity": False,                     # virtual: True if eid OR passport is True
        "tenancy": False,
        "ejari": False,
        "moa": False,
        "memorandum": False,                  # alias kept in sync with moa
        "certificate_of_incorporation": False,
        "coi": False,                          # alias kept in sync with certificate_of_incorporation
    }

    if not root.exists():
        return status

    # Load member progress
    from app.services.chatupload_helpers import load_member_progress
    mp = load_member_progress(email)
    member_names = (mp or {}).get("members", []) if mp else []

    try:
        # Get main user documents
        for item in root.iterdir():
            if not item.is_dir() or item.name in member_names or item.name == "members":
                continue

            out = item / "output.json"
            if not out.exists():
                continue

            try:
                with open(out, "r", encoding="utf-8") as f:
                    analysis = json.load(f)

                doc_type = (analysis.get("document_type") or "").lower()
                is_valid = analysis.get("is_valid", False)

                # ✅ FIX A: Normalize document type to canonical form
                if doc_type in ["tenancy", "tenancy contract"]:
                    doc_type = "ejari"
                elif doc_type in ["memorandum", "memorandum of association", "moa"]:
                    doc_type = "moa"
                elif doc_type in ["trade license", "trade_license"]:
                    doc_type = "commercial"
                elif doc_type in ["emirates id", "emirates_id", "identity card"]:
                    doc_type = "eid"
                elif doc_type in ["passport", "travel_document", "travel document", "intl_id"]:
                    doc_type = "passport"
                elif doc_type in [
                    "certificate_of_incorporation", "coi",
                    "certificate of incorporation", "incorporation",
                ]:
                    doc_type = "certificate_of_incorporation"

                if is_valid:
                    if doc_type in status:
                        status[doc_type] = True
                    # ✅ FIX A: Always set both ejari/tenancy aliases together
                    if doc_type in ("ejari", "tenancy"):
                        status["ejari"] = True
                        status["tenancy"] = True
                    # Keep moa/memorandum aliases in sync
                    if doc_type == "moa":
                        status["memorandum"] = True
                    # Keep coi/certificate_of_incorporation aliases in sync
                    if doc_type == "certificate_of_incorporation":
                        status["coi"] = True
                    # Passport satisfies the EID requirement
                    if doc_type == "passport":
                        status["eid"] = True
                        status["passport"] = True

            except Exception as e:
                logger.warning(f"[check_documents_status] failed to read {out}: {e}")

    except Exception as e:
        logger.error(f"[check_documents_status] failed for {email}: {e}", exc_info=True)

    # ✅ FIX Issue 1: Also scan member subdirectories for EID/Passport documents.
    # For Single Owner flows the account holder's EID is uploaded as a MEMBER document
    # (stored under email/member_name/...), so the main-user scan above misses it.
    # If ANY member has a verified EID or Passport, the "identity" virtual requirement
    # is satisfied.  This does not affect Multiple Owner flows because those flows use
    # allowed_types = ["eid", "passport"] (not "identity") for the member_eids stage.
    _MEMBER_ID_TYPES = {
        "eid", "emirates id", "emirates_id", "identity card",
        "passport", "travel_document", "travel document", "intl_id",
    }
    try:
        if not status.get("identity"):
            mp_scan = load_member_progress(email)
            if mp_scan:
                for _mn in mp_scan.get("members", []):
                    _mdir = root / _mn
                    if not _mdir.exists():
                        continue
                    for _mi in _mdir.iterdir():
                        if not _mi.is_dir():
                            continue
                        _mo = _mi / "output.json"
                        if not _mo.exists():
                            continue
                        try:
                            with open(_mo, "r", encoding="utf-8") as _mf:
                                _mdata = json.load(_mf)
                            _mdt  = (_mdata.get("document_type") or "").lower()
                            _mval = _mdata.get("is_valid", False)
                            if _mval and _mdt in _MEMBER_ID_TYPES:
                                if _mdt == "passport":
                                    status["passport"] = True
                                status["eid"] = True
                                logger.debug(f"[check_documents_status] member identity satisfied by {_mn} ({_mdt})")
                                break  # one verified member ID is enough for identity check
                        except Exception:
                            pass
                    if status.get("eid"):
                        break  # identity already satisfied
    except Exception as _me:
        logger.warning(f"[check_documents_status] member identity scan failed (non-fatal): {_me}")

    # ✅ Identity abstraction: identity = eid OR passport (recalculated including member dirs)
    status["identity"] = bool(status.get("eid") or status.get("passport"))

    return status


def load_member_progress(email: str) -> Optional[dict]:
    """Load member progress from JSON file"""
    p = member_progress_path(email)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[load_member_progress] failed for {p}: {e}")
        return None


# ============================================================================
# REMAINING DOCUMENTS
# ============================================================================

# Which "session" a document belongs to. Drives which capture-required card
# is allowed to mention it — see get_remaining_required_documents() below.
# Multiple Owners' STAGE_IDENTIFICATION never included "identity" in
# allowed_types to begin with, so this mapping is a no-op there; it only
# changes behaviour for Single Owner, where "identity" used to be bundled
# into the same flat required-docs list as the corporate documents and so
# leaked into the Corporate capture card before the Identity stage even
# started.
DOC_CATEGORY = {
    "commercial":                   "corporate",
    "ejari":                        "corporate",
    "tenancy":                      "corporate",
    "moa":                          "corporate",
    "memorandum":                   "corporate",
    "certificate_of_incorporation": "corporate",
    "coi":                          "corporate",
    "identity":                     "identity",
    "eid":                          "identity",
    "eid_or_passport":              "identity",
    "passport":                     "identity",
}


def get_remaining_required_documents(
    email: str, user_data: dict, categories: Optional[List[str]] = None
) -> List[str]:
    """
    Get list of remaining documents that user still needs to upload.

    categories: which document "sessions" to include — defaults to
    ["corporate"] only. Identity documents (EID/Passport) are deliberately
    excluded by default: they're tracked and surfaced through a separate
    mechanism (members_info / next_required_document, driven by
    member_progress.json) once the account reaches its identity-collection
    stage, the same way Multiple Owners already works. Mixing "Emirates ID
    or Passport" into the same list as "Memorandum of Association" and
    "Ejari" made the Corporate capture-required card mention a document
    that isn't a corporate document and isn't due yet. Pass
    categories=["corporate", "identity"] explicitly if a caller genuinely
    wants the old, unfiltered combined list (e.g. a full-journey checklist).

    Returns:
        List of document names that are still required, in the requested
        categories.
    """
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", STAGE_IDENTIFICATION)

    if categories is None:
        categories = ["corporate"]

    # Get allowed document types for this configuration
    allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)

    # Check which documents have been submitted and are valid
    doc_status = check_documents_status(email)

    remaining = []

    # Map document types to readable names
    doc_type_map = {
        "identity": "Identity Document (Emirates ID or Passport)",
        "eid": "Emirates ID (EID)",
        "eid_or_passport": "Emirates ID or Passport",
        "passport": "Passport",
        "commercial": "Commercial License",
        "ejari": "Ejari (Tenancy Contract)",
        "tenancy": "Ejari (Tenancy Contract)",
        "moa": "Memorandum of Association (MOA)",
        "memorandum": "Memorandum of Association (MOA)",
        "certificate_of_incorporation": "Certificate of Incorporation (CoI)",
        "coi": "Certificate of Incorporation (CoI)",
    }

    # Check each allowed type
    for doc_type_key in allowed_info["allowed_types"]:
        if DOC_CATEGORY.get(doc_type_key, "corporate") not in categories:
            continue
        # ✅ "identity" is a virtual type satisfied by EID OR Passport — check both aliases
        if doc_type_key == "identity":
            if not (doc_status.get("eid") or doc_status.get("passport") or doc_status.get("identity")):
                doc_name = doc_type_map.get("identity", "Emirates ID (EID) or Passport")
                if doc_name not in remaining:
                    remaining.append(doc_name)
        elif not doc_status.get(doc_type_key, False):
            doc_name = doc_type_map.get(doc_type_key, doc_type_key.upper())
            if doc_name not in remaining:
                remaining.append(doc_name)

    return remaining


# ============================================================================
# CONVERSATION LOGGING (Moved from chatupload.py)
# ============================================================================

def insert_conversation_log(
    user_email: str, 
    role: str, 
    message: str, 
    channel: str = "chat",
    metadata: Optional[dict] = None
) -> bool:
    """
    Insert conversation log with channel parameter and optional metadata.
    """
    try:
        from datetime import datetime, timezone
        
        # Validate channel value
        valid_channels = ['web', 'chat', 'email', 'api', 'document_upload', 'ai_assistant']
        if channel not in valid_channels:
            logger.warning(f"Invalid channel '{channel}', defaulting to 'chat'")
            channel = 'chat'
        
        # Prepare conversation data
        conversation_data = {
            "user_email": user_email,
            "role": role,
            "message": message,
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Add metadata if provided
        if metadata:
            conversation_data["metadata"] = metadata if isinstance(metadata, dict) else json.loads(metadata)

        # i18n (docs/multilingual-flow-approach.html, rule 2): a LocalizedStr
        # message carries all three renderings — persist them so a language
        # toggle / reload serves the stored rendering directly instead of an
        # LLM translation. Also stamp the language every agent row was
        # written in, so history translation knows its source language.
        try:
            from app.i18n import i18n_metadata
            from app.utils.language import request_language
            _i18n = i18n_metadata(message)
            if _i18n or role in ("agent", "assistant"):
                md = dict(conversation_data.get("metadata") or {})
                if _i18n:
                    md.update(_i18n)
                md.setdefault("language", request_language())
                conversation_data["metadata"] = md
            conversation_data["message"] = str(message)
        except Exception as _i18n_err:
            logger.warning(f"insert_conversation_log: i18n metadata skipped: {_i18n_err}")
        
        # Insert into database
        result = ConversationRepository.insert(conversation_data)
        
        if result.data:
            msg_type = metadata.get("message_type", "text") if metadata else "text"
            logger.info(f"[SUCCESS] Conversation logged (channel: {channel}, type: {msg_type})")
            return True
        else:
            logger.warning(f"Conversation log returned no data")
            return False
            
    except Exception as e:
        logger.error(f"insert_conversation_log: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    
# ============================================================================
# DOCUMENT STATE TRACKING (NEW)
# ============================================================================

def get_validated_documents(email: str) -> Dict[str, Dict[str, bool]]:
    """
    Get comprehensive state of all user documents
    
    Returns:
        Dict mapping doc_type to state flags:
        {
            "eid": {"uploaded": True, "validated": True, "verified": True},
            "commercial": {"uploaded": True, "validated": True, "verified": False},
            "ejari": {"uploaded": False, "validated": False, "verified": False}
        }
    """
    state = {
        "eid": {"uploaded": False, "validated": False, "verified": False},
        "passport": {"uploaded": False, "validated": False, "verified": False},
        "commercial": {"uploaded": False, "validated": False, "verified": False},
        "ejari": {"uploaded": False, "validated": False, "verified": False},
        "moa": {"uploaded": False, "validated": False, "verified": False}
    }
    
    root = user_docs_path(email)
    if not root or not root.exists():
        return state
    
    try:
        # Check main user documents
        for item in root.iterdir():
            if not item.is_dir() or item.name == "members":
                continue
            
            output_file = item / "output.json"
            if not output_file.exists():
                continue
            
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                doc_type = data.get("document_type", "").lower().strip()
                
                # Normalize document type
                if doc_type in ["memorandum", "memorandum of association"]:
                    doc_type = "moa"
                elif doc_type in ["tenancy", "tenancy contract"]:
                    doc_type = "ejari"
                elif doc_type in ["trade license", "trade_license"]:
                    doc_type = "commercial"
                elif doc_type in ["emirates id", "emirates_id", "identity card"]:
                    doc_type = "eid"
                elif doc_type in ["passport", "travel_document", "travel document", "intl_id"]:
                    doc_type = "passport"

                if doc_type in state:
                    state[doc_type]["uploaded"] = True
                    state[doc_type]["validated"] = data.get("is_valid", False)
                    state[doc_type]["verified"] = data.get("human_verified", False)
                    
            except Exception as e:
                logger.error(f"Reading {output_file}: {e}")
        
        # Check member documents (for partnerships) — new structure: members/ subfolder
        members_root = root / "members"
        if members_root.exists():
            for doc_folder in members_root.iterdir():
                if not doc_folder.is_dir():
                    continue

                output_file = doc_folder / "output.json"
                if not output_file.exists():
                    continue

                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    doc_type = data.get("document_type", "").lower().strip()
                    if doc_type in ["emirates id", "emirates_id"]:
                        # Member EIDs tracked separately (not blocking main flow)
                        pass

                except Exception as e:
                    logger.error(f"Reading member document: {e}")
    
    except Exception as e:
        logger.error(f"get_validated_documents: {e}")

    # Passport satisfies EID/identity requirement
    if state["passport"]["validated"]:
        state["eid"]["validated"] = True

    return state


def should_request_document(email: str, doc_type: str, user_data: dict) -> tuple:
    """
    Check if document should be requested/accepted for upload
    
    Args:
        email: User email
        doc_type: Document type being uploaded
        user_data: User information
        
    Returns:
        Tuple (should_accept: bool, reason: Optional[str])
        
        should_accept = False if:
        - Already validated and verified
        - Wrong document type for account
    """
    # Get current document state
    doc_state = get_validated_documents(email)
    
    # Normalize doc_type
    doc_type_normalized = doc_type.lower().strip()
    if doc_type_normalized in ["memorandum", "memorandum of association"]:
        doc_type_normalized = "moa"
    elif doc_type_normalized in ["tenancy", "tenancy contract"]:
        doc_type_normalized = "ejari"
    elif doc_type_normalized in ["trade license", "trade_license"]:
        doc_type_normalized = "commercial"
    elif doc_type_normalized in ["emirates id", "emirates_id", "identity card"]:
        doc_type_normalized = "eid"
    
    # Check if already validated AND verified
    if doc_type_normalized in doc_state:
        state = doc_state[doc_type_normalized]
        if state.get("validated") and state.get("verified"):
            return False, f"already_validated_and_verified:{doc_type_normalized}"
    
    # Check if correct document type for account
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", STAGE_IDENTIFICATION)
    
    allowed_info = get_allowed_document_types(account_type, ownership_type, document_stage)
    allowed_types = allowed_info["allowed_types"]
    
    # Handle "identity" virtual key: EID or Passport both satisfy the identity requirement
    if "identity" in allowed_types and doc_type_normalized in ("eid", "passport"):
        # Identity document is allowed — accept it
        return True, None

    if doc_type_normalized not in allowed_types:
        return False, f"wrong_document_type:{doc_type_normalized}"

    # Accept the document
    return True, None


def get_next_required_document(email: str, user_data: dict) -> Optional[Dict[str, any]]:
    """
    Intelligently determine next document needed
    NEVER returns a document that's already validated
    
    Returns:
        Dict with document info or None if all complete:
        {
            "type": "ejari",
            "display_name": "Ejari (Tenancy Contract)",
            "requires_member_name": False,
            "member_name": None
        }
    """
    account_type = user_data.get("account_type")
    ownership_type = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", STAGE_IDENTIFICATION)
    
    # Get current document state
    doc_state = get_validated_documents(email)
    
    # Determine required documents based on account type
    if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
        required_docs = ["commercial", "moa", "ejari", "identity"]
    elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
        if document_stage == STAGE_IDENTIFICATION:
            required_docs = ["commercial", "moa"]
        elif document_stage == STAGE_CORPORATE_SHAREHOLDER_DOCS:
            # CoI collection — caller must check member_progress for pending corps
            return {
                "type": "certificate_of_incorporation",
                "display_name": "Certificate of Incorporation (CoI)",
                "requires_member_name": True,
                "member_name": None  # Determined by member_progress pending_coi list
            }
        else:
            # member_eids stage - handled separately
            return {
                "type": "identity",
                "display_name": "Identity Document (Emirates ID or Passport)",
                "requires_member_name": True,
                "member_name": None  # Will be determined by member progress
            }
    else:
        required_docs = []

    # Find first document that's not validated
    for doc_type in required_docs:
        # Special handling for identity virtual type
        if doc_type == "identity":
            # Identity is satisfied by EID or Passport
            eid_state = doc_state.get("eid", {})
            passport_state = doc_state.get("passport", {})
            if eid_state.get("validated") or passport_state.get("validated"):
                continue  # Identity requirement met, skip
        else:
            state = doc_state.get(doc_type, {})
            if state.get("validated"):
                continue  # Already validated, skip

        # Found next required document
        display_names = {
            "identity": "Identity Document (Emirates ID or Passport)",
            "eid": "Emirates ID (EID)",
            "commercial": "Commercial License",
            "ejari": "Ejari (Tenancy Contract)",
            "moa": "Memorandum of Association (MOA)",
            "certificate_of_incorporation": "Certificate of Incorporation (CoI)",
        }

        return {
            "type": doc_type,
            "display_name": display_names.get(doc_type, doc_type.upper()),
            "requires_member_name": False,
            "member_name": None
            }

    # All required documents validated
    return None