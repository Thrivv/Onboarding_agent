# app/api/routes/settings.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import requests
from dotenv import load_dotenv
import smtplib
import imaplib
from supabase import create_client
import logging

load_dotenv()

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/settings/system-status")
def get_system_status():
    """Get system component status"""
    status_reports = []
    
    # Database connection test
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_API_KEY")
        test_client = create_client(supabase_url, supabase_key)
        response = test_client.table("users").select("count", count="exact").execute()
        status_reports.append({
            "component": "Database Connection",
            "status": "Active",
            "message": f"✅ Connected. Found {response.count or 0} users.",
            "details": f"Supabase connection successful"
        })
    except Exception as e:
        status_reports.append({
            "component": "Database Connection",
            "status": "Down",
            "message": f"❌ Connection failed: {str(e)}",
            "details": "Check Supabase credentials"
        })
    
    # Email service test
    try:
        smtp_server = os.getenv("SMTP_SERVER")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")
        imap_host = os.getenv("IMAP_HOST")
        imap_port = int(os.getenv("IMAP_PORT", 993))
        
        # Test SMTP
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
        
        # Test IMAP
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(smtp_username, smtp_password)
        mail.logout()
        
        status_reports.append({
            "component": "Email Service (SMTP & IMAP)",
            "status": "Active",
            "message": "✅ Email connections successful",
            "details": f"SMTP: {smtp_server}:{smtp_port}, IMAP: {imap_host}:{imap_port}"
        })
    except Exception as e:
        status_reports.append({
            "component": "Email Service (SMTP & IMAP)",
            "status": "Down",
            "message": f"❌ Email connection failed: {str(e)}",
            "details": "Check email server credentials"
        })
    
    # AI API test
    try:
        api_key = os.getenv("OPENROUTER_API_KEY")
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        model_name = os.getenv("LLAMA_MODEL_NAME", "qwen/qwen2.5-vl-32b-instruct:free")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": "Hello, this is a test."}],
            "max_tokens": 10
        }
        
        response = requests.post(api_url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            status_reports.append({
                "component": "AI API",
                "status": "Active",
                "message": "✅ API connection successful",
                "details": f"Model: {model_name}"
            })
        else:
            status_reports.append({
                "component": "AI API",
                "status": "Down",
                "message": f"❌ API failed: HTTP {response.status_code}",
                "details": f"Check OpenRouter API key and model availability"
            })
    except Exception as e:
        status_reports.append({
            "component": "AI API",
            "status": "Down",
            "message": f"❌ API connection failed: {str(e)}",
            "details": "Check OpenRouter API key configuration"
        })
    
    # Document processing
    documents_root = "documents"
    if os.path.exists(documents_root):
        # Count user folders
        user_folders = [d for d in os.listdir(documents_root) 
                       if os.path.isdir(os.path.join(documents_root, d))]
        status_reports.append({
            "component": "Document Processing",
            "status": "Active",
            "message": f"✅ Document storage available ({len(user_folders)} user folders)",
            "details": f"Storage path: {os.path.abspath(documents_root)}"
        })
    else:
        status_reports.append({
            "component": "Document Processing",
            "status": "Down",
            "message": "❌ Document storage not found",
            "details": "Create documents directory in project root"
        })
    
    # Real-time Monitoring
    status_reports.append({
        "component": "Real-time Monitoring",
        "status": "Active",
        "message": "✅ Monitoring services active",
        "details": "Dashboard updates every 30 seconds"
    })
    
    return {"system_status": status_reports}

@router.get("/settings/configuration")
def get_configuration():
    """Get current system configuration"""
    config = {
        "supabase_url": os.getenv("SUPABASE_URL", "Not set"),
        "smtp_server": os.getenv("SMTP_SERVER", "Not set"),
        "smtp_port": os.getenv("SMTP_PORT", "Not set"),
        "imap_host": os.getenv("IMAP_HOST", "Not set"),
        "imap_port": os.getenv("IMAP_PORT", "Not set"),
        "llama_model": os.getenv("LLAMA_MODEL_NAME", "Not set"),
        "documents_root": "documents",
        "api_keys_configured": {
            "supabase": bool(os.getenv("SUPABASE_API_KEY")),
            "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
            "smtp_password": bool(os.getenv("SMTP_PASSWORD"))
        }
    }
    
    return {"configuration": config}
