# backend/app/api/routes/auth.py

from fastapi import APIRouter, HTTPException, Header, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
import uuid
import html
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging
from app.services.supabase_client import supabase
from app.services.email_sender import send_welcome_email
from app.services.auth_service import hash_password, verify_password
from app.schemas.auth import SignupRequest, UserResponse, SignupResponse, LoginRequest, LogoutRequest
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
)
from app.domain.exceptions import (
    AuthError,
    ConflictError,
    DomainError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# hash_password and verify_password imported from app.services.auth_service

def create_session(user_id: str, email: str) -> dict:
    """Create a new session for user"""
    try:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=24)

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "email": email,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "is_active": True,
            "last_activity": now.isoformat(),
        }

        SessionRepository.create(session_data)
        logger.info(f"[AUTH] Session created: {session_id[:8]}...")

        return {
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
        }
    except Exception as e:
        logger.error(f"[AUTH] Session creation failed: {str(e)}")
        raise DomainError("Failed to create session")

# ============================================================================
# ROUTES
# ============================================================================

@router.post("/signup", response_model=SignupResponse)
@limiter.limit("10/hour")
async def signup(request: Request, body: SignupRequest):
    """
    Register a new user account

    Flow:
    1. Validate user doesn't exist
    2. Hash password
    3. Create user in database
    4. Send welcome email (simplified HTML email)
    5. Return success response
    """
    try:
        logger.info(f"[SIGNUP] Registration attempt for: {body.email}")
        
        # ============================================================
        # 1. CHECK IF USER EXISTS
        # ============================================================
        existing = UserRepository.get_by_email(body.email)
        
        if existing.data:
            logger.warning(f"[SIGNUP] Email already exists: {body.email}")
            raise ConflictError("Email already registered. Please login or use a different email.")
        
        # ============================================================
        # 2. HASH PASSWORD
        # ============================================================
        password_hash = hash_password(body.password, body.email)
        logger.info(f"[SIGNUP] Password hashed for {body.email}")
        
        # ============================================================
        # 3. PREPARE USER DATA
        # ============================================================
        # ✅ Derive display name
        full_name = body.name or f"{body.first_name} {body.last_name}".strip()

        user_data = {
            "email": body.email,
            "password_hash": password_hash,
            "first_name": body.first_name,
            "last_name": body.last_name,
            "name": full_name,
            "phone_number": body.phone_number,
            "dob": body.dob or None,   # ✅ NULL if not provided
            "business_name": body.business_name,
            "account_type": body.account_type,
            "ownership_type": body.ownership_type,
            "partnership_details": body.partnership_details,
            "annual_turnover": body.annual_turnover,
            "role": "user",
            "onboarding_step": "welcome",
            "onboarding_complete": False,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # ============================================================
        # 4. INSERT USER INTO DATABASE
        # ============================================================
        response = UserRepository.insert(user_data)
        
        if not response.data:
            logger.error(f"[SIGNUP] Database insertion failed for {body.email}")
            raise DomainError("Failed to create user account. Please try again.")
        
        user = response.data[0]
        logger.info(f"[SIGNUP] User created: ID={user.get('id')}, Email={body.email}")
        
        # ============================================================
        # 5. BUILD REGISTRATION DETAILS & SEND WELCOME EMAIL
        # ============================================================
        try:
            logger.info(f"[SIGNUP] Preparing welcome email for {body.email}...")
            
            # Build HTML details string — escape all user-supplied values
            safe_email = html.escape(body.email)
            safe_name = html.escape(full_name)
            safe_account_type = html.escape(body.account_type or "")

            details_html = f"""
            <strong>Your Registration Details:</strong><br><br>
            <strong>📧 Email:</strong> {safe_email}<br>
            <strong>👤 Name:</strong> {safe_name}<br>
            <strong>🏦 Account Type:</strong> {safe_account_type}<br>
            """

            # Add business name if provided
            if body.business_name:
                details_html += f"<strong>🏢 Business Name:</strong> {html.escape(body.business_name)}<br>"

            # Add ownership type if provided
            if body.ownership_type:
                details_html += f"<strong>👥 Ownership Type:</strong> {html.escape(body.ownership_type)}<br>"
            
            details_html += "<br><strong>📋 Required Documents:</strong><br>"
            
            # Add document requirements based on account type
            if body.account_type == ACCOUNT_CORPORATE and body.ownership_type == OWNERSHIP_SINGLE:
                details_html += """
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>📄 Commercial License (Trade License)</li>
                    <li>📇 Emirates ID (Owner)</li>
                    <li>🏠 Ejari (Tenancy Contract Registration)</li>
                </ul>
                """
            elif body.account_type == ACCOUNT_CORPORATE and body.ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
                details_html += """
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>📄 Commercial License (Trade License)</li>
                    <li>📋 Memorandum of Association (MOA)</li>
                    <li>📇 Emirates ID (All Partners and Managers)</li>
                </ul>
                """
            else:
                details_html += """
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>📋 All required business documentation</li>
                </ul>
                """
            
            details_html += """
            <br>
            <strong>🔐 Next Step:</strong><br>
            Log in to your account and upload the required documents to complete your onboarding.
            """
            
            # Send welcome email with details
            email_sent = send_welcome_email(
                to_email=body.email,
                details=details_html
            )
            
            if email_sent:
                logger.info(f"[SIGNUP] Welcome email sent successfully to {body.email}")
            else:
                logger.warning(f"[SIGNUP] Email send returned False for {body.email}")
                
        except Exception as email_error:
            logger.error(f"[SIGNUP] Email error: {str(email_error)}")
            import traceback
            logger.error(traceback.format_exc())
            # Don't fail signup if email fails - user is already created
            logger.info(f"[SIGNUP] Continuing signup despite email failure")
        
        # ============================================================
        # 6. RETURN SUCCESS RESPONSE
        # ============================================================
        return SignupResponse(
            success=True,
            message="Account created successfully! Please check your email for next steps.",
            user=UserResponse(
                id=str(user.get("id")),
                email=user.get("email"),
                name=user.get("name", full_name),
                account_type=user.get("account_type", ACCOUNT_CORPORATE),
                onboarding_step=user.get("onboarding_step", "welcome")
            )
        )
        
    except (HTTPException, DomainError):
        raise
        
    except Exception as e:
        logger.error(f"[SIGNUP] Unexpected error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=f"Signup failed: {str(e)}")


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    """Authenticate user and create session"""
    try:
        logger.info(f"[LOGIN] Login attempt: {body.email}")

        # Fetch user
        response = UserRepository.get_by_email(body.email)

        if not response.data:
            logger.warning(f"[LOGIN] User not found: {body.email}")
            raise AuthError("Invalid email or password")

        user = response.data[0]
        logger.info(f"[LOGIN] User found: {user['email']}")
        logger.info(f"[LOGIN] Role: {user.get('role', 'user')}")
        logger.info(f"[LOGIN] User ID: {user['id']}")

        # Check password hash exists
        stored_hash = user.get("password_hash")
        if not stored_hash:
            logger.error(f"[LOGIN] No password hash for: {body.email}")
            raise AuthError("Invalid email or password")

        logger.info(f"[LOGIN] Hash from DB: {stored_hash[:30]}...")

        # Verify password
        logger.info(f"[LOGIN] Verifying password...")
        is_valid = verify_password(body.password, body.email, stored_hash)
        
        if not is_valid:
            logger.warning(f"[LOGIN] Invalid password for: {body.email}")
            raise AuthError("Invalid email or password")
        
        logger.info(f"[LOGIN] Password correct!")
        
        # Create session
        session = create_session(user["id"], user["email"])
        
        logger.info(f"[LOGIN] Login successful: {user['email']} ({user.get('role')})")
        
        # Build display name: prefer 'name' column, fall back to first+last, then email prefix
        first = user.get("first_name") or ""
        last  = user.get("last_name") or ""
        display_name = (
            user.get("name")
            or f"{first} {last}".strip()
            or user["email"].split("@")[0]
        )

        return {
            "success": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": display_name,
                "first_name": first,
                "last_name": last,
                "role": user.get("role", "user"),
                "account_type": user.get("account_type", ACCOUNT_CORPORATE),
                "ownership_type": user.get("ownership_type") or ""
            },
            "session_id": session["session_id"],
            "expires_at": session["expires_at"]
        }
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[LOGIN] Unexpected error: {str(e)}")
        raise DomainError(context=str(e))

@router.post("/logout")
async def logout(request: LogoutRequest):
    """Invalidate session"""
    try:
        logger.info(f"[LOGOUT] Session: {request.session_id[:8]}...")
        
        response = SessionRepository.deactivate(request.session_id)
        
        logger.info(f"[LOGOUT] Session invalidated")
        
        return {
            "success": True,
            "message": "Logged out successfully"
        }
        
    except Exception as e:
        logger.error(f"[LOGOUT] Error: {str(e)}")
        raise DomainError(context=str(e))

@router.get("/verify-session")
async def verify_session(x_session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """Verify session validity — session ID read from X-Session-ID header"""
    try:
        if not x_session_id:
            return {"success": False, "message": "No session provided"}

        logger.info(f"[VERIFY] Checking: {x_session_id[:8]}...")

        response = SessionRepository.get_active(x_session_id)

        if not response.data:
            return {"success": False, "message": "Invalid session"}

        session = response.data[0]
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))

        if expires_at < now:
            SessionRepository.deactivate(x_session_id)
            return {"success": False, "message": "Session expired"}

        SessionRepository.touch(x_session_id, now.isoformat())

        return {
            "success": True,
            "session": {
                "email": session["email"],
                "user_id": session["user_id"],
            },
        }

    except Exception as e:
        logger.error(f"[VERIFY] Error: {str(e)}")
        return {"success": False, "message": "Session verification failed"}