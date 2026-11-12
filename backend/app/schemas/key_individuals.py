"""
Key individual and UBO models.

Moved verbatim from app/api/routes/chatupload.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class MoaAsRequest(BaseModel):
    email: str
    language: Optional[str] = "english"
    member_role_map: Optional[dict] = None   # NEW: { "MEMBER NAME": "AS" | "MEMBER" }
    member_as_map:   Optional[dict] = None   # LEGACY: { "MEMBER NAME": true/false }


class KiFormRequest(BaseModel):
    email: str
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    email_address: Optional[str] = None
    country: Optional[str] = "UAE"
    country_code: Optional[str] = None
    mobile_number: str
    telephone_number: Optional[str] = None
    nationality: Optional[str] = None
    id_type: str   # "EID" or "PASSPORT"
    id_number: str
    id_expiry_date: Optional[str] = None
    authentication_type: Optional[str] = None
    date_of_birth: Optional[str] = None
    role: Optional[str] = None
    is_authorised_signatory: bool = False


class KiVerifyRequest(BaseModel):
    email: str
    ki_id: str
    document_id: str


class UboConfirmRequest(BaseModel):
    email: str
    member_name: str
    is_ubo: bool


class SoAsSelectionRequest(BaseModel):
    email: str
    owner_role:  str           = "AS"   # NEW: "AS" | "MEMBER"
    owner_is_as: Optional[bool] = None  # LEGACY: kept for backwards compat


class KiAiAddRequest(BaseModel):
    email:          str
    role:           str           # "AS" | "MEMBER"
    document_id:    str           # OCR doc folder ID for the already-uploaded EID
    extracted_data: dict          # OCR output (name_english, id_number, etc.)


class KiContactInfoRequest(BaseModel):
    email:            str
    ki_name:          str
    system_role:      str            # "Self Admin" | "Maker" | "Approver"
    contact_email:    str
    phone_number:     str            # e.g. "+971501234567"
    share_percentage: Optional[float] = None   # ownership %, e.g. 25.0


class KiLoopFinalizeRequest(BaseModel):
    email: str
