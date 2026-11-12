# backend/app/services/handle_reply.py
from app import config
from app.utils.pii_masker import mask_pii
from app.services.run_model import call_local_llm
from app.services.supabase_client import supabase
# Canonical documents-directory resolver. Everything below used to build this
# path by hand as os.path.join("backend", "documents", "id", <email>) — which is
# relative, omits the "sme" segment, and keys on EMAIL rather than ref_no. The
# real layout is {DOCUMENTS_PATH}/{ref_no}. Every one of those lookups therefore
# hit a directory that does not exist and silently returned "nothing found".
from app.services.chatupload_helpers import user_docs_path
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_sender import send_email
from app.services.ocr_service import process_document, format_document_name, run_ocr
from app.services.specialized_ocr import ejari_extractor, trade_extractor, moa_extractor
from app.services.specialized_ocr.corporate_shareholder_detector import (
    detect_corporate_shareholders,
    run_type2_analysis,
    expand_ownership,
    compute_ubo,
)
from datetime import datetime
import os
import time
import json
from fpdf import FPDF
#from fpdf2 import FPDF
import json
import re
from app.services.eid_validation import validate_eid_before_confirmation


def _find_commercial_output_hr(from_email: str):
    """Scan all subfolders for the commercial license output.json.
    Returns (path_str, data) instead of assuming a hardcoded folder name."""
    import json as _json
    base = str(user_docs_path(from_email))
    if not os.path.exists(base):
        return None, {}
    for folder_name in os.listdir(base):
        folder_path = os.path.join(base, folder_name)
        if not os.path.isdir(folder_path):
            continue
        out_path = os.path.join(folder_path, "output.json")
        if os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as _f:
                    data = _json.load(_f)
                doc_type = data.get("document_type", "").lower()
                if doc_type in ("commercial", "trade_license", "commercial_license"):
                    return out_path, data
            except Exception:
                pass
    return None, {}

from app.services.tampering_service import verify_document_authenticity, update_user_tampering_status

from app.services.email_sender import (
    send_email,  # Base function
    send_welcome_email,
    send_document_verification_email,
    send_validation_pending_email,
    send_validation_passed_email,
    send_validation_failed_email,
    send_cross_validation_error_email,
    send_member_identification_email,
    send_member_eid_request_email,
    send_member_documents_confirmation_email,
    send_all_members_complete_email,
    send_document_status_email,
    send_missing_documents_email,
    send_completion_email,
    send_onboarding_completion_email
)

# Model selection is handled inside process_document based on doc_type. Two
# unused vision-model constants used to sit here as "fallback references"; they
# were never read by anything and named a model ocr_service had already dropped
# for returning 404. Model names now live in .env.docker via llm_client.

import os
import socket
from urllib.parse import quote
import logging
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

def get_api_base_url():
    """
    Get the correct API base URL for external access.
    Priority: 
    1. Environment variable API_BASE_URL
    2. Auto-detect public IP
    3. Fallback to localhost
    """
    # Check for environment variable first
    env_url = os.getenv("API_BASE_URL")
    if env_url:
        logger.info(f"Using API_BASE_URL from environment: {env_url}")
        return env_url
    
    # Try to get public IP
    try:
        import requests
        public_ip = requests.get('https://api.ipify.org', timeout=3).text.strip()
        api_url = f"http://{public_ip}:9000"
        logger.info(f"Auto-detected public IP API URL: {api_url}")
        return api_url
    except Exception as e:
        logger.warning(f"Could not detect public IP: {e}")
        # Fallback to localhost
        fallback = "http://localhost:9000"
        logger.info(f"Using fallback API URL: {fallback}")
        return fallback

# DEFINE API_BASE GLOBALLY AT MODULE LEVEL
API_BASE = get_api_base_url()
logger.info(f"API_BASE initialized: {API_BASE}")

    # ===========================
    # DOCUMENT REQUIREMENTS LOGIC
    # ===========================

def get_required_documents(account_type: str, ownership_type: str = None) -> dict:
    """
    Returns document requirements based on account flow
    """
    if account_type == ACCOUNT_CORPORATE:
        if ownership_type == OWNERSHIP_SINGLE:
            return {
                "stage": "single",
                "documents": ["commercial", "eid", "ejari"],
                "message": "Please submit your Commercial/Trade License, Emirates ID (EID), and Ejari"
            }
        
        elif ownership_type in [OWNERSHIP_PARTNERSHIP, "@Multiple Owners"]:
            return {
                "stage": STAGE_IDENTIFICATION,
                "documents": ["commercial", "moa"],
                "message": "First, please submit your Commercial License and MOA to identify all owners",
                "next_stage": STAGE_MEMBER_EIDS
            }
    
    return None


