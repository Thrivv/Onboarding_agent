"""
SMTP transport — the one place this application opens a mail socket.

Moved verbatim from `email_sender.py` in C4. Everything above `send_email` is
configuration; `send_email` itself is unchanged, byte for byte.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
from typing import Optional, List, Dict
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

# ============================================================================
# SMTP CONFIGURATION
# ============================================================================
SMTP_SERVER = config.SMTP_SERVER
SMTP_PORT = config.SMTP_PORT
SMTP_USERNAME = config.SMTP_USERNAME
SMTP_PASSWORD = config.SMTP_PASSWORD
FROM_EMAIL = config.FROM_EMAIL or "noreply@digiob.com"


def send_email(
    to_email: str, 
    subject: str, 
    body: str, 
    html: bool = False, 
    attachments: list = None
) -> bool:
    """
    Base email sending function with attachment support
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Email body (plain text or HTML)
        html: Whether body is HTML (default: False)
        attachments: List of dicts with 'filename', 'data', and optional 'mime_type'
                     Example: [{'filename': 'report.pdf', 'data': pdf_bytes, 'mime_type': 'application/pdf'}]
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Create message container
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
        else:
            msg = MIMEText(body, "html" if html else "plain", "utf-8")

        # Set headers
        msg["Subject"] = Header(subject, "utf-8")

        # Handle FROM_EMAIL with display name
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
                    part = MIMEBase(*mime_type.split("/"))
                    part.set_payload(data)
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition", f'attachment; filename="{filename}"'
                    )
                    msg.attach(part)
                    logger.info(f"Attached file: {filename} ({mime_type})")

        # Send email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(msg["From"], [to_email], msg.as_string())
        
        logger.info(f"[SUCCESS] Email sent to {to_email}" + 
              (f" with {len(attachments)} attachment(s)" if attachments else ""))
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
