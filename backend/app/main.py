# app/main.py
from fastapi import FastAPI
from app.api import api_router
from app.api.routes import chat, chatupload, register


app = FastAPI(title="Onboarding Agent API")

app.include_router(api_router)
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(chatupload.router, prefix="/chat", tags=["chat"])
app.include_router(register.router, prefix="/register", tags=["register"])
