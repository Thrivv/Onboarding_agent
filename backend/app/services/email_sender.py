# app/services/email_sender.py


import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL
from email.header import Header
from email.utils import formataddr
from typing import Optional, List, Dict



def send_welcome_email(to_email: str, details: str):
    subject = "Welcome to Thrivv 🎉"
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8f9fa; color: #333;">
        <div style="max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee;">
            <h2 style="color: #4CAF50;">Welcome to Thrivv! 🎉</h2>
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
    subject = "Incorrect Document Submitted ❌"
    required_docs_html = "".join([f"<li>{doc}</li>" for doc in required_docs])
    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8f9fa; color: #333;">
        <div style="max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee;">
            <h2 style="color: #e53935;">Incorrect Document Received ❌</h2>
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



# ============================================================================
# NEW: ENHANCED EMAIL FUNCTIONS WITH AI REASONING
# ============================================================================


def send_document_verification_email(
    to_email: str,
    user_name: str,
    document_type: str,
    status: str = "valid",
    filename: Optional[str] = None,
    reason: Optional[str] = None,
    extracted_data: Optional[Dict] = None,
    is_complete: bool = False,
    remaining_documents: Optional[List[str]] = None,
    member_name: Optional[str] = None
):
    """
    Enhanced document verification email with AI reasoning
    
    Args:
        to_email: Recipient email
        user_name: User's name
        document_type: Type of document (EID, Commercial, etc.)
        status: 'valid', 'invalid', or 'error'
        filename: Original filename
        reason: AI-generated reason/explanation
        extracted_data: Extracted document data
        is_complete: Whether onboarding is complete
        remaining_documents: List of remaining documents needed
        member_name: Optional member name for partnership accounts
    """
    
    member_context = f" for {member_name}" if member_name else ""
    
    if status == "valid":
        # ✅ VALID DOCUMENT EMAIL
        subject = f"✅ {document_type} Verified Successfully{member_context}"
        
        # Format extracted data
        data_html = ""
        if extracted_data:
            data_html = "<div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;'>"
            data_html += "<h3 style='margin: 0 0 10px 0; color: #28a745;'>📋 Extracted Information:</h3>"
            
            if document_type.upper() == "EID":
                data_html += f"<p style='margin: 5px 0;'><strong>Name:</strong> {extracted_data.get('Name') or extracted_data.get('name', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>ID Number:</strong> {extracted_data.get('ID Number') or extracted_data.get('id_number', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Nationality:</strong> {extracted_data.get('Nationality') or extracted_data.get('nationality', 'N/A')}</p>"
            
            elif document_type.upper() == "COMMERCIAL":
                eng = extracted_data.get("english", {})
                data_html += f"<p style='margin: 5px 0;'><strong>Company:</strong> {eng.get('company_name_english', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>License Number:</strong> {eng.get('license_number', 'N/A')}</p>"
            
            data_html += "</div>"
        
        # Remaining documents section
        remaining_html = ""
        if remaining_documents and len(remaining_documents) > 0:
            remaining_html = """
            <div style='background: #fff3cd; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #ffc107;'>
                <h3 style='margin: 0 0 10px 0; color: #856404;'>📋 Remaining Documents:</h3>
                <ul style='margin: 5px 0; padding-left: 20px;'>
            """
            for doc in remaining_documents:
                remaining_html += f"<li style='margin: 5px 0;'>{doc}</li>"
            remaining_html += "</ul></div>"
        
        # Completion banner
        completion_html = ""
        if is_complete:
            completion_html = """
            <div style='background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;'>
                <h2 style='margin: 0;'>🎉 Onboarding Complete!</h2>
                <p style='margin: 10px 0 0 0;'>Your account will be activated within 3-4 business days.</p>
            </div>
            """
        
        body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: #28a745; color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">✅ Document Verified</h1>
                </div>
                <div class="content">
                    <p>Dear {user_name},</p>
                    <p>Your <strong>{document_type}{member_context}</strong> has been successfully verified!</p>
                    
                    {data_html}
                    
                    {reason if reason else ''}
                    
                    {completion_html}
                    
                    {remaining_html}
                    
                    <p style="margin-top: 20px;">Thank you for your submission!</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">Thrivv Onboarding Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    elif status == "invalid":
        # ❌ INVALID DOCUMENT EMAIL WITH AI REASONING
        subject = f"❌ Document Validation Issue - {document_type}{member_context}"
        
        body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: #dc3545; color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; }}
                .reasoning-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .action-box {{ background: #e7f3ff; border-left: 4px solid #2196F3; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">⚠️ Document Validation Issue</h1>
                </div>
                <div class="content">
                    <p>Dear {user_name},</p>
                    <p>We encountered an issue while processing your <strong>{document_type}{member_context}</strong>.</p>
                    
                    {f'<p style="color: #666;"><strong>📄 File:</strong> {filename}</p>' if filename else ''}
                    
                    <div class="reasoning-box">
                        <h3 style="margin: 0 0 15px 0; color: #856404;">🔍 Analysis Results</h3>
                        <p style="margin: 0; color: #856404;">{reason if reason else 'Document could not be validated. Please ensure the document is clear and readable.'}</p>
                    </div>
                    
                    <div class="action-box">
                        <h3 style="margin: 0 0 15px 0; color: #0c5460;">📌 What to do next:</h3>
                        <ul style="margin: 10px 0; padding-left: 20px;">
                            <li style="margin: 8px 0;">📸 Take a clear photo with good lighting</li>
                            <li style="margin: 8px 0;">👁️ Ensure all text is visible and readable</li>
                            <li style="margin: 8px 0;">🚫 Avoid glare, shadows, or blurriness</li>
                            <li style="margin: 8px 0;">📏 Capture the entire document without cropping</li>
                            <li style="margin: 8px 0;">🎯 Use high resolution (avoid pixelated images)</li>
                        </ul>
                    </div>
                    
                    <p style="margin-top: 25px;">Please re-upload the corrected document through the chat interface or by replying to this email.</p>
                    
                    <p style="margin-top: 25px; color: #666;">💬 If you need assistance, feel free to reply to this email. Our team is here to help!</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">Thrivv Onboarding Team</p>
                    <p style="margin: 5px 0 0 0; font-size: 14px;">🤖 Automated Document Verification System</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    else:  # error
        # ⚙️ PROCESSING ERROR EMAIL
        subject = f"⚙️ Document Processing Error - {document_type}{member_context}"
        
        body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: #ff9800; color: white; padding: 30px; text-align: center; }}
                .content {{ padding: 30px; }}
                .error-box {{ background: #fff3e0; border-left: 4px solid #ff9800; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0;">⚙️ Processing Error</h1>
                </div>
                <div class="content">
                    <p>Dear {user_name},</p>
                    <p>We encountered a technical issue while processing your <strong>{document_type}{member_context}</strong>.</p>
                    
                    {f'<p style="color: #666;"><strong>📄 File:</strong> {filename}</p>' if filename else ''}
                    
                    <div class="error-box">
                        <h3 style="margin: 0 0 15px 0; color: #e65100;">⚠️ Issue Details</h3>
                        <p style="margin: 0; color: #e65100;">{reason if reason else 'Technical error during document processing.'}</p>
                    </div>
                    
                    <p><strong>🔧 What to do next:</strong></p>
                    <ul>
                        <li>🔄 Try uploading the document again</li>
                        <li>📑 Try a different file format (PDF, PNG, JPG)</li>
                        <li>📞 Contact support if the issue persists</li>
                    </ul>
                    
                    <p style="margin-top: 25px;">We apologize for the inconvenience. Please try again or contact our support team.</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">Thrivv Onboarding Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[SUCCESS] ✅ Document verification email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] Failed to send document verification email: {e}")



def send_onboarding_completion_email(to_email: str, user_name: str):
    """
    Send final onboarding completion email
    """
    subject = "🎉 Document Verification Stage Complete - Account Activation Pending"
    
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .success-box {{ background: #d4edda; border: 2px solid #4CAF50; padding: 25px; margin: 20px 0; border-radius: 10px; text-align: center; }}
            .timeline {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">🎉 Congratulations!</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <div class="success-box">
                    <h2 style="margin: 0 0 15px 0; color: #4CAF50;">✅ Document Verification Stage Complete!</h2>
                    <p style="margin: 0; font-size: 16px;">All your documents have been successfully verified.</p>
                </div>
                
                <div class="timeline">
                    <h3 style="margin: 0 0 15px 0; color: #333;">📅 Next Steps:</h3>
                    <ul style="list-style: none; padding: 0; margin: 0;">
                        <li style="padding: 10px 0; border-bottom: 1px solid #dee2e6;">
                            <strong>🔍 Step 1:</strong> Your account will be reviewed by our team
                        </li>
                        <li style="padding: 10px 0; border-bottom: 1px solid #dee2e6;">
                            <strong>⏱️ Step 2:</strong> Account activation within <strong>3-4 business days</strong>
                        </li>
                        <li style="padding: 10px 0;">
                            <strong>📧 Step 3:</strong> You'll receive your account details via email
                        </li>
                    </ul>
                </div>
                
                <p style="margin-top: 30px; padding: 20px; background: #e3f2fd; border-radius: 8px; border-left: 4px solid #2196F3;">
                    <strong>💡 What happens next?</strong><br>
                    Once your account is activated, you'll be able to access all Thrivv banking services. 
                    We'll send you login credentials and a welcome package with detailed instructions.
                </p>
                
                <p style="margin-top: 30px;">Thank you for choosing Thrivv Bank! 🏦</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">Thrivv Onboarding Team</p>
                <p style="margin: 5px 0 0 0; font-size: 14px;">🚀 Building the future of banking together</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        send_email(to_email, subject, body, html=True)
        print(f"[SUCCESS] ✅ Onboarding completion email sent to {to_email}")
    except Exception as e:
        print(f"[ERROR] Failed to send completion email: {e}")
        
def send_cross_validation_error_email(to_email: str, validation_result: dict):
    """
    Send email when cross-validation fails
    """
    mismatches = validation_result.get("mismatches", [])
    
    mismatch_html = "".join([
        f"<li style='margin:10px 0;'><strong>❌ {mismatch}</strong></li>"
        for mismatch in mismatches
    ])
    
    subject = "⚠️ Document Verification - Inconsistencies Detected"
    
    body_html = f"""
    <html><body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
        <div style='max-width: 600px; margin: 0 auto; padding: 20px;'>
            <h2 style='color: #ff6b6b;'>⚠️ Document Cross-Validation Failed</h2>
            
            <p>Dear User,</p>
            
            <p>We've reviewed your submitted documents but found some inconsistencies that need to be resolved:</p>
            
            <div style='background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;'>
                <h3 style='margin-top: 0; color: #856404;'>🔍 Issues Found:</h3>
                <ul style='margin: 10px 0;'>
                    {mismatch_html}
                </ul>
            </div>
            
            <p><strong>🔧 What to do next:</strong></p>
            <p>Please verify your information and re-upload the affected documents with correct details.</p>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    
def send_validation_pending_email(to_email: str, user_name: str):
    """Send email when validation is pending"""
    subject = "⏳ Document Validation In Progress"
    
    body_html = f"""
    <html><body style='font-family: Arial, sans-serif;'>
        <div style='max-width: 600px; margin: 0 auto; padding: 20px;'>
            <h2 style='color: #2196F3;'>⏳ Internal Validation In Progress</h2>
            <p>Dear {user_name},</p>
            
            <p>Thank you for submitting all required documents! 📄</p>
            
            <div style='background: #e3f2fd; border-left: 4px solid #2196F3; padding: 15px; margin: 20px 0;'>
                <p style='margin: 0;'><strong>🔍 Status:</strong> Your documents are undergoing internal cross-validation to ensure data consistency.</p>
            </div>
            
            <p><strong>⏱️ What happens next:</strong></p>
            <ul>
                <li>🤖 Our system will verify that information matches across all documents</li>
                <li>⏰ You'll receive results within 5 minutes</li>
                <li>📧 If any issues are found, we'll guide you on corrections</li>
            </ul>
            
            <p style='margin-top: 20px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_validation_failed_email(to_email: str, user_name: str, mismatches: list, attempt_count: int):
    """Send email when validation fails"""
    mismatch_html = "".join([
        f"<li style='margin: 10px 0;'><strong>❌ {m}</strong></li>"
        for m in mismatches
    ])
    
    subject = "⚠️ Document Validation - Action Required"
    
    body_html = f"""
    <html><body style='font-family: Arial, sans-serif;'>
        <div style='max-width: 600px; margin: 0 auto; padding: 20px;'>
            <h2 style='color: #ff6b6b;'>⚠️ Cross-Validation Failed</h2>
            <p>Dear {user_name},</p>
            
            <p>Your documents have been reviewed, but we found some inconsistencies that need correction:</p>
            
            <div style='background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;'>
                <h3 style='margin-top: 0; color: #856404;'>❌ Issues Found:</h3>
                <ul style='margin: 10px 0;'>
                    {mismatch_html}
                </ul>
            </div>
            
            <div style='background: #e7f3ff; border-left: 4px solid #2196F3; padding: 15px; margin: 20px 0;'>
                <h3 style='margin-top: 0; color: #0c5460;'>🔧 How to Fix:</h3>
                <p style='margin: 0;'>Simply reply to this email with corrected documents, or upload them via your dashboard.</p>
            </div>
            
            <p><strong>🔢 Validation Attempt:</strong> #{attempt_count}</p>
            
            <p style='margin-top: 20px;'>💬 Need help? Reply to this email and our team will assist you.</p>
            
            <p style='margin-top: 20px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_validation_passed_email(to_email: str, user_name: str):
    """Send email when validation passes"""
    subject = "✅ Document Verification Complete"
    
    body_html = f"""
    <html><body style='font-family: Arial, sans-serif;'>
        <div style='max-width: 600px; margin: 0 auto; padding: 20px;'>
            <h2 style='color: #4CAF50;'>✅ Document Verification Complete</h2>
            <p>Dear {user_name},</p>
            
            <p>Great news! 🎉 Your documents have passed internal validation.</p>
            
            <div style='background: #d4edda; border-left: 4px solid #4CAF50; padding: 15px; margin: 20px 0;'>
                <h3 style='margin-top: 0; color: #155724;'>✅ All Verification Checks Passed:</h3>
                <ul style='margin: 10px 0;'>
                    <li>🏢 Company name consistency: ✓</li>
                    <li>👤 Owner information match: ✓</li>
                    <li>🌍 Nationality verification: ✓</li>
                </ul>
            </div>
            
            <div style='background: #e3f2fd; border-left: 4px solid #2196F3; padding: 15px; margin: 20px 0;'>
                <h3 style='margin-top: 0; color: #0c5460;'>🎯 Final Step:</h3>
                <p style='margin: 0;'>Please confirm your documents are correct, and we'll complete your onboarding.</p>
            </div>
            
            <p style='margin-top: 20px;'>Best regards,<br><strong>Thrivv Onboarding Team</strong></p>
        </div>
    </body></html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    