def check_document_stage_completion(user_email: str, required_docs: list) -> dict:
    """
    Check if all required documents for current stage are submitted and valid
    FIXED VERSION - Actually reads output.json files
    """
    user_docs_dir = str(user_docs_path(user_email))
    
    submitted = {
        "commercial": False,
        "eid": False,
        "ejari": False,
        "moa": False
    }
    
    if not os.path.exists(user_docs_dir):
        logger.debug(f"Directory does not exist: {user_docs_dir}")
        return {
            "complete": False, 
            "submitted": submitted, 
            "missing": required_docs
        }
    
    logger.debug(f"Scanning directory: {user_docs_dir}")
    logger.debug(f"Looking for: {required_docs}")
    
    # List all items in directory
    all_items = os.listdir(user_docs_dir)
    logger.debug(f"Found {len(all_items)} items in directory: {all_items}")
    
    # Check each item
    for item in all_items:
        item_path = os.path.join(user_docs_dir, item)
        
        # Skip files (only check directories)
        if not os.path.isdir(item_path):
            logger.debug(f"Skipping file: {item}")
            continue
        
        # Skip member_progress.json directory (shouldn't exist but just in case)
        if item == "member_progress.json":
            logger.debug(f"Skipping member_progress.json")
            continue
        
        # Check for output.json
        output_path = os.path.join(item_path, "output.json")
        logger.debug(f"Checking: {item}/")
        
        if not os.path.exists(output_path):
            logger.debug(f"No output.json found")
            continue
        
        # Read and parse output.json
        try:
            logger.debug(f"   Reading output.json...")
            with open(output_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            
            doc_type = analysis.get("document_type", "unknown")
            is_valid = analysis.get("is_valid", False)
            filename = analysis.get("filename", item)
            
            logger.debug(f"   Filename: {filename}")
            logger.debug(f"   Document type: {doc_type}")
            logger.debug(f"   Is valid: {is_valid}")
            
            # Update submission status if valid
            if doc_type in submitted:
                if is_valid:
                    submitted[doc_type] = True
                    logger.debug(f"   MARKED {doc_type.upper()} AS VALID")
                else:
                    logger.debug(f"    {doc_type.upper()} is INVALID")
            else:
                logger.debug(f"     Unknown document type: {doc_type}")
            
        except json.JSONDecodeError as e:
            logger.error(f"   Failed to parse JSON: {e}")
        except Exception as e:
            logger.error(f"   Error reading file: {e}")
    
    # Calculate missing documents
    missing = [doc for doc in required_docs if not submitted.get(doc, False)]
    complete = len(missing) == 0
    
    # Print final summary
    logger.info(f"\n{'='*70}")
    logger.debug(f"VALIDATION SUMMARY FOR {user_email}")
    logger.info(f"{'='*70}")
    logger.debug(f"Required documents: {required_docs}")
    logger.debug(f"")
    logger.debug(f"Status by document type:")
    for doc_type in ["eid", "ejari", "commercial", "moa"]:
        if doc_type in required_docs:
            status = "VALID" if submitted[doc_type] else "MISSING"
            logger.debug(f"  {doc_type:12} : {status}")
    logger.debug(f"")
    logger.debug(f"Missing: {missing if missing else 'None'}")
    logger.debug(f"Complete: {'YES ' if complete else 'NO '}")
    logger.info(f"{'='*70}\n")
    
    return {
        "complete": complete,
        "submitted": submitted,
        "missing": missing
    }

# ===========================
# HELPERS
# ===========================

def _names_are_same(name_a: str, name_b: str) -> bool:
    """
    Fuzzy name match — treats names as equal if one is a substring of the other.
    Handles cases like 'ALICE SMITH' vs 'ALICE SMITH AL DUBAI'.
    Both inputs must be pre-lowercased and stripped.
    """
    if not name_a or not name_b:
        return False
    return name_a in name_b or name_b in name_a


def _parse_share(share_str) -> float:
    """
    Safely parse share percentage string to float.
    '60.0000000%' → 60.0
    '50%'         → 50.0
    None / ''     → 0.0
    """
    if not share_str:
        return 0.0
    try:
        return float(str(share_str).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


def extract_members_from_documents(user_email: str, commercial_only: bool = False) -> dict:
    """
    Extract member names from Commercial License and (optionally) MOA.

    commercial_only=True  → skip MOA entirely; use Commercial License only.
                            Used by Type-1 Multiple Owner path so that MOA fields
                            (owner_name, manager_name) are never added to the pool.
    commercial_only=False → default; reads both Commercial + MOA (Type-2 / chat path).

    TYPE-2 AWARE: If member_progress.json already contains expanded_members
    (from a completed Type-2 CoI flow), those are used directly instead of
    re-reading the raw Commercial License partners.

    NEW LOGIC (updated):
    ─────────────────────────────────────────────────────────
    1. Collect names from BOTH managers[] and partners[] in Commercial License
    2. Collect names from MOA (owner_name, manager_name)
    3. Deduplicate across all sources by name similarity
    4. Aggregate share percentages per unique person
    5. Classify as UBO (>=25% share) or Member
    6. Apply registered-user inclusion/exclusion logic (unchanged)

    Returns:
    {
        "ubos":         [{"name": str, "share_percentage": str, "source": str}, ...],
        "members":      [{"name": str, "share_percentage": str, "source": str}, ...],
        "all_names":    [str, ...],   flat list used by EID collection loop
        "includes_user": bool,
        "user_validation": dict
    }
    """
    user_docs_dir = str(user_docs_path(user_email))

    # ── TYPE-2 SHORTCUT: use pre-expanded members if available ────────────────
    progress = get_member_progress(user_email)
    if progress and progress.get("expanded_members"):
        expanded = progress["expanded_members"]
        ubo_names = progress.get("ubo_names", [])
        logger.info(f"Using Type-2 expanded_members from member_progress.json ({len(expanded)} owners)")
        ubos    = [{"name": o["name"], "share_percentage": str(o.get("effective_percentage", "")), "source": o.get("source", "corporate_expansion")} for o in expanded if o["name"] in ubo_names]
        members = [{"name": o["name"], "share_percentage": str(o.get("effective_percentage", "")), "source": o.get("source", "direct")} for o in expanded if o["name"] not in ubo_names]
        all_names = [o["name"] for o in expanded]
        return {
            "ubos": ubos,
            "members": members,
            "all_names": all_names,
            "includes_user": False,
            "user_validation": {"found": False, "registered_name": "", "found_in": []},
        }

    logger.info(f"\n{'='*80}")
    logger.info(f"EXTRACTING MEMBERS FROM DOCUMENTS (UBO-AWARE)")
    logger.info(f"{'='*80}\n")

    # ── STEP 1: Check if registered user is in company documents ──────────────
    user_validation   = is_registered_user_in_company_documents(user_email)
    user_in_documents = user_validation["found"]
    registered_name   = user_validation["registered_name"]

    logger.info(f"Registered User : '{registered_name}'")
    logger.info(f"Found in docs   : {user_in_documents}")
    logger.info(f"Found in        : {user_validation['found_in']}")

    if not os.path.exists(user_docs_dir):
        return {
            "ubos":           [],
            "members":        [],
            "all_names":      [],
            "includes_user":  False,
            "user_validation": user_validation,
        }

    # ── STEP 2: Build unified person pool ─────────────────────────────────────
    # Each entry: { "name": str, "share": float, "source": str }
    # Source values: "manager", "partner", "moa", "both"
    person_pool: list[dict] = []

    def _add_to_pool(name: str, share: float, source: str):
        """
        Add a person to the pool.
        If they already exist (fuzzy match), merge — sum shares and combine source.
        """
        name = name.strip()
        if not name:
            return
        name_lc = name.lower()

        for existing in person_pool:
            if _names_are_same(existing["name_lc"], name_lc):
                # Merge — sum share, combine source label
                existing["share"] += share
                existing["share"] = round(existing["share"], 7)

                sources = set(existing["source"].split("+"))
                sources.add(source)
                existing["source"] = "+".join(sorted(sources))

                # Keep the longer/more complete name
                if len(name) > len(existing["name"]):
                    existing["name"]    = name
                    existing["name_lc"] = name_lc

                logger.debug(f"Merged duplicate: '{name}' → "
                      f"share={existing['share']}%, source={existing['source']}")
                return

        # New person
        person_pool.append({
            "name":    name,
            "name_lc": name_lc,
            "share":   share,
            "source":  source,
        })
        logger.debug(f"Added to pool: '{name}' | share={share}% | source={source}")

    # ── STEP 3: Build the canonical commercial path (commercial_only mode) ──────
    # When commercial_only=True there may be multiple commercial output.json files
    # on disk from previous sessions.  We must only read the MOST RECENT one to
    # avoid pulling names from stale/wrong Commercial License files.
    _canonical_commercial_path: str | None = None
    if commercial_only:
        _best_mtime  = -1.0
        for _ci in os.listdir(user_docs_dir):
            _ci_path = os.path.join(user_docs_dir, _ci)
            if not os.path.isdir(_ci_path):
                continue
            _ci_out = os.path.join(_ci_path, "output.json")
            if not os.path.exists(_ci_out):
                continue
            try:
                with open(_ci_out, "r", encoding="utf-8") as _f:
                    _ci_data = json.load(_f)
                if _ci_data.get("document_type") == "commercial" and _ci_data.get("is_valid"):
                    _mt = os.path.getmtime(_ci_out)
                    if _mt > _best_mtime:
                        _best_mtime = _mt
                        _canonical_commercial_path = _ci_out
            except Exception:
                pass
        if _canonical_commercial_path:
            logger.debug(f"commercial_only: using most recent commercial → {_canonical_commercial_path}")
        else:
            logger.debug(f"commercial_only: no valid commercial found for {user_email}")

    # ── STEP 4: Read documents and populate pool ───────────────────────────────
    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)

        if not os.path.isdir(item_path):
            continue

        output_path = os.path.join(item_path, "output.json")
        if not os.path.exists(output_path):
            continue

        try:
            with open(output_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)

            doc_type = analysis.get("document_type")

            # ── Commercial License ─────────────────────────────────────────────
            if doc_type == "commercial":
                # commercial_only mode: skip all except the single canonical file
                if commercial_only and output_path != _canonical_commercial_path:
                    logger.debug(f"commercial_only: skipping stale commercial → {output_path}")
                    continue
                extracted = analysis.get("extracted_fields", {})

                # --- Managers ---
                managers = extracted.get("managers", [])
                logger.debug(f"Commercial License → {len(managers)} manager(s)")
                for mgr in managers:
                    name  = mgr.get("name_english", "").strip()
                    share = _parse_share(mgr.get("share_percentage"))
                    if name:
                        _add_to_pool(name, share, "manager")

                # --- Partners (skip service agents) ---
                partners = extracted.get("partners", [])
                logger.debug(f"Commercial License → {len(partners)} partner(s)")
                for prt in partners:
                    if prt.get("is_agent", False):
                        logger.debug(f"Skipping service agent: {prt.get('name_english','?')}")
                        continue
                    name  = prt.get("name_english", "").strip()
                    share = _parse_share(prt.get("share_percentage"))
                    if name:
                        _add_to_pool(name, share, "partner")

                # --- Single Owner case: owner dict ---
                owner = extracted.get("owner", {})
                if owner:
                    name  = owner.get("name_english", "").strip()
                    share = _parse_share(owner.get("share_percentage"))
                    if name:
                        _add_to_pool(name, share, "partner")

            # ── MOA ───────────────────────────────────────────────────────────
            elif doc_type == "moa":
                if commercial_only:
                    # Type-1 path: skip MOA fields entirely — Commercial is the
                    # sole source of member names for Type-1 Multiple Owners.
                    logger.debug(f"Skipping MOA for member extraction (commercial_only=True)")
                    continue

                extracted  = analysis.get("extracted_fields", {})
                eng        = extracted.get("english", {})

                owner_name   = eng.get("owner_name",   "").strip()
                manager_name = eng.get("manager_name", "").strip()

                if owner_name:
                    _add_to_pool(owner_name, 0.0, "moa")
                if manager_name:
                    _add_to_pool(manager_name, 0.0, "moa")

        except Exception as e:
            logger.error(f"Failed to read {output_path}: {e}")

    logger.info(f"\n[INFO] Total unique persons in pool: {len(person_pool)}")

    # ── STEP 4: UBO Classification ─────────────────────────────────────────────
    #
    # Primary rule  : anyone with aggregated share ≥ 25% is a UBO
    #                 (aligns with UAE AML/KYC beneficial ownership threshold)
    # Fallback rule : if NO one reaches 25% (e.g. all shares unknown/zero),
    #                 promote the person(s) with the highest share to UBO
    #
    UBO_THRESHOLD = 25.0

    ubos:    list[dict] = []
    members: list[dict] = []

    total_share = sum(p["share"] for p in person_pool)
    has_share_data = total_share > 0.0

    if has_share_data:
        max_share = max(p["share"] for p in person_pool)

        for p in person_pool:
            entry = {
                "name":             p["name"],
                "share_percentage": f"{p['share']:.7f}%" if p["share"] > 0 else "",
                "source":           p["source"],
            }
            if p["share"] >= UBO_THRESHOLD:
                ubos.append(entry)
                logger.info(f"UBO    : '{p['name']}' — {p['share']:.2f}%")
            else:
                members.append(entry)
                logger.info(f"Member : '{p['name']}' — {p['share']:.2f}%")

        # Fallback: no one crossed 25% — promote whoever has the highest share
        if not ubos and person_pool:
            logger.warning(f"No one crossed {UBO_THRESHOLD}% threshold. "
                  f"Promoting highest share holder(s) to UBO.")
            for p in person_pool:
                entry = {
                    "name":             p["name"],
                    "share_percentage": f"{p['share']:.7f}%" if p["share"] > 0 else "",
                    "source":           p["source"],
                }
                if p["share"] == max_share:
                    ubos.append(entry)
                    logger.info(f"UBO (fallback): '{p['name']}' — {p['share']:.2f}%")
                else:
                    members.append(entry)

    else:
        # No share data at all — everyone is a plain member, no UBOs assigned
        logger.warning(f"[WARN] No share percentage data found — cannot classify UBOs. "
              f"All persons treated as Members.")
        for p in person_pool:
            members.append({
                "name":             p["name"],
                "share_percentage": "",
                "source":           p["source"],
            })

    logger.info(f"\n[INFO] UBOs   : {len(ubos)}")
    logger.info(f"Members: {len(members)}")

    # ── STEP 5: Registered user inclusion/exclusion (logic unchanged) ──────────
    all_entries: list[dict] = ubos + members   # working combined list

    if registered_name:
        reg_lc = registered_name.lower()

        if user_in_documents:
            # Ensure registered user is present somewhere in the combined list
            already_present = any(
                _names_are_same(reg_lc, e["name"].lower())
                for e in all_entries
            )
            if not already_present:
                # Add with no share data — they were confirmed present in docs
                # but weren't extracted (edge case: name format mismatch in extractor)
                members.insert(0, {
                    "name":             registered_name,
                    "share_percentage": "",
                    "source":           "registered_user",
                })
                logger.info(f"Added registered user '{registered_name}' to members "
                      f"(confirmed in docs but not extracted)")
            else:
                logger.info(f"Registered user '{registered_name}' already in list")

        else:
            # Remove registered user from both lists if present
            before = len(ubos) + len(members)
            ubos    = [e for e in ubos    if not _names_are_same(reg_lc, e["name"].lower())]
            members = [e for e in members if not _names_are_same(reg_lc, e["name"].lower())]
            after   = len(ubos) + len(members)
            if after < before:
                logger.info(f"Removed registered user '{registered_name}' "
                      f"(not found in company documents)")

    # ── STEP 6: Build flat all_names list for EID collection loop ──────────────
    # UBOs first, then members — preserves priority order
    all_names = [e["name"] for e in ubos] + [e["name"] for e in members]

    # ── STEP 7: Persist user_in_company_docs to DB (unchanged) ────────────────
    try:
        UserRepository.update_by_email(user_email, {
            "user_in_company_docs": user_in_documents,
            "user_doc_validation":  json.dumps(user_validation),
        })
        logger.info(f"Saved validation result to database")
    except Exception as e:
        logger.warning(f"Could not save validation to database: {e}")

    logger.info(f"\n[INFO] Final all_names list ({len(all_names)}): {all_names}")
    logger.info(f"{'='*80}\n")

    return {
        "ubos":            ubos,
        "members":         members,
        "all_names":       all_names,
        "includes_user":   user_in_documents,
        "user_validation": user_validation,
    }        


# ===========================
# MEMBER PROGRESS TRACKING
# ===========================

def get_member_progress(user_email: str):
    """Load member processing progress from JSON file."""
    progress_file = str(user_docs_path(user_email) / "member_progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load member progress: {e}")
            return None
    return None


def save_member_progress(
    user_email: str,
    members: list,
    current_index: int,
    ubo_names: list = None,
    expanded_members: list = None,
    pending_coi: list = None,
):
    """
    Save member processing progress to JSON file.

    Extended schema (Type-2 support):
        members          - flat list of display names used for EID loop
        current_index    - index into `members` for current EID request
        ubo_names        - names flagged as UBO (effective ownership > 25%)
        expanded_members - full expanded owner list (from corporate_shareholder_detector)
        pending_coi      - corporate entity names still awaiting their CoI upload
        updated_at       - ISO timestamp
    """
    # Resolve base path via document_helpers so DOCUMENTS_PATH env var is honoured
    # (avoids hardcoded "backend/documents/id" which is wrong inside Docker)
    try:
        from app.services.document_helpers import get_documents_base_path, get_document_ref_no
        _mp_root = get_document_ref_no(user_email)
        progress_dir = str(get_documents_base_path() / _mp_root)
    except Exception:
        # Fallback must resolve to the SAME place as the primary branch above.
        # It previously fell back to the email-keyed relative path, so if the
        # import ever failed, progress was written somewhere get_member_progress
        # would never look — the reader/writer split this fix exists to remove.
        _mp_root = user_email
        progress_dir = str(user_docs_path(user_email))

    os.makedirs(progress_dir, exist_ok=True)
    progress_file = os.path.join(progress_dir, "member_progress.json")
    progress_data = {
        "members": members,
        "current_index": current_index,
        "ubo_names": ubo_names or [],
        "expanded_members": expanded_members or [],
        "pending_coi": pending_coi or [],
        "updated_at": datetime.utcnow().isoformat(),
    }

    try:
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved member progress: Member {current_index + 1}/{len(members)}")
    except Exception as e:
        logger.error(f"Failed to save member progress: {e}")


# ===========================
# DOCUMENT PROCESSING
# ===========================

def generate_reasoning_for_wrong_document(raw_text: str, doc_type: str) -> str:
    """
    Generate reasoning for why the document is wrong using call_local_llm.

    PII MASKING (prompt-remediation Phase 1, item #1): this is a downstream
    consumer of already-extracted text, not the extraction call itself --
    the extraction that produced raw_text has already run and captured
    whatever real values it needed. Explaining *why a document was
    rejected* never requires the reader (model or human) to see the actual
    EID number, phone, email, or MRZ line, so raw_text is masked before it
    is interpolated into the prompt. mask_pii() falls back to its free-text
    regex pass (_mask_text_patterns) for a bare string like this one, the
    same pass already used for log lines elsewhere in the codebase -- this
    is simply the first time it runs before a model call instead of after.
    """
    try:
        masked_text = mask_pii(raw_text)
        # ARCHITECTURE FIX (prompt-remediation Phase 2): task-specific system
        # prompt instead of the shared generic banking-assistant sentence in
        # run_model.py, and a lower temperature (0.3) suited to a factual
        # explanatory summary rather than open-ended chat.
        system_prompt = (
            f"You are a document-verification assistant for {config.BRAND_NAME}. "
            "Explain, clearly and factually, why a submitted document was "
            "rejected, in plain user-friendly language."
        )
        prompt = f"""
        The following raw text was extracted from a document of type '{doc_type}'.
        The document was marked as invalid. Please summarize the extracted text and provide a detailed reason
        why the document is invalid. Ensure the response is clear and user-friendly.

        Raw Text:
        {masked_text}
        """
        reasoning = call_local_llm(prompt, system_prompt=system_prompt, temperature=0.3)
        return reasoning
    except Exception as e:
        logger.error(f"Failed to generate reasoning for wrong document: {e}")
        return "Unable to generate reasoning due to an error."

def send_reasoning_email(to_email: str, filename: str, doc_type: str, reasoning: str):
    """
    Send reasoning email - uses existing email_sender function
    
    Args:
        to_email: User's email
        filename: Uploaded filename
        doc_type: Document type
        reasoning: AI-generated reasoning for why document is invalid
    """
    from app.services.email_sender import send_document_verification_email
    
    logger.info(f"Sending reasoning email via email_sender...")
    
    # Use existing email function from email_sender
    send_document_verification_email(
        to_email=to_email,
        user_name="User",
        document_type=doc_type.upper(),
        status="invalid",
        filename=filename,
        reason=reasoning,
        extracted_data=None,
        is_complete=False,
        remaining_documents=None,
        member_name=None
    )
    
    logger.info(f"[SUCCESS] Reasoning email sent via email_sender")

def process_user_documents(from_email: str, attachments: list, is_member: bool = False, member_name: str = None):
    """Process user/member documents with specialized extractors"""
    
    # First get user info and account type
    user_response = UserRepository.get_identity_summary(from_email)
    user_info = user_response.data[0] if user_response.data else {}
    account_type = user_info.get("account_type", "")
    ownership_type = user_info.get("ownership_type", "")
    user_name = user_info.get("name", "").strip().lower()

    try:
        from pathlib import Path as _Path
        from app.services.document_helpers import get_documents_base_path, get_document_ref_no
        _base = get_documents_base_path()
        _ref = get_document_ref_no(from_email)
    except Exception:
        # Same rule as above: the fallback resolves to the real documents root,
        # not the email-keyed relative path that never existed.
        from pathlib import Path as _Path
        _base = user_docs_path(from_email).parent
        _ref = user_docs_path(from_email).name

    if is_member and member_name:
        # Member temp files land in members/ — OCR will rename to MEID-{ref_no}-{N}/
        save_dir = str(_base / _ref / "members")
        user_path = f"{_ref}/members"
    else:
        save_dir = str(_base / _ref)
        user_path = _ref

    os.makedirs(save_dir, exist_ok=True)

    processed_results = {
        "success": [],
        "failed": [],
        "invalid": [],
        "wrong_type": []
    }

    for attachment in attachments:
        filename = attachment["filename"]
        filedata = attachment["data"]

        filepath = os.path.join(save_dir, filename)
        with open(filepath, "wb") as f:
            f.write(filedata)

        document_id = os.path.splitext(filename)[0]

        # ============================================================================
        # ðŸ”’ TAMPERING DETECTION (NEW CODE)
        # ============================================================================
        logger.info(f"\n[TAMPERING] Verifying email attachment: {filename}")
        
        from app.services.tampering_service import verify_document_authenticity, update_user_tampering_status
        
        tampering_result = verify_document_authenticity(
            file_path=filepath,
            user_email=from_email,
            doc_type="unknown",  # Will be determined by tampering detector
            send_notifications=True
        )
        
        logger.info(f"[TAMPERING] Decision: {tampering_result.decision}")
        logger.info(f"[TAMPERING] Score: {tampering_result.overall_tampering_score}")
        
        # Update user status in database
        if tampering_result.test_report_id:
            from app.services.supabase_client import get_supabase_client
            supabase_client = get_supabase_client()
            
            update_user_tampering_status(
                user_email=from_email,
                test_report_id=tampering_result.test_report_id,
                decision=tampering_result.decision,
                tampering_score=tampering_result.overall_tampering_score,
                supabase_client=supabase_client
            )
        
        # ============================================================================
        # Handle REJECT Decision
        # ============================================================================
        if tampering_result.decision == "REJECT":
            logger.info(f"[TAMPERING] Email attachment rejected: {filename}")
            
            processed_results["failed"].append({
                "filename": filename,
                "reason": "Tampering detected",
                "test_report_id": tampering_result.test_report_id,
                "error": tampering_result.reason,
                "tampering_score": tampering_result.overall_tampering_score,
                "llm_analysis": tampering_result.llm_analysis
            })
            
            # Delete the rejected file
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"Rejected file deleted: {filepath}")
            except Exception as e:
                logger.warning(f"Failed to delete rejected file: {e}")
            
            # Email already sent by tampering_service
            continue  # Skip to next attachment
        
        # ============================================================================
        # Handle ESCALATE Decision
        # ============================================================================
        if tampering_result.decision == "ESCALATE":
            logger.info(f"[TAMPERING] Email attachment requires manual review: {filename}")
            
            processed_results["failed"].append({
                "filename": filename,
                "reason": "Manual review required",
                "test_report_id": tampering_result.test_report_id,
                "error": "Document flagged for manual verification",
                "tampering_score": tampering_result.overall_tampering_score,
                "llm_analysis": tampering_result.llm_analysis
            })
            
            # Email already sent by tampering_service
            continue  # Skip to next attachment
        
        logger.info(f"[TAMPERING] Email attachment accepted - proceeding to extraction\n")
        
        # ============================================================================
        # ACCEPT - Continue with extraction (EXISTING CODE)
        # ============================================================================
        # model_name omitted — process_document auto-selects based on doc_type:
        #   EID / Passport  → vision model (llama-3.2-11b-vision-instruct)
        #   All other docs  → text  model (llama-3.3-70b-instruct)
        try:
            result = process_document(
                user_email=user_path,
                document_id=document_id,
                file_path=filepath,
                is_member=is_member
            )

            doc_type = result.get("document_type", "unknown")
            is_valid = result.get("is_valid", False)
            raw_text = result.get("raw_text", "")

            if doc_type == "unknown":
                logger.warning("Unknown document type - extracting text for reasoning")
                
                # EXTRACT TEXT FIRST before marking as unknown
                #
                # BUGFIX: `ext` was never bound in this scope, so the very first
                # line of this block raised NameError. The surrounding
                # `except Exception` swallowed it and set raw_text to
                # "[TEXT EXTRACTION FAILED]", which is why reasoning about
                # unrecognised documents never actually worked. Derived here the
                # same way ocr_service.py does it.
                ext = os.path.splitext(filename)[1].lower()
                try:
                    if ext == '.pdf':
                        import fitz
                        doc = fitz.open(filepath)
                        raw_text = ""
                        for i in range(min(5, doc.page_count)):
                            page = doc.load_page(i)
                            raw_text += page.get_text()
                        doc.close()
                        logger.info(f"Extracted {len(raw_text)} characters from PDF")
                    elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
                        # Use OCR for images
                        # BUGFIX: `model` was undefined here. run_ocr's second
                        # parameter (model_name) already defaults to the
                        # configured OCR model, so it is simply omitted.
                        raw_text = run_ocr(filepath)
                        logger.info(f"OCR extracted {len(raw_text)} characters from image")
                    elif ext in ['.docx', '.doc']:
                        with open(filepath, 'rb') as f:
                            doc_bytes = f.read()
                        # BUGFIX: line 6 imports the ejari_extractor MODULE, not
                        # the class, so the bare name was undefined.
                        extractor = ejari_extractor.EjariExtractor()
                        raw_text = extractor.extract_text_from_docx(doc_bytes)
                        logger.info(f"Extracted {len(raw_text)} characters from DOCX")
                    else:
                        raw_text = "[UNSUPPORTED FILE FORMAT]"
                        logger.warning(f"Unsupported file format: {ext}")
                        
                except Exception as e:
                    logger.error(f"Failed to extract text from unknown document: {e}")
                    raw_text = "[TEXT EXTRACTION FAILED]"

                # Generate reasoning for the invalid document
                reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)

                # Send reasoning email
                send_reasoning_email(
                    to_email=from_email,
                    filename=filename,
                    doc_type=doc_type,
                    reasoning=reasoning
                )

                # Add to invalid results with extracted text
                processed_results["invalid"].append({
                    "filename": filename,
                    "type": "unknown",
                    "issues": ["Unknown document type"],
                    "raw_text": raw_text,
                    "reasoning": reasoning
                })
                continue

            if not is_valid:
                # Generate reasoning for the invalid document
                reasoning = generate_reasoning_for_wrong_document(raw_text, doc_type)

                # Send reasoning email
                send_reasoning_email(
                    to_email=from_email,
                    filename=filename,
                    doc_type=doc_type,
                    reasoning=reasoning
                )

                # Add to invalid results
                processed_results["invalid"].append({
                    "filename": filename,
                    "type": doc_type,
                    "issues": result.get("validation", {}).get("missing_fields", []),
                    "reasoning": reasoning
                })
                continue

            # --- Name validation ONLY for EID ---
            extracted = result.get("extracted_fields", {})
            logger.debug(f"[DEBUG-375] Extracted Data: {extracted}")
            extracted_name = ""
            name_match = True  # Default to True (no validation for non-EID docs)

            # ONLY extract and validate name for EID documents
            if doc_type == "eid":
                extracted_name = extracted.get("Name", "").strip().lower()
                logger.debug(f"Document: {filename} | Type: {doc_type}")
                logger.debug(f"Extracted Name: '{extracted_name}' | Expected Name: '{user_name}'")
                
                # Name validation is currently not performed for any account type.
                # Corporate Single Owner is intentionally skipped — the EID uploader
                # may not be the registered account holder. (Savings accounts, the
                # only type this validation used to run for, have been removed.)
                should_validate = False

                if should_validate:
                    name_match = user_name and extracted_name and (user_name in extracted_name or extracted_name in user_name)
                    logger.debug(f"Name validation performed: {name_match}")
                else:
                    name_match = True
                    logger.debug(f"Name validation SKIPPED for Multiple Owners")

            # ONLY apply validation rejection for EID documents
            if doc_type == "eid" and not name_match:
                logger.warning(f"Name mismatch for EID {filename}. Marking as invalid and requesting resubmission.")
                # Update output.json to reflect invalid status
                output_json_path = os.path.join(save_dir, os.path.splitext(filename)[0], "output.json")
                if os.path.exists(output_json_path):
                    try:
                        with open(output_json_path, "r", encoding="utf-8") as f:
                            output_data = json.load(f)
                        output_data["is_valid"] = False
                        output_data["validation"] = output_data.get("validation", {})
                        output_data["validation"]["name_mismatch"] = True
                        with open(output_json_path, "w", encoding="utf-8") as f:
                            json.dump(output_data, f, ensure_ascii=False, indent=2)
                        logger.debug(f"Updated output.json for {filename} to set is_valid=False due to name mismatch.")
                    except Exception as e:
                        logger.error(f"Could not update output.json for {filename}: {e}")

                processed_results["invalid"].append({
                    "filename": filename,
                    "type": doc_type,
                    "issues": ["Name mismatch with registration data"],
                    "extracted_name": extracted_name,
                    "expected_name": user_name
                })
                continue
            else:
                logger.debug(f"Validation passed for {filename} (type: {doc_type})")

            if is_member:
                # For members, ONLY accept EID
                if doc_type == "eid" and is_valid:
                    processed_results["success"].append({
                        "filename": filename,
                        "type": doc_type,
                        "result": result
                    })
                elif doc_type != "eid":
                    processed_results["wrong_type"].append({
                        "filename": filename,
                        "type": doc_type,
                        "expected": "eid"
                    })
                else:
                    processed_results["invalid"].append({
                        "filename": filename,
                        "type": doc_type,
                        "issues": result.get("validation", {}).get("missing_fields", []),
                        "extracted_name": extracted_name,
                        "expected_name": user_name
                    })
            else:
                # For main user, accept any valid document
                if is_valid:
                    processed_results["success"].append({
                        "filename": filename,
                        "type": doc_type,
                        "result": result
                    })
                elif doc_type == "unknown":
                    processed_results["wrong_type"].append({
                        "filename": filename,
                        "type": doc_type,
                        "expected": "eid, commercial, ejari, or moa"
                    })
                else:
                    processed_results["invalid"].append({
                        "filename": filename,
                        "type": doc_type,
                        "issues": result.get("validation", {}).get("missing_fields", []),
                        "extracted_name": extracted_name,
                        "expected_name": user_name
                    })
            
            # Wait 60 seconds between API calls to avoid rate limits
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            processed_results["failed"].append({
                "filename": filename,
                "error": str(e)
            })
    
    return processed_results


