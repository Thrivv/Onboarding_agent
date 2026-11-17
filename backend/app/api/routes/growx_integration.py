# backend/app/api/routes/growx_integration.py
"""
GrowX Integration — Submit onboarding data to GrowX APIs.

Calls 3 GrowX APIs in sequence after user completes onboarding:
  1. POST /growx/api/v1/customers/sme/users/pre-auth/self/onboard/create  — user details
  2. POST /growx/api/v1/customers/sme/users/set-password                  — set password
  3. POST /growx/api/v1/customers/sme/pre-auth/create                     — SME company
"""

import json
import logging
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException

from app.services.supabase_client import supabase
from app.repositories.user_repository import UserRepository
from app.services.document_helpers import get_document_ref_no
from app.services.chatupload_helpers import user_docs_path
from app.services.product_package_service import get_package_selection, get_fee_id
from app import config
from app.schemas.growx import SubmitToGrowxRequest, SubmitToGrowxResponse
from app.domain.exceptions import (
    NotFoundError,
    UpstreamError,
    ValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/growx", tags=["GrowX Integration"])

# ============================================================================
# CONFIG  — set GROWX_BASE_URL in your .env once client provides production URL
# ============================================================================

GROWX_BASE_URL = config.GROWX_BASE_URL

GROWX_API_USER_CREATE  = "/growx/api/v1/customers/sme/users/pre-auth/self/onboard/create"
GROWX_API_SET_PASSWORD = "/growx/api/v1/customers/sme/users/set-password"
GROWX_API_SME_CREATE   = "/growx/api/v1/customers/sme/pre-auth/create"

# NOTE: crtdBy (API 3's "created by" field) used to be a static account-level
# ID from GROWX_CRTD_BY. Now uses the real, per-user GrowX userId returned by
# API 1 for that user instead — see trigger_api3()'s crtd_by param and the
# growx_user_id column read below.


# ============================================================================
# HELPERS
# ============================================================================

_GROWX_USER_COLS_FULL = "email, first_name, last_name, phone_number, password_hash, ref_no, growx_user_ref_id, growx_user_id"
_GROWX_USER_COLS_SAFE = "email, first_name, last_name, phone_number, password_hash, ref_no"


def _get_user_from_supabase(email: str) -> dict:
    """
    Fetch user row from Supabase users table.

    growx_user_ref_id / growx_user_id are optional columns that may not exist
    on every environment's schema yet (seen live: Postgres error 42703
    "column users.growx_user_ref_id does not exist"). Previously that made
    the whole select() throw, get swallowed by the except below, and return
    {} — which then made every caller (trigger_api1_api2, trigger_api3, the
    manual endpoints) think the user didn't exist at all and abort the entire
    GrowX flow, even though the user was right there in the table.

    Fix: try the full column list first; if that specific query fails, retry
    with just the guaranteed-to-exist columns (same set test_growx_apis.py
    already uses successfully) instead of giving up entirely. The two
    optional fields just come back as None in that case.
    """
    try:
        result = UserRepository.get_growx_profile(email, _GROWX_USER_COLS_FULL)
        return result.data or {}
    except Exception as e:
        logger.warning(
            f"[GROWX] Full user select failed for {email} ({e}) — "
            f"retrying with safe column set (growx_user_ref_id/growx_user_id may be missing from schema)"
        )
        try:
            result = UserRepository.get_growx_profile(email, _GROWX_USER_COLS_SAFE)
            data = result.data or {}
            data.setdefault("growx_user_ref_id", None)
            data.setdefault("growx_user_id", None)
            return data
        except Exception as e2:
            logger.error(f"[GROWX] Supabase user lookup failed for {email}: {e2}")
            return {}


def _find_eid_data(email: str) -> dict:
    """
    Find the EID output.json for this user.
    Checks both root subfolders and members/ subfolders.
    Returns extracted_fields dict.
    """
    base = user_docs_path(email)
    if not base.exists():
        return {}

    # Search all subfolders including members/*
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


def _find_trade_license_data(email: str) -> dict:
    """
    Find the Trade License / Commercial License output.json for this user.
    Searches root subfolders AND members/ subfolders.
    Returns extracted english fields dict.
    """
    base = user_docs_path(email)
    if not base.exists():
        return {}

    commercial_types = ("commercial", "trade_license", "commercial_license")
    candidates = []

    # ✅ Use rglob to search ALL subfolders including members/
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
    doc_data = candidates[0][1]

    extracted = doc_data.get("extracted_fields", doc_data.get("extracted_data", {}))
    if "english" in extracted and isinstance(extracted["english"], dict):
        extracted = extracted["english"]
    return extracted


# ============================================================================
# EXPORTED TRIGGER HELPERS — called by other routes at the right lifecycle stage
# ============================================================================

async def trigger_api1_api2(email: str) -> dict:
    """
    Called after EID is verified and saved to disk.
    Reads EID number + user details from Supabase/disk, then:
      1. Calls GrowX API 1 (user create) with real EID number
      2. Calls GrowX API 2 (set password) using userId from API 1 response
    Saves growx_user_id back to Supabase users table.
    Non-blocking — caller should fire-and-forget via asyncio.create_task().
    """
    logger.info(f"[GROWX] trigger_api1_api2 called for {email}")

    user = _get_user_from_supabase(email)
    if not user:
        logger.error(f"[GROWX] trigger_api1_api2: no Supabase user for {email}")
        return {"success": False, "error": "User not found"}

    eid = _find_eid_data(email)
    eid_number = (
        eid.get("ID Number") or eid.get("id_number") or eid.get("emirates_id", "")
    )
    if not eid_number:
        logger.warning(f"[GROWX] trigger_api1_api2: EID number still empty for {email} — aborting")
        return {"success": False, "error": "EID number not found on disk"}

    first_name    = user.get("first_name", "")
    last_name     = user.get("last_name", "")
    phone_number  = user.get("phone_number", "")
    password_hash = user.get("password_hash", "")

    # ── API 1 — User Create ───────────────────────────────────────────────
    api1_payload = {
        "emailId":            email,
        "userLoginId":        email,
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
    logger.debug(f"[GROWX] API1 payload (EID trigger): {api1_payload}")

    growx_user_id = None
    api1_result   = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r1 = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}",
                json=api1_payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            api1_result = r1.json()
        except Exception:
            api1_result = {"raw": r1.text}

        api1_data     = api1_result.get("data", {}) or {}
        growx_user_id = api1_data.get("userId") or api1_result.get("userId")
        logger.info(f"[GROWX] API1 status={r1.status_code} userId={growx_user_id}")
        logger.debug(f"[GROWX] API1 full response: {api1_result}")

    except Exception as e:
        logger.error(f"[GROWX] API1 failed: {e}")
        return {"success": False, "error": str(e)}

    if not growx_user_id:
        logger.warning(f"[GROWX] API1 did not return userId — API2 skipped")
        return {"success": False, "api1": api1_result, "error": "No userId from API1"}

    # ── API 2 — Set Password ──────────────────────────────────────────────
    api2_payload = {
        "userLoginId": email,
        "emailId":     email,
        "userId":      growx_user_id,
        "password":    password_hash,
    }
    logger.debug(f"[GROWX] API2 payload (EID trigger): userLoginId={email} userId={growx_user_id}")

    api2_result = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r2 = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}",
                json=api2_payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            api2_result = r2.json()
        except Exception:
            api2_result = {"raw": r2.text}

        logger.info(f"[GROWX] API2 status={r2.status_code} userCode={(api2_result.get('data') or {}).get('userCode') if isinstance(api2_result, dict) else None}")
        logger.debug(f"[GROWX] API2 full response: {api2_result}")

    except Exception as e:
        logger.error(f"[GROWX] API2 failed: {e}")

    # ── Save growx_user_id + userRefId to Supabase ────────────────────────
    # If growx_user_ref_id doesn't exist in the schema, the update() call
    # fails atomically — meaning growx_user_id (a column that DOES exist)
    # would silently fail to save too, breaking the manual retry endpoints
    # which read it back later. Save growx_user_id on its own first, then
    # try growx_user_ref_id separately so one missing optional column can't
    # take the required one down with it.
    try:
        from app.services.supabase_client import supabase as _sb
        UserRepository.update_by_email(email, {"growx_user_id": int(growx_user_id)})
        logger.info(f"[GROWX] Saved growx_user_id={growx_user_id} to Supabase for {email}")
    except Exception as e:
        logger.warning(f"[GROWX] Could not save growx_user_id to Supabase: {e}")

    try:
        user_ref_id = None
        if api2_result and isinstance(api2_result, dict):
            user_ref_id = (api2_result.get("data") or {}).get("userRefId")
        if user_ref_id:
            from app.services.supabase_client import supabase as _sb2
            UserRepository.update_by_email(email, {"growx_user_ref_id": user_ref_id})
            logger.info(f"[GROWX] Saved growx_user_ref_id={user_ref_id} to Supabase for {email}")
    except Exception as e:
        logger.warning(
            f"[GROWX] Could not save growx_user_ref_id to Supabase for {email} ({e}) — "
            f"column may not exist in schema yet; growx_user_id was still saved above"
        )

    return {"success": True, "growx_user_id": growx_user_id, "api1": api1_result, "api2": api2_result}


