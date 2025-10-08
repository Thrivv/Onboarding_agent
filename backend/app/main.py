# app/main.py
from fastapi import FastAPI
from app.api import api_router

app = FastAPI(title="Onboarding Agent API")

app.include_router(api_router)
