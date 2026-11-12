"""
Document Tampering Verification Service
Integrates tampering detection into the document upload workflow
"""

import os
import logging
from typing import Dict, Optional
from datetime import datetime

# Since PYTHONPATH includes /app, just import directly
from app.services.tampering.tampering_detector import detect_tampering
from app.services.tampering.llm_integration import get_document_analysis
from app.repositories.user_repository import UserRepository
from app.services.email_sender import (
    send_tampering_rejection_email,
    send_manual_review_email_tampering,
)

logger = logging.getLogger(__name__)


class DocumentVerificationResult:
    """Structured result from tampering verification"""

    def __init__(self, decision: str, status: str, reason: str,
                 test_report_id: Optional[str] = None,
                 overall_tampering_score: float = 0.0,
                 llm_analysis: Optional[str] = None):
        self.decision = decision  # ACCEPT, ESCALATE, REJECT
        self.status = status  # AUTHENTIC, REVIEW_REQUIRED, TAMPERED
        self.reason = reason
        self.test_report_id = test_report_id
        self.overall_tampering_score = overall_tampering_score
        self.llm_analysis = llm_analysis

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision,
            "status": self.status,
            "reason": self.reason,
            "test_report_id": self.test_report_id,
            "overall_tampering_score": self.overall_tampering_score,
            "llm_analysis": self.llm_analysis
        }


def verify_document_authenticity(
    file_path: str,
    user_email: str,
    doc_type: str = "unknown",
    send_notifications: bool = False  # Emails are handled by the upload routes, not here
) -> DocumentVerificationResult:
    """
    Primary function to verify document authenticity using tampering detection

    Args:
        file_path: Absolute path to uploaded document
        user_email: User's email for notifications
        doc_type: Document type (eid, commercial, ejari, etc.)
        send_notifications: Whether to send email notifications (default: False)
                           Set to False to let upload routes handle emails with reasoning model

    Returns:
        DocumentVerificationResult with decision and details
    """

    logger.debug(f"[TAMPERING] verification started: {user_email} - {doc_type} - {os.path.basename(file_path)}")

    start_time = datetime.now()

    try:
        # =====================================
        # Step 1: Run Tampering Detection
        # =====================================
        tampering_result = detect_tampering(
            file_path=file_path,
            generate_evidence=False  # Evidence stored in Supabase
        )

        processing_time = (datetime.now() - start_time).total_seconds()

        decision = tampering_result.get("decision", "ERROR")
        status = tampering_result.get("status", "ERROR")
        reason = tampering_result.get("reason", "Unknown error")
        test_report_id = tampering_result.get("test_report_id")
        overall_score = tampering_result.get("overall_tampering_score", 0.0)

        # =====================================
        # Step 2: Get LLM Analysis (if rejected/escalated)
        # =====================================

        llm_analysis_text = None

        # =====================================================================
        # PASSPORT-AWARE THRESHOLD ADJUSTMENT
        # Passports are multi-colour photo booklets - they naturally score higher
        # on JPEG quantization, ELA, and font consistency forensics compared to
        # the flat Emirates ID card the engine was calibrated for.
        # Apply more lenient threshold: treat ESCALATE as ACCEPT when the
        # overall score is below 70 for passport documents.
        # REJECT decisions are kept regardless of document type.
        # =====================================================================
        # Detect passport from filename if doc_type was not pre-identified
        _fname_lower = os.path.basename(file_path).lower()
        _fname_stem  = _fname_lower.rsplit(".", 1)[0]
        _pp_hints = ["passport", "passpt", "_pp_", "_pp.", "_pp", "pp_", "intl_id", "travel_doc"]
        _is_passport_file = (
            doc_type == "passport" or
            any(h in _fname_stem for h in _pp_hints) or
            any(h in _fname_lower for h in _pp_hints)
        )
        if _is_passport_file and decision == "ESCALATE" and overall_score < 70:
            logger.debug(
                f"[TAMPERING] passport leniency applied: ESCALATE ({overall_score:.1f}) -> ACCEPT "
                f"(passport forensic baseline is naturally higher than EID)"
            )
            decision = "ACCEPT"
            status = "AUTHENTIC"
            reason = "Passport forensic baseline accepted (score within normal range for passport documents)"

        if test_report_id and decision in ["REJECT", "ESCALATE"]:
            try:
                llm_analysis = get_document_analysis(test_report_id, regenerate=False)
                if llm_analysis:
                    llm_analysis_text = llm_analysis.get("analysis_text")
            except Exception as e:
                logger.error(f"[TAMPERING] LLM analysis generation failed for report {test_report_id}: {e}")

        # =====================================
        # Step 3: Handle Decision-Based Actions
        # =====================================

        if decision == "REJECT":
            logger.warning(
                f"[TAMPERING] {user_email} {doc_type} REJECTED score={overall_score} "
                f"({processing_time:.2f}s) report={test_report_id}"
            )

            # Delete tampered file immediately (security measure)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"[TAMPERING] failed to delete rejected file {file_path}: {e}")

            return DocumentVerificationResult(
                decision="REJECT",
                status="TAMPERED",
                reason=llm_analysis_text or reason,
                test_report_id=test_report_id,
                overall_tampering_score=overall_score,
                llm_analysis=llm_analysis_text
            )

        elif decision == "ESCALATE":
            logger.warning(
                f"[TAMPERING] {user_email} {doc_type} ESCALATE (manual review) score={overall_score} "
                f"({processing_time:.2f}s) report={test_report_id}"
            )

            return DocumentVerificationResult(
                decision="ESCALATE",
                status="REVIEW_REQUIRED",
                reason=llm_analysis_text or reason,
                test_report_id=test_report_id,
                overall_tampering_score=overall_score,
                llm_analysis=llm_analysis_text
            )

        else:  # ACCEPT
            logger.info(
                f"[TAMPERING] {user_email} {doc_type} ACCEPT score={overall_score} "
                f"({processing_time:.2f}s) report={test_report_id}"
            )

            return DocumentVerificationResult(
                decision="ACCEPT",
                status="AUTHENTIC",
                reason="Document verified as authentic",
                test_report_id=test_report_id,
                overall_tampering_score=overall_score
            )

    except FileNotFoundError:
        logger.error(f"[TAMPERING] file not found: {file_path}")
        return DocumentVerificationResult(
            decision="ERROR",
            status="ERROR",
            reason="File not found"
        )

    except Exception as e:
        logger.error(f"[TAMPERING] verification error for {user_email}: {e}", exc_info=True)
        return DocumentVerificationResult(
            decision="ERROR",
            status="ERROR",
            reason=f"Verification failed: {str(e)}"
        )