# ===========================
# PDF GENERATION - ALL COMMENTED OUT
# ===========================

def is_registered_user_in_company_documents(user_email: str) -> dict:
    """
    Check if registered user's name appears in Commercial License or MOA
    
    Returns: {
        "found": bool,
        "found_in": str,  # "commercial", "moa", "both", or "none"
        "matched_field": str,  # Which field matched
        "registered_name": str
    }
    """
    user_docs_dir = str(user_docs_path(user_email))
    
    # Get registered user's name
    try:
        user_response = UserRepository.get_name(user_email)
        registered_name = user_response.data[0].get("name", "").strip().lower() if user_response.data else None
        
        if not registered_name:
            logger.warning(f"No registered name found for {user_email}")
            return {
                "found": False,
                "found_in": "none",
                "matched_field": None,
                "registered_name": None
            }
            
    except Exception as e:
        logger.error(f"Failed to get registered user name: {e}")
        return {
            "found": False,
            "found_in": "none",
            "matched_field": None,
            "registered_name": None
        }
    
    if not os.path.exists(user_docs_dir):
        return {
            "found": False,
            "found_in": "none",
            "matched_field": None,
            "registered_name": registered_name
        }
    
    logger.info(f"\n{'='*80}")
    logger.info(f" CHECKING IF '{registered_name}' APPEARS IN COMPANY DOCUMENTS")
    logger.info(f"{'='*80}\n")
    
    found_in = []
    matched_fields = []
    
    # Check Commercial License and MOA documents
    for item in os.listdir(user_docs_dir):
        item_path = os.path.join(user_docs_dir, item)
        
        if not os.path.isdir(item_path):
            continue
        
        output_path = os.path.join(item_path, "output.json")
        
        if os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                
                doc_type = analysis.get("document_type", "")
                
                # Only check Commercial and MOA documents
                if doc_type not in ["commercial", "moa"]:
                    continue
                
                logger.info(f" Checking {doc_type.upper()} document...")
                
                extracted = analysis.get("extracted_fields", {})
                
                # Convert entire extracted data to string for searching
                extracted_text = json.dumps(extracted, ensure_ascii=False).lower()
                
                # Check if registered name appears anywhere
                if registered_name in extracted_text:
                    found_in.append(doc_type)
                    logger.info(f"[SUCCESS] Found '{registered_name}' in {doc_type.upper()} (general match)")
                    matched_fields.append(f"{doc_type}_general")
                    continue
                
                # Detailed field checking
                if doc_type == "commercial":
                    # Check managers
                    managers = extracted.get("managers", [])
                    for mgr in managers:
                        mgr_name = mgr.get("name_english", "").strip().lower()
                        if mgr_name and (registered_name in mgr_name or mgr_name in registered_name):
                            found_in.append("commercial")
                            matched_fields.append("commercial_manager")
                            logger.info(f"[SUCCESS] Found '{registered_name}' as MANAGER in Commercial License")
                            break
                    
                    # Check owner
                    if "commercial" not in found_in:
                        owner = extracted.get("owner", {})
                        owner_name = owner.get("name_english", "").strip().lower()
                        if owner_name and (registered_name in owner_name or owner_name in registered_name):
                            found_in.append("commercial")
                            matched_fields.append("commercial_owner")
                            logger.info(f"[SUCCESS] Found '{registered_name}' as OWNER in Commercial License")
                
                elif doc_type == "moa":
                    eng = extracted.get("english", {})
                    
                    # Check owner
                    owner_name = eng.get("owner_name", "").strip().lower()
                    if owner_name and (registered_name in owner_name or owner_name in registered_name):
                        found_in.append("moa")
                        matched_fields.append("moa_owner")
                        logger.info(f"[SUCCESS] Found '{registered_name}' as OWNER in MOA")
                        continue
                    
                    # Check manager
                    manager_name = eng.get("manager_name", "").strip().lower()
                    if manager_name and (registered_name in manager_name or manager_name in registered_name):
                        found_in.append("moa")
                        matched_fields.append("moa_manager")
                        logger.info(f"[SUCCESS] Found '{registered_name}' as MANAGER in MOA")
                
            except Exception as e:
                logger.error(f"Failed to check {output_path}: {e}")
                continue
    
    # Determine result
    found = len(found_in) > 0
    
    if len(found_in) == 2:
        location = "both"
    elif len(found_in) == 1:
        location = found_in[0]
    else:
        location = "none"
    
    result = {
        "found": found,
        "found_in": location,
        "matched_field": ", ".join(matched_fields) if matched_fields else None,
        "registered_name": registered_name
    }
    
    logger.info(f"\n{'='*80}")
    logger.info(f"VALIDATION RESULT")
    logger.info(f"{'='*80}")
    logger.info(f"Registered Name: '{registered_name}'")
    logger.info(f"Found in Documents: {found}")
    logger.info(f"Found In: {location}")
    logger.info(f"Matched Fields: {matched_fields}")
    logger.info(f"{'='*80}\n")
    
    return result


