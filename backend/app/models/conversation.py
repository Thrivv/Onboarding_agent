# app/models/conversation.py

from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Literal

class ConversationLog(BaseModel):
    user_email: EmailStr
    role: Literal["user", "agent"]
    message: str
    timestamp: datetime
