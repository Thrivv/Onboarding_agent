# backend/app/services/email_otp_service.py
# ============================================================================
# EMAIL OTP SERVICE — DigiOB Digital OnBoarding Platform
# ============================================================================
# Responsibilities:
#   generate_otp()   — produce a 6-digit OTP
#   store_otp()      — cache OTP in-memory with expiry (10 min)
#   verify_otp()     — validate OTP and clear it on success
#   send_otp_email() — render OTP email (hardcoded template by default;
#                       optional opt-in LLM-authored copy) and dispatch
# ============================================================================

import random
import re
import time
import smtplib
import hmac
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

    _cleaned = otp_input.strip()

    # TEST-ENVIRONMENT BYPASS (config.OTP_BYPASS_ENABLED, default False).
    # When explicitly turned on for an isolated test/QA deployment, accept
    # any well-formed 6-digit code without checking it against the one that
    # was actually generated and emailed. A record must still exist and not
    # be expired/exhausted (checks above), so this only skips the *value*
    # comparison — it does not disable the OTP flow entirely. See
    # config.OTP_BYPASS_ENABLED for why this must never be on anywhere real
    # users can reach.
    if config.OTP_BYPASS_ENABLED and re.fullmatch(r"\d{6}", _cleaned):
        del _otp_store[key]
        logger.warning(f"[OTP] BYPASS: accepted OTP {_cleaned} for {email} (OTP_BYPASS_ENABLED=true)")
        return True, "verified"

    # Compare against the actual stored OTP. This used to accept ANY
    # 6-digit input ("DEMO BYPASS") unconditionally — meaning
    # email-verification and password-reset codes could be satisfied
    # without ever receiving the email, by anyone who knew the target's
    # address, in every environment including production. Fixed to a real,
    # constant-time comparison against the code that was generated and
    # emailed, with the bypass now opt-in and test-only (see above).
    if hmac.compare_digest(_cleaned, record["otp"]):
        del _otp_store[key]          # consume OTP — one-time use
        logger.info(f"[OTP] OTP verified for {email}")
        return True, "verified"

    # Increment attempt counter on failure
    _otp_store[key]["attempts"] += 1
    remaining = MAX_VERIFY_ATTEMPTS - _otp_store[key]["attempts"]
    logger.warning(f"[OTP] Wrong OTP for {email}. Attempts left: {remaining}")
    return False, "invalid"


# ============================================================================
# EMAIL CONTENT
# ============================================================================
# SECURITY FIX (prompt-remediation Phase 1, item #2): this module used to
# build the verification email by interpolating the LIVE OTP and the
# recipient's real email address directly into an LLM prompt
# (_generate_email_content_via_llm(email, otp), removed here), then parsing
# the subject/body back out of free-form text via a brittle
# "SUBJECT:"/"BODY:" convention that silently degraded to
# "<pre>{raw}</pre>" whenever the model didn't follow it. A one-time bearer
# credential has no legitimate reason to leave the process boundary into a
# model provider (and its request/response path) just to have a paragraph
# phrased around it. The hardcoded template below is now the default and
# only path: it renders the OTP correctly with zero model calls, zero
# secret exposure, and zero parsing risk.
#
# config.OTP_EMAIL_LLM_PERSONALIZATION_ENABLED (default False) opts back
# into LLM-authored copy for teams that want varied phrasing. When it is
# on, _generate_email_copy_via_llm() asks the model to write the email
# around a placeholder token — the real OTP and the recipient's address
# are never included in the prompt — and the placeholder is substituted
# with the real code only after the model call returns.

_OTP_PLACEHOLDER = "{{OTP_CODE}}"


def _generate_email_copy_via_llm(otp: str) -> Tuple[str, str]:
    """
    Optional, opt-in (config.OTP_EMAIL_LLM_PERSONALIZATION_ENABLED) path:
    ask the LLM to phrase the OTP email around a placeholder token, never
    the real code or the recipient's address, then substitute the real OTP
    into the model's output afterwards.

    Falls back to the hardcoded template if the LLM fails or omits the
    placeholder.

    Returns:
        (subject: str, html_body: str)
    """
    try:
        from app.services.run_model import call_local_llm

        prompt = (
            f"Generate a professional email for the {config.BRAND_NAME} Digital OnBoarding platform.\n"
            "The email should contain a one-time verification code for account email "
            "verification. Do not invent a code -- use exactly this placeholder token "
            "everywhere the code should appear: " + _OTP_PLACEHOLDER + "\n"
            "The email should:\n"
            "  1. Have a clear, professional subject line that also uses the "
            "placeholder token in place of the code.\n"
            "  2. Greet the user warmly (no name is known -- use a generic greeting).\n"
            "  3. Display the placeholder token prominently as the code.\n"
            "  4. State that the code is valid for 10 minutes.\n"
            "  5. Warn the user not to share the code.\n"
            f"  6. Close professionally with '{config.BRAND_NAME} Support Team'.\n"
            "Return the response in this exact format (two lines only):\n"
            "SUBJECT: <subject line here>\n"
            "BODY: <full HTML email body here>\n"
        )

        raw = call_local_llm(prompt)

        subject = None
        body_html = None

        lines = raw.strip().split("\n", 1)
        if lines and lines[0].upper().startswith("SUBJECT:"):
            subject = lines[0][len("SUBJECT:"):].strip()
        if len(lines) > 1 and lines[1].upper().startswith("BODY:"):
            body_html = lines[1][len("BODY:"):].strip()

        # The model must have used the placeholder -- otherwise we have no
        # reliable way to know where the real OTP belongs, and we do not
        # guess. Any deviation falls back to the hardcoded template.
        if not subject or not body_html or _OTP_PLACEHOLDER not in subject + body_html:
            logger.warning("[OTP] LLM email copy missing placeholder token, using fallback")
            return _fallback_email_content(otp)

        subject = subject.replace(_OTP_PLACEHOLDER, otp)
        body_html = body_html.replace(_OTP_PLACEHOLDER, otp)

        logger.info(f"[OTP] LLM generated email copy (subject: {len(subject)} chars)")
        return subject, body_html

    except Exception as e:
        logger.warning(f"[OTP] LLM email copy generation failed, using fallback: {e}")
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
        if config.OTP_EMAIL_LLM_PERSONALIZATION_ENABLED:
            subject, html_body = _generate_email_copy_via_llm(otp)
        else:
            subject, html_body = _fallback_email_content(otp)

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
