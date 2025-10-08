# app/api/__init__.py
from fastapi import APIRouter
from app.api.routes.register import router as register_router
from app.api.routes.chat import router as chat_router  # ADD THIS

api_router = APIRouter()

api_router.include_router(register_router, tags=["registration"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])  # ADD THIS