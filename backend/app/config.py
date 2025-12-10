# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()  # Load from .env file in project root

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# SMTP settings
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))  # Default 587
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL")

if not SUPABASE_URL or not SUPABASE_API_KEY:
    raise ValueError("Supabase credentials are not set in the .env file")
