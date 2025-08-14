# app/services/email_sender.py

import smtplib
from email.mime.text import MIMEText
from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL


def send_welcome_email(to_email: str, user_name: str):
    subject = "Welcome to Thrivv 🎉"
    body = f"""
    Hi {user_name},

    Welcome to Thrivv!
    We are delighted that you registered with us.

    I am your onboarding agent and I will help you get onboarded.
    Please reply with 'Continue' if you are interested, otherwise reply with 'Exit'.

    Cheers,  
    Thrivv Onboarding Agent
    """

    send_email(to_email, subject, body)


def send_email(to_email: str, subject: str, body: str):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