# ===========================
# EMAIL-REPLY PROMPT BUILDER
# ===========================
# Moved here from llm_runner/prompt_templates.py — process_user_reply() below
# is the only caller, so keeping it in a separate top-level package added an
# import hop for nothing. Behaviour is unchanged.

def build_onboarding_system_prompt() -> str:
    """Task-specific system prompt for the email-reply chat pipeline (see
    build_onboarding_prompt / process_user_reply below)."""
    return f"You are an intelligent and friendly onboarding assistant at {config.BRAND_NAME}."


def build_onboarding_prompt(
    user_message: str, context: str = "", registration_data: dict = None
) -> str:
    onboarding_step = "welcome"
    if context.startswith("Onboarding Step:"):
        onboarding_step = context.split("\n")[0].split(":")[1].strip()

    # Build registration details string.
    #
    # PII MASKING (prompt-remediation Phase 1, item #1): date of birth,
    # phone number, and email used to go into this prompt as plain text on
    # every chat turn, even though none of the branches below ("Instructions:
    # ...") ever reference those specific values -- the model only needs
    # them, if at all, in generic form. mask_pii() replaces DOB with
    # '***DOB***', the phone with a last-4-digits mask, and the email with a
    # first-character + domain mask, so the conversational assistant can
    # still see *that* these fields are on file without the raw bearer
    # values leaving the process boundary into the model provider on every
    # turn. The customer's own name is deliberately left unmasked here (and
    # is NOT passed through mask_pii, which would otherwise hash it to
    # "PERSON_<hash>") because this prompt's whole job is to let the model
    # address the user personally in its reply -- masking it would be a
    # real UX regression for no corresponding privacy gain, since it is the
    # same user's own name being reflected back to them, not disclosed to a
    # third party. Business/account fields (business_name, account_type,
    # ownership_type) are never PII and pass through unchanged either way.
    reg_details = ""
    if registration_data:
        _sensitive = mask_pii({
            "dob": registration_data.get("dob"),
            "phone_number": registration_data.get("phone_number"),
            "email": registration_data.get("email"),
        })
        reg_details = (
            f"- Name: {registration_data.get('name')}\n"
            f"- Date of Birth: {_sensitive.get('dob')}\n"
            f"- Phone Number: {_sensitive.get('phone_number')}\n"
            f"- Email: {_sensitive.get('email')}\n"
            f"- Business Name: {registration_data.get('business_name')}\n"
            f"- Account Type: {registration_data.get('account_type')}\n"
            f"- Ownership Type: {registration_data.get('ownership_type')}\n"
            f"- Partnership Details: {registration_data.get('partnership_details')}\n"
            f"- Expected Annual Turnover: {registration_data.get('annual_turnover')}\n"
            f"- Above 18: {'Yes' if registration_data.get('is_above_18') else 'No'}\n"
        )

    # Document instructions based on account type
    account_type = registration_data.get("account_type") if registration_data else None
    if onboarding_step == "welcome":
        if account_type == ACCOUNT_CORPORATE:
            instructions = "Please submit your Commercial License as image files."
        else:
            instructions = (
                "Please submit your documents as image files to continue onboarding."
            )
    elif onboarding_step == "document_verification":
        instructions = "Inform the user that all relevant documents have been received and are being verified. Ask if they have any other queries."

    elif onboarding_step == "verification_in_progress":
        instructions = "Inform the user that some documents have been received and are verified. Ask then to submit the remaining documents."

    elif onboarding_step == "verification_complete":
        instructions = "Congratulate the user for being onboarded and inform them that account details will be shared within 3-4 business days."
    else:
        instructions = "Respond helpfully to the user's query."

    # ARCHITECTURE FIX (prompt-remediation Phase 2): the assistant-identity
    # line moved out of the returned prompt text and into
    # build_onboarding_system_prompt() below, so process_user_reply() can
    # pass it through the model's actual system role instead of textually
    # embedding it as the first line of the user turn.
    prompt = f"""
Current onboarding step: {onboarding_step}
Instructions: {instructions}

User registration details:
{reg_details}

Here is a question from the user:
\"\"\"{user_message}\"\"\"

Relevant background information:
\"\"\"{context}\"\"\"

Please respond in a helpful, conversational tone.
"""
    return prompt.strip()


