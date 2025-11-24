## app/services/eid_validation.py
import os
import json
import requests
import time
from pathlib import Path
from typing import Dict, Tuple, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Configuration
SUREPASS_API_URL = "https://sandbox.surepass.io/api/v1/uae/emirates-verification-v2"
SUREPASS_JWT_TOKEN = os.getenv("SUREPASS_JWT_TOKEN", "")

from app.services.cross_validator import CrossValidator

# ========================================================================
# TOGGLE CONFIGURATION FOR SUREPASS EID VALIDATION
# ========================================================================
def is_surepass_enabled(account_type: str, ownership_type: str = "") -> bool:
    """
    Check if SurePass EID validation is enabled for the given account type
    
    Args:
        account_type: Account type (e.g., 'Savings', 'Corporate')
        ownership_type: Ownership type (e.g., 'Single Owner', 'Partnership')
        
    Returns:
        bool: True if validation is enabled, False otherwise
    """
    # Map account types to environment variable keys
    if account_type == "Savings":
        env_key = "EID_VALIDATION_SAVINGS"
    elif account_type == "Corporate" and ownership_type == "Single Owner":
        env_key = "EID_VALIDATION_CORPORATE_SINGLE"
    elif account_type == "Corporate" and ownership_type == "Partnership":
        env_key = "EID_VALIDATION_CORPORATE_PARTNERSHIP"
    else:
        # Unknown account type - default to disabled
        return False
    
    # Read environment variable (default to 'false')
    value = os.getenv(env_key, 'false').lower()
    return value in ('true', '1', 'yes')


def validate_eid_before_confirmation(email: str) -> Tuple[bool, str]:
    """
    Main validation function with CROSS-VALIDATION FIRST
    
    Flow:
    1. ✅ Cross-validate documents against each other
    2. ✅ SurePass validate EID against government records (if enabled)
    3. ✅ Return result
    """
    print(f"\n{'='*80}")
    print(f"🔍 [VALIDATION PIPELINE] Starting document verification...")
    print(f"{'='*80}\n")
    
    try:
        # STEP 1: Get user data
        user = _get_user_data(email)
        if not user:
            return False, "❌ User not found"
        
        account_type = user.get("account_type", "")
        ownership = user.get("ownership_type", "")
        
        requires_validation = (
            account_type == "Savings" or 
            (account_type == "Corporate" and ownership == "Single Owner")
        )
        
        if not requires_validation:
            print(f"ℹ️  [INFO] Validation not required for this account type")
            return True, "✅ Validation not required"
        
        print(f"✅ [STEP 1/3] Cross-Validation Starting...")
        print(f"{'='*80}\n")
        
        # ========================================================================
        # STEP 1: CROSS-VALIDATION (NEW!)
        # ========================================================================
        cross_validator = CrossValidator()
        cross_validation_result = cross_validator.validate_documents(email, user)
        
        # Save cross-validation result
        cross_validator.save_validation_result(email, cross_validation_result)
        
        if not cross_validation_result.get("passed", False):
            # Cross-validation failed
            mismatches = cross_validation_result.get("mismatches", [])
            error_msg = f"📋 Cross-validation failed:\n" + "\n".join([f"  • {m}" for m in mismatches])
            
            print(f"\n❌ [CROSS-VALIDATION FAILED]")
            print(f"{error_msg}")
            print(f"{'='*80}\n")
            
            return False, error_msg
        
        print(f"\n✅ [STEP 1/3] Cross-Validation PASSED")
        print(f"   All document data is consistent and matches\n")
        
        # ========================================================================
        # STEP 2: SUREPASS EID VALIDATION (WITH TOGGLE)
        # ========================================================================
        print(f"✅ [STEP 2/3] SurePass EID Validation Starting...")
        print(f"{'='*80}\n")
        
        # 🔧 CHECK IF SUREPASS IS ENABLED FOR THIS ACCOUNT TYPE
        if not is_surepass_enabled(account_type, ownership):
            print(f"ℹ️  [INFO] SurePass validation is DISABLED for {account_type} - {ownership}")
            print(f"   Skipping SurePass API call...\n")
            print(f"✅ [STEP 2/3] SurePass EID Validation SKIPPED (Disabled)")
            print(f"{'='*80}\n")
            print(f"🎉 [SUCCESS] All required verification checks passed!")
            print(f"   ✅ Cross-Validation: PASSED")
            print(f"   ⏭️  SurePass Validation: SKIPPED (Disabled)")
            print(f"{'='*80}\n")
            return True, "✅ Validation completed (SurePass disabled)"
        
        print(f"✅ [INFO] SurePass validation is ENABLED for {account_type} - {ownership}")
        
        eid_data = _get_eid_data(email)
        if not eid_data:
            error = "📋 EID data extraction failed"
            print(f"\n❌ [SUREPASS VALIDATION ERROR]")
            print(f"{error}")
            print(f"{'='*80}\n")
            _send_failure_email(email, user.get("name", "User"), error)
            return False, error
        
        print(f"✅ EID data extracted successfully")
        print(f"  - ID Number: {eid_data['id_number']}")
        print(f"  - DOB: {eid_data['dob']}")
        print(f"  - Nationality: {eid_data['nationality']}\n")
        
        # Call SurePass API with retry
        is_valid, message = _call_api_with_retry(
            eid_data["id_number"],
            eid_data["dob"],
            eid_data["nationality"],
            max_retries=3,
            timeout=60
        )
        
        if is_valid:
            print(f"\n✅ [STEP 2/3] SurePass EID Validation PASSED")
            print(f"   Emirates ID matches government records\n")
        else:
            print(f"\n❌ [SUREPASS VALIDATION FAILED]")
            print(f"{message}")
            print(f"{'='*80}\n")
            _send_failure_email(email, user.get("name", "User"), message)
            return False, message
        
        # ========================================================================
        # STEP 3: ALL VALIDATIONS PASSED
        # ========================================================================
        print(f"✅ [STEP 3/3] All Validations Complete")
        print(f"{'='*80}\n")
        print(f"🎉 [SUCCESS] All verification checks passed!")
        print(f"   ✅ Cross-Validation: PASSED")
        print(f"   ✅ SurePass Validation: PASSED")
        print(f"{'='*80}\n")
        
        return True, "✅ All validations passed successfully"
    
    except Exception as e:
        error = f"⚠️ System error: {str(e)}"
        print(f"\n❌ [UNEXPECTED ERROR]")
        print(f"{error}")
        print(f"{'='*80}\n")
        import traceback
        traceback.print_exc()
        return False, error

