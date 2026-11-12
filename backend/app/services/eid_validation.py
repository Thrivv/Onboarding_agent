# backend/app/services/eid_validation.py

"""
Emirates ID Validation Service
Validates EID documents using:
1. Cross-validation against other submitted documents
2. SurePass API validation against UAE government records (with toggle)
"""

import requests
import json
import logging
import os
import time
from typing import Dict, Optional, Tuple
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# IMPORTS - CENTRALIZED EMAIL FUNCTIONS
# ============================================================================
from app.services.email_sender import send_document_verification_email
from app.services.supabase_client import supabase
from app.services.cross_validator import CrossValidator
from app import config
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
)

logger = logging.getLogger(__name__)

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================
SUREPASS_API_URL = "https://sandbox.surepass.io/api/v1/uae/emirates-verification-v2"
SUREPASS_JWT_TOKEN = config.SUREPASS_JWT_TOKEN


# ============================================================================
# TOGGLE CONFIGURATION FOR SUREPASS EID VALIDATION
# ============================================================================
def is_surepass_enabled(account_type: str, ownership_type: str = "") -> bool:
    """
    Check if SurePass EID validation is enabled for the given account type

    Args:
        account_type: Account type (e.g., 'Corporate')
        ownership_type: Ownership type (e.g., 'Single Owner', 'Partnership')

    Returns:
        bool: True if validation is enabled, False otherwise
    """
    # Map account types to environment variable keys
    if account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
        env_key = "EID_VALIDATION_CORPORATE_SINGLE"
    elif account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_PARTNERSHIP:
        env_key = "EID_VALIDATION_CORPORATE_PARTNERSHIP"
    else:
        # Unknown account type - default to disabled
        return False

    # Read environment variable (default to 'false')
    value = os.getenv(env_key, 'false').lower()
    is_enabled = value in ('true', '1', 'yes')

    logger.debug(f"[SUREPASS] enabled={is_enabled} for {account_type}/{ownership_type}")
    return is_enabled


# ============================================================================
# MAIN VALIDATION FUNCTION
# ============================================================================
def validate_eid_before_confirmation(
    email: str,
    precomputed_cross_validation_result: Optional[dict] = None,
) -> Tuple[bool, str]:
    """
    Main validation function with CROSS-VALIDATION FIRST, then SurePass

    Flow:
    1. Cross-validate documents against each other
    2. SurePass validate EID against government records (if enabled)
    3. Return result

    Args:
        email: User's email address
        precomputed_cross_validation_result: if the caller already ran
            CrossValidator().validate_documents() for this email (e.g.
            self_declaration_confirm runs it right before calling this
            function), pass that result here so step 1 reuses it instead of
            running the exact same cross-validation a second time. Still
            persisted via cross_validator.save_validation_result() below —
            only the (expensive, duplicate) computation is skipped.

    Returns:
        Tuple[bool, str]: (success, message)
    """
    try:
        # ====================================================================
        # STEP 0: GET USER DATA
        # ====================================================================
        user = _get_user_data(email)
        if not user:
            error = "User not found"
            logger.error(f"[VALIDATION] {error}: {email}")
            return False, error

        user_name = user.get("name", "User")
        account_type = user.get("account_type", "")
        ownership = user.get("ownership_type", "")

        # Check if validation is required for this account type
        requires_validation = (
            account_type == ACCOUNT_CORPORATE and ownership == OWNERSHIP_SINGLE
        )

        if not requires_validation:
            logger.debug(f"[VALIDATION] not required for {account_type}/{ownership} ({email})")
            return True, "Validation not required for this account type"

        # ====================================================================
        # STEP 1: CROSS-VALIDATION
        # ====================================================================
        cross_validator = CrossValidator()
        if precomputed_cross_validation_result is not None:
            cross_validation_result = precomputed_cross_validation_result
            logger.debug(f"[VALIDATION] reusing precomputed cross-validation result for {email}")
        else:
            cross_validation_result = cross_validator.validate_documents(email, user)

        # Save cross-validation result (audit trail — always written once here)
        cross_validator.save_validation_result(email, cross_validation_result)

        if not cross_validation_result.get("passed", False):
            mismatches = cross_validation_result.get("mismatches", [])
            error_msg = "Cross-validation failed:\n" + "\n".join([f"  - {m}" for m in mismatches])
            logger.warning(f"[VALIDATION] {email} cross-validation FAILED: {mismatches}")
            _send_failure_email(email, user_name, error_msg)
            return False, error_msg

        # ====================================================================
        # STEP 2: SUREPASS EID VALIDATION (WITH TOGGLE)
        # ====================================================================
        if not is_surepass_enabled(account_type, ownership):
            logger.info(f"[VALIDATION] {email} cross-validation PASSED, SurePass disabled — validation complete")
            return True, "Validation completed (SurePass disabled)"

        # Extract EID data
        eid_data = _get_eid_data(email)
        if not eid_data:
            error = "EID data extraction failed - missing required fields"
            logger.error(f"[VALIDATION] {email} {error}")
            _send_failure_email(email, user_name, error)
            return False, error

        # Call SurePass API with retry logic
        is_valid, message = _call_api_with_retry(
            eid_data["id_number"],
            eid_data["dob"],
            eid_data["nationality"],
            max_retries=3,
            timeout=60
        )

        if not is_valid:
            logger.warning(f"[VALIDATION] {email} SurePass FAILED: {message}")
            _send_failure_email(email, user_name, message)
            return False, message

        logger.info(f"[VALIDATION] {email} cross-validation + SurePass both PASSED")
        return True, "All validations passed successfully"

    except Exception as e:
        error = f"System error: {str(e)}"
        logger.error(f"[VALIDATION] unexpected error for {email}: {e}", exc_info=True)
        return False, error


