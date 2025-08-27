# app/api/routes/email_system.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.services.supabase_client import supabase
from datetime import datetime, timezone, timedelta
import imaplib
import email
from email.header import decode_header
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
import logging
from typing import List, Dict

load_dotenv()

router = APIRouter()
logger = logging.getLogger(__name__)

# Email configuration
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL")
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

class EmailSend(BaseModel):
    to_email: EmailStr
    subject: str
    body: str

@router.get("/email/unread")
def get_unread_emails():
    """Get unread emails from IMAP server"""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select("inbox")
        
        status, messages = mail.search(None, 'UNSEEN')
        if status != 'OK':
            mail.logout()
            raise HTTPException(status_code=500, detail="Failed to search emails")
        
        email_ids = messages[0].split()
        emails = []
        
        for eid in email_ids[-10:]:  # Get last 10 unread emails
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != 'OK':
                continue
                
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    # Extract subject
                    subject = msg.get("Subject", "")
                    if subject:
                        decoded_subject = decode_header(subject)[0]
                        if isinstance(decoded_subject[0], bytes):
                            subject = decoded_subject[0].decode(decoded_subject[1] or 'utf-8')
                        else:
                            subject = decoded_subject[0]
                    
                    # Extract sender
                    from_email = email.utils.parseaddr(msg.get("From"))[1]
                    
                    # Extract body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body = payload.decode(errors='ignore')
                                    break
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors='ignore')
                    
                    emails.append({
                        "from": from_email,
                        "subject": subject,
                        "body": body.strip()[:200] + "..." if len(body.strip()) > 200 else body.strip(),
                        "timestamp": msg.get("Date", "")
                    })
        
        mail.logout()
        return {"emails": emails, "count": len(emails)}
        
    except Exception as e:
        logger.error(f"Failed to fetch unread emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/email/send")
def send_email_api(email_data: EmailSend):
    """Send email via SMTP"""
    try:
        msg = MIMEText(email_data.body)
        msg["Subject"] = email_data.subject
        msg["From"] = FROM_EMAIL
        msg["To"] = email_data.to_email
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        # Log the sent email
        try:
            supabase.table("conversations").insert({
                "user_email": email_data.to_email,
                "role": "agent",
                "message": f"Email sent: {email_data.subject}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception as log_error:
            logger.warning(f"Failed to log sent email: {log_error}")
        
        return {"message": "Email sent successfully"}
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/email/statistics")
def get_email_statistics():
    """Get email statistics for the last 30 days"""
    try:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Get conversations (emails) from last 30 days
        response = supabase.table("conversations").select("*").gte("timestamp", thirty_days_ago.isoformat()).execute()
        conversations = response.data if response.data else []
        
        # Calculate statistics
        total_emails = len(conversations)
        agent_emails = len([c for c in conversations if c.get('role') == 'agent'])
        user_emails = len([c for c in conversations if c.get('role') == 'user'])
        
        # Calculate daily email counts for chart
        daily_counts = {}
        for i in range(30):
            date_key = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            daily_counts[date_key] = {"sent": 0, "received": 0}
        
        for conv in conversations:
            try:
                conv_date = datetime.fromisoformat(conv.get('timestamp', '').replace('Z', '+00:00')).strftime('%Y-%m-%d')
                if conv_date in daily_counts:
                    if conv.get('role') == 'agent':
                        daily_counts[conv_date]["sent"] += 1
                    else:
                        daily_counts[conv_date]["received"] += 1
            except:
                continue
        
        # Format for frontend
        chart_data = []
        for date_str, counts in sorted(daily_counts.items()):
            chart_data.append({
                "date": date_str,
                "sent": counts["sent"],
                "received": counts["received"]
            })
        
        return {
            "total_emails": total_emails,
            "sent_emails": agent_emails,
            "received_emails": user_emails,
            "daily_data": chart_data[-7:]  # Last 7 days for chart
        }
        
    except Exception as e:
        logger.error(f"Failed to get email statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/email/templates")
def get_email_templates():
    """Get available email templates"""
    templates = {
        "welcome": {
            "subject": "Welcome to Thrivv Bank 🎉",
            "body": """Hi {name},

Welcome to Thrivv Bank!

We are delighted that you registered with us. I am your AI onboarding agent and I will help you get onboarded smoothly.

To get started, please reply with 'Continue' if you are interested in proceeding with account opening, otherwise reply with 'Exit'.

Best regards,
Thrivv Bank Onboarding Team"""
        },
        "document_request": {
            "subject": "Document Upload Required - Thrivv Bank",
            "body": """Hi {name},

Thank you for choosing Thrivv Bank. To proceed with your account opening, we need you to upload the following documents:

Required Documents:
• Commercial License (clear photo/scan)
• Emirates ID - Front and Back (clear photo/scan)

Please reply to this email with your documents attached.

Best regards,
Thrivv Bank Document Team"""
        },
        "verification_complete": {
            "subject": "Account Verification Complete - Thrivv Bank ✅",
            "body": """Hi {name},

Great news! Your document verification has been completed successfully.

Your account application has been approved and is being processed. You will receive your account details within 2-3 business days.

Best regards,
Thrivv Bank Account Services"""
        }
    }
    
    return {"templates": templates}
