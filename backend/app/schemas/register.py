"""
Registration and signup models.

Moved verbatim from app/api/routes/register.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    # ✅ Updated: first_name + last_name replace single 'name' field
    first_name: str
    last_name: str
    # ✅ name is computed from first_name + last_name; kept for backward compat
    name: Optional[str] = None
    # ✅ dob is now optional (NULL allowed)
    dob: Optional[date] = None
    phone_number: str
    business_name: str
    account_type: str
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    nature_of_business: Optional[List[str]] = None
    incorporation_country: Optional[str] = None
    incorporation_city: Optional[str] = None
    terms_accepted: bool


class SignupResponse(BaseModel):
    success: bool
    message: str
    user_email: str


class UserRegisterRequest(BaseModel):
    """Legacy model for backward compatibility"""
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    name: Optional[str] = None
    dob: Optional[date] = None        # ✅ optional
    phone_number: str
    business_name: str
    account_type: str
    ownership_type: Optional[str] = None
    partnership_details: Optional[str] = None
    terms_accepted: bool = True


class ConversationLog(BaseModel):
    user_email: str
    role: str
    message: str
    timestamp: datetime