async def trigger_api3(email: str, crtd_by: Optional[int] = None) -> dict:
    """
    Called after self-declaration is submitted.
    Reads Trade License data + feeId + ref_no, then calls GrowX API 3 (SME company create).
    Non-blocking — caller should fire-and-forget via asyncio.create_task().

    crtd_by: the real GrowX userId (from API 1) to send as "crtdBy". Pass it
    directly when calling right after trigger_api1_api2 in the same flow —
    avoids a Supabase round-trip and any read-after-write timing risk. If not
    passed, falls back to whatever growx_user_id is already saved on the
    user's Supabase row (from a previous API 1 call). If neither is
    available, crtdBy is sent as None and GrowX decides what to do with it —
    we don't block API 3 from firing just because crtdBy is missing.
    """
    logger.info(f"[GROWX] trigger_api3 called for {email}")

    user = _get_user_from_supabase(email)
    if not user:
        logger.error(f"[GROWX] trigger_api3: no Supabase user for {email}")
        return {"success": False, "error": "User not found"}

    tl = _find_trade_license_data(email)
    if not tl:
        logger.error(f"[GROWX] trigger_api3: no Trade License data for {email}")
        return {"success": False, "error": "No Trade License data found"}

    pkg = get_package_selection(email)
    if not pkg:
        logger.error(f"[GROWX] trigger_api3: no product package for {email}")
        return {"success": False, "error": "No product package selected"}

    selected_package = pkg.get("selected_package", "Essential")
    fee_id           = get_fee_id(selected_package)
    company_name     = tl.get("trade_name_english") or tl.get("company_name_english", "")
    mobile           = tl.get("mobile") or tl.get("phone") or user.get("phone_number", "")
    address          = tl.get("license_address") or tl.get("commerce_address", "")
    po_box           = tl.get("po_box", "")
    landline         = tl.get("fax", "")
    license_number = tl.get("license_number", "")

    # docRefId: this user's UUID (ref_no), generated at signup and unique per user
    doc_ref_id = user.get("ref_no", "")

    resolved_crtd_by = crtd_by if crtd_by is not None else user.get("growx_user_id")
    logger.info(
        f"[GROWX] trigger_api3: license_number={license_number} docRefId={doc_ref_id} "
        f"crtdBy={resolved_crtd_by} (passed={crtd_by is not None})"
    )

    api3_payload = {
        "type":               "FO",
        "routingTypeCode":    "CB",
        "groupCompName":      company_name,
        "groupCompType":      "CORPORATE",
        "emailId":            email,
        "mobileCode":         "+971",
        "mobileNo":           mobile,
        "countryCode2":       "AE",
        "addressLine1":       address or "N/A",
        "addressLine2":       "",
        "addressLine3":       "",
        "addressLine4":       "UAE",
        "contactName":        company_name,
        "companyLandline":    landline or "N/A",
        "companyPoBox":       po_box or "00000",
        "feeId":              fee_id,
        "supportedCountries": "AE",
        "crtdBy":             resolved_crtd_by,
        "docRefId":           doc_ref_id,      # this user's UUID (ref_no)
        "tradeLicenseNumber": license_number,  # OCR-extracted Trade License number
    }
    logger.debug(f"[GROWX] API3 payload (declaration trigger): {api3_payload}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r3 = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}",
                json=api3_payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            api3_result = r3.json()
        except Exception:
            api3_result = {"raw": r3.text}

        logger.info(f"[GROWX] API3 status={r3.status_code} groupId={(api3_result.get('data') or {}).get('groupId') if isinstance(api3_result, dict) else None}")
        logger.debug(f"[GROWX] API3 full response: {api3_result}")
        return {"success": r3.status_code in (200, 201, 202), "api3": api3_result}

    except Exception as e:
        logger.error(f"[GROWX] API3 failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================


# ============================================================================
# MAIN ENDPOINT
# ============================================================================

@router.post("/submit", response_model=SubmitToGrowxResponse)
async def submit_to_growx(req: SubmitToGrowxRequest):
    """
    Reads user data + Trade License + product package for the given email,
    then calls all 3 GrowX APIs in sequence.

    Flow:
      1. GrowX user create  → returns growx userId
      2. GrowX set password → uses growx userId from step 1
      3. GrowX SME create   → uses Trade License data + feeId from product package
    """
    logger.info(f"[GROWX] submit_to_growx called for {req.email}")
    errors = []

    # ── 1. Load user from Supabase ────────────────────────────────────────
    user = _get_user_from_supabase(req.email)
    if not user:
        raise NotFoundError(f"User '{req.email}' not found in database.")

    first_name     = user.get("first_name", "")
    last_name      = user.get("last_name", "")
    phone_number   = user.get("phone_number", "")
    password_hash  = user.get("password_hash", "")

    # ── 2. Load EID data (for documentValue) ─────────────────────────────
    eid = _find_eid_data(req.email)
    eid_number = (
        eid.get("ID Number")
        or eid.get("id_number")
        or eid.get("emirates_id", "")
    )

    # ── 3. Load Trade License data ────────────────────────────────────────
    tl = _find_trade_license_data(req.email)
    if not tl:
        raise NotFoundError("No Trade License data found. Ensure the document has been uploaded and verified.")

    company_name   = tl.get("trade_name_english") or tl.get("company_name_english", "")
    mobile         = tl.get("mobile") or tl.get("phone") or phone_number
    address        = tl.get("license_address") or tl.get("commerce_address", "")
    po_box         = tl.get("po_box", "")
    license_number = tl.get("license_number", "")
    landline       = tl.get("fax", "")

    # ── 4. Load product package → feeId ──────────────────────────────────
    pkg = get_package_selection(req.email)
    if not pkg:
        raise NotFoundError("No product package selected. Complete package selection first.")
    selected_package = pkg.get("selected_package", "Essential")
    fee_id = get_fee_id(selected_package)

    # ── 5. Call GrowX API 1 — User Create ────────────────────────────────
    user_payload = {
        "emailId":            req.email,
        "userLoginId":        req.email,
        "firstName":          first_name,
        "lastName":           last_name,
        "mobileNo":           phone_number,
        "mobileCode":         req.mobile_code,
        "documentType":       "Emirates ID",
        "documentValue":      eid_number,
        "supportedCountries": req.supported_countries,
        "companyExistsFlag":  "N",       # ✅ default N
        "isWhatsappNotify":   req.is_whatsapp_notify,
    }

    logger.info(f"[GROWX] API1 payload: {user_payload}")

    api1_result = None
    growx_user_id = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r1 = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}",
                json=user_payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            api1_result = r1.json()
        except Exception:
            api1_result = {"raw": r1.text}

        # ✅ Extract userId from data.userId (confirmed from live response)
        growx_user_id = (
            api1_result.get("data", {}).get("userId")
            or api1_result.get("userId")
            or api1_result.get("id")
        )
        logger.info(f"[GROWX] API1 response: {r1.status_code} | userId={growx_user_id}")
        logger.info(f"[GROWX] API1 full response: {api1_result}")

        if r1.status_code not in (200, 201, 202):
            errors.append(f"API1 user create returned {r1.status_code}")

    except httpx.ConnectError:
        errors.append(f"API1: Cannot connect to GrowX at {GROWX_BASE_URL}")
        api1_result = {"error": "Connection failed"}

    # ── 6. Call GrowX API 2 — Set Password ───────────────────────────────
    # ✅ Only proceed if API 1 returned a valid userId
    api2_result = None

    if not growx_user_id:
        errors.append("API2 skipped: API1 did not return a valid userId")
        api2_result = {"error": "Skipped — no userId from API1"}
        logger.warning(f"[GROWX] API2 skipped — no growx_user_id from API1")
    else:
        logger.info(f"[GROWX] API2 password_hash (first 15 chars): {password_hash[:15]}...")
        password_payload = {
            "userLoginId": req.email,
            "emailId":     req.email,
            "userId":      growx_user_id,
            "password":    password_hash,
        }
        logger.info(f"[GROWX] API2 payload (password masked): userLoginId={req.email}, userId={growx_user_id}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r2 = await client.post(
                    f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}",
                    json=password_payload,
                    headers={"Content-Type": "application/json"},
                )
            try:
                api2_result = r2.json()
            except Exception:
                api2_result = {"raw": r2.text}

            logger.info(f"[GROWX] API2 response: {r2.status_code}")
            logger.info(f"[GROWX] API2 full response: {api2_result}")

            if r2.status_code not in (200, 201, 202):
                errors.append(f"API2 set-password returned {r2.status_code}")

        except httpx.ConnectError:
            errors.append(f"API2: Cannot connect to GrowX at {GROWX_BASE_URL}")
            api2_result = {"error": "Connection failed"}

    # ── 7. Call GrowX API 3 — SME Company Create ─────────────────────────
    # docRefId: this user's UUID (ref_no), generated at signup and unique per user
    doc_ref_id = user.get("ref_no", "")
    logger.info(f"[GROWX] API3 docRefId={doc_ref_id} license_number={license_number}")

    sme_payload = {
        "type":               "FO",
        "routingTypeCode":    "CB",
        "groupCompName":      company_name,
        "groupCompType":      "CORPORATE",
        "emailId":            req.email,
        "mobileCode":         req.mobile_code,
        "mobileNo":           mobile,
        "countryCode2":       "AE",
        "addressLine1":       address or "N/A",
        "addressLine2":       "",
        "addressLine3":       "",
        "addressLine4":       "UAE",
        "contactName":        company_name,
        "companyLandline":    landline or "N/A",
        "companyPoBox":       po_box or "00000",
        "feeId":              fee_id,
        "supportedCountries": req.supported_countries,
        "crtdBy":             growx_user_id,  # real userId from API 1, called earlier in this same request
        "docRefId":           doc_ref_id,      # this user's UUID (ref_no)
        "tradeLicenseNumber": license_number,  # OCR-extracted Trade License number
    }
    logger.info(f"[GROWX] API3 payload: {sme_payload}")

    api3_result = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r3 = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}",
                json=sme_payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            api3_result = r3.json()
        except Exception:
            api3_result = {"raw": r3.text}

        logger.info(f"[GROWX] API3 response: {r3.status_code}")

        if r3.status_code not in (200, 201):
            errors.append(f"API3 SME create returned {r3.status_code}")

    except httpx.ConnectError:
        errors.append(f"API3: Cannot connect to GrowX at {GROWX_BASE_URL}")
        api3_result = {"error": "Connection failed"}

    # ── 8. Return consolidated result ─────────────────────────────────────
    success = len(errors) == 0
    return SubmitToGrowxResponse(
        success=success,
        message="All 3 GrowX APIs called successfully." if success else f"Completed with errors: {'; '.join(errors)}",
        api1_user_create=api1_result,
        api2_set_password=api2_result,
        api3_sme_create=api3_result,
        errors=errors if errors else None,
    )


