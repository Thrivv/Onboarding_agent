"""
GrowX integration models.

Moved verbatim from app/api/routes/growx_integration.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, EmailStr


class SubmitToGrowxRequest(BaseModel):
    email: EmailStr
    supported_countries: Optional[str] = "AE"
    mobile_code: Optional[str] = "+971"
    country_code: Optional[str] = "AE"
    is_whatsapp_notify: Optional[str] = "N"


class SubmitToGrowxResponse(BaseModel):
    success: bool
    message: str
    api1_user_create: Optional[dict] = None
    api2_set_password: Optional[dict] = None
    api3_sme_create: Optional[dict] = None
    errors: Optional[list] = None
