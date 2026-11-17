"""
test_growx_apis.py
------------------
Tests all 3 GrowX APIs exactly as the main integration does:
  - Reads user from Supabase (ref_no, password_hash, etc.)
  - Reads EID number from disk (output.json via rglob)
  - Reads Trade License data from disk (output.json via rglob)
  - Reads feeId from product_package.json on disk
  - Calls API 1 → extracts userId live → calls API 2 → calls API 3

Run:  python test_growx_apis.py
      python test_growx_apis.py someuser@email.com
"""

import json
import os
import sys
import requests
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────────
def load_env(env_path: str):
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root  = os.path.dirname(_script_dir)
# Prefer a local backend/.env if present, then fall back to the repo-root
# .env.docker (which is what actually has SUPABASE_URL / SUPABASE_API_KEY
# populated in this project — there is no backend/.env checked in).
load_env(os.path.join(_script_dir, ".env"))
load_env(os.path.join(_repo_root, ".env.docker"))

BASE_URL         = os.getenv("GROWX_BASE_URL", "https://demo.growx.global")
SUPABASE_URL     = os.getenv("SUPABASE_URL", "")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY", "")
# NOTE: crtdBy no longer comes from a static GROWX_CRTD_BY env var — API 3
# uses the real userId this script just got back from API 1 (growx_user_id,
# captured below), same as the production code now does.

# NOTE: DOCUMENTS_PATH used to be reimplemented here by hand ("documents/id"
# relative to this script), which silently drifted from the real app's path
# logic and pointed at the wrong folder for anyone running this outside
# Docker. Now delegates to the same get_documents_base_path() helper that
# growx_integration.py, chatupload_helpers.py, and ocr_service.py all use —
# guaranteed to always resolve to wherever documents were actually saved,
# regardless of DOCUMENTS_PATH being set or not.
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
from app.services.document_helpers import get_documents_base_path
DOCUMENTS_PATH = str(get_documents_base_path())

API1 = f"{BASE_URL}/growx/api/v1/customers/sme/users/pre-auth/self/onboard/create"
API2 = f"{BASE_URL}/growx/api/v1/customers/sme/users/set-password"
API3 = f"{BASE_URL}/growx/api/v1/customers/sme/pre-auth/create"

# NOTE: GrowX confirmed these are public endpoints — no Authorization/Bearer
# token required. (Previously a dead GROWX_BEARER_TOKEN sat here unused.)
HEADERS = {"accept": "*/*", "Content-Type": "application/json"}

TEST_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "m4@test.com"


# ============================================================================
# HELPERS — mirror growx_integration.py exactly
# ============================================================================

def fetch_supabase_user(email: str) -> dict:
    if not SUPABASE_URL or not SUPABASE_API_KEY:
        print("   ❌ SUPABASE_URL / SUPABASE_API_KEY not set in .env")
        return {}
    url = f"{SUPABASE_URL}/rest/v1/users"
    headers = {
        "apikey":        SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type":  "application/json",
    }
    params = {
        "email":   f"eq.{email}",
        "select":  "email,first_name,last_name,phone_number,password_hash,ref_no",
        "limit":   "1",
    }
    r = requests.get(url, headers=headers, params=params, timeout=10)
    rows = r.json()
    return rows[0] if rows else {}


