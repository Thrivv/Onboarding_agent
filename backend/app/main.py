# backend/app/main.py - FIXED VERSION

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import chat, chatupload, register, documentpage, auth

app = FastAPI(title="Thrivv Onboarding Agent API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3030",
        "http://localhost:3030",
        "http://frontend:3030",
        "http://172.18.0.3:3030",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers with proper prefixes
app.include_router(auth.router)  # Auth routes (login/logout) - NO PREFIX
app.include_router(register.router)  # Register routes (signup) - NO PREFIX
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(chatupload.router)  # ✅ FIXED: No prefix, chatupload has its own
app.include_router(documentpage.router)  # ✅ FIXED: No prefix, documentpage has its own

@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "API is running"}

@app.get("/")
async def root():
    return {
        "message": "Thrivv Onboarding Agent API",
        "version": "2.0.0",
        "docs": "/docs"
    }