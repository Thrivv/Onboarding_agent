"""
Core conversational onboarding models.

Moved verbatim from app/api/routes/chatupload.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, EmailStr


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str


class StartConversationRequest(BaseModel):
    email: EmailStr
    language: str = "english"


class ChatConversationalRequest(BaseModel):
    email: EmailStr
    message: str
    language: str = "english"
    chat_history: Optional[List[ChatMessage]] = []


class UploadConversationalResponse(BaseModel):
    success: bool
    message: str
    document_type: Optional[str] = None
    is_complete: bool
    awaiting_verification: bool
    next_document: Optional[str] = None


class OnboardingStatusResponse(BaseModel):
    stage: str
    required_documents: List[str]
    submitted_documents: List[dict]
    pending_documents: List[str]
    next_required_document: Optional[dict]
    members_info: Optional[dict]
    ai_message: str
    is_complete: bool


class ValidateRefRequest(BaseModel):
    reference_number: str
    user_email: str   # must match the session owner for security


class CrossValidationRequest(BaseModel):
    email: str
    language: Optional[str] = "english"
