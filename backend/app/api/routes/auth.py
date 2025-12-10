# backend/app/api/routes/auth.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
#import generate_admin_hash
import uuid
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
import logging
import os
from supabase import create_client, Client

# Setup logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    phone_number: Optional[str] = None
    dob: Optional[str] = None
    business_name: Optional[str] = None
    account_type: Optional[str] = "Savings"
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    annual_turnover: Optional[str] = None
    terms_accepted: bool = False

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LogoutRequest(BaseModel):
    session_id: str

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt with 12 rounds"""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password, salt).decode('utf-8')
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash - FIXED VERSION"""
    try:
        logger.info(f"[AUTH] 🔐 Starting password verification")
        logger.info(f"[AUTH] 📏 Password length: {len(plain_password)}")
        logger.info(f"[AUTH] 📏 Hash length: {len(hashed_password)}")
        logger.info(f"[AUTH] 🔑 Hash starts with: {hashed_password[:10]}")
        
        # CRITICAL: Encode strings to bytes
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = hashed_password.encode('utf-8')
        
        # Verify with bcrypt
        is_valid = bcrypt.checkpw(password_bytes, hash_bytes)
        
        logger.info(f"[AUTH] {'✅' if is_valid else '❌'} Verification result: {is_valid}")
        return is_valid
        
    except ValueError as ve:
        logger.error(f"[AUTH] ❌ ValueError during verification: {str(ve)}")
        logger.error(f"[AUTH] 💡 Hash might be corrupted or invalid format")
        return False
    except Exception as e:
        logger.error(f"[AUTH] ❌ Unexpected error: {type(e).__name__}: {str(e)}")
        return False

def create_session(user_id: str, email: str) -> dict:
    """Create a new session for user"""
    try:
        session_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "email": email,
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
            "is_active": True,
            "last_activity": datetime.utcnow().isoformat()
        }
        
        response = supabase.table("sessions").insert(session_data).execute()
        logger.info(f"[AUTH] ✅ Session created: {session_id[:8]}...")
        
        return {
            "session_id": session_id,
            "expires_at": expires_at.isoformat()
        }
    except Exception as e:
        logger.error(f"[AUTH] ❌ Session creation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create session")

# ============================================================================
# ROUTES
# ============================================================================

@router.post("/signup")
async def signup(request: SignupRequest):
    """Register a new user"""
    try:
        logger.info(f"[SIGNUP] 📝 New signup: {request.email}")
        
        # Check existing user
        existing = supabase.table("users").select("*").eq("email", request.email).execute()
        
        if existing.data:
            logger.warning(f"[SIGNUP] ⚠️ Email exists: {request.email}")
            raise HTTPException(status_code=409, detail="Email already registered")
        
        # Hash password
        password_hash = hash_password(request.password)
        logger.info(f"[SIGNUP] 🔐 Password hashed: {password_hash[:20]}...")
        
        # Prepare user data
        user_data = {
            "email": request.email,
            "password_hash": password_hash,
            "name": request.name,
            "phone_number": request.phone_number,
            "dob": request.dob,
            "business_name": request.business_name,
            "account_type": request.account_type,
            "ownership_type": request.ownership_type,
            "partnership_details": request.partnership_details,
            "annual_turnover": request.annual_turnover,
            "role": "user",
            "onboarding_step": "welcome",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Insert user
        response = supabase.table("users").insert(user_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        logger.info(f"[SIGNUP] ✅ User created: {request.email}")
        
        return {
            "success": True,
            "message": "Account created successfully",
            "email": request.email
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SIGNUP] ❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/login")
async def login(request: LoginRequest):
    """Authenticate user and create session"""
    try:
        logger.info(f"[LOGIN] 🔐 Login attempt: {request.email}")
        
        # Fetch user
        response = supabase.table("users").select("*").eq("email", request.email).execute()
        
        if not response.data:
            logger.warning(f"[LOGIN] ⚠️ User not found: {request.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        user = response.data[0]
        logger.info(f"[LOGIN] ✅ User found: {user['email']}")
        logger.info(f"[LOGIN] 👤 Role: {user.get('role', 'user')}")
        logger.info(f"[LOGIN] 🆔 User ID: {user['id']}")
        
        # Check password hash exists
        stored_hash = user.get("password_hash")
        if not stored_hash:
            logger.error(f"[LOGIN] ❌ No password hash for: {request.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        logger.info(f"[LOGIN] 🔍 Hash from DB: {stored_hash[:30]}...")
        
        # Verify password
        logger.info(f"[LOGIN] 🔐 Verifying password...")
        is_valid = verify_password(request.password, stored_hash)
        
        if not is_valid:
            logger.warning(f"[LOGIN] ❌ Invalid password for: {request.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        logger.info(f"[LOGIN] ✅ Password correct!")
        
        # Create session
        session = create_session(user["id"], user["email"])
        
        logger.info(f"[LOGIN] 🎉 Login successful: {user['email']} ({user.get('role')})")
        
        return {
            "success": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name"),
                "role": user.get("role", "user")
            },
            "session_id": session["session_id"],
            "expires_at": session["expires_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[LOGIN] ❌ Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/logout")
async def logout(request: LogoutRequest):
    """Invalidate session"""
    try:
        logger.info(f"[LOGOUT] 🚪 Session: {request.session_id[:8]}...")
        
        response = supabase.table("sessions")\
            .update({"is_active": False})\
            .eq("session_id", request.session_id)\
            .execute()
        
        logger.info(f"[LOGOUT] ✅ Session invalidated")
        
        return {
            "success": True,
            "message": "Logged out successfully"
        }
        
    except Exception as e:
        logger.error(f"[LOGOUT] ❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/verify-session")
async def verify_session(session_id: str):
    """Verify session validity"""
    try:
        logger.info(f"[VERIFY] 🔍 Checking: {session_id[:8]}...")
        
        response = supabase.table("sessions")\
            .select("*")\
            .eq("session_id", session_id)\
            .eq("is_active", True)\
            .execute()
        
        if not response.data:
            return {"success": False, "message": "Invalid session"}
        
        session = response.data[0]
        expires_at = datetime.fromisoformat(session["expires_at"].replace('Z', '+00:00'))
        
        if expires_at < datetime.utcnow().replace(tzinfo=expires_at.tzinfo):
            return {"success": False, "message": "Session expired"}
        
        # Update last activity
        supabase.table("sessions")\
            .update({"last_activity": datetime.utcnow().isoformat()})\
            .eq("session_id", session_id)\
            .execute()
        
        return {
            "success": True,
            "session": {
                "email": session["email"],
                "user_id": session["user_id"]
            }
        }
        
    except Exception as e:
        logger.error(f"[VERIFY] ❌ Error: {str(e)}")
        return {"success": False, "message": str(e)}