def process_user_reply(from_email: str, body: str, attachments: list = None):
    """
    Enhanced reply handler with cross-validation + SurePass API validation

    VALIDATION REQUIREMENT:
    - CORPORATE (Single Owner): Validate Commercial + EID + Ejari, then SurePass API, then ask for confirmation
    - CORPORATE (Multiple Owners): NO validation, NO SurePass - proceed directly to member EID collection
      * Extracts members from BOTH managers[] and partners[]
      * Classifies UBOs (>=25% share) separately from Members
      * UBOs listed first in EID collection order
    """
    logger.info(f"\n{'='*80}")
    logger.info(f"NEW EMAIL PROCESSING STARTED")
    logger.info(f"From: {from_email}")
    logger.info(f"Attachments: {len(attachments) if attachments else 0}")
    logger.info(f"{'='*80}\n")

    # Get user data
    user_response = UserRepository.get_by_email(from_email)
    if not user_response.data:
        logger.warning(f"Email not found: {from_email}")
        return

    user             = user_response.data[0]
    account_type     = user.get("account_type")
    ownership_type   = user.get("ownership_type")
    onboarding_step  = user.get("onboarding_step", "welcome")
    document_stage   = user.get("document_stage", STAGE_IDENTIFICATION)
    user_name        = user.get("name", "User")

    logger.info(f"Processing reply from {from_email}")
    logger.info(f"       Account Type   : {account_type}")
    logger.info(f"       Ownership Type : {ownership_type}")
    logger.info(f"       Onboarding Step: {onboarding_step}")
    logger.info(f"       Document Stage : {document_stage}")

    doc_requirements = get_required_documents(account_type, ownership_type)
    if not doc_requirements:
        logger.error(f"Could not determine document requirements for {from_email}")
        return

    # ========================================
    # PROCESS ATTACHMENTS
    # ========================================
    if attachments:
        logger.info(f"Processing {len(attachments)} documents for {from_email}")

        # === CORPORATE - MULTIPLE OWNERS - MEMBER EID COLLECTION ===
        if (account_type == ACCOUNT_CORPORATE and
                ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
                document_stage == STAGE_MEMBER_EIDS):

            logger.info("Processing member EID documents (no validation needed)")

            progress = get_member_progress(from_email)
            if not progress:
                logger.error(f"No member progress found for {from_email}")
                return

            members       = progress["members"]
            current_index = progress["current_index"]

            if current_index >= len(members):
                logger.error(f"Invalid member index: {current_index}/{len(members)}")
                return

            current_member = members[current_index]
            logger.info(f"Processing documents for member "
                  f"{current_index + 1}/{len(members)}: {current_member}")

            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=True,
                member_name=current_member,
            )

            success_eid = any(
                doc["type"] == "eid"
                for doc in results.get("success", [])
            )

            if success_eid:
                logger.info(f"[SUCCESS] Valid EID received for {current_member}")
                current_index += 1

                if current_index < len(members):
                    next_member = members[current_index]
                    save_member_progress(from_email, members, current_index)
                    logger.info(f"Requesting EID for next member: {next_member}")
                    send_member_eid_request_email(
                        from_email, next_member, current_index + 1, len(members)
                    )
                    return
                else:
                    logger.info(f"[SUCCESS] All {len(members)} member EIDs collected!")
                    UserRepository.update_by_email(from_email, {
                        "onboarding_step": "awaiting_confirmation",
                        "document_stage":  "member_eids_complete",
                    })
                    send_member_documents_confirmation_email(from_email, members)
                    logger.info("Confirmation email sent. Awaiting user confirmation.")
                    return
            else:
                logger.warning(f"Invalid EID for {current_member}, requesting resubmission")
                send_document_status_email(
                    from_email, results, is_member=True, member_name=current_member
                )
                save_member_progress(from_email, members, current_index)
                return

        # === REGULAR DOCUMENT PROCESSING (NON-MEMBER) ===
        else:
            logger.info("Processing user documents (validation required for this flow)")

            results = process_user_documents(
                from_email=from_email,
                attachments=attachments,
                is_member=False,
            )

            # ====================================
            # STAGE 2: CORPORATE - SINGLE OWNER
            # ====================================
            if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
                logger.info("Checking Corporate Single Owner completion (with confirmation)")

                stage_check = check_document_stage_completion(
                    from_email, ["commercial", "eid", "ejari"]
                )

                if stage_check["complete"]:
                    logger.info("[SUCCESS] All Corporate Single Owner documents valid")
                    logger.info("\n[INFO] Running cross-validation for Corporate Single Owner...")

                    try:
                        from app.services.cross_validator import CrossValidator

                        validator = CrossValidator()

                        logger.info("Sending validation pending notification...")
                        send_validation_pending_email(from_email, user_name)
                        logger.info("[SUCCESS] Validation pending email sent")

                        logger.info("Running cross-validation...")
                        validation_result = validator.validate_documents(from_email, user)

                        logger.info("Saving validation result...")
                        validator.save_validation_result(from_email, validation_result)
                        logger.info("[SUCCESS] Validation result saved to JSON")

                        if validation_result["passed"]:
                            logger.info("[SUCCESS] Cross-validation passed!")
                            logger.info(f"\n{'='*80}")
                            logger.info(f"[SUREPASS] Running government verification for Emirates ID...")
                            logger.info(f"{'='*80}")

                            surepass_valid, surepass_message = validate_eid_before_confirmation(from_email)

                            if not surepass_valid:
                                logger.error(f"ERROR: SurePass validation failed")
                                logger.error(f"Reason: {surepass_message}")
                                return
                            else:
                                logger.info(f"SUCCESS: SurePass validation passed!")
                                send_validation_passed_email(from_email, user_name)
                                logger.info("Validation success email sent")
                                send_document_status_email(from_email, results, is_member=False)
                                logger.info("Confirmation email sent. Awaiting user confirmation.")
                                return
                        else:
                            logger.error(f"[ERROR] Cross-validation failed for Corporate Single Owner")
                            logger.info(f"Mismatches: {validation_result['mismatches']}")
                            send_validation_failed_email(
                                to_email=from_email,
                                user_name=user_name,
                                mismatches=validation_result["mismatches"],
                                attempt_count=validation_result.get("attempt_count", 1),
                            )
                            logger.info("Validation failure email sent with detailed mismatches")
                            return

                    except Exception as e:
                        logger.error(f"Cross-validation system error: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        logger.warning("Proceeding without cross-validation due to system error")
                        send_document_status_email(from_email, results, is_member=False)
                        logger.info("Confirmation email sent (cross-validation skipped)")
                        return
                else:
                    logger.info(f"Missing/invalid documents: {stage_check['missing']}")
                    send_missing_documents_email(
                        from_email,
                        stage_check["missing"],
                        "Sole Proprietorship",
                    )
                    return

            # ====================================
            # STAGE 3: CORPORATE - MULTIPLE OWNERS
            # UBO-aware member extraction
            # ====================================
            elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
                logger.info("Corporate Multiple Owners — Identification Stage")

                if document_stage == STAGE_IDENTIFICATION:
                    logger.info("Stage: Identification (need Commercial + MOA)")

                    stage_check = check_document_stage_completion(
                        from_email, ["commercial", "moa"]
                    )

                    if stage_check["complete"]:
                        logger.info("[SUCCESS] Commercial + MOA received, extracting members")

                        # ══════════════════════════════════════════════════════════
                        # TYPE-2 CHECK: Detect corporate shareholders in Commercial
                        # License partners list before proceeding to member EIDs
                        # ══════════════════════════════════════════════════════════
                        _hr_comm_path1, comm_data = _find_commercial_output_hr(from_email)
                        corporate_detected = False
                        pending_coi_list = []

                        if _hr_comm_path1 is not None:
                            try:
                                partners_list = comm_data.get("extracted_fields", {}).get("partners", [])
                                if not partners_list:
                                    # Also try top-level partners key
                                    partners_list = comm_data.get("partners", [])
                                if partners_list:
                                    from app.services.specialized_ocr.corporate_shareholder_detector import detect_corporate_shareholders as _detect_corps
                                    corp_detection = _detect_corps(partners_list)
                                    if corp_detection["has_corporate_shareholders"]:
                                        corporate_detected = True
                                        pending_coi_list = [
                                            c["name"] for c in corp_detection["corporate_shareholders"]
                                        ]
                                        logger.info(f"[TYPE-2] Corporate shareholders found: {pending_coi_list}")
                            except Exception as _e:
                                logger.warning(f"Type-2 detection failed (non-fatal): {_e}")

                        if corporate_detected and pending_coi_list:
                            # ── TYPE-2 PATH: Request Certificates of Incorporation ──
                            logger.info(f"[TYPE-2] Transitioning to corporate_shareholder_docs stage")

                            # Save pending CoI list in member_progress.json
                            save_member_progress(
                                from_email,
                                members=[],         # EID names filled after expansion
                                current_index=0,
                                pending_coi=pending_coi_list,
                            )

                            # Update stage
                            UserRepository.update_by_email(from_email, {
                                "document_stage":  STAGE_CORPORATE_SHAREHOLDER_DOCS,
                                "onboarding_step": "corporate_shareholder_docs_required",
                            })

                            # Send email requesting CoI for first corporate entity
                            first_corp = pending_coi_list[0]
                            _total = len(pending_coi_list)
                            from app.services.email_sender import send_corporate_shareholder_request_email
                            send_corporate_shareholder_request_email(
                                to_email=from_email,
                                corp_name=first_corp,
                                corp_index=1,
                                total_corps=_total,
                            )
                            logger.info(f"[TYPE-2] CoI requested for: {first_corp} (1/{_total})")
                            return

                        # ── STANDARD PATH (no corporate shareholders) ──────────────
                        # ── UPDATED: UBO-aware member extraction ──────────────
                        member_data       = extract_members_from_documents(from_email)
                        ubos              = member_data["ubos"]
                        members           = member_data["members"]
                        all_names         = member_data["all_names"]   # UBOs first, then members
                        user_in_documents = member_data["includes_user"]
                        user_validation   = member_data["user_validation"]

                        logger.info(f"UBOs identified      : {len(ubos)}")
                        for u in ubos:
                            logger.info(f"         -> {u['name']} ({u['share_percentage']})")

                        logger.info(f"Members identified   : {len(members)}")
                        for m in members:
                            logger.info(f"         -> {m['name']} ({m['share_percentage'] or 'no share data'})")

                        logger.info(f"Total EIDs to collect: {len(all_names)}")
                        logger.info(f"Registered user in docs : {user_in_documents}")

                        if all_names and len(all_names) > 0:
                            # Create member directories
                            base_docs_dir = str(user_docs_path(from_email))
                            for name in all_names:
                                os.makedirs(os.path.join(base_docs_dir, name), exist_ok=True)

                            # Save progress — UBOs come first in all_names
                            save_member_progress(
                                from_email,
                                all_names,
                                0,
                                ubo_names=[u["name"] for u in ubos],
                            )

                            # Update stage
                            UserRepository.update_by_email(from_email, {
                                "document_stage":  STAGE_MEMBER_EIDS,
                                "onboarding_step": "member_documents_required",
                            })

                            # Send identification email with UBO + member split
                            send_member_identification_email(
                                from_email,
                                ubos,             # list of dicts: name + share_percentage + source
                                members,          # list of dicts: name + share_percentage + source
                                user_in_documents,
                                user_validation,
                            )

                            # Request first person's EID immediately (UBO first)
                            send_member_eid_request_email(
                                from_email,
                                all_names[0],
                                1,
                                len(all_names),
                            )

                            logger.info(f"Proceeding to member EID collection")
                            return

                        else:
                            # No members found
                            logger.error("Could not identify owners from documents")

                            subject   = "Error Identifying Owners"
                            body_html = """
                            <html><body style='font-family:Arial,sans-serif;color:#333;'>
                                <div style='max-width:600px;margin:auto;padding:24px;background:#fff;
                                            border-radius:10px;box-shadow:0 2px 8px #eee;'>
                                    <h2 style='color:#c62828;'>❌ Error Identifying Owners</h2>
                                    <p>Dear User,</p>
                                    <p>We could not identify the owners/members from your
                                       Commercial License and MOA documents.</p>
                                    <p>Please ensure:</p>
                                    <ul>
                                        <li>The Commercial License contains the partners/members section</li>
                                        <li>The MOA contains owner/manager information</li>
                                        <li>All text is clearly visible and readable</li>
                                    </ul>
                                    <p>Please resubmit clear copies of both documents.</p>
                                    <p style='margin-top:32px;'>Best regards,<br>
                                       <strong>DigiOB Onboarding Team</strong></p>
                                </div>
                            </body></html>
                            """
                            send_email(
                                to_email=from_email,
                                subject=subject,
                                body=body_html,
                                html=True,
                            )
                            return
                    else:
                        # Still need Commercial and/or MOA
                        logger.info(f"Still need documents: {stage_check['missing']}")
                        send_missing_documents_email(
                            from_email,
                            stage_check["missing"],
                            "Joint Ownership - Identification Stage",
                        )
                        return

                # ====================================
                # TYPE-2: CORPORATE SHAREHOLDER CoI
                # ====================================
                elif document_stage == STAGE_CORPORATE_SHAREHOLDER_DOCS:
                    logger.info("Stage: corporate_shareholder_docs (CoI collection)")

                    # Load progress to find which corp entity is next
                    progress = get_member_progress(from_email)
                    if not progress:
                        logger.error("No member_progress.json found in corporate_shareholder_docs stage")
                        return

                    pending_coi = progress.get("pending_coi", [])
                    if not pending_coi:
                        logger.warning("pending_coi list is empty — transitioning directly to member_eids")
                        # Fallback: no CoI needed, proceed normally
                        UserRepository.update_by_email(from_email, {
                            "document_stage": STAGE_MEMBER_EIDS,
                            "onboarding_step": "member_documents_required",
                        })
                        return

                    # Get first pending corporate entity name
                    current_corp = pending_coi[0]
                    logger.info(f"[TYPE-2] Processing CoI for: {current_corp}")

                    # Process the uploaded CoI document
                    results = process_user_documents(
                        from_email=from_email,
                        attachments=attachments,
                        is_member=False,
                    )

                    # Check if a certificate_of_incorporation was successfully extracted
                    coi_success = any(
                        doc.get("type") == "certificate_of_incorporation"
                        for doc in results.get("success", [])
                    )

                    if not coi_success:
                        logger.warning(f"No valid CoI received for {current_corp}")
                        # Re-request
                        from app.services.email_sender import send_corporate_shareholder_request_email
                        send_corporate_shareholder_request_email(
                            to_email=from_email,
                            corp_name=current_corp,
                            corp_index=1,
                            total_corps=len(pending_coi),
                        )
                        return

                    # CoI received — read the extracted output
                    coi_output_path = str(user_docs_path(from_email) / "certificate_of_incorporation" / "output.json")
                    coi_individuals = []
                    if os.path.exists(coi_output_path):
                        try:
                            with open(coi_output_path, "r", encoding="utf-8") as _f:
                                coi_data = json.load(_f)
                            das = coi_data.get("extracted_fields", {}).get("directors_and_shareholders", [])
                            coi_individuals = [
                                ind for ind in das
                                if isinstance(ind, dict) and float(ind.get("share_percentage", 0)) > 0
                            ]
                            logger.info(f"[TYPE-2] CoI individuals extracted: {[i.get('name') for i in coi_individuals]}")
                        except Exception as _e:
                            logger.error(f"Failed to read CoI output: {_e}")

                    # Remove this corp from pending_coi
                    remaining_coi = pending_coi[1:]
                    logger.info(f"[TYPE-2] Remaining CoI pending: {remaining_coi}")

                    if remaining_coi:
                        # More corporations still need CoI
                        save_member_progress(
                            from_email,
                            members=[],
                            current_index=0,
                            pending_coi=remaining_coi,
                        )
                        next_corp = remaining_coi[0]
                        from app.services.email_sender import send_corporate_shareholder_request_email
                        send_corporate_shareholder_request_email(
                            to_email=from_email,
                            corp_name=next_corp,
                            corp_index=len(pending_coi) - len(remaining_coi) + 1,
                            total_corps=len(pending_coi),
                        )
                        logger.info(f"[TYPE-2] Requesting CoI for next corp: {next_corp}")
                        return

                    # All CoIs collected — run full Type-2 expansion
                    logger.info("[TYPE-2] All CoIs collected — running ownership expansion")

                    # Build coi_map from all collected CoI outputs
                    coi_map = {}
                    coi_dir_path = str(user_docs_path(from_email) / "certificate_of_incorporation")
                    if os.path.exists(coi_dir_path):
                        try:
                            with open(os.path.join(coi_dir_path, "output.json"), "r", encoding="utf-8") as _f:
                                _coi = json.load(_f)
                            _corp_name_in_coi = _coi.get("extracted_fields", {}).get("company_name", current_corp)
                            _das = _coi.get("extracted_fields", {}).get("directors_and_shareholders", [])
                            coi_map[_corp_name_in_coi] = [
                                ind for ind in _das if float(ind.get("share_percentage", 0)) > 0
                            ]
                        except Exception as _e:
                            logger.error(f"Failed to build coi_map: {_e}")

                    # Run Type-2 analysis
                    _hr_comm_path2, _hr_comm_data2 = _find_commercial_output_hr(from_email)
                    expanded_owners = []
                    ubo_names_type2 = []

                    if _hr_comm_path2 is not None:
                        try:
                            partners_list = _hr_comm_data2.get("extracted_fields", {}).get("partners", [])
                            if not partners_list:
                                partners_list = _hr_comm_data2.get("partners", [])

                            type2_result = run_type2_analysis(partners_list, coi_map)
                            expanded_owners = type2_result.get("expanded_owners") or []
                            ubo_names_type2 = type2_result.get("ubo_names", [])
                            logger.info(f"[TYPE-2] Expanded owners: {[o['name'] for o in expanded_owners]}")
                            logger.info(f"[TYPE-2] UBOs: {ubo_names_type2}")
                        except Exception as _e:
                            logger.error(f"Type-2 expansion failed: {_e}")
                            import traceback; logger.error(traceback.format_exc())

                    # Build final EID collection list from expanded owners (exclude pure corporates)
                    all_names_expanded = [o["name"] for o in expanded_owners if o.get("name")]

                    if not all_names_expanded:
                        # Fallback to standard extraction
                        logger.warning("No expanded owners — falling back to standard member extraction")
                        member_data = extract_members_from_documents(from_email)
                        all_names_expanded = member_data["all_names"]
                        ubo_names_type2 = [u["name"] for u in member_data["ubos"]]

                    # Create member directories
                    base_docs_dir = str(user_docs_path(from_email))
                    for name in all_names_expanded:
                        os.makedirs(os.path.join(base_docs_dir, name), exist_ok=True)

                    # Save full progress
                    save_member_progress(
                        from_email,
                        members=all_names_expanded,
                        current_index=0,
                        ubo_names=ubo_names_type2,
                        expanded_members=expanded_owners,
                        pending_coi=[],
                    )

                    # Transition to member_eids
                    UserRepository.update_by_email(from_email, {
                        "document_stage":  STAGE_MEMBER_EIDS,
                        "onboarding_step": "member_documents_required",
                    })

                    # Send UBO identification email
                    from app.services.email_sender import send_ubo_identified_email
                    send_ubo_identified_email(
                        to_email=from_email,
                        expanded_owners=expanded_owners,
                        ubo_names=ubo_names_type2,
                    )

                    # Request EID for first expanded member
                    send_member_eid_request_email(
                        from_email,
                        all_names_expanded[0],
                        1,
                        len(all_names_expanded),
                    )
                    logger.info(f"[TYPE-2] Proceeding to member EID collection ({len(all_names_expanded)} members)")
                    return

    # ========================================
    # NO ATTACHMENTS — REGULAR CHAT
    # ========================================
    logger.info("No attachments, processing as chat message")

    ConversationRepository.insert({
        "user_email": from_email,
        "role":       "user",
        "message":    body,
        "timestamp":  datetime.utcnow().isoformat(),
    })

    try:
        # BUGFIX: this filtered on .eq("email", ...), but the conversations
        # table has no `email` column — every other query against it (12 of
        # them) filters on `user_email`, and insert_conversation_log() writes
        # `user_email`. Supabase therefore errored on an unknown column, the
        # except below swallowed it, and convo_context was set to "" — so every
        # inbound email reply was answered by the LLM with NO prior context.
        convo_response = ConversationRepository.list_all(from_email)
        convo_history = convo_response.data if convo_response.data else []
        convo_context = "\n".join(
            [f"{msg['role']}: {msg['message']}" for msg in convo_history[-6:]]
        )
    except Exception as e:
        logger.warning(f"Conversation history retrieval failed: {e}")
        convo_context = ""

    full_context = (
        f"Onboarding Step: {onboarding_step}\n\n"
        f"{convo_context}"
    )

    try:
        prompt = build_onboarding_prompt(
            user_message=body,
            context=full_context,
            registration_data={
                "name":           user.get("name"),
                "email":          user.get("email"),
                "business_name":  user.get("business_name"),
                "account_type":   user.get("account_type"),
                "ownership_type": user.get("ownership_type"),
            },
        )
        llm_response = call_local_llm(
            prompt, system_prompt=build_onboarding_system_prompt(), temperature=0.5
        )
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        llm_response = "Thank you for your message. Our team will respond to you shortly."

    subject = "Re: Your query with DigiOB"
    send_email(to_email=from_email, subject=subject, body=llm_response)

    ConversationRepository.insert({
        "user_email": from_email,
        "role":       "agent",
        "message":    llm_response,
        "timestamp":  datetime.utcnow().isoformat(),
    })

    logger.info(f"Chat response sent to: {from_email}")