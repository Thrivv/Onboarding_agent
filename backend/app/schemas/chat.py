"""
Legacy chat endpoint models.

Moved verbatim from app/api/routes/chat.py in Stage B1 — these were
declared inline among the route handlers, several of them past line 7000.
Field definitions are unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class ChatRequest(BaseModel):
    email: EmailStr
    message: str


class ChatResponse(BaseModel):
    response: str
    success: bool


class UserVerifyRequest(BaseModel):
    email: EmailStr


class ResumeRequest(BaseModel):
    ref_id: str
