# backend/app/services/email_sender.py
"""
Re-export shim. The implementation moved to `app/services/mail/` in Stage C4.

This file was 2,215 lines: SMTP transport, a 324-line PDF builder and 19 HTML
message composers in one module. Fourteen modules import from it — several
from inside function bodies, where a missed rename would not surface until that
branch ran — so the module path is kept rather than updated at every call site.
Nothing here re-implements anything; every name below is the same object.

New code should import from the specific module:

    from app.services.mail.transport import send_email
    from app.services.mail.messages import send_welcome_email

`config`, `supabase` and `user_docs_path` are re-exported because they were
importable from here before the split, and something importing them from this
path would otherwise break silently.
"""

from app import config  # noqa: F401  (re-export: was importable from here pre-C4)
from app.services.supabase_client import supabase  # noqa: F401  (re-export)
from app.services.chatupload_helpers import user_docs_path  # noqa: F401  (re-export)

from app.services.mail.transport import (  # noqa: F401
    send_email,
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    FROM_EMAIL,
)
from app.services.mail.summary_pdf import (  # noqa: F401
    sanitize_pdf_text,
    generate_user_summary_pdf,
)
from app.services.mail.messages import (  # noqa: F401
    send_welcome_email,
    send_document_verification_email,
    send_wrong_document_email,
    send_validation_pending_email,
    send_validation_passed_email,
    send_validation_failed_email,
    send_cross_validation_error_email,
    send_tampering_rejection_email,
    send_manual_review_email_tampering,
    send_member_identification_email,
    send_member_eid_request_email,
    send_member_documents_confirmation_email,
    send_all_members_complete_email,
    send_document_status_email,
    send_missing_documents_email,
    send_onboarding_completion_email,
    send_completion_email,
    send_corporate_shareholder_request_email,
    send_ubo_identified_email,
)

__all__ = [
    "send_email",
    "SMTP_SERVER",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "FROM_EMAIL",
    "sanitize_pdf_text",
    "generate_user_summary_pdf",
    "send_welcome_email",
    "send_document_verification_email",
    "send_wrong_document_email",
    "send_validation_pending_email",
    "send_validation_passed_email",
    "send_validation_failed_email",
    "send_cross_validation_error_email",
    "send_tampering_rejection_email",
    "send_manual_review_email_tampering",
    "send_member_identification_email",
    "send_member_eid_request_email",
    "send_member_documents_confirmation_email",
    "send_all_members_complete_email",
    "send_document_status_email",
    "send_missing_documents_email",
    "send_onboarding_completion_email",
    "send_completion_email",
    "send_corporate_shareholder_request_email",
    "send_ubo_identified_email",
]