# ============================================================================
# INDIVIDUAL ENDPOINTS — call each GrowX API separately
# ============================================================================

@router.post("/user-create")
async def growx_user_create(req: SubmitToGrowxRequest):
    """
    API 1 — Send user details to GrowX.
    POST /growx/api/v1/customers/sme/users/pre-auth/self/onboard/create
    """
    user = _get_user_from_supabase(req.email)
    if not user:
        raise NotFoundError(f"User '{req.email}' not found.")

    eid = _find_eid_data(req.email)
    eid_number = eid.get("ID Number") or eid.get("id_number", "")

    payload = {
        "emailId":            req.email,
        "userLoginId":        req.email,
        "firstName":          user.get("first_name", ""),
        "lastName":           user.get("last_name", ""),
        "mobileNo":           user.get("phone_number", ""),
        "mobileCode":         req.mobile_code,
        "documentType":       "Emirates ID",
        "documentValue":      eid_number,
        "supportedCountries": req.supported_countries,
        "companyExistsFlag":  "N",        # ✅ default N
        "isWhatsappNotify":   req.is_whatsapp_notify,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            result = r.json()
        except Exception:
            result = {"raw": r.text}

        return {"success": r.status_code in (200, 201), "status_code": r.status_code, "payload_sent": payload, "response": result}

    except httpx.RequestError as e:
        # Covers ConnectError, TimeoutException, ReadTimeout, TLS errors, etc.
        logger.error(f"[GROWX] user-create network error: {type(e).__name__}: {e}")
        raise UpstreamError(context=f"Cannot reach GrowX at {GROWX_BASE_URL}: {type(e).__name__}: {e}")


@router.post("/set-password")
async def growx_set_password(req: SubmitToGrowxRequest):
    """
    API 2 — Set user password in GrowX.
    POST /growx/api/v1/customers/sme/users/set-password
    Uses growx_user_id stored in Supabase after API 1 completes.
    """
    user = _get_user_from_supabase(req.email)
    if not user:
        raise NotFoundError(f"User '{req.email}' not found.")

    growx_user_id = user.get("growx_user_id")
    if not growx_user_id:
        raise ValidationError("growx_user_id not found — run API 1 (user-create) first.")

    payload = {
        "userLoginId": req.email,
        "emailId":     req.email,
        "userId":      growx_user_id,
        "password":    user.get("password_hash", ""),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            result = r.json()
        except Exception:
            result = {"raw": r.text}

        return {"success": r.status_code in (200, 201), "status_code": r.status_code, "payload_sent": payload, "response": result}

    except httpx.RequestError as e:
        logger.error(f"[GROWX] set-password network error: {type(e).__name__}: {e}")
        raise UpstreamError(context=f"Cannot reach GrowX at {GROWX_BASE_URL}: {type(e).__name__}: {e}")


@router.post("/sme-create")
async def growx_sme_create(req: SubmitToGrowxRequest):
    """
    API 3 — Send SME company + Trade License data to GrowX.
    POST /growx/api/v1/customers/sme/pre-auth/create
    """
    user = _get_user_from_supabase(req.email)
    if not user:
        raise NotFoundError(f"User '{req.email}' not found.")

    tl = _find_trade_license_data(req.email)
    if not tl:
        raise NotFoundError("No Trade License data found.")

    pkg = get_package_selection(req.email)
    if not pkg:
        raise NotFoundError("No product package selected.")

    fee_id         = get_fee_id(pkg.get("selected_package", "Essential"))
    company_name   = tl.get("trade_name_english") or tl.get("company_name_english", "")
    license_number = tl.get("license_number", "")

    payload = {
        "type":               "FO",
        "routingTypeCode":    "CB",
        "groupCompName":      company_name,
        "groupCompType":      "CORPORATE",
        "emailId":            req.email,
        "mobileCode":         req.mobile_code,
        "mobileNo":           tl.get("mobile") or tl.get("phone", ""),
        "countryCode2":       "AE",
        "addressLine1":       tl.get("license_address") or tl.get("commerce_address") or "N/A",
        "addressLine2":       "",
        "addressLine3":       "",
        "addressLine4":       "UAE",
        "contactName":        company_name,
        "companyLandline":    tl.get("fax") or "N/A",
        "companyPoBox":       tl.get("po_box") or "00000",
        "feeId":              fee_id,
        "supportedCountries": req.supported_countries,
        "crtdBy":             user.get("growx_user_id"),  # real userId from a prior API 1 call
        "docRefId":           user.get("ref_no", ""),  # this user's UUID (ref_no)
        "tradeLicenseNumber": license_number,   # OCR-extracted Trade License number
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        try:
            result = r.json()
        except Exception:
            result = {"raw": r.text}

        return {"success": r.status_code in (200, 201), "status_code": r.status_code, "payload_sent": payload, "response": result}

    except httpx.RequestError as e:
        logger.error(f"[GROWX] sme-create network error: {type(e).__name__}: {e}")
        raise UpstreamError(context=f"Cannot reach GrowX at {GROWX_BASE_URL}: {type(e).__name__}: {e}")


# ============================================================================
# INDIVIDUAL PREVIEW ENDPOINTS — GET, browser-friendly, no GrowX call
# ============================================================================

@router.get("/preview/api1_user_create/{email}")
async def preview_api1_user_create(email: str):
    """Preview payload for API 1 — User Details"""
    user = _get_user_from_supabase(email)
    eid  = _find_eid_data(email)
    return {
        "api": "API 1 — User Create",
        "url": f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}",
        "payload": {
            "emailId":            email,
            "userLoginId":        email,
            "firstName":          user.get("first_name", ""),
            "lastName":           user.get("last_name", ""),
            "mobileNo":           user.get("phone_number", ""),
            "mobileCode":         "+971",
            "documentType":       "Emirates ID",
            "documentValue":      eid.get("ID Number") or eid.get("id_number", ""),
            "supportedCountries": "AE",
            "companyExistsFlag":  "N",    # ✅ default N
            "isWhatsappNotify":   "N",
        },
    }


@router.get("/preview/api2_set_password/{email}")
async def preview_api2_set_password(email: str):
    """Preview payload for API 2 — Set Password"""
    user = _get_user_from_supabase(email)
    return {
        "api": "API 2 — Set Password",
        "url": f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}",
        "payload": {
            "userLoginId": email,
            "emailId":     email,
            "userId":      "<returned from API 1 response>",
            "password":    user.get("password_hash", ""),
        },
    }


@router.get("/preview/api3_sme_create/{email}")
async def preview_api3_sme_create(email: str):
    """Preview payload for API 3 — SME Company Create"""
    user = _get_user_from_supabase(email)
    tl   = _find_trade_license_data(email)
    pkg  = get_package_selection(email)
    selected_package = pkg.get("selected_package", "Essential") if pkg else "Essential"
    fee_id       = get_fee_id(selected_package)
    company_name = tl.get("trade_name_english") or tl.get("company_name_english", "")
    ref_no       = user.get("ref_no", "") if user else ""
    return {
        "api": "API 3 — SME Company Create",
        "url": f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}",
        "payload": {
            "type":               "FO",
            "routingTypeCode":    "CB",
            "groupCompName":      company_name,
            "groupCompType":      "CORPORATE",
            "emailId":            email,
            "mobileCode":         "+971",
            "mobileNo":           tl.get("mobile") or tl.get("phone", ""),
            "countryCode2":       "AE",
            "addressLine1":       tl.get("license_address") or tl.get("commerce_address", ""),
            "addressLine2":       "",
            "addressLine3":       "",
            "addressLine4":       "UAE",
            "contactName":        company_name,
            "companyLandline":    tl.get("fax", ""),
            "companyPoBox":       tl.get("po_box", ""),
            "feeId":              fee_id,
            "supportedCountries": "AE",
            "crtdBy":             user.get("growx_user_id") if user else None,
            "docRefId":           ref_no,  # this user's UUID (ref_no)
            "tradeLicenseNumber": tl.get("license_number", ""), # OCR-extracted Trade License number
        },
    }