def update_user_tampering_status(
    user_email: str,
    test_report_id: str,
    decision: str,
    tampering_score: float,
    supabase_client
):
    """
    Update user's tampering status in database
    """

    try:
        # Get user_id for logging
        user_response = UserRepository.get_id(user_email, client=supabase_client)

        if not user_response.data or len(user_response.data) == 0:
            logger.error(f"[TAMPERING] update_user_tampering_status: user not found: {user_email}")
            return False

        user_id = user_response.data[0].get("id")

        if not user_id:
            logger.error(f"[TAMPERING] update_user_tampering_status: user id is None for email: {user_email}")
            return False

        # Map decision to valid database status values
        if decision == "ACCEPT":
            document_status = "verified"
        elif decision == "ESCALATE":
            document_status = "pending"
        elif decision == "REJECT":
            document_status = "rejected"
        else:
            document_status = "pending"

        # Prepare update data
        update_data = {
            "document_status": document_status,
            "tampering_score": tampering_score,
            "tampering_report_id": test_report_id,
            "requires_manual_review": (decision == "ESCALATE"),
            "tampering_checked_at": datetime.now().isoformat()
        }

        logger.debug(f"[TAMPERING] updating user status: {user_email} update={update_data}")

        # Update database
        response = UserRepository.update_by_email(user_email, update_data, client=supabase_client)

        if response.data:
            logger.info(f"[TAMPERING] user status updated: {user_email} {decision} -> {document_status}")
            return True
        else:
            logger.warning(f"[TAMPERING] update returned no data for: {user_email}")
            return False

    except Exception as e:
        logger.error(f"[TAMPERING] user status update failed for {user_email}: {e}", exc_info=True)
        return False
