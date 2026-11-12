"""
Ownership type and role-mismatch models.

Moved verbatim from app/api/routes/chatupload.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class OwnershipTypeSaveRequest(BaseModel):
    email: str
    ownership_type: str          # "Single Owner" | "Partnership" | "Multiple Owners"
    partnership_details: Optional[str] = None  # only meaningful when not "Single Owner"


class MismatchRoleRequest(BaseModel):
    email: str
    extracted_name: str
    extracted_business_name: Optional[str] = None
    assigned_role: str   # "authorized_signatory" | "key_individual"
    mobile_number: Optional[str] = ""
    id_type: Optional[str] = "EID"
    id_number: Optional[str] = ""
