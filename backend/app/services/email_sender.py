# app/services/email_sender.py

import smtplib
from email.mime.text import MIMEText
from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL


def send_welcome_email(to_email: str, details: str):
    subject = "Welcome to Thrivv 🎉"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8f9fa; color: #333;">
        <div style="max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee;">
            <h2 style="color: #4CAF50;">Welcome to Thrivv!</h2>
            <p>Dear User,</p>
            <p>Thank you for registering with Thrivv. We're excited to have you onboard!</p>
            <div style="background: #f1f1f1; padding: 16px; border-radius: 8px; margin: 16px 0;">
                {details}
            </div>
            <p>If you have any questions, feel free to reply to this email.</p>
            <p style="margin-top:32px;">Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body>
    </html>
    """

    send_email(to_email, subject, body, html=True)


def send_email(to_email: str, subject: str, body: str, html: bool = False):
    msg = MIMEText(body, "html" if html else "plain")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

def send_wrong_document_email(to_email: str, filename: str, summary: str, required_docs: list):
    subject = "Incorrect Document Submitted"
    required_docs_html = "".join([f"<li>{doc}</li>" for doc in required_docs])
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8f9fa; color: #333;">
        <div style="max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee;">
            <h2 style="color: #e53935;">Incorrect Document Received</h2>
            <p>Dear User,</p>
            <p>We have received the file <strong>{filename}</strong> you submitted. Upon verification, this document is not the required one.</p>
            <div style="background: #f1f1f1; padding: 16px; border-radius: 8px; margin: 16px 0;">
                <strong>Reason:</strong><br>
                {summary}
            </div>
            <p>Please resend the correct document(s) as listed below:</p>
            <ul>{required_docs_html}</ul>
            <p>If you have any questions, feel free to reply to this email.</p>
            <p style="margin-top:32px;">Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body>
    </html>
    """
    send_email(to_email, subject, body, html=True)
