# app/api/__init__.py

from fastapi import APIRouter
from app.api.routes import register

api_router = APIRouter()
api_router.include_router(register.router, prefix="", tags=["Registration"])
