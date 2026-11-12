"""
One-time-password models.

Moved verbatim from app/api/routes/otp.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class GenerateOTPRequest(BaseModel):
    email: EmailStr


class GenerateOTPResponse(BaseModel):
    success: bool
    message: str


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str


class VerifyOTPResponse(BaseModel):
    success: bool
    message: str