# ============================================================================
# SUREPASS API CALL WITH RETRY LOGIC
# ============================================================================
def _call_api_with_retry(id_number: str, dob: str, nationality: str,
                         max_retries: int = 3, timeout: int = 60) -> Tuple[bool, str]:
    """
    Call SurePass API with retry logic for network failures

    Args:
        id_number: Emirates ID number
        dob: Date of birth (will be formatted to YYYY-MM-DD)
        nationality: Nationality
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds

    Returns:
        Tuple[bool, str]: (success, message)
    """
    # Clean and format data
    clean_id = id_number.replace("-", "").replace(" ", "").strip()
    formatted_dob = _format_date(dob)
    clean_nationality = nationality.lower().strip()

    headers = {
        "Authorization": f"Bearer {SUREPASS_JWT_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "id_number": clean_id,
        "date_of_birth": formatted_dob,
        "current_nationality": clean_nationality
    }

    logger.debug(f"[SUREPASS] calling API id={clean_id} dob={formatted_dob} nationality={clean_nationality}")

    # RETRY LOOP
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                SUREPASS_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout
            )

            result = response.json()
            logger.debug(f"[SUREPASS] attempt {attempt}/{max_retries} status={response.status_code} body={result}")

            if response.status_code == 200:
                success = result.get("success", False)
                status_code = result.get("status_code", 0)

                if success and status_code == 200:
                    logger.info("[SUREPASS] validation PASSED")
                    return True, "Emirates ID validated successfully"
                else:
                    error = result.get("message", "Validation failed")
                    logger.warning(f"[SUREPASS] validation FAILED: {error}")
                    return False, error
            else:
                error = result.get("message", f"API error {response.status_code}")
                logger.error(f"[SUREPASS] API error: {error}")
                return False, error

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                wait = 2 * attempt
                logger.warning(f"[SUREPASS] attempt {attempt} timed out, retrying in {wait}s")
                time.sleep(wait)
                continue
            else:
                error = "Validation request timed out after all retries"
                logger.error(f"[SUREPASS] {error}")
                return False, error

        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                wait = 2 * attempt
                logger.warning(f"[SUREPASS] network error on attempt {attempt}: {e}, retrying in {wait}s")
                time.sleep(wait)
                continue
            else:
                error = f"Network error: {str(e)}"
                logger.error(f"[SUREPASS] {error}")
                return False, error

        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            logger.error(f"[SUREPASS] {error}", exc_info=True)
            return False, error

    return False, "Max retries exceeded"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_user_data(email: str) -> Optional[Dict]:
    """
    Get user data from database

    Args:
        email: User's email

    Returns:
        User data dictionary or None if not found
    """
    try:
        from app.services.supabase_client import get_user_by_email
        user = get_user_by_email(email)
        if not user:
            logger.error(f"[VALIDATION] user not found in database: {email}")
        return user
    except Exception as e:
        logger.error(f"[VALIDATION] failed to get user data for {email}: {e}", exc_info=True)
        return None


