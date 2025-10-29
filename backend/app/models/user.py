# app/models/user.py

from pydantic import BaseModel, EmailStr
from datetime import date


class UserRegisterRequest(BaseModel):
    name: str
    dob: date
    phone_number: str
    email: EmailStr
    business_name: str
    account_type: str | None = None
    ownership_type: str | None = None
    partnership_details: str | None = None
    annual_turnover: str | None = None
    terms_accepted: bool | None = None