# ============================================================================
# PING ENDPOINT — checks if all 3 GrowX API endpoints are reachable
# ============================================================================

@router.get("/ping")
async def ping_growx_apis():
    """
    Health check — sends a minimal POST to each GrowX API and reports reachability.
    A 400/422 response means the server is UP (it rejected test data, as expected).
    A connection error or timeout means the server is DOWN.
    """

    def verdict(status_code: int) -> str:
        if status_code in (200, 201, 202):
            return "✅ Server is UP — accepted"
        elif status_code in (400, 422):
            return "✅ Server is UP — rejected test payload (expected)"
        elif status_code == 500:
            return "✅ Server is UP — rejected invalid test payload (expected)"
        elif status_code == 404:
            return "⚠️ Server reached but URL path not found (404)"
        elif status_code == 405:
            return "⚠️ Server reached but method not allowed (405)"
        elif status_code == 403:
            return "⚠️ Server reached but access forbidden (403)"
        else:
            return f"⚠️ Server responded with unexpected status {status_code}"

    results = {}

    # ── API 1 — User Create ───────────────────────────────────────────────
    url1 = f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url1, json={"ping": True}, headers={"Content-Type": "application/json"})
        results["api1_user_create"] = {
            "url": url1,
            "reachable": True,
            "status_code": r.status_code,
            "verdict": verdict(r.status_code),
        }
    except httpx.ConnectError:
        results["api1_user_create"] = {"url": url1, "reachable": False, "status_code": None, "verdict": "❌ Cannot connect to server"}
    except httpx.TimeoutException:
        results["api1_user_create"] = {"url": url1, "reachable": False, "status_code": None, "verdict": "❌ Request timed out"}
    except Exception as e:
        results["api1_user_create"] = {"url": url1, "reachable": False, "status_code": None, "verdict": f"❌ Error: {str(e)}"}

    # ── API 2 — Set Password ──────────────────────────────────────────────
    url2 = f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url2, json={"ping": True}, headers={"Content-Type": "application/json"})
        results["api2_set_password"] = {
            "url": url2,
            "reachable": True,
            "status_code": r.status_code,
            "verdict": verdict(r.status_code),
        }
    except httpx.ConnectError:
        results["api2_set_password"] = {"url": url2, "reachable": False, "status_code": None, "verdict": "❌ Cannot connect to server"}
    except httpx.TimeoutException:
        results["api2_set_password"] = {"url": url2, "reachable": False, "status_code": None, "verdict": "❌ Request timed out"}
    except Exception as e:
        results["api2_set_password"] = {"url": url2, "reachable": False, "status_code": None, "verdict": f"❌ Error: {str(e)}"}

    # ── API 3 — SME Create ────────────────────────────────────────────────
    url3 = f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url3, json={"ping": True}, headers={"Content-Type": "application/json"})
        results["api3_sme_create"] = {
            "url": url3,
            "reachable": True,
            "status_code": r.status_code,
            "verdict": verdict(r.status_code),
        }
    except httpx.ConnectError:
        results["api3_sme_create"] = {"url": url3, "reachable": False, "status_code": None, "verdict": "❌ Cannot connect to server"}
    except httpx.TimeoutException:
        results["api3_sme_create"] = {"url": url3, "reachable": False, "status_code": None, "verdict": "❌ Request timed out"}
    except Exception as e:
        results["api3_sme_create"] = {"url": url3, "reachable": False, "status_code": None, "verdict": f"❌ Error: {str(e)}"}

    overall = all(v.get("reachable") for v in results.values())
    return {
        "overall": "✅ All GrowX APIs reachable" if overall else "❌ One or more GrowX APIs unreachable",
        "base_url": GROWX_BASE_URL,
        "results": results,
    }