def _get_eid_data(email: str) -> Optional[Dict]:
    """
    Extract EID data from output.json

    Args:
        email: User's email

    Returns:
        Dictionary with id_number, dob, nationality or None if extraction fails
    """
    try:
        # Resolve user's document root (ref_no-based, with email fallback)
        try:
            from app.services.document_helpers import get_document_ref_no, get_documents_base_path
            _ref_no = get_document_ref_no(email)
            _docs_base = get_documents_base_path()
        except Exception:
            _ref_no = email
            _docs_base = Path("/app/backend/documents/id")
        base_path_rno = _docs_base / _ref_no
        base_path_email = _docs_base / email
        base_path = base_path_rno if base_path_rno.exists() else base_path_email

        # Check multiple possible locations (new prefix-based + legacy names)
        possible_paths = [
            base_path / f"EID-{_ref_no}" / "output.json",   # new convention
            base_path / "eid" / "output.json",
            base_path / "EID" / "output.json",
        ]

        eid_file = None
        for path in possible_paths:
            if path.exists():
                eid_file = path
                break

        if not eid_file:
            # Recursive scan for any EID output.json
            for subfolder in base_path.iterdir() if base_path.exists() else []:
                if not subfolder.is_dir():
                    continue
                candidate = subfolder / "output.json"
                if candidate.exists():
                    try:
                        import json as _json
                        _d = _json.loads(candidate.read_text())
                        if _d.get("document_type", "").lower() in {"eid", "emirates_id", "emirates id"}:
                            eid_file = candidate
                            break
                    except Exception:
                        continue

        if not eid_file:
            logger.error(f"[VALIDATION] EID output.json not found for {email} (searched {base_path})")
            return None

        # Read JSON file
        with open(eid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        extracted = data.get("extracted_fields", {})

        # Extract required fields (try multiple possible keys)
        id_number = (
            extracted.get("ID Number") or
            extracted.get("id_number") or
            extracted.get("Id Number") or
            ""
        ).strip()

        dob = (
            extracted.get("Date of Birth") or
            extracted.get("date_of_birth") or
            extracted.get("DOB") or
            extracted.get("dob") or
            ""
        ).strip()

        nationality = (
            extracted.get("Nationality") or
            extracted.get("nationality") or
            ""
        ).strip()

        # Validate all required fields are present
        if not id_number or not dob or not nationality:
            missing = []
            if not id_number: missing.append("ID Number")
            if not dob: missing.append("Date of Birth")
            if not nationality: missing.append("Nationality")
            logger.error(f"[VALIDATION] {email} missing required EID fields: {', '.join(missing)}")
            return None

        return {
            "id_number": id_number,
            "dob": dob,
            "nationality": nationality
        }

    except Exception as e:
        logger.error(f"[VALIDATION] failed to extract EID data for {email}: {e}", exc_info=True)
        return None


def _format_date(dob: str) -> str:
    """
    Convert date to YYYY-MM-DD format required by SurePass API

    Supported input formats:
    - YYYY-MM-DD (already correct)
    - DD/MM/YYYY
    - DD-MM-YYYY

    Args:
        dob: Date of birth string

    Returns:
        Formatted date string (YYYY-MM-DD)
    """
    dob = dob.strip()

    # Already in correct format (YYYY-MM-DD)
    if len(dob) == 10 and dob[4] == '-' and dob[7] == '-':
        return dob

    # DD/MM/YYYY format
    if '/' in dob:
        parts = dob.split('/')
        if len(parts) == 3:
            day, month, year = parts
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # DD-MM-YYYY format
    elif '-' in dob and len(dob.split('-')[0]) <= 2:
        parts = dob.split('-')
        if len(parts) == 3:
            day, month, year = parts
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    logger.warning(f"[VALIDATION] could not parse date format: {dob!r}, returning as-is")
    return dob


def _save_surepass_result(email: str, result_data: dict) -> str:
    """
    Save SurePass API validation result to JSON file for audit trail

    Args:
        email: User's email
        result_data: Dictionary containing validation results

    Returns:
        Path to saved JSON file (empty string if save failed)
    """
    try:
        try:
            from app.services.document_helpers import get_document_ref_no as _gdr_eid, get_documents_base_path as _gdbp_eid
            _rno_eid = _gdr_eid(email)
            _docs_base_eid = _gdbp_eid()
        except Exception:
            _rno_eid = email
            _docs_base_eid = Path("/app/backend/documents/id")
        _eid_base = _docs_base_eid / _rno_eid
        if not _eid_base.exists():
            _eid_base = _docs_base_eid / email
        user_docs_dir = _eid_base
        user_docs_dir.mkdir(parents=True, exist_ok=True)

        save_path = user_docs_dir / "surepass_validation.json"

        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

        return str(save_path)

    except Exception as e:
        logger.error(f"[VALIDATION] failed to save SurePass result for {email}: {e}", exc_info=True)
        return ""


def _send_failure_email(email: str, user_name: str, error_message: str):
    """
    Send failure notification email using centralized email function

    Args:
        email: User's email address
        user_name: User's name
        error_message: Detailed error message from validation
    """
    try:
        # USE CENTRALIZED EMAIL FUNCTION
        send_document_verification_email(
            to_email=email,
            user_name=user_name,
            document_type="Emirates ID",
            status="invalid",  # Document failed validation
            filename=None,
            reason=error_message,
            extracted_data=None,
            is_complete=False,
            remaining_documents=["Emirates ID (EID)"],
            member_name=None
        )

        logger.info(f"[VALIDATION] failure email sent to {email}")

    except Exception as e:
        logger.error(f"[VALIDATION] failed to send failure email to {email}: {e}", exc_info=True)
