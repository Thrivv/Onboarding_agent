# app/api/__init__.py

from fastapi import APIRouter
from app.api.routes import register, dashboard, chatbot, email_system, settings, users

api_router = APIRouter()

# Include all route modules
api_router.include_router(register.router, tags=["Registration"])
api_router.include_router(dashboard.router, tags=["Dashboard"])
api_router.include_router(chatbot.router, tags=["Chatbot"])
api_router.include_router(email_system.router, tags=["Email System"])
api_router.include_router(settings.router, tags=["Settings"])
api_router.include_router(users.router, tags=["Users"])