def _call_api_with_retry(id_number: str, dob: str, nationality: str, 
                         max_retries: int = 3, timeout: int = 60) -> Tuple[bool, str]:
    """
    Call SurePass API with retry logic
    """
    # Clean data
    clean_id = id_number.replace("-", "").replace(" ", "").strip()
    formatted_dob = _format_date(dob)
    clean_nationality = nationality.lower().strip()
    
    print(f"[INFO] 📤 Calling SurePass API...")
    print(f"  ID: {clean_id}")
    print(f"  DOB: {formatted_dob}")
    print(f"  Nationality: {clean_nationality}")
    
    headers = {
        "Authorization": f"Bearer {SUREPASS_JWT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "id_number": clean_id,
        "date_of_birth": formatted_dob,
        "current_nationality": clean_nationality
    }
    
    print(f"[DEBUG] 📨 Payload: {json.dumps(payload, indent=2)}")
    
    # 🔧 RETRY LOOP
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n[INFO] 🔄 Attempt {attempt}/{max_retries}...")
            
            response = requests.post(
                SUREPASS_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout  # Increased timeout
            )
            
            print(f"[INFO] ✅ Response received: {response.status_code}")
            
            result = response.json()
            print(f"[DEBUG] 📋 Response: {json.dumps(result, indent=2)}")
            
            if response.status_code == 200:
                success = result.get("success", False)
                status_code = result.get("status_code", 0)
                
                if success and status_code == 200:
                    print(f"[SUCCESS] ✅ Validation PASSED")
                    return True, "Emirates ID validated successfully"
                else:
                    error = result.get("message", "Validation failed")
                    print(f"[FAILED] ❌ {error}")
                    return False, error
            else:
                error = result.get("message", f"API error {response.status_code}")
                print(f"[ERROR] ❌ {error}")
                return False, error
        
        except requests.exceptions.Timeout:
            print(f"[ERROR] ⏱️ Attempt {attempt} timed out")
            if attempt < max_retries:
                wait = 2 * attempt
                print(f"[INFO] ⏳ Retrying in {wait} seconds...")
                time.sleep(wait)
                continue
            else:
                error = "Validation request timed out after all retries"
                print(f"[ERROR] ❌ {error}")
                return False, error
        
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 🌐 Network error: {e}")
            if attempt < max_retries:
                wait = 2 * attempt
                print(f"[INFO] ⏳ Retrying in {wait} seconds...")
                time.sleep(wait)
                continue
            else:
                error = f"Network error: {str(e)}"
                return False, error
        
        except Exception as e:
            error = f"Unexpected error: {str(e)}"
            print(f"[ERROR] ❌ {error}")
            return False, error
    
    return False, "Max retries exceeded"

def _get_user_data(email: str) -> Optional[Dict]:
    """Get user from database"""
    try:
        from app.services.supabase_client import get_user_by_email
        return get_user_by_email(email)
    except Exception as e:
        print(f"[ERROR] Failed to get user: {e}")
        return None


