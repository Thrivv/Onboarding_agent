"""
FATCA, PEP and self-declaration models.

Moved verbatim from app/api/routes/chatupload.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class FatcaNoRequest(BaseModel):
    email: str
    language: Optional[str] = "english"


class FatcaYesRequest(BaseModel):
    email: str
    language: Optional[str] = "english"
    entity_type: Optional[str] = None
    country_of_tax_residence: Optional[str] = "UAE"
    passive_nffe_us_ownership: Optional[str] = None
    entity_incorporated_in_usa: Optional[str] = None
    entity_has_us_ownership: Optional[str] = None
    address_or_phone_in_usa: Optional[str] = None
    payment_instruction_to_usa: Optional[str] = None
    income_from_us_sources: Optional[str] = None
    irs_form_obtained: Optional[str] = None
    us_tax_id: Optional[str] = None


class PepRequest(BaseModel):
    email: str
    language: Optional[str] = "english"
    domestic_pep: Optional[dict] = None   # {status, name, position}
    foreign_pep:  Optional[dict] = None   # {status, country, name, position}


class SelfDeclConfirmRequest(BaseModel):
    email: str
    language: Optional[str] = "english"
