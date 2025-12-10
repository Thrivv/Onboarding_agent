# backend/app/api/routes/register.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
import bcrypt
from datetime import date, datetime, timedelta
from typing import Optional
from app.services.supabase_client import supabase, get_user_by_email, insert_user
from app.services.email_sender import send_welcome_email

router = APIRouter(prefix="/register", tags=["register"])

# ============================================================================
# MODELS
# ============================================================================

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    dob: date
    phone_number: str
    business_name: str
    account_type: str
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    annual_turnover: Optional[str] = None
    terms_accepted: bool

class SignupResponse(BaseModel):
    success: bool
    message: str
    user_email: str

class UserRegisterRequest(BaseModel):
    """Legacy model for backward compatibility"""
    email: EmailStr
    name: str
    dob: date
    phone_number: str
    business_name: str
    account_type: str
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    annual_turnover: Optional[str] = None
    terms_accepted: bool = True

class ConversationLog(BaseModel):
    user_email: str
    role: str
    message: str
    timestamp: datetime

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_total_users() -> int:
    """Get total number of users"""
    try:
        result = supabase.table("users").select("id", count="exact").execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"[ERROR] Failed to get total users: {e}")
        return 0

def get_verified_users_count() -> int:
    """Get count of verified users (onboarding complete)"""
    try:
        result = supabase.table("users").select("id", count="exact").eq(
            "onboarding_step", "verification_complete"
        ).execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"[ERROR] Failed to get verified users: {e}")
        return 0

def get_users_registered_today() -> int:
    """Get count of users registered today"""
    try:
        today = datetime.utcnow().date().isoformat()
        result = supabase.table("users").select("id", count="exact").gte(
            "created_at", today
        ).execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"[ERROR] Failed to get today's registrations: {e}")
        return 0

def get_users_registered_this_week() -> int:
    """Get count of users registered this week"""
    try:
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        result = supabase.table("users").select("id", count="exact").gte(
            "created_at", week_ago
        ).execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"[ERROR] Failed to get week's registrations: {e}")
        return 0

def insert_conversation_log(log_data: dict):
    """Insert conversation log into database"""
    try:
        supabase.table("conversations").insert(log_data).execute()
    except Exception as e:
        print(f"[ERROR] Failed to insert conversation log: {e}")