def _get_eid_data(email: str) -> Optional[Dict]:
    """Extract EID data from output.json"""
    try:
        base_path = Path(f"/app/backend/documents/id/{email}")
        
        print(f"[DEBUG] 🔍 Searching for EID in: {base_path}")
        
        possible_paths = [
            base_path / "eid" / "output.json",
            base_path / "EID" / "output.json",
        ]
        
        eid_file = None
        for path in possible_paths:
            print(f"[DEBUG]   Checking: {path} ... {('✅ Found' if path.exists() else '❌ Missing')}")
            if path.exists():
                eid_file = path
                break
        
        if not eid_file:
            print(f"[ERROR] EID output.json not found")
            return None
        
        print(f"[SUCCESS] ✅ Found EID at: {eid_file}")
        
        with open(eid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"[DEBUG] JSON structure keys: {list(data.keys())}")
        
        extracted = data.get("extracted_fields", {})
        
        print(f"[DEBUG] Extracted keys: {list(extracted.keys())}")
        print(f"[DEBUG] Sample extracted values:")
        for key, value in list(extracted.items())[:3]:
            print(f"       {key}: {value}")
        
        # Extract fields
        id_number = (
            extracted.get("ID Number") or
            extracted.get("id_number") or
            ""
        ).strip()
        
        dob = (
            extracted.get("Date of Birth") or
            extracted.get("date_of_birth") or
            extracted.get("DOB") or
            ""
        ).strip()
        
        nationality = (
            extracted.get("Nationality") or
            extracted.get("nationality") or
            ""
        ).strip()
        
        print(f"\n[DEBUG] ✅ Extracted Values:")
        print(f"  - ID Number: '{id_number}' (empty: {not id_number})")
        print(f"  - DOB: '{dob}' (empty: {not dob})")
        print(f"  - Nationality: '{nationality}' (empty: {not nationality})")
        
        if not id_number or not dob or not nationality:
            missing = []
            if not id_number: missing.append("ID Number")
            if not dob: missing.append("Date of Birth")
            if not nationality: missing.append("Nationality")
            print(f"[ERROR] ❌ Missing fields: {', '.join(missing)}")
            return None
        
        return {
            "id_number": id_number,
            "dob": dob,
            "nationality": nationality
        }
    
    except Exception as e:
        print(f"[ERROR] Failed to read EID: {e}")
        import traceback
        traceback.print_exc()
        return None


def _format_date(dob: str) -> str:
    """Convert date to YYYY-MM-DD"""
    dob = dob.strip()
    
    print(f"[DEBUG] 📅 Formatting date: '{dob}'")
    
    # Already correct
    if len(dob) == 10 and dob[4] == '-' and dob[7] == '-':
        print(f"[DEBUG] ✅ Date already in correct format")
        return dob
    
    # DD/MM/YYYY
    if '/' in dob:
        parts = dob.split('/')
        if len(parts) == 3:
            day, month, year = parts
            formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            print(f"[DEBUG] ✅ Converted DD/MM/YYYY to: {formatted}")
            return formatted
    
    # DD-MM-YYYY
    elif '-' in dob and len(dob.split('-')[0]) <= 2:
        parts = dob.split('-')
        if len(parts) == 3:
            day, month, year = parts
            formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            print(f"[DEBUG] ✅ Converted DD-MM-YYYY to: {formatted}")
            return formatted
    
    print(f"[WARN] ⚠️ Could not parse date, returning as-is")
    return dob

def _save_surepass_result(email: str, result_data: dict) -> str:
    """
    Save SurePass API validation result to JSON file for audit trail
    
    Args:
        email: User's email
        result_data: Dictionary containing validation results
        
    Returns:
        Path to saved JSON file
    """
    try:
        user_docs_dir = Path(f"/app/backend/documents/id/{email}")
        user_docs_dir.mkdir(parents=True, exist_ok=True)
        
        save_path = user_docs_dir / "surepass_validation.json"
        
        print(f"[INFO] 💾 Saving SurePass result to: {save_path}")
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)
        
        print(f"[SUCCESS] ✅ SurePass result saved successfully")
        return str(save_path)
        
    except Exception as e:
        print(f"[ERROR] ❌ Failed to save SurePass result: {e}")
        import traceback
        traceback.print_exc()
        return ""


def _send_failure_email(email: str, user_name: str, error_message: str):
    """Send failure notification email"""
    try:
        from app.services.email_sender import send_email
        
        print(f"[INFO] 📧 Sending validation failure email to {email}")
        
        subject = "Emirates ID Verification Failed - Action Required"
        
        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; }}
        .content {{ background: #fff; padding: 30px; border: 1px solid #ddd; }}
        .alert {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ Emirates ID Verification Failed</h1>
        </div>
        <div class="content">
            <p>Dear {user_name},</p>
            
            <div class="alert">
                <strong>Validation Failed:</strong> {error_message}
            </div>
            
            <h3>Next Steps:</h3>
            <ol>
                <li>Check your Emirates ID information is correct</li>
                <li>Ensure the document is clear and readable</li>
                <li>Re-upload your Emirates ID</li>
            </ol>
            
            <p>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </div>
</body>
</html>
"""
        
        send_email(to_email=email, subject=subject, body=body, html=True)
        print(f"[SUCCESS] ✅ Email sent to {email}")
    
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
