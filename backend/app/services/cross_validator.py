# backend/app/services/cross_validator.py

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re
from difflib import SequenceMatcher
from dotenv import load_dotenv
from app import config
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
)

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def _resolve_user_docs_dir(email: str) -> Optional[Path]:
    """Return the user's document root, trying ref_no first then email fallback."""
    try:
        from app.services.document_helpers import get_documents_base_path, get_document_ref_no
        base = get_documents_base_path()
        ref_no = get_document_ref_no(email)
    except Exception:
        base = Path("backend/documents/id")
        ref_no = email

    candidates = [
        base / ref_no,
        # Legacy email-based path for backward compat with old data
        base / email,
        # Absolute Docker path fallbacks (in case base resolved differently)
        Path(f"/app/backend/documents/id/{ref_no}"),
        Path(f"/app/backend/documents/id/{email}"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class CrossValidator:
    """Cross-validation service for document verification"""
    
    def __init__(self):
        self.mismatches = []
        self.validation_details = {}
        
        # Load configuration from environment
        self.config = {
            "corporate_single_enabled": config.CROSS_VALIDATION_CORPORATE_SINGLE,
            "corporate_partnership_enabled": config.CROSS_VALIDATION_CORPORATE_PARTNERSHIP,
            "fuzzy_threshold": config.FUZZY_MATCH_THRESHOLD,
            "debug_logging": config.CROSS_VALIDATION_DEBUG_LOGGING,
        }
        
        # ✅ NEW: Legal type normalization mappings
        self.legal_type_mappings = {
            # Limited Liability Company variations
            "llc": ["limited liability company", "llc", "l.l.c", "l.l.c.", "liability company"],
            "llc_so": ["single owner", "llc - so", "llc-so", "one person", "sole proprietor"],
            "llc_mo": ["multiple owners", "llc - mo", "llc-mo", "partnership", "partners"],
            
            # Company type variations
            "establishment": ["establishment", "est", "est.", "individual establishment"],
            "branch": ["branch", "foreign branch", "overseas branch"],
            "freelance": ["freelance", "free lance", "freelancer"],
            
            # General terms
            "private": ["private", "pvt", "pvt.", "pte"],
            "public": ["public", "plc", "p.l.c"],
        }
        
        if self.config["debug_logging"]:
            logger.debug(f"\n[CONFIG] Cross-Validation Settings:")
            logger.debug(f"   - Corporate Single: {'Enabled' if self.config['corporate_single_enabled'] else 'Disabled'}")
            logger.debug(f"   - Corporate Partnership: {'Enabled' if self.config['corporate_partnership_enabled'] else 'Disabled'}")
            logger.debug(f"   - Fuzzy Match Threshold: {self.config['fuzzy_threshold']:.0%}\n")
    
    # ============================================================================
    # MAIN VALIDATION ENTRY POINT
    # ============================================================================
    
    def validate_documents(self, email: str, user_data: dict) -> dict:
        """
        Main cross-validation function with environment-based toggles
        
        Args:
            email: User email
            user_data: User registration data from database
        
        Returns:
            {
                "passed": bool,
                "mismatches": [],
                "validation_details": {},
                "message": str,
                "skipped": bool,
                "skip_reason": str
            }
        """
        self.mismatches = []
        self.validation_details = {}
        
        account_type = user_data.get("account_type", "")
        ownership_type = user_data.get("ownership_type", "")
        
        logger.debug(f"\n{'='*80}")
        logger.debug(f"[CROSS-VALIDATION] Starting validation for {email}")
        logger.debug(f"   Account Type: {account_type}")
        logger.debug(f"   Ownership Type: {ownership_type}")
        logger.debug(f"{'='*80}")
        
        # ============================================================================
        # CHECK IF VALIDATION IS ENABLED FOR THIS ACCOUNT TYPE
        # ============================================================================
        
        # Corporate Single Owner
        if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
            if not self.config["corporate_single_enabled"]:
                logger.debug(f"⏭ [SKIPPED] Corporate Single Owner validation is disabled in .env")
                return {
                    "passed": True,
                    "mismatches": [],
                    "validation_details": {},
                    "message": "Cross-validation skipped: Disabled for Corporate Single Owner",
                    "skipped": True,
                    "skip_reason": "CROSS_VALIDATION_CORPORATE_SINGLE=false"
                }
        
        # Corporate Partnership
        elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            if not self.config["corporate_partnership_enabled"]:
                logger.debug(f"⏭ [SKIPPED] Corporate Partnership validation is disabled in .env")
                return {
                    "passed": True,
                    "mismatches": [],
                    "validation_details": {},
                    "message": "Cross-validation skipped: Disabled for Corporate Partnership",
                    "skipped": True,
                    "skip_reason": "CROSS_VALIDATION_CORPORATE_PARTNERSHIP=false"
                }
        
        # ============================================================================
        # LOAD DOCUMENTS
        # ============================================================================
        documents = self._load_all_documents(email)
        
        if not documents:
            return {
                "passed": False,
                "mismatches": ["No documents found for validation"],
                "validation_details": {},
                "message": "Unable to load documents for cross-validation",
                "skipped": False,
                "skip_reason": None
            }
        
        # ============================================================================
        # ROUTE TO APPROPRIATE VALIDATOR
        # ============================================================================
        
        if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
            result = self._validate_corporate_single_owner(user_data, documents)
        
        elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            result = self._validate_corporate_partnership(user_data, documents)
        
        else:
            return {
                "passed": True,
                "mismatches": [],
                "validation_details": {},
                "message": f"Cross-validation not implemented for: {account_type} - {ownership_type}",
                "skipped": True,
                "skip_reason": "Not implemented"
            }
        
        # Add skip status to result
        result["skipped"] = False
        result["skip_reason"] = None
        
        return result
    
    # ============================================================================
    # CORPORATE SINGLE OWNER VALIDATION
    # ============================================================================
    
    def _load_member_eid_for_single_owner(self, email: str, owner_name: str) -> dict:
        """
        For Corporate Single Owner, the owner's EID/Passport is expected under
        a member subfolder whose name matches the commercial owner name:
            <user_dir>/<member_name>/eid/output.json
            <user_dir>/<member_name>/<any_subfolder>/output.json  (passport)

        In practice the KI/member-upload flow (chatupload.py) actually saves
        the verified identity doc under a generated-ID folder instead:
            <user_dir>/members/MEID-<ref_no>-<n>/output.json
        A top-level folder named after the owner can also exist but be empty
        (leftover from an earlier step) — matching on that name alone finds
        the empty folder and gives up before ever checking members/.

        Steps:
        1. Try the direct top-level folder-name match (legacy path).
        2. If that finds no valid identity doc, fall back to scanning
           <user_dir>/members/*/output.json and match by the extracted Name
           field instead of the folder name — mirrors what _load_member_eids()
           already does successfully for Corporate Partnership validation.
        """
        EID_TYPES = {"eid", "emirates id", "emirates_id", "identity card"}
        PASSPORT_TYPES = {"passport", "travel document", "travel_document", "intl_id"}

        user_docs_dir = _resolve_user_docs_dir(email)

        if not user_docs_dir:
            return {}

        def normalize(s):
            return re.sub(r'\s+', ' ', s.lower().strip())

        def folder_matches_owner(folder_name: str, owner: str) -> bool:
            f = normalize(folder_name)
            o = normalize(owner)
            if f == o:
                return True
            # Subset check — handles "VARSHA BALAJI BALAJI" vs "VARSHA BALAJI"
            f_parts = set(f.split())
            o_parts = set(o.split())
            if f_parts.issubset(o_parts) or o_parts.issubset(f_parts):
                return True
            # Fuzzy ratio fallback
            ratio = SequenceMatcher(None, f, o).ratio()
            return ratio >= 0.80

        def extract_identity(doc_type: str, extracted: dict) -> Optional[dict]:
            if doc_type in EID_TYPES:
                return extracted
            if doc_type in PASSPORT_TYPES:
                given_names = extracted.get("given_names", "")
                surname = extracted.get("surname", "")
                full_name = f"{given_names} {surname}".strip() or extracted.get("full_name", "")
                return {
                    "Name": full_name,
                    "name": full_name,
                    "Nationality": extracted.get("nationality") or extracted.get("Nationality", ""),
                    "nationality": extracted.get("nationality", ""),
                    "Date of Birth": extracted.get("date_of_birth") or extracted.get("Date of Birth", ""),
                    "_source": "passport",
                }
            return None

        logger.debug(f"  [SO] Looking for member folder matching owner: '{owner_name}'")

        # ── Pass 1: direct top-level folder-name match (legacy path) ──────────
        matched_member_dir = None
        for member_dir in user_docs_dir.iterdir():
            if not member_dir.is_dir() or member_dir.name == "members":
                continue
            if folder_matches_owner(member_dir.name, owner_name):
                logger.debug(f"  [SO] Matched member folder: '{member_dir.name}'")
                matched_member_dir = member_dir
                break

        if not matched_member_dir:
            logger.debug(f"   [SO] No top-level member folder matched owner '{owner_name}' — listing available folders:")
            for d in user_docs_dir.iterdir():
                if d.is_dir():
                    logger.debug(f"       - {d.name}")
        else:
            for doc_subdir in matched_member_dir.iterdir():
                if not doc_subdir.is_dir():
                    continue
                output_json = doc_subdir / "output.json"
                if not output_json.exists():
                    continue
                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not data.get("is_valid", False):
                        continue
                    doc_type = data.get("document_type", "").lower().strip()
                    extracted = data.get("extracted_fields") or data.get("extracted_data")
                    if not extracted or not isinstance(extracted, dict):
                        continue
                    identity = extract_identity(doc_type, extracted)
                    if identity:
                        src = "Passport" if identity.get("_source") == "passport" else "EID"
                        logger.debug(f"  [SO] Loaded {src} from: {matched_member_dir.name}/{doc_subdir.name}")
                        return identity
                except Exception as e:
                    logger.debug(f"   [SO] Error reading {output_json}: {e}")

            logger.debug(f"   [SO] No valid EID/Passport found inside folder: '{matched_member_dir.name}'")

        # ── Pass 2: fall back to members/*/output.json, matched by extracted
        # Name instead of folder name. This is where the KI/member-upload flow
        # actually saves verified identity docs (folder named MEID-<ref>-<n>,
        # not the person's name) — applies to every account, not just one email.
        members_dir = user_docs_dir / "members"
        if members_dir.exists() and members_dir.is_dir():
            logger.debug(f"  [SO] Falling back to members/ subfolder scan for '{owner_name}'")
            for doc_subdir in members_dir.iterdir():
                if not doc_subdir.is_dir():
                    continue
                output_json = doc_subdir / "output.json"
                if not output_json.exists():
                    continue
                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not data.get("is_valid", False):
                        continue
                    doc_type = data.get("document_type", "").lower().strip()
                    extracted = data.get("extracted_fields") or data.get("extracted_data")
                    if not extracted or not isinstance(extracted, dict):
                        continue
                    identity = extract_identity(doc_type, extracted)
                    if not identity:
                        continue
                    candidate_name = (identity.get("Name") or identity.get("name") or "").strip()
                    if self._fuzzy_name_match(owner_name, candidate_name):
                        src = "Passport" if identity.get("_source") == "passport" else "EID"
                        logger.debug(f"  [SO] Loaded {src} from members/{doc_subdir.name} (Name={candidate_name!r})")
                        return identity
                except Exception as e:
                    logger.debug(f"   [SO] Error reading {output_json}: {e}")

            logger.debug(f"   [SO] members/ scan found no identity doc matching '{owner_name}'")

        return {}

    def _validate_corporate_single_owner(self, user_data: dict, documents: dict) -> dict:
        """
        Validate Corporate Single Owner (Commercial License + MOA + EID/Passport + Ejari)

        Validation Rules:
        - Company Name: Commercial.company_name_english = Ejari.tenant_company
        - Owner/Manager Name: Commercial.owner.name_english = EID/Passport Name
        - Owner Name: Commercial.owner.name_english = MOA.owner_name
        - Nationality: Commercial.owner.nationality_english = EID/Passport Nationality
        """
        logger.debug("\n" + "="*80)
        logger.debug("CORPORATE SINGLE OWNER CROSS-VALIDATION")
        logger.debug("="*80)

        commercial_data = documents.get("commercial", {})
        ejari_data = documents.get("ejari", {})
        moa_data = documents.get("moa", {})

        # Extract owner name from commercial first — needed to find the right member folder
        commercial_english = commercial_data.get("english", {}) if commercial_data else {}
        commercial_owner = commercial_data.get("owner", {}) if commercial_data else {}
        owner_name = commercial_owner.get("name_english", "").strip()

        # For Single Owner, the owner's EID is stored in a member subfolder whose name
        # matches the commercial owner name. Always search the member subfolder FIRST
        # (using the owner name from the commercial license) so we pick up the correct
        # owner EID instead of an unrelated KI/member passport that _load_all_documents
        # may have mapped into the top-level "eid" slot.
        email = user_data.get("email", "")
        eid_data = {}
        if owner_name:
            logger.debug(f"   Scanning member subfolder for owner EID: '{owner_name}' ({email})")
            eid_data = self._load_member_eid_for_single_owner(email, owner_name)
        if not eid_data:
            # Fall back to top-level EID document (e.g. direct upload without member folder)
            logger.debug(f"   No owner EID in member folder — falling back to top-level EID")
            eid_data = documents.get("eid", {})

        if not commercial_data:
            self.mismatches.append("Commercial License document not found")
        if not moa_data:
            self.mismatches.append("Memorandum of Association (MOA) document not found")
        if not eid_data:
            self.mismatches.append("Owner identity document (EID or Passport) not found")
        if not ejari_data:
            self.mismatches.append("Ejari (Tenancy Contract) document not found")

        if not commercial_data or not moa_data or not eid_data or not ejari_data:
            return self._build_result(False, "Missing required documents")
        
        commercial_company_name = commercial_english.get("company_name_english", "").strip()
        owner_name = commercial_owner.get("name_english", "").strip()
        owner_nationality = commercial_owner.get("nationality_english", "").strip()
        
        ejari_tenant_company = ejari_data.get("tenant_company", "").strip()
        eid_name = (eid_data.get("Name") or eid_data.get("name") or "").strip()
        eid_nationality = (eid_data.get("Nationality") or eid_data.get("nationality") or "").strip()
        
        logger.debug(f"\nExtracted Data:")
        logger.debug(f"  Commercial Company Name: {commercial_company_name}")
        logger.debug(f"  Ejari Tenant Company: {ejari_tenant_company}")
        logger.debug(f"  Commercial Owner Name: {owner_name}")
        logger.debug(f"  EID Name: {eid_name}")
        logger.debug(f"  Commercial Owner Nationality: {owner_nationality}")
        logger.debug(f"  EID Nationality: {eid_nationality}")
        
        # Validation 1: Company Name
        logger.debug(f"\nValidating Company Name...")
        company_match = self._fuzzy_name_match(commercial_company_name, ejari_tenant_company)
        
        if not company_match:
            mismatch = f"Company name mismatch: Commercial License ('{commercial_company_name}') vs Ejari ('{ejari_tenant_company}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  Company Name Match")
        
        self.validation_details["company_name_validation"] = {
            "commercial_company_name": commercial_company_name,
            "ejari_tenant_company": ejari_tenant_company,
            "match": company_match
        }
        
        # Validation 2: Owner Name
        logger.debug(f"\nValidating Owner Name...")
        owner_name_match = self._fuzzy_name_match(owner_name, eid_name)
        
        if not owner_name_match:
            mismatch = f"Owner name mismatch: Commercial License ('{owner_name}') vs EID ('{eid_name}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  Owner Name Match")
        
        self.validation_details["owner_name_validation"] = {
            "commercial_owner_name": owner_name,
            "eid_name": eid_name,
            "match": owner_name_match
        }

        # Validation 2b: MOA Owner Name
        # Mirrors the inline check already run at upload time (upload.py's
        # _so_moa_id_stage block) — repeated here so the final gate before
        # SurePass/completion also catches it if the on-disk data changed.
        logger.debug(f"\nValidating MOA Owner Name...")
        moa_owner_name = (moa_data.get("owner_name") or "").strip()
        moa_owner_name_match = self._fuzzy_name_match(owner_name, moa_owner_name)

        if not moa_owner_name_match:
            mismatch = f"Owner name mismatch: Commercial License ('{owner_name}') vs MOA ('{moa_owner_name}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  MOA Owner Name Match")

        self.validation_details["moa_owner_name_validation"] = {
            "commercial_owner_name": owner_name,
            "moa_owner_name": moa_owner_name,
            "match": moa_owner_name_match
        }

        # Validation 3: Nationality
        logger.debug(f"\nValidating Nationality...")
        nationality_match = self._fuzzy_name_match(owner_nationality, eid_nationality)
        
        if not nationality_match:
            mismatch = f"Nationality mismatch: Commercial License ('{owner_nationality}') vs EID ('{eid_nationality}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  Nationality Match")
        
        self.validation_details["nationality_validation"] = {
            "commercial_nationality": owner_nationality,
            "eid_nationality": eid_nationality,
            "match": nationality_match
        }
        
        passed = len(self.mismatches) == 0
        message = "All cross-validation checks passed for Corporate Single Owner" if passed else f"Cross-validation failed: {len(self.mismatches)} issue(s) found"
        (logger.info if passed else logger.warning)(f"[CROSS-VALIDATION] Corporate Single Owner: {message}")
        logger.debug(f"{'='*80}\n")
        
        return self._build_result(passed, message)
    
    # ============================================================================
    # CORPORATE PARTNERSHIP VALIDATION (NEW)
    # ============================================================================
    
    def _validate_corporate_partnership(self, user_data: dict, documents: dict) -> dict:
        """
        Validate Corporate Partnership (Commercial License + MOA + Multiple EIDs)
        
        Stage 1 Validation (Commercial + MOA):
        - Company Name: Commercial.company_name_english = MOA.company_name
        - Legal Type: Commercial.legal_type = MOA.company_type (with normalization)
        - Business Activities: Commercial.activity_X = MOA.activity_X
        
        Stage 2 Validation (Partners' EIDs):
        - Partner Names: Commercial.partners[].name_english = Individual EID.Name
        - Nationality: Commercial.partners[].nationality_english = Individual EID.Nationality
        - Member Count: Total partners in license = Total EIDs collected
        """
        logger.debug("\n" + "="*80)
        logger.debug("CORPORATE PARTNERSHIP CROSS-VALIDATION")
        logger.debug("="*80)
        
        commercial_data = documents.get("commercial", {})
        moa_data = documents.get("moa", {})
        
        if not commercial_data:
            self.mismatches.append("Commercial License document not found")
        if not moa_data:
            self.mismatches.append("Memorandum of Association (MOA) document not found")
        
        if not commercial_data or not moa_data:
            return self._build_result(False, "Missing required Stage 1 documents")
        
        commercial_english = commercial_data.get("english", {})
        moa_english = moa_data if isinstance(moa_data, dict) else {}
        
        # ============================================================================
        # STAGE 1: COMPANY IDENTITY VERIFICATION
        # ============================================================================
        logger.debug(f"\nSTAGE 1: Company Identity Verification")
        logger.debug(f"{'='*80}")
        
        # Extract company names
        commercial_company = commercial_english.get("company_name_english", "").strip()
        moa_company = moa_english.get("company_name", "").strip()
        
        logger.debug(f"\nValidating Company Name...")
        logger.debug(f"  Commercial: {commercial_company}")
        logger.debug(f"  MOA: {moa_company}")
        
        company_match = self._fuzzy_name_match(commercial_company, moa_company)
        
        if not company_match:
            mismatch = f"Company name mismatch: Commercial License ('{commercial_company}') vs MOA ('{moa_company}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  Company Name Match")
        
        self.validation_details["company_identity"] = {
            "commercial_company_name": commercial_company,
            "moa_company_name": moa_company,
            "match": company_match
        }
        
        # ============================================================================
        # ✅ UPDATED: Legal Type Validation with Normalization
        # ============================================================================
        commercial_legal_type = commercial_english.get("legal_type", "").strip()
        moa_company_type = moa_english.get("company_type", "").strip()
        
        logger.debug(f"\nValidating Legal Type...")
        logger.debug(f"  Commercial: {commercial_legal_type}")
        logger.debug(f"  MOA: {moa_company_type}")
        
        # ✅ USE NEW LEGAL TYPE MATCHING (instead of fuzzy_name_match)
        legal_type_match = self._legal_type_match(commercial_legal_type, moa_company_type)
        
        if not legal_type_match:
            mismatch = f"Legal type mismatch: Commercial ('{commercial_legal_type}') vs MOA ('{moa_company_type}')"
            self.mismatches.append(mismatch)
            logger.debug(f"  {mismatch}")
        else:
            logger.debug(f"  Legal Type Match")
        
        self.validation_details["legal_type_validation"] = {
            "commercial_legal_type": commercial_legal_type,
            "moa_company_type": moa_company_type,
            "match": legal_type_match
        }
        
        # ============================================================================
        # STAGE 1: BUSINESS ACTIVITY VERIFICATION
        # ============================================================================
        logger.debug(f"\nBusiness Activity Verification")
        logger.debug(f"{'='*80}")
        
        activities_to_check = ["activity_1", "activity_2", "activity_3"]
        
        for activity_key in activities_to_check:
            commercial_activity = commercial_english.get(activity_key, "").strip()
            moa_activity = moa_english.get(activity_key, "").strip()
            
            if commercial_activity and moa_activity:
                logger.debug(f"\nValidating {activity_key.upper()}...")
                logger.debug(f"  Commercial: {commercial_activity}")
                logger.debug(f"  MOA: {moa_activity}")
                
                activity_match = self._fuzzy_name_match(commercial_activity, moa_activity)
                
                if not activity_match:
                    mismatch = f"{activity_key} mismatch: Commercial ('{commercial_activity}') vs MOA ('{moa_activity}')"
                    self.mismatches.append(mismatch)
                    logger.debug(f"  {mismatch}")
                else:
                    logger.debug(f"  {activity_key.upper()} Match")
        
        # ============================================================================
        # STAGE 2: PARTNER EID VERIFICATION (TYPE-2 AWARE)
        # For Type-2 flows, validate against expanded individual owners rather
        # than the raw Commercial License partners (which include corporate entities)
        # ============================================================================
        logger.debug(f"\n STAGE 2: Partner EID Verification")
        logger.debug(f"{'='*80}")

        # ── Determine validation list: use expanded members if available ──────────
        email = user_data.get("email", "")
        effective_partners = []  # [{name, nationality}] for EID cross-check

        # Try to load expanded members from member_progress.json (Type-2 flow)
        member_progress_path = None
        try:
            from app.services.document_helpers import get_documents_base_path, get_document_ref_no
            _mp_ref = get_document_ref_no(email)
            _mp_primary = get_documents_base_path() / _mp_ref / "member_progress.json"
            if _mp_primary.exists():
                member_progress_path = _mp_primary
        except Exception:
            _mp_ref = email
        if not member_progress_path:
            # Legacy email-based fallback
            for base in [Path("/app/backend/documents/id"), Path("backend/documents/id")]:
                candidate = base / email / "member_progress.json"
                if candidate.exists():
                    member_progress_path = candidate
                    break

        if member_progress_path:
            try:
                import json as _json
                mp = _json.loads(member_progress_path.read_text(encoding="utf-8"))
                expanded = mp.get("expanded_members", [])
                if expanded:
                    logger.debug(f"  [TYPE-2] Using {len(expanded)} expanded owners from member_progress.json")
                    for owner in expanded:
                        effective_partners.append({
                            "name": owner.get("name", ""),
                            "nationality": "",   # CoI may not have nationality; EID validation will cover it
                            "effective_percentage": owner.get("effective_percentage", 0),
                            "is_ubo": owner.get("is_ubo", False),
                        })
            except Exception as _mp_err:
                logger.debug(f"  [WARN] Could not load member_progress: {_mp_err}")

        # Fall back to raw Commercial License partners
        if not effective_partners:
            raw_partners = commercial_data.get("partners", [])
            for p in raw_partners:
                effective_partners.append({
                    "name": p.get("name_english", "").strip(),
                    "nationality": p.get("nationality_english", "").strip(),
                    "effective_percentage": float(str(p.get("share_percentage", 0)).replace("%","").strip() or 0),
                    "is_ubo": False,
                })

        if not effective_partners:
            logger.debug(f"  Warning: No partners/owners found for identity verification")
        else:
            logger.debug(f"  Found {len(effective_partners)} effective owner(s) for identity verification")

            # Get all identity documents (EID or Passport) for members
            member_eids = self._load_member_eids(email)
            logger.debug(f"  Found {len(member_eids)} member identity document(s) submitted")

            # Validate partner count
            if len(effective_partners) != len(member_eids):
                mismatch = (
                    f"Owner count mismatch: {len(effective_partners)} effective owner(s) "
                    f"but {len(member_eids)} identity document(s) submitted (Emirates ID or Passport)"
                )
                self.mismatches.append(mismatch)
                logger.debug(f"  MISMATCH: {mismatch}")
            else:
                logger.debug(f"  Owner count matches: {len(effective_partners)}")

            # Validate each effective owner's identity document (EID or Passport)
            for idx, owner in enumerate(effective_partners, 1):
                owner_name = owner["name"]
                owner_nationality = owner.get("nationality", "")

                logger.debug(f"\n  Validating Owner #{idx}: {owner_name}")

                # Find matching identity doc by fuzzy name match
                matching_eid = None
                matched_folder = None
                for member_name, eid_data in member_eids.items():
                    eid_name = (eid_data.get("Name") or eid_data.get("name") or "").strip()
                    if self._fuzzy_name_match(owner_name, eid_name):
                        matching_eid = eid_data
                        matched_folder = member_name
                        doc_src = "Passport" if eid_data.get("_source") == "passport" else "EID"
                        logger.debug(f"    Matched {doc_src} for folder: {member_name}")
                        break

                if not matching_eid:
                    mismatch = f"No matching identity document (Emirates ID or Passport) found for owner: {owner_name}"
                    self.mismatches.append(mismatch)
                    logger.debug(f"    MISMATCH: {mismatch}")
                    continue

                # Validate nationality only when it was present in source document
                if owner_nationality:
                    eid_nationality = (matching_eid.get("Nationality") or matching_eid.get("nationality") or "").strip()
                    if eid_nationality and not self._fuzzy_name_match(owner_nationality, eid_nationality):
                        id_label = "Passport" if matching_eid.get("_source") == "passport" else "EID"
                        mismatch = (
                            f"Nationality mismatch for {owner_name}: "
                            f"Source ('{owner_nationality}') vs {id_label} ('{eid_nationality}')"
                        )
                        self.mismatches.append(mismatch)
                        logger.debug(f"    MISMATCH: {mismatch}")
                    else:
                        logger.debug(f"    Nationality OK: {eid_nationality or '(not checked)'}")
        
        # ============================================================================
        # FINAL RESULT
        # ============================================================================
        passed = len(self.mismatches) == 0
        message = "All cross-validation checks passed for Corporate Partnership" if passed else f"Cross-validation failed: {len(self.mismatches)} issue(s) found"
        (logger.info if passed else logger.warning)(f"[CROSS-VALIDATION] Corporate Partnership: {message}")
        logger.debug(f"{'='*80}\n")
        
        return self._build_result(passed, message)
    
    # ============================================================================
    # HELPER METHODS
    # ============================================================================
    
    def _load_member_eids(self, email: str) -> dict:
        """
        Load all member identity documents (EID or Passport) for Corporate Partnership.
        Either document type satisfies the identity requirement for a member.

        Returns:
            {
                "member_name_1": {...identity_data...},   # EID fields, or passport-mapped fields
                "member_name_2": {...identity_data...}
            }
        """
        member_eids = {}

        user_docs_dir = _resolve_user_docs_dir(email)

        if not user_docs_dir:
            return member_eids

        EID_TYPES = {"eid", "emirates id", "emirates_id", "identity card"}
        PASSPORT_TYPES = {"passport", "travel document", "travel_document", "intl_id"}

        # Look for member directories
        for item in user_docs_dir.iterdir():
            if not item.is_dir():
                continue

            # Skip already-loaded member (EID takes priority over passport)
            for sub_item in item.iterdir():
                if not sub_item.is_dir():
                    continue

                output_json = sub_item / "output.json"
                if not output_json.exists():
                    continue

                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    doc_type = data.get("document_type", "").lower().strip()
                    is_valid = data.get("is_valid", False)

                    if not is_valid:
                        continue

                    extracted = data.get("extracted_fields") or data.get("extracted_data")
                    if not extracted:
                        continue

                    if doc_type in EID_TYPES:
                        # EID: use directly; overrides any previously found passport
                        member_eids[item.name] = extracted
                        logger.debug(f"  Loaded EID for member: {item.name}")

                    elif doc_type in PASSPORT_TYPES and item.name not in member_eids:
                        # Passport: map to EID-compatible field names so existing
                        # name-matching logic works without changes
                        given_names = extracted.get("given_names", "")
                        surname = extracted.get("surname", "")
                        full_name = f"{given_names} {surname}".strip() or extracted.get("full_name", "")
                        passport_alias = {
                            "Name": full_name,
                            "name": full_name,
                            "Nationality": extracted.get("nationality") or extracted.get("Nationality", ""),
                            "nationality": extracted.get("nationality", ""),
                            "Date of Birth": extracted.get("date_of_birth") or extracted.get("Date of Birth", ""),
                            "date_of_birth": extracted.get("date_of_birth", ""),
                            "Sex": extracted.get("sex") or extracted.get("Sex", ""),
                            "sex": extracted.get("sex", ""),
                            "Expiry Date": extracted.get("date_of_expiry") or extracted.get("Date of Expiry", ""),
                            "expiry_date": extracted.get("date_of_expiry", ""),
                            "passport_number": extracted.get("passport_number", ""),
                            "_source": "passport",
                        }
                        member_eids[item.name] = passport_alias
                        logger.debug(f"  Loaded Passport for member: {item.name} (Name={full_name!r})")

                except Exception as e:
                    logger.debug(f"   Error reading {output_json}: {e}")

        return member_eids
    
    def _load_all_documents(self, email: str) -> dict:
        """Load all document output.json files with complete structure"""
        logger.debug(f"\nLoading documents for: {email}")
        
        user_docs_dir = _resolve_user_docs_dir(email)

        if not user_docs_dir:
            logger.warning(f"[CROSS-VALIDATION] documents directory not found for {email}")
            return {}
        
        logger.debug(f"Found directory: {user_docs_dir}")
        
        documents = {}
        
        try:
            for item in user_docs_dir.iterdir():
                if not item.is_dir():
                    continue
                
                if item.name in ["member_progress.json", "members"]:
                    continue
                
                output_json = item / "output.json"
                
                if not output_json.exists():
                    continue
                
                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    doc_type = data.get("document_type", "").lower().strip()
                    is_valid = data.get("is_valid", False)
                    
                    if not is_valid:
                        continue
                    
                    # Normalize document type
                    if doc_type in ["memorandum", "memorandum of association"]:
                        doc_type = "moa"
                    elif doc_type in ["tenancy", "tenancy contract", "ejari"]:
                        doc_type = "ejari"
                    elif doc_type in ["trade license", "trade_license", "commercial"]:
                        doc_type = "commercial"
                    elif doc_type in ["emirates id", "emirates_id", "identity card", "eid"]:
                        doc_type = "eid"
                    
                    extracted = data.get("extracted_fields") or data.get("extracted_data")
                    
                    if not extracted or not isinstance(extracted, dict):
                        continue
                    
                    # Store complete structure for commercial (includes partners)
                    if doc_type == "commercial":
                        documents[doc_type] = extracted
                        logger.debug(f"  Loaded {doc_type}: Full structure")
                    
                    # For ejari/moa, store English fields
                    elif doc_type in ["ejari", "moa"]:
                        english_data = extracted.get("english", {})
                        if english_data:
                            documents[doc_type] = english_data
                            logger.debug(f"  Loaded {doc_type}: {len(english_data)} fields")
                        else:
                            # MOA might not have nested english structure
                            documents[doc_type] = extracted
                            logger.debug(f"  Loaded {doc_type}: {len(extracted)} fields")
                    
                    # For EID, use direct fields
                    elif doc_type == "eid":
                        documents[doc_type] = extracted
                        logger.debug(f"  Loaded {doc_type}: {len(extracted)} fields")

                    # For Passport, load and also map to eid-compatible fields
                    elif doc_type in ["passport", "travel document", "travel_document", "intl_id"]:
                        documents["passport"] = extracted
                        logger.debug(f"  Loaded passport: {len(extracted)} fields")
                        # Create an EID-compatible alias so cross-validators can use
                        # either document transparently
                        if "eid" not in documents:
                            given_names = extracted.get("given_names", "")
                            surname = extracted.get("surname", "")
                            full_name = f"{given_names} {surname}".strip() or extracted.get("full_name", "")
                            documents["eid"] = {
                                "Name": full_name,
                                "name": full_name,
                                "Nationality": extracted.get("nationality") or extracted.get("Nationality", ""),
                                "nationality": extracted.get("nationality", ""),
                                "Date of Birth": extracted.get("date_of_birth") or extracted.get("Date of Birth", ""),
                                "date_of_birth": extracted.get("date_of_birth", ""),
                                "Sex": extracted.get("sex") or extracted.get("Sex", ""),
                                "sex": extracted.get("sex", ""),
                                "Issuing Date": extracted.get("date_of_issue") or extracted.get("Date of Issue", ""),
                                "issuing_date": extracted.get("date_of_issue", ""),
                                "Expiry Date": extracted.get("date_of_expiry") or extracted.get("Date of Expiry", ""),
                                "expiry_date": extracted.get("date_of_expiry", ""),
                                # Keep passport-specific fields too
                                "passport_number": extracted.get("passport_number", ""),
                                "_source": "passport",  # marker so we know this came from passport
                            }
                            logger.debug(f"  Mapped passport → eid alias (Name={full_name!r})")
                
                except Exception as e:
                    logger.debug(f"  Error reading {output_json}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"[CROSS-VALIDATION] error scanning directory: {e}", exc_info=True)
        
        logger.debug(f"\nTotal documents loaded: {len(documents)}")
        if documents:
            logger.debug(f"Document types: {list(documents.keys())}")
        
        return documents
    
    def _fuzzy_name_match(self, name1: str, name2: str, threshold: Optional[float] = None) -> bool:
        """
        Fuzzy name matching to handle spelling variations
        
        Args:
            name1: First name
            name2: Second name
            threshold: Similarity threshold (uses config if not provided)
        
        Returns:
            True if names match
        """
        if not name1 or not name2:
            return False
        
        # Use configured threshold if not provided
        if threshold is None:
            threshold = self.config["fuzzy_threshold"]
        
        # Normalize names
        name1_norm = self._normalize_name(name1)
        name2_norm = self._normalize_name(name2)
        
        # Exact match
        if name1_norm == name2_norm:
            return True

        # Subset match: one name is fully contained in the other
        # Handles cases like "VARSHA BALAJI BALAJI" vs "VARSHA BALAJI" (duplicate surname)
        name1_parts = set(name1_norm.split())
        name2_parts = set(name2_norm.split())
        if name1_parts.issubset(name2_parts) or name2_parts.issubset(name1_parts):
            if self.config["debug_logging"]:
                logger.debug(f"    Name subset match: ({name1_norm} vs {name2_norm})")
            return True

        # Calculate similarity
        similarity = SequenceMatcher(None, name1_norm, name2_norm).ratio()

        if self.config["debug_logging"]:
            logger.debug(f"    Name similarity: {similarity:.2%} ({name1_norm} vs {name2_norm})")

        return similarity >= threshold
    
    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison"""
        name = name.lower()
        name = re.sub(r'\s+', ' ', name)
        name = re.sub(r'[^\w\s]', '', name)
        return name.strip()
    
    def _date_match(self, date1: str, date2: str) -> bool:
        """Match dates with flexible format handling"""
        if not date1 or not date2:
            return False
        
        parsed_date1 = self._parse_date(date1)
        parsed_date2 = self._parse_date(date2)
        
        if not parsed_date1 or not parsed_date2:
            return self._normalize_name(date1) == self._normalize_name(date2)
        
        return parsed_date1 == parsed_date2
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string with multiple format support"""
        date_formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d.%m.%Y",
            "%d %B %Y",
            "%d %b %Y",
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        
        return None
    
    def _build_result(self, passed: bool, message: str) -> dict:
        """Build validation result dictionary"""
        return {
            "passed": passed,
            "mismatches": self.mismatches,
            "validation_details": self.validation_details,
            "message": message
        }
        
    def save_validation_result(self, email: str, result: dict) -> bool:
        """Save validation result as JSON in user's folder"""
        try:
            # Determine save path (ref_no-based, with email fallback)
            user_docs_dir = _resolve_user_docs_dir(email)

            if not user_docs_dir:
                from app.services.document_helpers import get_documents_base_path, get_document_ref_no
                _rno = get_document_ref_no(email)
                user_docs_dir = get_documents_base_path() / _rno
                user_docs_dir.mkdir(parents=True, exist_ok=True)
            
            validation_file = user_docs_dir / "validation_result.json"
            
            # Add metadata
            result_with_meta = {
                **result,
                "email": email,
                "timestamp": datetime.now().isoformat(),
                "attempt_count": self._get_attempt_count(validation_file) + 1
            }
            
            with open(validation_file, 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"[INFO] Validation result saved: {validation_file}")
            return True
        
        except Exception as e:
            logger.error(f"[CROSS-VALIDATION] failed to save validation result: {e}", exc_info=True)
            return False

    def load_validation_result(self, email: str) -> Optional[dict]:
        """Load validation result from JSON"""
        try:
            user_docs_dir = _resolve_user_docs_dir(email)
            possible_paths = (
                [user_docs_dir / "validation_result.json"] if user_docs_dir else []
            ) + [
                Path(f"/app/backend/documents/id/{email}/validation_result.json"),
                Path(f"backend/documents/id/{email}/validation_result.json"),
            ]

            for path in possible_paths:
                if path and path.exists():
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
            
            return None
        
        except Exception as e:
            logger.error(f"[CROSS-VALIDATION] failed to load validation result: {e}", exc_info=True)
            return None

    def _get_attempt_count(self, validation_file: Path) -> int:
        """Get current attempt count"""
        if not validation_file.exists():
            return 0
        
        try:
            with open(validation_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("attempt_count", 0)
        except:
            return 0
        
    def _normalize_legal_type(self, legal_type: str) -> str:
        """
        Normalize legal type to a standard format for comparison
        
        Args:
            legal_type: Raw legal type string from document
        
        Returns:
            Normalized legal type string
        """
        if not legal_type:
            return ""
        
        # Convert to lowercase and remove extra whitespace
        normalized = legal_type.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove common punctuation
        normalized = normalized.replace("(", "").replace(")", "").replace("-", " ")
        normalized = normalized.replace(".", "").replace(",", "")
        
        # Check for known patterns
        if any(term in normalized for term in ["single owner", "one person", "sole"]):
            return "llc_single_owner"
        
        if any(term in normalized for term in ["multiple owner", "partnership", "partners", "multi"]):
            return "llc_multiple_owners"
        
        if any(term in normalized for term in ["limited liability", "llc", "l l c"]):
            return "llc_general"
        
        if any(term in normalized for term in ["establishment", "est"]):
            return "establishment"
        
        if any(term in normalized for term in ["branch", "foreign"]):
            return "branch"
        
        if any(term in normalized for term in ["freelance", "free lance"]):
            return "freelance"
        
        # Return cleaned version if no pattern matched
        return normalized


    def _legal_type_match(self, type1: str, type2: str) -> bool:
        """
        Compare two legal types with normalization and fuzzy matching
        
        Args:
            type1: First legal type string
            type2: Second legal type string
        
        Returns:
            True if legal types match
        """
        if not type1 or not type2:
            return False
        
        # Normalize both types
        norm1 = self._normalize_legal_type(type1)
        norm2 = self._normalize_legal_type(type2)
        
        logger.debug(f"    Legal type comparison:")
        logger.debug(f"      Raw 1: {type1}")
        logger.debug(f"      Raw 2: {type2}")
        logger.debug(f"      Normalized 1: {norm1}")
        logger.debug(f"      Normalized 2: {norm2}")
        
        # Exact match after normalization
        if norm1 == norm2:
            return True
        
        # Check if both are LLC variations (single owner)
        if norm1 == "llc_single_owner" and norm2 == "llc_single_owner":
            return True
        
        if norm1 == "llc_general" and norm2 == "llc_single_owner":
            return True
        
        if norm1 == "llc_single_owner" and norm2 == "llc_general":
            return True
        
        # Check if both are LLC variations (multiple owners)
        if norm1 == "llc_multiple_owners" and norm2 == "llc_multiple_owners":
            return True
        
        if norm1 == "llc_general" and norm2 == "llc_multiple_owners":
            return True
        
        if norm1 == "llc_multiple_owners" and norm2 == "llc_general":
            return True
        
        # Fuzzy string matching as fallback
        similarity = SequenceMatcher(None, norm1, norm2).ratio()
        
        logger.debug(f"      Similarity: {similarity:.2%}")
        
        return similarity >= 0.75  # Lower threshold for legal types