def get_document_requirements_message(account_type: str, ownership_type: str = None) -> str:
    """Get document requirements message based on account flow"""
    if account_type == "Savings":
        return """
**📋 Required Documents:**
1. Emirates ID (EID)
2. Ejari (Tenancy Contract)

Please log in to your account and upload both documents to continue your onboarding."""
    elif account_type == "Corporate":
        if ownership_type == "Single Owner":
            return """
**📋 Required Documents:**
1. Emirates ID (EID)
2. Ejari (Tenancy Contract)
3. Trade License

Please log in to your account and upload all three documents to continue your onboarding."""
        elif ownership_type in ["Multiple Owners", "Partnership"]:
            return """
**📋 Required Documents:**
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
    """
    try:
        # Validate terms acceptance
        if not request.terms_accepted:
            raise HTTPException(
                status_code=400,
                detail="You must accept the terms and conditions"
            )

        # Check if email already exists
        existing_user = supabase.table("users").select("email").eq(
            "email", request.email
        ).execute()
        if existing_user.data:
            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(
            request.password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        # Determine initial onboarding step and document stage
        if request.account_type == "Savings":
            onboarding_step = "document_collection"
            document_stage = "identification"
        elif request.account_type == "Corporate":
            if request.ownership_type == "Single Owner":
                onboarding_step = "document_collection"
                document_stage = "identification"
            else:
                onboarding_step = "document_collection"
                document_stage = "identification"
        else:
            onboarding_step = "welcome"
            document_stage = "identification"

        # Prepare user data for database
        user_data = {
            "email": request.email,
            "password_hash": password_hash,
            "name": request.name,
            "dob": request.dob.isoformat(),
            "phone_number": request.phone_number,
            "business_name": request.business_name,
            "account_type": request.account_type,
            "ownership_type": request.ownership_type,
            "onboarding_step": onboarding_step,
            "document_stage": document_stage,
            "document_confirmation_sent": False,
            "role": "user",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        # Add optional fields if present
        if request.partnership_details:
            user_data["partnership_details"] = request.partnership_details
        if request.annual_turnover:
            user_data["annual_turnover"] = request.annual_turnover

        # Insert user into database
        result = supabase.table("users").insert(user_data).execute()
        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Failed to create user account"
            )

        # Build welcome email content
        doc_requirements = get_document_requirements_message(
            request.account_type,
            request.ownership_type
        )

        email_details = f"""
Welcome to Thrivv, **{request.name}**!

**📝 Your Registration Details:**
- Account Type: {request.account_type}
- Business Name: {request.business_name}

{doc_requirements}

If you have any questions, feel free to contact our support team."""

        # Send welcome email
        try:
            send_welcome_email(request.email, email_details, request.account_type)
        except Exception as email_error:
            print(f"[WARN] Failed to send welcome email: {email_error}")

        # Log conversation start
        try:
            supabase.table("conversations").insert({
                "user_email": request.email,
                "role": "agent",
                "message": f"Welcome {request.name}! Your {request.account_type} account registration is complete. Please proceed to upload your documents.",
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        except Exception as log_error:
            print(f"[WARN] Failed to log conversation: {log_error}")

        return SignupResponse(
            success=True,
            message="Account created successfully! Please login to continue.",
            user_email=request.email
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Signup error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Registration failed: {str(e)}"
        )

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
        print(f"[ERROR] Get total users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get-verified-users-count")
def verified_user_count():
    """Get count of verified users"""
    try:
        verified_user_count = get_verified_users_count()
        return {"verified_users_count": verified_user_count}
    except Exception as e:
        print(f"[ERROR] Get verified users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get-pending-verification-count")
def pending_verification_count():
    """Get count of users pending verification"""
    try:
        total_users = get_total_users()
        verified_users = get_verified_users_count()
        pending_users = total_users - verified_users
        return {"pending_verification_count": pending_users}
    except Exception as e:
        print(f"[ERROR] Get pending verification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/registered-today")
def users_registered_today():
    """Get count of users registered today"""
    try:
        users_today = get_users_registered_today()
        return {"users_registered_today": users_today}
    except Exception as e:
        print(f"[ERROR] Get today's registrations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/regisetered-this-week")
def users_registered_this_week():
    """Get count of users registered this week"""
    try:
        users_this_week = get_users_registered_this_week()
        return {"users_registered_this_week": users_this_week}
    except Exception as e:
        print(f"[ERROR] Get week's registrations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# NEW DASHBOARD ENDPOINTS - USER LIST & STATS
# ============================================================================

@router.get("/list-users")
def list_all_users():
    """Get all users with basic info for admin dashboard"""
    try:
        result = supabase.table("users").select(
            "id, email, name, role, account_type, ownership_type, "
            "onboarding_step, created_at"
        ).order("created_at", desc=True).execute()
        
        return {"users": result.data if result.data else []}
    except Exception as e:
        print(f"[ERROR] List users error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account-type-summary")
def account_type_summary():
    """Get count of users by account type for charts"""
    try:
        savings = supabase.table("users").select("id", count="exact").eq(
            "account_type", "Savings"
        ).execute()
        
        corporate = supabase.table("users").select("id", count="exact").eq(
            "account_type", "Corporate"
        ).execute()
        
        return {
            "account_types": [
                {"name": "Savings", "count": savings.count or 0},
                {"name": "Corporate", "count": corporate.count or 0}
            ]
        }
    except Exception as e:
        print(f"[ERROR] Account type summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            result = supabase.table("users").select("id", count="exact").eq(
                "onboarding_step", step
            ).execute()
            
            summary.append({
                "step": step.replace("_", " ").title(),
                "count": result.count or 0
            })
        
        return {"onboarding_steps": summary}
    except Exception as e:
        print(f"[ERROR] Onboarding summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
