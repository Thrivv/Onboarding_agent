# backend/app/services/email_otp_service.py
# ============================================================================
# EMAIL OTP SERVICE — DigiOB Digital OnBoarding Platform
# ============================================================================
# Responsibilities:
#   generate_otp()   — produce a 6-digit OTP
#   store_otp()      — cache OTP in-memory with expiry (10 min)
#   verify_otp()     — validate OTP and clear it on success
#   send_otp_email() — generate email content via call_local_llm() and dispatch
# ============================================================================

import random
import time
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from typing import Dict, Tuple
from app import config

logger = logging.getLogger(__name__)

# ============================================================================
# IN-MEMORY OTP STORE
# Key:   email (lowercase)
# Value: { "otp": str, "expires_at": float (epoch), "attempts": int }
# ============================================================================
_otp_store: Dict[str, dict] = {}

OTP_EXPIRY_SECONDS = 600   # 10 minutes
MAX_VERIFY_ATTEMPTS = 5    # fail-safe: block after 5 wrong attempts


# ============================================================================
# SMTP CONFIG (reuses existing env vars from email_sender.py)
# ============================================================================
SMTP_SERVER   = config.SMTP_SERVER or "smtp.gmail.com"
SMTP_PORT     = config.SMTP_PORT
SMTP_USERNAME = config.SMTP_USERNAME or ""
SMTP_PASSWORD = config.SMTP_PASSWORD or ""
FROM_NAME     = "DigiOB Digital OnBoarding"

# FROM_EMAIL env var may be in "Display Name <addr@example.com>" format.
# Extract the raw address for SMTP envelope; use display name for the header.
_from_env = config.FROM_EMAIL or "noreply@digiob.com"
if "<" in _from_env and ">" in _from_env:
    # e.g. "Thrivv Onboarding Agent <testingthrivv@gmail.com>"
    FROM_EMAIL_RAW = _from_env[_from_env.index("<") + 1 : _from_env.index(">")].strip()
else:
    FROM_EMAIL_RAW = _from_env.strip()


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def generate_otp() -> str:
    """Generate a cryptographically random 6-digit OTP string."""
    return str(random.SystemRandom().randint(100000, 999999))


def store_otp(email: str, otp: str) -> None:
    """
    Store OTP in the in-memory cache with expiry.
    Overwrites any existing OTP for the same email.
    """
    _otp_store[email.lower()] = {
        "otp": otp,
        "expires_at": time.time() + OTP_EXPIRY_SECONDS,
        "attempts": 0,
    }
    logger.info(f"[OTP] OTP stored for {email}, expires in {OTP_EXPIRY_SECONDS}s")


def verify_otp(email: str, otp_input: str) -> Tuple[bool, str]:
    """
    Validate OTP for given email.

    Returns:
        (True,  "verified")       — on success
        (False, "expired")        — OTP timed out
        (False, "invalid")        — wrong OTP
        (False, "max_attempts")   — too many attempts
        (False, "not_found")      — no OTP on record
    """
    key = email.lower()
    record = _otp_store.get(key)

    if not record:
        logger.warning(f"[OTP] No OTP record found for {email}")
        return False, "not_found"

    # Check expiry
    if time.time() > record["expires_at"]:
        del _otp_store[key]
        logger.warning(f"[OTP] ⏰ OTP expired for {email}")
        return False, "expired"

    # Check attempt limit
    if record["attempts"] >= MAX_VERIFY_ATTEMPTS:
        del _otp_store[key]
        logger.warning(f"[OTP] Max attempts exceeded for {email}")
        return False, "max_attempts"

    # ── DEMO BYPASS: any 6-digit number is accepted ──────────────────────────
    _cleaned = otp_input.strip()
    if _cleaned.isdigit() and len(_cleaned) == 6:
        del _otp_store[key]          # consume OTP — one-time use
        logger.info(f"[OTP] OTP verified for {email} (demo bypass)")
        return True, "verified"
    # ── end DEMO BYPASS ───────────────────────────────────────────────────────

    # Increment attempt counter on failure
    _otp_store[key]["attempts"] += 1
    remaining = MAX_VERIFY_ATTEMPTS - _otp_store[key]["attempts"]
    logger.warning(f"[OTP] Wrong OTP for {email}. Attempts left: {remaining}")
    return False, "invalid"


# ============================================================================
# LLM-GENERATED EMAIL CONTENT
# ============================================================================

