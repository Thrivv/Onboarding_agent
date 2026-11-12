# backend/app/api/routes/register.py

from fastapi import APIRouter, HTTPException
import uuid
from datetime import date, datetime, timedelta
from typing import Optional, List
from app.services.supabase_client import supabase, get_user_by_email, insert_user
from app.services.email_sender import send_welcome_email
from app.services.message_generator import MessageGenerator
from app.services import bedrock_client
from app.services.auth_service import hash_password
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
import logging
from app.schemas.register import SignupRequest, SignupResponse, UserRegisterRequest, ConversationLog
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_IDENTIFICATION,
)
from app.domain.exceptions import (
    ConflictError,
    DomainError,
    ValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/register", tags=["register"])

# ============================================================================
# MODELS
# ============================================================================


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def validate_password_policy(password: str) -> Optional[str]:
    """
    Enforce the signup password policy server-side (mirrors the frontend's
    real-time checklist in Signup.jsx / validation.js). Returns None if the
    password passes, otherwise a human-readable message describing the
    first unmet rule.
    """
    import re

    if len(password) < 8:
        return "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return "Password must contain at least one special character"
    return None


def get_total_users() -> int:
    """Get total number of users"""
    try:
        result = UserRepository.count_all()
        return result.count if result.count else 0
    except Exception as e:
        logger.error(f"Failed to get total users: {e}")
        return 0

def get_verified_users_count() -> int:
    """Get count of verified users (onboarding complete)"""
    try:
        result = UserRepository.count_where("onboarding_step", "verification_complete")
        return result.count if result.count else 0
    except Exception as e:
        logger.error(f"Failed to get verified users: {e}")
        return 0

def get_users_registered_today() -> int:
    """Get count of users registered today"""
    try:
        today = datetime.utcnow().date().isoformat()
        result = UserRepository.count_created_since(today)
        return result.count if result.count else 0
    except Exception as e:
        logger.error(f"Failed to get today's registrations: {e}")
        return 0

def get_users_registered_this_week() -> int:
    """Get count of users registered this week"""
    try:
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        result = UserRepository.count_created_since(week_ago)
        return result.count if result.count else 0
    except Exception as e:
        logger.error(f"Failed to get week's registrations: {e}")
        return 0

def insert_conversation_log(log_data: dict):
    """Insert conversation log into database"""
    try:
        ConversationRepository.insert(log_data)
    except Exception as e:
        logger.error(f"Failed to insert conversation log: {e}")

def get_document_requirements_message(account_type: str, ownership_type: str = None) -> str:
    """Get document requirements message based on account flow"""
    if account_type == ACCOUNT_CORPORATE:
        if ownership_type == OWNERSHIP_SINGLE:
            return """
**ðŸ“‹ Required Documents:**
1. Emirates ID (EID)
2. Ejari (Tenancy Contract)
3. Trade License

Please log in to your account and upload all three documents to continue your onboarding."""
        elif ownership_type in [OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP]:
            return """
**ðŸ“‹ Required Documents:**
1. Memorandum of Association (MOA)
2. Trade License

To identify all owners/members, please first submit:
- Memorandum of Association (MOA)
- Trade License

After we identify all owners, we will request Emirates ID (EID) for each member individually.

**Note:** The number of EIDs required will depend on the number of owners listed in your Commercial License.

Please log in to your account and submit the required documents to continue your onboarding."""
    return ""

# ============================================================================
# SIGNUP ENDPOINT (NEW - PRIMARY)
# ============================================================================


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest):
    """
    New user signup with complete registration data
    Creates user account with password and starts onboarding process
    âœ… Now uses dynamic LLM-generated welcome messages
    """
    try:
        # Validate terms acceptance
        if not request.terms_accepted:
            raise ValidationError("You must accept the terms and conditions")

        # Validate password policy (8+ chars, uppercase, lowercase, number, special char)
        password_error = validate_password_policy(request.password)
        if password_error:
            raise ValidationError(password_error)

        # Check if email already exists
        existing_user = UserRepository.get_email_if_exists(request.email)
        if existing_user.data:
            raise ConflictError("Email already registered")

        # Derive display name from first_name + last_name
        full_name = request.name or f"{request.first_name} {request.last_name}".strip()

        # Generate unique Reference Number (ref_no) for this onboarding request.
        # All documents uploaded during this onboarding are named using this UUID.
        ref_no = str(uuid.uuid4())
        logger.info(f"Generated ref_no: {ref_no} for {request.email}")

        # Hash password using two-step SHA256 scheme
        password_hash = hash_password(request.password, request.email)

        # Determine initial onboarding step and document stage
        # (All Corporate ownership types currently resolve to the same values;
        # kept as explicit fields for future account-type-specific logic.)
        onboarding_step = "document_collection"
        document_stage = STAGE_IDENTIFICATION

        # Prepare user data for database
        user_data = {
            "email": request.email,
            "password_hash": password_hash,
            "first_name": request.first_name,
            "last_name": request.last_name,
            "name": full_name,
            "dob": request.dob.isoformat() if request.dob else None,
            "phone_number": request.phone_number,
            "business_name": request.business_name,
            "account_type": request.account_type,
            "ownership_type": request.ownership_type,
            "onboarding_step": onboarding_step,
            "document_stage": document_stage,
            "document_confirmation_sent": False,
            "role": "user",
            # Unique reference number shared across all documents for this user
            "ref_no": ref_no,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        # Add optional fields if present
        if request.partnership_details:
            user_data["partnership_details"] = request.partnership_details
        if request.nature_of_business:
            user_data["nature_of_business"] = request.nature_of_business
        if request.incorporation_country:
            user_data["incorporation_country"] = request.incorporation_country
        if request.incorporation_city:
            user_data["incorporation_city"] = request.incorporation_city

        # Insert user into database
        result = UserRepository.insert(user_data)
        if not result.data:
            raise DomainError("Failed to create user account")

        logger.info(f"[INFO] User account created: {request.email}")

        # Send welcome email
        try:
            send_welcome_email(request.email, full_name, request.account_type)
            logger.info(f"Welcome email sent to: {request.email}")
        except Exception as email_error:
            logger.warning(f"Failed to send welcome email: {email_error}")
            # Don't fail registration if email fails

        # ============================================================================
        # âœ… GENERATE DYNAMIC REGISTRATION WELCOME MESSAGE
        # ============================================================================
        try:
            welcome_msg = MessageGenerator.registration_welcome(
                user_name=full_name,
                account_type=request.account_type
            )
            logger.info(f"Dynamic registration message generated: {len(welcome_msg)} chars")
        except Exception as e:
            logger.warning(f"Registration welcome generation failed, using fallback: {e}")
            # Fallback to hardcoded message
            welcome_msg = f"Good to have you here, {full_name}. Your registration on DigiOB is complete — please log in to upload your documents."

        # Log conversation start with dynamic message
        try:
            ConversationRepository.insert({
                "user_email": request.email,
                "role": "agent",
                "message": welcome_msg,
                "timestamp": datetime.utcnow().isoformat()
            })
            logger.info(f"Registration welcome logged to conversations")
        except Exception as log_error:
            logger.warning(f"Failed to log conversation: {log_error}")
            # Don't fail registration if logging fails

        return SignupResponse(
            success=True,
            message="Account created successfully! Please login to continue.",
            user_email=request.email
        )

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=f"Registration failed: {str(e)}")


