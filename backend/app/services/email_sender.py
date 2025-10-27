# app/services/email_sender.py

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL
from email.header import Header
from email.utils import formataddr


def send_welcome_email(to_email: str, details: str):
    subject = "Welcome to Thrivv "
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


def send_email(
    to_email: str, subject: str, body: str, html: bool = False, attachments: list = None
):
    """
    Send email with optional attachments

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        html: Whether body is HTML (default: False)
        attachments: List of dicts with 'filename', 'data', and optional 'mime_type'
                     Example: [{'filename': 'report.pdf', 'data': pdf_bytes, 'mime_type': 'application/pdf'}]
    """
    # Create message container
    if attachments:
        msg = MIMEMultipart()
        # Attach the body
        msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
    else:
        msg = MIMEText(body, "html" if html else "plain", "utf-8")

    # Set headers
    msg["Subject"] = Header(subject, "utf-8")

    if "<" in FROM_EMAIL and ">" in FROM_EMAIL:
        name, addr = FROM_EMAIL.split("<")
        name = name.strip()
        addr = addr.strip(" >")
        msg["From"] = formataddr((str(Header(name, "utf-8")), addr))
    else:
        msg["From"] = FROM_EMAIL

    msg["To"] = to_email

    # Add attachments if provided
    if attachments:
        for attachment in attachments:
            filename = attachment.get("filename", "attachment")
            data = attachment.get("data")
            mime_type = attachment.get("mime_type", "application/octet-stream")

            if data:
                # Create attachment part
                part = MIMEBase(*mime_type.split("/"))
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
                msg.attach(part)
                print(f"[INFO] Attached file: {filename} ({mime_type})")

    # Send email
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        print(
            f"[SUCCESS] Email sent to {to_email}"
            + (f" with {len(attachments)} attachment(s)" if attachments else "")
        )
    except Exception as e:
        print(f"[ERROR] Failed to send email to {to_email}: {e}")
        raise


def send_wrong_document_email(
    to_email: str, filename: str, summary: str, required_docs: list
):
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
