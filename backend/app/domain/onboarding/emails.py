"""
Onboarding email composition triggered by document events.

Two senders: one confirming a document was received and verified, one telling
the user they uploaded the wrong document type. Both build their body via the
LLM message generator, so they live here rather than in `services/email` —
what they say is a product decision, how it is delivered is not.

Moved verbatim from `app/api/routes/chatupload.py` in Stage B4.
"""

from __future__ import annotations

import logging
from typing import List, Optional
from app.services.document_messaging import (
    # generate_dynamic_valid_document_response is not called here — it is
    # re-exported from this module and imported by documentpage.py.
    generate_dynamic_valid_document_response,
    generate_dynamic_invalid_document_response,
    generate_welcome_message,
    generate_ai_reasoning_for_invalid_document,
    generate_unknown_document_reasoning,
    format_extraction_message,
    extract_document_text_for_reasoning,
)
from app.services.chatupload_helpers import (
    user_docs_path,
    member_progress_path,
    get_display_document_name,
    get_allowed_document_types,
    check_documents_status,
    should_request_document,
    load_member_progress,
    get_remaining_required_documents,
    insert_conversation_log,
    
)
from app.services.email_sender import (
    send_email,
    send_tampering_rejection_email,
    send_manual_review_email_tampering,
    send_validation_failed_email,
    send_validation_passed_email,
    send_document_verification_email,
    # send_onboarding_completion_email is not called here — it is re-exported
    # from this module and imported by documentpage.py.
    send_onboarding_completion_email,
    send_corporate_shareholder_request_email,   # TYPE-2
    send_ubo_identified_email,                  # TYPE-2
)

logger = logging.getLogger(__name__)

def send_document_verification_email(to_email: str, user_name: str, doc_type: str, extracted_data: dict, member_name: Optional[str] = None):
    """Send email notification after document verification with extracted data"""
    
    subject = f"Document Verified - {doc_type.upper()}"
    
    # Format extracted data for email
    if doc_type.lower() == "eid":
        name = extracted_data.get("Name") or extracted_data.get("name") or "N/A"
        id_number = extracted_data.get("ID Number") or extracted_data.get("id_number") or "N/A"
        nationality = extracted_data.get("Nationality") or extracted_data.get("nationality") or "N/A"
        
        member_info = f"<p><strong>Member:</strong> {member_name}</p>" if member_name else ""
        
        data_html = f"""
        {member_info}
        <p><strong>Name:</strong> {name}</p>
        <p><strong>ID Number:</strong> {id_number}</p>
        <p><strong>Nationality:</strong> {nationality}</p>
        """
    
    elif doc_type.lower() == "commercial":
        eng = extracted_data.get("english", {})
        company = eng.get("company_name_english", "N/A")
        license_num = eng.get("license_number", "N/A")
        
        data_html = f"""
        <p><strong>Company Name:</strong> {company}</p>
        <p><strong>License Number:</strong> {license_num}</p>
        """
    
    elif doc_type.lower() in ("ejari", "tenancy"):
        eng = extracted_data.get("english", {})
        contract_num = eng.get("contract_number", "N/A")
        property_type = eng.get("property_type", "N/A")
        
        data_html = f"""
        <p><strong>Contract Number:</strong> {contract_num}</p>
        <p><strong>Property Type:</strong> {property_type}</p>
        """
    
    else:
        data_html = "<p>Document verified successfully</p>"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            .header {{ background: #28a745; color: white; padding: 30px; text-align: center; border-radius: 12px 12px 0 0; }}
            .content {{ padding: 30px; }}
            .success-box {{ background: #d4edda; border-left: 4px solid #28a745; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; border-radius: 0 0 12px 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">Document Verified</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                <p>Your <strong>{doc_type.upper()}</strong> has been successfully verified!</p>
                
                <div class="success-box">
                    <h3 style="margin: 0 0 15px 0; color: #28a745;">Extracted Information</h3>
                    {data_html}
                </div>
                
                <p>Continue uploading any remaining documents to complete your onboarding.</p>
            </div>
            <div class="footer">
                <p style="margin: 0;">Best regards,</p>
                <p style="margin: 5px 0 0 0; font-weight: 600;">Thrivv Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        logger.info(f"Verification email sent for {doc_type}")
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")


def send_wrong_document_type_email_dynamic(
    to_email: str,
    user_name: str,
    uploaded_doc_type: str,
    allowed_info: dict,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None
):
    """
    Send email for wrong document type - uses existing email_sender function
    
    NOTE: This function ONLY handles wrong document types.
    Tampering emails are sent separately by tampering_service.py using:
    - send_tampering_rejection_email() for REJECT cases
    - send_manual_review_email_tampering() for ESCALATE cases
    """
    from app.services.email_sender import send_document_verification_email
    
    logger.info(f"Sending wrong document type email via email_sender...")
    
    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user_data)
    
    # Generate the reasoning message (reuse existing function)
    error_message = generate_dynamic_invalid_document_response(
        uploaded_doc_type=uploaded_doc_type,
        allowed_info=allowed_info,
        email=email,
        user_data=user_data,
        member_name=member_name
    )
    
    # Use existing email function from email_sender
    send_document_verification_email(
        to_email=to_email,
        user_name=user_name,
        document_type=uploaded_doc_type.upper(),
        status="invalid",
        filename=None,
        reason=error_message,
        extracted_data=None,
        is_complete=False,
        remaining_documents=remaining_docs,
        member_name=member_name
    )
    
    logger.info(f"[SUCCESS] Wrong document type email sent via email_sender")
