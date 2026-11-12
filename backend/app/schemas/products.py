"""
Product package models.

Moved verbatim from app/api/routes/chatupload.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProductPackageSaveRequest(BaseModel):
    email:            str
    selected_package: str   # "Essential" | "Plus" | "Advanced"
    availed_products: list  # list of product name strings
