# backend/app/services/cross_validator.py

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class CrossValidator:
    """Cross-validation service for document verification"""
    
    def __init__(self):
        self.mismatches = []
        self.validation_details = {}
        
        # Load configuration from environment
        self.config = {
            "savings_enabled": os.getenv("CROSS_VALIDATION_SAVINGS", "true").lower() == "true",
            "corporate_single_enabled": os.getenv("CROSS_VALIDATION_CORPORATE_SINGLE", "true").lower() == "true",
            "corporate_partnership_enabled": os.getenv("CROSS_VALIDATION_CORPORATE_PARTNERSHIP", "false").lower() == "true",
            "fuzzy_threshold": float(os.getenv("FUZZY_MATCH_THRESHOLD", "0.85")),
            "debug_logging": os.getenv("CROSS_VALIDATION_DEBUG_LOGGING", "true").lower() == "true",
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
            print(f"\n🔧 [CONFIG] Cross-Validation Settings:")
            print(f"   - Savings: {'✅ Enabled' if self.config['savings_enabled'] else '❌ Disabled'}")
            print(f"   - Corporate Single: {'✅ Enabled' if self.config['corporate_single_enabled'] else '❌ Disabled'}")
            print(f"   - Corporate Partnership: {'✅ Enabled' if self.config['corporate_partnership_enabled'] else '❌ Disabled'}")
            print(f"   - Fuzzy Match Threshold: {self.config['fuzzy_threshold']:.0%}\n")
    
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
        
        print(f"\n{'='*80}")
        print(f"🔍 [CROSS-VALIDATION] Starting validation for {email}")
        print(f"   Account Type: {account_type}")
        print(f"   Ownership Type: {ownership_type}")
        print(f"{'='*80}")
        
        # ============================================================================
        # CHECK IF VALIDATION IS ENABLED FOR THIS ACCOUNT TYPE
        # ============================================================================
        
        # Savings Account
        if account_type == "Savings":
            if not self.config["savings_enabled"]:
                print(f"⏭️  [SKIPPED] Savings account validation is disabled in .env")
                return {
                    "passed": True,
                    "mismatches": [],
                    "validation_details": {},
                    "message": "Cross-validation skipped: Disabled for Savings accounts",
                    "skipped": True,
                    "skip_reason": "CROSS_VALIDATION_SAVINGS=false"
                }
        
        # Corporate Single Owner
        elif account_type == "Corporate" and ownership_type == "Single Owner":
            if not self.config["corporate_single_enabled"]:
                print(f"⏭️  [SKIPPED] Corporate Single Owner validation is disabled in .env")
                return {
                    "passed": True,
                    "mismatches": [],
                    "validation_details": {},
                    "message": "Cross-validation skipped: Disabled for Corporate Single Owner",
                    "skipped": True,
                    "skip_reason": "CROSS_VALIDATION_CORPORATE_SINGLE=false"
                }
        
        # Corporate Partnership
        elif account_type == "Corporate" and ownership_type in ["Partnership", "Multiple Owners"]:
            if not self.config["corporate_partnership_enabled"]:
                print(f"⏭️  [SKIPPED] Corporate Partnership validation is disabled in .env")
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
        
        if account_type == "Savings":
            result = self._validate_savings_account(user_data, documents)
        
        elif account_type == "Corporate" and ownership_type == "Single Owner":
            result = self._validate_corporate_single_owner(user_data, documents)
        
        elif account_type == "Corporate" and ownership_type in ["Partnership", "Multiple Owners"]:
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
    # SAVINGS ACCOUNT VALIDATION
    # ============================================================================
    
    def _validate_savings_account(self, user_data: dict, documents: dict) -> dict:
        """
        Validate Savings Account (User Registration + EID + Ejari)
        
        Validation Rules:
        - Full Name: user_registration.name = EID.Name
        - DOB: user_registration.dob = EID.Date of Birth
        - Business Name: Should be NULL or match Ejari.tenant_company
        """
        print("\n" + "="*80)
        print("🔍 SAVINGS ACCOUNT CROSS-VALIDATION")
        print("="*80)
        
        eid_data = documents.get("eid", {})
        ejari_data = documents.get("ejari", {})
        
        if not eid_data:
            self.mismatches.append("Emirates ID (EID) document not found")
        
        if not ejari_data:
            self.mismatches.append("Ejari (Tenancy Contract) document not found")
        
        if not eid_data or not ejari_data:
            return self._build_result(False, "Missing required documents")
        
        user_name = user_data.get("name", "").strip()
        user_dob = user_data.get("dob", "").strip()
        user_business_name = user_data.get("business_name", "").strip()
        
        eid_name = (eid_data.get("Name") or eid_data.get("name") or "").strip()
        eid_dob = (eid_data.get("Date of Birth") or eid_data.get("date_of_birth") or "").strip()
        ejari_tenant_company = ejari_data.get("tenant_company", "").strip()
        
        print(f"\n📋 Extracted Data:")
        print(f"  User Registration Name: {user_name}")
        print(f"  EID Name: {eid_name}")
        print(f"  Ejari Tenant Company: {ejari_tenant_company}")
        print(f"  User DOB: {user_dob}")
        print(f"  EID DOB: {eid_dob}")
        print(f"  User Business Name: {user_business_name}")
        
        # Validation 1: Full Name
        print(f"\n✓ Validating Full Name...")
        name_match = self._fuzzy_name_match(user_name, eid_name)
        
        if not name_match:
            mismatch = f"Name mismatch between User Registration ('{user_name}') and EID ('{eid_name}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ User Registration ↔ EID: Match")
        
        self.validation_details["name_validation"] = {
            "user_registration_name": user_name,
            "eid_name": eid_name,
            "match": name_match
        }
        
        # Validation 2: Date of Birth
        print(f"\n✓ Validating Date of Birth...")
        dob_match = self._date_match(user_dob, eid_dob)
        
        if not dob_match:
            mismatch = f"Date of Birth mismatch: User Registration ('{user_dob}') vs EID ('{eid_dob}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ DOB Match: {user_dob}")
        
        self.validation_details["dob_validation"] = {
            "user_registration_dob": user_dob,
            "eid_dob": eid_dob,
            "match": dob_match
        }
        
        # Validation 3: Business Name
        print(f"\n✓ Validating Business Name...")
        business_name_valid = True
        
        if user_business_name:
            if ejari_tenant_company:
                business_match = self._fuzzy_name_match(user_business_name, ejari_tenant_company)
                if not business_match:
                    mismatch = f"Business name mismatch: Registration ('{user_business_name}') vs Ejari ('{ejari_tenant_company}')"
                    self.mismatches.append(mismatch)
                    business_name_valid = False
                    print(f"  ❌ {mismatch}")
                else:
                    print(f"  ✅ Business Name matches Ejari Tenant Company")
            else:
                print(f"  ⚠️  Warning: User has business name but Ejari shows no tenant company")
        else:
            print(f"  ✅ No business name declared (valid for Savings Account)")
        
        self.validation_details["business_name_validation"] = {
            "user_business_name": user_business_name,
            "ejari_tenant_company": ejari_tenant_company,
            "valid": business_name_valid
        }
        
        passed = len(self.mismatches) == 0
        message = "✅ All cross-validation checks passed for Savings Account" if passed else f"❌ Cross-validation failed: {len(self.mismatches)} issue(s) found"
        
        print(f"\n{'='*80}")
        print(f"RESULT: {message}")
        print(f"{'='*80}\n")
        
        return self._build_result(passed, message)
    
    # ============================================================================
    # CORPORATE SINGLE OWNER VALIDATION
    # ============================================================================
    
    def _validate_corporate_single_owner(self, user_data: dict, documents: dict) -> dict:
        """
        Validate Corporate Single Owner (Commercial License + EID + Ejari)
        
        Validation Rules:
        - Company Name: Commercial.company_name_english = Ejari.tenant_company
        - Owner/Manager Name: Commercial.owner.name_english = EID.Name
        - Nationality: Commercial.owner.nationality_english = EID.Nationality
        """
        print("\n" + "="*80)
        print("🔍 CORPORATE SINGLE OWNER CROSS-VALIDATION")
        print("="*80)
        
        commercial_data = documents.get("commercial", {})
        eid_data = documents.get("eid", {})
        ejari_data = documents.get("ejari", {})
        
        if not commercial_data:
            self.mismatches.append("Commercial License document not found")
        if not eid_data:
            self.mismatches.append("Emirates ID (EID) document not found")
        if not ejari_data:
            self.mismatches.append("Ejari (Tenancy Contract) document not found")
        
        if not commercial_data or not eid_data or not ejari_data:
            return self._build_result(False, "Missing required documents")
        
        commercial_english = commercial_data.get("english", {})
        commercial_owner = commercial_data.get("owner", {})
        
        commercial_company_name = commercial_english.get("company_name_english", "").strip()
        owner_name = commercial_owner.get("name_english", "").strip()
        owner_nationality = commercial_owner.get("nationality_english", "").strip()
        
        ejari_tenant_company = ejari_data.get("tenant_company", "").strip()
        eid_name = (eid_data.get("Name") or eid_data.get("name") or "").strip()
        eid_nationality = (eid_data.get("Nationality") or eid_data.get("nationality") or "").strip()
        
        print(f"\n📋 Extracted Data:")
        print(f"  Commercial Company Name: {commercial_company_name}")
        print(f"  Ejari Tenant Company: {ejari_tenant_company}")
        print(f"  Commercial Owner Name: {owner_name}")
        print(f"  EID Name: {eid_name}")
        print(f"  Commercial Owner Nationality: {owner_nationality}")
        print(f"  EID Nationality: {eid_nationality}")
        
        # Validation 1: Company Name
        print(f"\n✓ Validating Company Name...")
        company_match = self._fuzzy_name_match(commercial_company_name, ejari_tenant_company)
        
        if not company_match:
            mismatch = f"Company name mismatch: Commercial License ('{commercial_company_name}') vs Ejari ('{ejari_tenant_company}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ Company Name Match")
        
        self.validation_details["company_name_validation"] = {
            "commercial_company_name": commercial_company_name,
            "ejari_tenant_company": ejari_tenant_company,
            "match": company_match
        }
        
        # Validation 2: Owner Name
        print(f"\n✓ Validating Owner Name...")
        owner_name_match = self._fuzzy_name_match(owner_name, eid_name)
        
        if not owner_name_match:
            mismatch = f"Owner name mismatch: Commercial License ('{owner_name}') vs EID ('{eid_name}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ Owner Name Match")
        
        self.validation_details["owner_name_validation"] = {
            "commercial_owner_name": owner_name,
            "eid_name": eid_name,
            "match": owner_name_match
        }
        
        # Validation 3: Nationality
        print(f"\n✓ Validating Nationality...")
        nationality_match = self._fuzzy_name_match(owner_nationality, eid_nationality)
        
        if not nationality_match:
            mismatch = f"Nationality mismatch: Commercial License ('{owner_nationality}') vs EID ('{eid_nationality}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ Nationality Match")
        
        self.validation_details["nationality_validation"] = {
            "commercial_nationality": owner_nationality,
            "eid_nationality": eid_nationality,
            "match": nationality_match
        }
        
        passed = len(self.mismatches) == 0
        message = "✅ All cross-validation checks passed for Corporate Single Owner" if passed else f"❌ Cross-validation failed: {len(self.mismatches)} issue(s) found"
        
        print(f"\n{'='*80}")
        print(f"RESULT: {message}")
        print(f"{'='*80}\n")
        
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
        print("\n" + "="*80)
        print("🔍 CORPORATE PARTNERSHIP CROSS-VALIDATION")
        print("="*80)
        
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
        print(f"\n📋 STAGE 1: Company Identity Verification")
        print(f"{'='*80}")
        
        # Extract company names
        commercial_company = commercial_english.get("company_name_english", "").strip()
        moa_company = moa_english.get("company_name", "").strip()
        
        print(f"\n✓ Validating Company Name...")
        print(f"  Commercial: {commercial_company}")
        print(f"  MOA: {moa_company}")
        
        company_match = self._fuzzy_name_match(commercial_company, moa_company)
        
        if not company_match:
            mismatch = f"Company name mismatch: Commercial License ('{commercial_company}') vs MOA ('{moa_company}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ Company Name Match")
        
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
        
        print(f"\n✓ Validating Legal Type...")
        print(f"  Commercial: {commercial_legal_type}")
        print(f"  MOA: {moa_company_type}")
        
        # ✅ USE NEW LEGAL TYPE MATCHING (instead of fuzzy_name_match)
        legal_type_match = self._legal_type_match(commercial_legal_type, moa_company_type)
        
        if not legal_type_match:
            mismatch = f"Legal type mismatch: Commercial ('{commercial_legal_type}') vs MOA ('{moa_company_type}')"
            self.mismatches.append(mismatch)
            print(f"  ❌ {mismatch}")
        else:
            print(f"  ✅ Legal Type Match")
        
        self.validation_details["legal_type_validation"] = {
            "commercial_legal_type": commercial_legal_type,
            "moa_company_type": moa_company_type,
            "match": legal_type_match
        }
        
        # ============================================================================
        # STAGE 1: BUSINESS ACTIVITY VERIFICATION
        # ============================================================================
        print(f"\n📋 Business Activity Verification")
        print(f"{'='*80}")
        
        activities_to_check = ["activity_1", "activity_2", "activity_3"]
        
        for activity_key in activities_to_check:
            commercial_activity = commercial_english.get(activity_key, "").strip()
            moa_activity = moa_english.get(activity_key, "").strip()
            
            if commercial_activity and moa_activity:
                print(f"\n✓ Validating {activity_key.upper()}...")
                print(f"  Commercial: {commercial_activity}")
                print(f"  MOA: {moa_activity}")
                
                activity_match = self._fuzzy_name_match(commercial_activity, moa_activity)
                
                if not activity_match:
                    mismatch = f"{activity_key} mismatch: Commercial ('{commercial_activity}') vs MOA ('{moa_activity}')"
                    self.mismatches.append(mismatch)
                    print(f"  ❌ {mismatch}")
                else:
                    print(f"  ✅ {activity_key.upper()} Match")
        
        # ============================================================================
        # STAGE 2: PARTNER EID VERIFICATION
        # ============================================================================
        print(f"\n📋 STAGE 2: Partner EID Verification")
        print(f"{'='*80}")
        
        # Get partners from commercial license
        partners = commercial_data.get("partners", [])
        
        if not partners:
            print(f"⚠️  Warning: No partners found in Commercial License")
        else:
            print(f"\n👥 Found {len(partners)} partner(s) in Commercial License")
            
            # Get all EID documents (for members)
            member_eids = self._load_member_eids(user_data.get("email", ""))
            
            print(f"📄 Found {len(member_eids)} member EID(s) submitted")
            
            # Validate partner count
            if len(partners) != len(member_eids):
                mismatch = f"Partner count mismatch: Commercial License has {len(partners)} partner(s) but {len(member_eids)} EID(s) submitted"
                self.mismatches.append(mismatch)
                print(f"  ❌ {mismatch}")
            else:
                print(f"  ✅ Partner count matches: {len(partners)} partner(s)")
            
            # Validate each partner's EID
            for idx, partner in enumerate(partners, 1):
                partner_name = partner.get("name_english", "").strip()
                partner_nationality = partner.get("nationality_english", "").strip()
                
                print(f"\n✓ Validating Partner #{idx}: {partner_name}")
                
                # Find matching EID
                matching_eid = None
                for member_name, eid_data in member_eids.items():
                    eid_name = (eid_data.get("Name") or eid_data.get("name") or "").strip()
                    if self._fuzzy_name_match(partner_name, eid_name):
                        matching_eid = eid_data
                        print(f"  ✅ Found matching EID for {member_name}")
                        break
                
                if not matching_eid:
                    mismatch = f"No matching EID found for partner: {partner_name}"
                    self.mismatches.append(mismatch)
                    print(f"  ❌ {mismatch}")
                    continue
                
                # Validate nationality
                eid_nationality = (matching_eid.get("Nationality") or matching_eid.get("nationality") or "").strip()
                
                if not self._fuzzy_name_match(partner_nationality, eid_nationality):
                    mismatch = f"Nationality mismatch for {partner_name}: Commercial ('{partner_nationality}') vs EID ('{eid_nationality}')"
                    self.mismatches.append(mismatch)
                    print(f"  ❌ {mismatch}")
                else:
                    print(f"  ✅ Nationality matches: {eid_nationality}")
        
        # ============================================================================
        # FINAL RESULT
        # ============================================================================
        passed = len(self.mismatches) == 0
        message = "✅ All cross-validation checks passed for Corporate Partnership" if passed else f"❌ Cross-validation failed: {len(self.mismatches)} issue(s) found"
        
        print(f"\n{'='*80}")
        print(f"RESULT: {message}")
        print(f"{'='*80}\n")
        
        return self._build_result(passed, message)
    
    # ============================================================================
    # HELPER METHODS
    # ============================================================================
    
    def _load_member_eids(self, email: str) -> dict:
        """
        Load all member EID documents for Corporate Partnership
        
        Returns:
            {
                "member_name_1": {...eid_data...},
                "member_name_2": {...eid_data...}
            }
        """
        member_eids = {}
        
        possible_paths = [
            Path(f"/app/backend/documents/id/{email}"),
            Path(f"backend/documents/id/{email}"),
            Path(f"documents/id/{email}"),
        ]
        
        user_docs_dir = None
        for path in possible_paths:
            if path.exists():
                user_docs_dir = path
                break
        
        if not user_docs_dir:
            return member_eids
        
        # Look for member directories
        for item in user_docs_dir.iterdir():
            if not item.is_dir():
                continue
            
            # Check if this is a member directory (has EID subdirectory)
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
                    
                    if doc_type in ["eid", "emirates id", "emirates_id", "identity card"] and is_valid:
                        extracted = data.get("extracted_fields") or data.get("extracted_data")
                        if extracted:
                            member_eids[item.name] = extracted
                            print(f"  ✅ Loaded EID for member: {item.name}")
                
                except Exception as e:
                    print(f"  ⚠️  Error reading {output_json}: {e}")
        
        return member_eids
    
    def _load_all_documents(self, email: str) -> dict:
        """Load all document output.json files with complete structure"""
        print(f"\n📂 Loading documents for: {email}")
        
        possible_paths = [
            Path(f"/app/backend/documents/id/{email}"),
            Path(f"backend/documents/id/{email}"),
            Path(f"documents/id/{email}"),
        ]
        
        user_docs_dir = None
        for path in possible_paths:
            if path.exists():
                user_docs_dir = path
                break
        
        if not user_docs_dir:
            print(f"❌ Documents directory not found for {email}")
            return {}
        
        print(f"✅ Found directory: {user_docs_dir}")
        
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
                        print(f"  ✅ Loaded {doc_type}: Full structure")
                    
                    # For ejari/moa, store English fields
                    elif doc_type in ["ejari", "moa"]:
                        english_data = extracted.get("english", {})
                        if english_data:
                            documents[doc_type] = english_data
                            print(f"  ✅ Loaded {doc_type}: {len(english_data)} fields")
                        else:
                            # MOA might not have nested english structure
                            documents[doc_type] = extracted
                            print(f"  ✅ Loaded {doc_type}: {len(extracted)} fields")
                    
                    # For EID, use direct fields
                    elif doc_type == "eid":
                        documents[doc_type] = extracted
                        print(f"  ✅ Loaded {doc_type}: {len(extracted)} fields")
                
                except Exception as e:
                    print(f"  ❌ Error reading {output_json}: {e}")
                    continue
        
        except Exception as e:
            print(f"❌ Error scanning directory: {e}")
        
        print(f"\n📊 Total documents loaded: {len(documents)}")
        if documents:
            print(f"📋 Document types: {list(documents.keys())}")
        
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
        
        # Calculate similarity
        similarity = SequenceMatcher(None, name1_norm, name2_norm).ratio()
        
        if self.config["debug_logging"]:
            print(f"    Name similarity: {similarity:.2%} ({name1_norm} vs {name2_norm})")
        
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
            # Determine save path
            possible_paths = [
                Path(f"/app/backend/documents/id/{email}"),
                Path(f"backend/documents/id/{email}"),
            ]
            
            user_docs_dir = None
            for path in possible_paths:
                if path.exists():
                    user_docs_dir = path
                    break
            
            if not user_docs_dir:
                user_docs_dir = Path(f"backend/documents/id/{email}")
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
            
            print(f"[INFO] ✅ Validation result saved: {validation_file}")
            return True
        
        except Exception as e:
            print(f"[ERROR] Failed to save validation result: {e}")
            return False

    def load_validation_result(self, email: str) -> Optional[dict]:
        """Load validation result from JSON"""
        try:
            possible_paths = [
                Path(f"/app/backend/documents/id/{email}/validation_result.json"),
                Path(f"backend/documents/id/{email}/validation_result.json"),
            ]
            
            for path in possible_paths:
                if path.exists():
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
            
            return None
        
        except Exception as e:
            print(f"[ERROR] Failed to load validation result: {e}")
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
        
        print(f"    Legal type comparison:")
        print(f"      Raw 1: {type1}")
        print(f"      Raw 2: {type2}")
        print(f"      Normalized 1: {norm1}")
        print(f"      Normalized 2: {norm2}")
        
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
        
        print(f"      Similarity: {similarity:.2%}")
        
        return similarity >= 0.75  # Lower threshold for legal types