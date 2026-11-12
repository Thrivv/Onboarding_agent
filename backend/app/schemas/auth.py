"""
Authentication request/response models.

Moved verbatim from app/api/routes/auth.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr
from app.domain.onboarding.stage_table import ACCOUNT_CORPORATE


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    # ✅ Updated: split name fields; name computed if omitted
    first_name: str
    last_name: str
    name: Optional[str] = None
    phone_number: Optional[str] = None
    dob: Optional[str] = None         # ✅ optional — NULL allowed in DB
    business_name: Optional[str] = None
    account_type: Optional[str] = ACCOUNT_CORPORATE
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    annual_turnover: Optional[str] = None
    terms_accepted: bool = False


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    account_type: str
    onboarding_step: str


class SignupResponse(BaseModel):
    success: bool
    message: str
    user: UserResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LogoutRequest(BaseModel):
    # Optional now that the session id travels as an httpOnly cookie rather
    # than something the frontend can read out of localStorage and send back
    # in the body. Kept as a fallback for any caller that still supplies it.
    session_id: Optional[str] = None


class RequestPasswordResetRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