# ============================================================================
# DASHBOARD METRICS ENDPOINTS
# ============================================================================

@router.get("/get-total-users")
def total_users():
    """Get total number of registered users"""
    try:
        total_users = get_total_users()
        return {"total_users": total_users}
    except Exception as e:
        logger.error(f"Get total users error: {e}")
        raise DomainError(context=str(e))

@router.get("/get-verified-users-count")
def verified_user_count():
    """Get count of verified users"""
    try:
        verified_user_count = get_verified_users_count()
        return {"verified_users_count": verified_user_count}
    except Exception as e:
        logger.error(f"Get verified users error: {e}")
        raise DomainError(context=str(e))

@router.get("/get-pending-verification-count")
def pending_verification_count():
    """Get count of users pending verification"""
    try:
        total_users = get_total_users()
        verified_users = get_verified_users_count()
        pending_users = total_users - verified_users
        return {"pending_verification_count": pending_users}
    except Exception as e:
        logger.error(f"Get pending verification error: {e}")
        raise DomainError(context=str(e))

@router.get("/registered-today")
def users_registered_today():
    """Get count of users registered today"""
    try:
        users_today = get_users_registered_today()
        return {"users_registered_today": users_today}
    except Exception as e:
        logger.error(f"Get today's registrations error: {e}")
        raise DomainError(context=str(e))

@router.get("/regisetered-this-week")
def users_registered_this_week():
    """Get count of users registered this week"""
    try:
        users_this_week = get_users_registered_this_week()
        return {"users_registered_this_week": users_this_week}
    except Exception as e:
        logger.error(f"Get week's registrations error: {e}")
        raise DomainError(context=str(e))

# ============================================================================
# NEW DASHBOARD ENDPOINTS - USER LIST & STATS
# ============================================================================

@router.get("/list-users")
def list_all_users():
    """Get all users with basic info for admin dashboard"""
    try:
        result = UserRepository.list_directory()
        
        return {"users": result.data if result.data else []}
    except Exception as e:
        logger.error(f"List users error: {e}")
        raise DomainError(context=str(e))

@router.get("/account-type-summary")
def account_type_summary():
    """Get count of users by account type for charts"""
    try:
        corporate = UserRepository.count_where("account_type", ACCOUNT_CORPORATE)

        return {
            "account_types": [
                {"name": ACCOUNT_CORPORATE, "count": corporate.count or 0}
            ]
        }
    except Exception as e:
        logger.error(f"Account type summary error: {e}")
        raise DomainError(context=str(e))


@router.get("/bedrock-status")
def bedrock_status():
    """
    Real, on-demand AWS Bedrock connectivity check for the Dashboard's
    System Infrastructure panel. Deliberately NOT part of Docker's /health
    (see bedrock_client.check_connection docstring) — this runs a small
    live request against Bedrock only when the dashboard asks for it.
    """
    result = bedrock_client.check_connection()
    return {
        "bedrock_connected": result["connected"],
        "detail": result["detail"],
        "latency_ms": result["latency_ms"],
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/onboarding-summary")
def onboarding_summary():
    """Get count of users by onboarding step for charts"""
    try:
        steps = [
            "welcome",
            "document_collection",
            "document_verification",
            "verification_complete"
        ]
        
        summary = []
        for step in steps:
            result = UserRepository.count_where("onboarding_step", step)
            
            summary.append({
                "step": step.replace("_", " ").title(),
                "count": result.count or 0
            })
        
        return {"onboarding_steps": summary}
    except Exception as e:
        logger.error(f"Onboarding summary error: {e}")
        raise DomainError(context=str(e))