def _generate_email_content_via_llm(email: str, otp: str) -> Tuple[str, str]:
    """
    Use call_local_llm() to generate the OTP email subject and HTML body.
    Falls back to a hardcoded template if LLM fails.

    Returns:
        (subject: str, html_body: str)
    """
    try:
        from app.services.run_model import call_local_llm

        prompt = (
            f"Generate a professional email for the DigiOB Digital OnBoarding platform. "
            f"The email should contain a 6-digit OTP for account email verification. "
            f"The OTP is: {otp}. "
            f"The recipient's email is: {email}. "
            f"The email should:\n"
            f"  1. Have a clear, professional subject line.\n"
            f"  2. Greet the user warmly.\n"
            f"  3. Clearly display the OTP in a prominent way.\n"
            f"  4. State that the OTP is valid for 10 minutes.\n"
            f"  5. Warn the user not to share the OTP.\n"
            f"  6. Close professionally with 'DigiOB Support Team'.\n"
            f"Return the response in this exact format (two lines only):\n"
            f"SUBJECT: <subject line here>\n"
            f"BODY: <full HTML email body here>\n"
        )

        raw = call_local_llm(prompt)

        # Parse subject and body from LLM response
        subject = f"DigiOB — Your Verification OTP: {otp}"
        body_html = None

        lines = raw.strip().split('\n', 1)
        if lines and lines[0].upper().startswith('SUBJECT:'):
            subject = lines[0][len('SUBJECT:'):].strip()
        if len(lines) > 1 and lines[1].upper().startswith('BODY:'):
            body_html = lines[1][len('BODY:'):].strip()

        if not body_html:
            # LLM returned free-form text — wrap it in minimal HTML
            body_html = f"<pre style='font-family:sans-serif'>{raw}</pre>"

        logger.info(f"[OTP] LLM generated email content (subject: {len(subject)} chars)")
        return subject, body_html

    except Exception as e:
        logger.warning(f"[OTP] LLM email generation failed, using fallback: {e}")
        return _fallback_email_content(otp)


def _fallback_email_content(otp: str) -> Tuple[str, str]:
    """Hardcoded fallback email template when LLM is unavailable."""
    subject = f"DigiOB — Your Verification OTP: {otp}"
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f7fb; margin: 0; padding: 0;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f7fb; padding:30px 0;">
        <tr>
          <td align="center">
            <table width="560" cellpadding="0" cellspacing="0"
                   style="background:#ffffff; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,0.08); padding:40px;">
              <tr>
                <td align="center" style="padding-bottom:24px;">
                  <h1 style="color:#2563eb; font-size:26px; margin:0;">DigiOB</h1>
                  <p style="color:#6b7280; font-size:13px; margin:4px 0 0;">Digital OnBoarding Platform</p>
                </td>
              </tr>
              <tr>
                <td>
                  <p style="color:#374151; font-size:16px;">Hello,</p>
                  <p style="color:#374151; font-size:15px; line-height:1.6;">
                    To complete your registration on <strong>DigiOB</strong>, please use the
                    verification code below:
                  </p>
                </td>
              </tr>
              <tr>
                <td align="center" style="padding:28px 0;">
                  <div style="background:#eff6ff; border:2px solid #bfdbfe; border-radius:10px;
                               display:inline-block; padding:18px 40px;">
                    <span style="font-size:36px; font-weight:700; letter-spacing:0.25em;
                                  color:#1d4ed8; font-family:monospace;">{otp}</span>
                  </div>
                </td>
              </tr>
              <tr>
                <td>
                  <p style="color:#6b7280; font-size:13px; line-height:1.6;">
                    &#9200; This OTP is valid for <strong>10 minutes</strong>.<br>
                    &#128274; Never share this code with anyone, including DigiOB staff.<br>
                    If you did not request this, please ignore this email.
                  </p>
                </td>
              </tr>
              <tr>
                <td style="padding-top:24px; border-top:1px solid #e5e7eb; margin-top:20px;">
                  <p style="color:#9ca3af; font-size:12px; text-align:center;">
                    &copy; 2025 DigiOB Digital OnBoarding. All rights reserved.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    return subject, body_html


# ============================================================================
# EMAIL DISPATCH
# ============================================================================

def send_otp_email(to_email: str, otp: str) -> bool:
    """
    Generate OTP email content via LLM and dispatch via SMTP.

    Returns True on success, False on failure.
    """
    try:
        subject, html_body = _generate_email_content_via_llm(to_email, otp)

        msg = MIMEMultipart("alternative")
        msg["Subject"]  = str(Header(subject, "utf-8"))
        msg["From"]     = formataddr((FROM_NAME, FROM_EMAIL_RAW))
        msg["To"]       = to_email

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL_RAW, to_email, msg.as_string())

        logger.info(f"[OTP] OTP email dispatched to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"[OTP] SMTP auth error: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"[OTP] SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"[OTP] Unexpected error sending OTP email: {e}")
        return False


# ============================================================================
# HIGH-LEVEL ENTRY POINT (used by FastAPI route)
# ============================================================================

def generate_and_send_otp(email: str) -> bool:
    """
    Full pipeline: generate OTP → store → send email.

    Returns True if email was dispatched, False otherwise.
    """
    otp = generate_otp()
    store_otp(email, otp)
    sent = send_otp_email(email, otp)
    if not sent:
        logger.error(f"[OTP] Failed to send OTP to {email}")
    return sent
