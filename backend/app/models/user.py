# app/models/user.py

from pydantic import BaseModel, EmailStr
from datetime import date

class UserRegisterRequest(BaseModel):
    name: str
    dob: date
    phone_number: str
    email: EmailStr
    business_name: str