# ============================================================================
# PREVIEW ENDPOINT — shows all 3 payloads without calling GrowX
# ============================================================================

@router.get("/preview/{email}")
async def preview_growx_payloads(email: str):
    """
    Returns all 3 payloads that would be sent to GrowX — without calling the APIs.
    Use this to verify field mapping before going live.
    """
    user = _get_user_from_supabase(email)
    eid  = _find_eid_data(email)
    tl   = _find_trade_license_data(email)
    pkg  = get_package_selection(email)

    selected_package = pkg.get("selected_package", "Essential") if pkg else "Essential"
    fee_id = get_fee_id(selected_package)

    eid_number   = eid.get("ID Number") or eid.get("id_number", "")
    company_name = tl.get("trade_name_english") or tl.get("company_name_english", "")

    return {
        "email": email,
        "data_sources": {
            "user_found":       bool(user),
            "eid_found":        bool(eid),
            "trade_license_found": bool(tl),
            "package":          selected_package,
            "fee_id":           fee_id,
        },
        "api1_user_create": {
            "url":     f"{GROWX_BASE_URL}{GROWX_API_USER_CREATE}",
            "payload": {
                "emailId":            email,
                "userLoginId":        email,
                "firstName":          user.get("first_name", ""),
                "lastName":           user.get("last_name", ""),
                "mobileNo":           user.get("phone_number", ""),
                "mobileCode":         "+971",
                "documentType":       "Emirates ID",
                "documentValue":      eid_number,
                "supportedCountries": "AE",
                "companyExistsFlag":  "N",    # ✅ default N
                "isWhatsappNotify":   "N",
            },
        },
        "api2_set_password": {
            "url":     f"{GROWX_BASE_URL}{GROWX_API_SET_PASSWORD}",
            "payload": {
                "userLoginId": email,
                "emailId":     email,
                "userId":      "<returned from API 1>",
                "password":    user.get("password_hash", ""),
            },
        },
        "api3_sme_create": {
            "url":     f"{GROWX_BASE_URL}{GROWX_API_SME_CREATE}",
            "payload": {
                "type":               "FO",
                "routingTypeCode":    "CB",
                "groupCompName":      company_name,
                "groupCompType":      "CORPORATE",
                "emailId":            email,
                "mobileCode":         "+971",
                "mobileNo":           tl.get("mobile") or tl.get("phone", ""),
                "countryCode2":       "AE",
                "addressLine1":       tl.get("license_address") or tl.get("commerce_address", ""),
                "companyPoBox":       tl.get("po_box", ""),
                "feeId":              fee_id,
                "supportedCountries": "AE",
                "crtdBy":             user.get("growx_user_id") if user else None,
                "docRefId":           user.get("ref_no", "") if user else "",  # this user's UUID (ref_no)
                "tradeLicenseNumber": tl.get("license_number", ""),    # OCR-extracted Trade License number
            },
        },
    }
