"""
Document upload, status and listing models.

Moved verbatim from app/api/routes/documentpage.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, EmailStr


class GetDocumentRequirementsRequest(BaseModel):
    email: EmailStr


class DocumentUploadRequest(BaseModel):
    email: EmailStr
    member_name: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    success: bool
    message: str
    document_type: Optional[str] = None
    extracted_data: Optional[dict] = None
    is_valid: bool
    is_complete: bool
    awaiting_verification: bool
    next_document: Optional[dict] = None
    remaining_documents: Optional[List[str]] = None
    wrong_document_type: bool = False
    document_file_path: Optional[str] = None
    cross_validation_passed: Optional[bool] = None
    cross_validation_errors: Optional[List[str]] = None
    
    decision: Optional[str] = None
    test_report_id: Optional[str] = None
    tampering_detected: Optional[bool] = None
    manual_review_required: Optional[bool] = None
    llm_analysis: Optional[str] = None
    tampering_score: Optional[float] = None
    
    filename: Optional[str] = None
    uploaded_at: Optional[str] = None
    expiry_failed: Optional[bool] = None
    expiry_validation: Optional[dict] = None
    version: Optional[int] = None
    status_category: Optional[str] = None
    ai_reasoning: Optional[str] = None
    updated_member_progress: Optional[dict] = None
    error_display: Optional[dict] = None
    # ── v4 additions ──────────────────────────────────────────────────────────
    fatca_trigger: Optional[bool] = None
    pep_trigger: Optional[bool] = None
    mismatch_detected: Optional[bool] = None
    mismatch_extracted_name: Optional[str] = None
    mismatch_extracted_business: Optional[str] = None

    class Config:
        extra = "ignore"


class DocumentStatusResponse(BaseModel):
    email: str
    documents: List[dict]
    remaining_documents: List[str]
    is_complete: bool
    stage: str
    members_info: Optional[dict] = None


class MemberListResponse(BaseModel):
    email: str
    members: List[dict]
    total: int
    verified: int