def find_eid_data(ref_no: str) -> dict:
    """Mirror _find_eid_data() — rglob all output.json, return first EID."""
    base = Path(DOCUMENTS_PATH) / ref_no
    if not base.exists():
        return {}
    for json_file in base.rglob("output.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("document_type") == "eid":
                ef = data.get("extracted_fields", data.get("extracted_data", {}))
                if "english" in ef and isinstance(ef["english"], dict):
                    ef = ef["english"]
                return ef
        except Exception:
            continue
    return {}


def find_trade_license_data(ref_no: str) -> dict:
    """Mirror _find_trade_license_data() — latest commercial output.json."""
    base = Path(DOCUMENTS_PATH) / ref_no
    if not base.exists():
        return {}
    commercial_types = ("commercial", "trade_license", "commercial_license")
    candidates = []
    for json_file in base.rglob("output.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("document_type") in commercial_types:
                candidates.append((json_file.stat().st_mtime, data))
        except Exception:
            continue
    if not candidates:
        return {}
    candidates.sort(key=lambda x: x[0], reverse=True)
    extracted = candidates[0][1].get("extracted_fields", {})
    if "english" in extracted and isinstance(extracted["english"], dict):
        extracted = extracted["english"]
    return extracted


def find_package_data(ref_no: str) -> dict:
    """Read product_package.json from disk."""
    pkg_path = Path(DOCUMENTS_PATH) / ref_no / "product_package.json"
    if not pkg_path.exists():
        return {}
    try:
        return json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_fee_id(selected_package: str) -> int:
    return {"Essential": 1, "Plus": 2, "Advanced": 3}.get(selected_package, 1)


def print_result(name, url, status, response_text):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  URL    : {url}")
    print(f"  Status : {status}")
    try:
        print(f"  Response:\n{json.dumps(json.loads(response_text), indent=4)}")
    except Exception:
        print(f"  Response: {response_text[:500]}")
    print(f"{'='*60}")


# ============================================================================
# TEST RUNNER
# ============================================================================

def run():
    print(f"\n🚀 GrowX Integration Test")
    print(f"   Base URL : {BASE_URL}")
    print(f"   Email    : {TEST_EMAIL}\n")

    # ── 1. Fetch user from Supabase ───────────────────────────────────────
    print("▶ Step 1 — Fetching user from Supabase...")
    user = fetch_supabase_user(TEST_EMAIL)
    if not user:
        print("   ❌ User not found in Supabase. Stopping.")
        return

    ref_no        = user.get("ref_no", "")
    password_hash = user.get("password_hash", "")
    first_name    = user.get("first_name", "")
    last_name     = user.get("last_name", "")
    phone_number  = user.get("phone_number", "")

    print(f"   ✅ User found | ref_no: {ref_no}")
    print(f"   ✅ password_hash present: {bool(password_hash)} (first 15: {password_hash[:15]}...)")

    # ── 2. Read EID from disk ─────────────────────────────────────────────
    print("\n▶ Step 2 — Reading EID from disk...")
    eid = find_eid_data(ref_no)
    eid_number = eid.get("ID Number") or eid.get("id_number") or eid.get("emirates_id", "")
    if not eid_number:
        print("   ❌ EID number not found on disk. Stopping.")
        return
    print(f"   ✅ EID number: {eid_number}")

    # ── 3. Read Trade License from disk ──────────────────────────────────
    print("\n▶ Step 3 — Reading Trade License from disk...")
    tl = find_trade_license_data(ref_no)
    if not tl:
        print("   ❌ Trade License data not found on disk. API 3 will fail.")
    else:
        print(f"   ✅ Trade License found | license_number: {tl.get('license_number', 'MISSING')}")
        print(f"   ✅ Company: {tl.get('trade_name_english', tl.get('company_name_english', 'MISSING'))}")

    # ── 4. Read product package ───────────────────────────────────────────
    print("\n▶ Step 4 — Reading product package from disk...")
    pkg = find_package_data(ref_no)
    selected_package = pkg.get("selected_package", "Essential") if pkg else "Essential"
    fee_id = get_fee_id(selected_package)
    print(f"   {'✅' if pkg else '⚠ No package found — defaulting to'} package: {selected_package} → feeId: {fee_id}")

    # ── 5. API 1 — User Create ────────────────────────────────────────────
    api1_payload = {
        "emailId":            TEST_EMAIL,
        "userLoginId":        TEST_EMAIL,
        "firstName":          first_name,
        "lastName":           last_name,
        "mobileNo":           phone_number,
        "mobileCode":         "+971",
        "documentType":       "Emirates ID",
        "documentValue":      eid_number,
        "supportedCountries": "AE",
        "companyExistsFlag":  "N",
        "isWhatsappNotify":   "N",
    }

    print("\n▶ Calling API 1 — User Create...")
    growx_user_id = None
    try:
        r1 = requests.post(API1, headers=HEADERS, json=api1_payload, timeout=15)
        print_result("API 1 — User Create", API1, r1.status_code, r1.text)
        api1_data     = r1.json().get("data", {}) or {}
        growx_user_id = api1_data.get("userId") or r1.json().get("userId")
        if growx_user_id:
            print(f"   ✅ userId extracted live from API 1: {growx_user_id}")
        else:
            print("   ❌ No userId in API 1 response — API 2 skipped.")
            return
    except Exception as e:
        print(f"   ❌ API 1 failed: {e}")
        return

    # ── 6. API 2 — Set Password (userId from API 1, password_hash from Supabase) ──
    api2_payload = {
        "userLoginId": TEST_EMAIL,
        "emailId":     TEST_EMAIL,
        "userId":      growx_user_id,       # ← live from API 1
        "password":    password_hash,        # ← from Supabase
    }

    print("\n▶ Calling API 2 — Set Password...")
    print(f"   userId (from API 1): {growx_user_id}")
    print(f"   password_hash (from Supabase, first 15): {password_hash[:15]}...")
    growx_user_ref_id = None
    try:
        r2 = requests.post(API2, headers=HEADERS, json=api2_payload, timeout=15)
        print_result("API 2 — Set Password", API2, r2.status_code, r2.text)
        api2_body = r2.json()
        api2_data = api2_body.get("data", {}) or {}
        growx_user_ref_id = api2_data.get("userRefId")
        if api2_body.get("status") == 1:
            print(f"   ✅ API 2 succeeded | userRefId from GrowX: {growx_user_ref_id}")
        else:
            print(f"   ❌ API 2 failed | errorCode: {api2_body.get('errorCode')} | {api2_body.get('errorMessage')}")
    except Exception as e:
        print(f"   ❌ API 2 error: {e}")

    # ── 7. API 3 — SME Company Create ────────────────────────────────────
    if not tl:
        print("\n   ⚠ Skipping API 3 — no Trade License data.")
        return

    company_name          = tl.get("trade_name_english") or tl.get("company_name_english", "")
    mobile                = tl.get("mobile") or tl.get("phone") or phone_number
    address               = tl.get("license_address") or tl.get("commerce_address", "")
    po_box                = tl.get("po_box") or "00000"
    landline              = tl.get("fax") or "N/A"
    license_number        = tl.get("license_number", "")
    commercial_reg_number = tl.get("commercial_register_number", "")

    print(f"   ℹ license_number        : {license_number}")
    print(f"   ℹ commercial_reg_number : {commercial_reg_number}")
    print(f"   ℹ growx_user_ref_id     : {growx_user_ref_id}")

    # docRefId is this user's UUID (ref_no), generated at signup and unique
    # per user — matches growx_integration.py, which no longer uses a random
    # 9-digit number here.
    doc_ref_id = ref_no
    print(f"   ℹ docRefId (uuid no / ref_no): {doc_ref_id}")

    api3_payload = {
        "type":               "FO",
        "routingTypeCode":    "CB",
        "groupCompName":      company_name,
        "groupCompType":      "CORPORATE",
        "emailId":            TEST_EMAIL,
        "mobileCode":         "+971",
        "mobileNo":           mobile,
        "countryCode2":       "AE",
        "addressLine1":       address or "N/A",
        "addressLine2":       "",
        "addressLine3":       "",
        "addressLine4":       "UAE",
        "contactName":        company_name,
        "companyLandline":    landline,
        "companyPoBox":       po_box,
        "feeId":              fee_id,
        "supportedCountries": "AE",
        "crtdBy":             growx_user_id,      # ← real userId from API 1's live response above
        "docRefId":           doc_ref_id,         # ← this user's UUID (ref_no / uuid no)
        "tradeLicenseNumber": license_number,     # ← from OCR output.json
    }

    print("\n▶ Calling API 3 — SME Company Create...")
    print(f"   Full payload being sent:")
    print(json.dumps(api3_payload, indent=6))
    try:
        r3 = requests.post(API3, headers=HEADERS, json=api3_payload, timeout=15)
        print_result("API 3 — SME Company Create", API3, r3.status_code, r3.text)
        api3_body = r3.json()
        if api3_body.get("status") == 1:
            print("   ✅ API 3 succeeded")
        else:
            print(f"   ❌ API 3 failed | errorCode: {api3_body.get('errorCode')} | {api3_body.get('errorMessage')}")
    except Exception as e:
        print(f"   ❌ API 3 error: {e}")

    print("\n✅ Test run complete.\n")


if __name__ == "__main__":
    run()
