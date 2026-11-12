# backend/app/api/routes/otp.py
# ============================================================================
# OTP ENDPOINTS — DigiOB Digital OnBoarding Platform
# ============================================================================
# POST /otp/generate-otp   — generate & email a 6-digit OTP
# POST /otp/verify-otp     — validate the submitted OTP
# ============================================================================

from fastapi import APIRouter, HTTPException
import logging

from app.services.email_otp_service import generate_and_send_otp, verify_otp
from app.schemas.otp import GenerateOTPRequest, GenerateOTPResponse, VerifyOTPRequest, VerifyOTPResponse
from app.domain.exceptions import (
    DomainError,
    ValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otp", tags=["OTP"])


# ── Request / Response Models ────────────────────────────────────────────────


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate-otp", response_model=GenerateOTPResponse)
async def generate_otp_endpoint(request: GenerateOTPRequest):
    """
    Generate a 6-digit OTP and send it to the provided email address.
    Uses call_local_llm() to generate the email content dynamically.
    """
    try:
        logger.info(f"[OTP-ROUTE] Generate OTP request for: {request.email}")

        sent = generate_and_send_otp(request.email)

        if not sent:
            raise HTTPException(
                status_code=503,
                detail="Failed to send OTP email. Please check your email address and try again."
            )

        logger.info(f"[OTP-ROUTE] OTP sent successfully to: {request.email}")
        return GenerateOTPResponse(
            success=True,
            message=f"OTP sent to {request.email}. It is valid for 10 minutes."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[OTP-ROUTE] Unexpected error: {e}")
        raise DomainError(context=f"OTP generation failed: {str(e)}")


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(request: VerifyOTPRequest):
    """
    Verify the OTP submitted by the user.
    On success the OTP is consumed (one-time use).
    """
    try:
        logger.info(f"[OTP-ROUTE] Verify OTP request for: {request.email}")

        is_valid, reason = verify_otp(request.email, request.otp)

        if is_valid:
            logger.info(f"[OTP-ROUTE] OTP verified for: {request.email}")
            return VerifyOTPResponse(
                success=True,
                message="Email verified successfully. You may proceed."
            )

        # Map reason codes to user-friendly error messages
        error_messages = {
            "expired":      "Your OTP has expired. Please request a new one.",
            "max_attempts": "Too many failed attempts. Please request a new OTP.",
            "not_found":    "No OTP found for this email. Please request one first.",
            "invalid":      "Incorrect OTP. Please check and try again.",
        }
        detail = error_messages.get(reason, "OTP verification failed.")
        logger.warning(f"[OTP-ROUTE] OTP verification failed for {request.email}: {reason}")
        raise ValidationError(detail)

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[OTP-ROUTE] Unexpected error: {e}")
        raise DomainError(context=f"OTP verification failed: {str(e)}")
