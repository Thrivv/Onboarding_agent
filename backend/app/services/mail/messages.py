"""
The 19 message composers.

Moved verbatim from `email_sender.py` in C4. Each function builds a subject and
an HTML body and hands them to `transport.send_email`. No SMTP work happens
here.

These are still hand-built HTML strings rather than templates. Turning them
into real templates would change the rendered markup, which is user-visible;
C4 was a move, so the markup is untouched.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from app import config
from app.repositories.user_repository import UserRepository
# See the note in handle_reply.py: the documents root is {DOCUMENTS_PATH}/{ref_no},
# not the email-keyed relative path this module used to build by hand.
from app.services.chatupload_helpers import user_docs_path
from app.services.mail.transport import (
    send_email,
    FROM_EMAIL,
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
)
from app.services.mail.summary_pdf import generate_user_summary_pdf, sanitize_pdf_text

logger = logging.getLogger(__name__)


def send_welcome_email(to_email: str, user_name: str, account_type: str) -> bool:
    """
    Send welcome email after successful signup
    
    Args:
        to_email: User's email
        user_name: User's name
        account_type: Type of account (e.g. Corporate)
    """
    subject = f"🎉 Welcome, {user_name}! Your DigiOB Account is Ready" if user_name else "🎉 Welcome to DigiOB!"

    # Ownership Type (Single Owner vs Partnership/Multiple Owners) is no longer
    # collected at signup — the AI assistant asks it as the first onboarding
    # question — so the exact document list isn't known yet at welcome-email
    # time. Show a generic "we'll confirm shortly" note instead of guessing.
    docs_pending_note = (
        "Our assistant will ask a couple of quick questions about your "
        "business structure, then let you know exactly which documents to "
        "upload."
    )

    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .highlight {{ background: #f0f4ff; border-left: 4px solid #667eea; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .button {{ display: inline-block; padding: 14px 28px; background: #667eea; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 20px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">🎉 Welcome{f', {user_name}' if user_name else ''} to DigiOB!</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <p>Thank you for choosing DigiOB! We're excited to have you on board.</p>
                
                <div class="highlight">
                    <h3 style="margin: 0 0 15px 0; color: #667eea;">📋 Next Steps: Document Submission</h3>
                    <p style="margin: 0;">To complete your account setup, {docs_pending_note}</p>
                </div>

                <p><strong>💡 How to Submit:</strong></p>
                <ul style="line-height: 1.8;">
                    <li>Reply to this email with documents attached, OR</li>
                    <li>Use our AI Assistant chat interface</li>
                </ul>
                
                <p style="margin-top: 25px;">We'll guide you through each step of the process!</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                <p style="margin: 5px 0 0 0; font-size: 14px;">🚀 Building the future of banking together</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html, html=True)


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
    Universal document verification email for all document types and statuses
    
    Args:
        to_email: Recipient email
        user_name: User's name
        document_type: Type of document (EID, Commercial, MOA, Ejari)
        status: 'valid', 'invalid', or 'error'
        filename: Original filename
        reason: AI-generated reason/explanation
        extracted_data: Extracted document data
        is_complete: Whether onboarding is complete
        remaining_documents: List of remaining documents needed
        member_name: Optional member name for partnership accounts
    """
    member_context = f" for {member_name}" if member_name else ""
    
    # ========================================================================
    # STATUS: VALID DOCUMENT
    # ========================================================================
    if status == "valid":
        subject = f"{document_type} Verified Successfully{member_context}"
        
        # Format extracted data
        data_html = ""
        if extracted_data:
            data_html = "<div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;'>"
            data_html += "<h3 style='margin: 0 0 10px 0; color: #28a745;'>📋 Extracted Information:</h3>"
            
            # EID Data
            if document_type.upper() == "EID":
                data_html += f"<p style='margin: 5px 0;'><strong>Name:</strong> {extracted_data.get('Name') or extracted_data.get('name', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>ID Number:</strong> {extracted_data.get('ID Number') or extracted_data.get('id_number', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Nationality:</strong> {extracted_data.get('Nationality') or extracted_data.get('nationality', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Date of Birth:</strong> {extracted_data.get('Date of Birth') or extracted_data.get('date_of_birth', 'N/A')}</p>"
            
            # Commercial License Data
            elif document_type.upper() == "COMMERCIAL":
                eng = extracted_data.get("english", {})
                data_html += f"<p style='margin: 5px 0;'><strong>Company:</strong> {eng.get('company_name_english', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>License No:</strong> {eng.get('license_number', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Legal Form:</strong> {eng.get('legal_form', 'N/A')}</p>"
                
                owner = extracted_data.get("owner", {})
                if owner:
                    data_html += f"<p style='margin: 5px 0;'><strong>Owner:</strong> {owner.get('name_english', 'N/A')}</p>"
            
            # MOA Data
            elif document_type.upper() == "MOA":
                data_html += f"<p style='margin: 5px 0;'><strong>Company:</strong> {extracted_data.get('company_name', 'N/A')}</p>"
                
                owners = extracted_data.get("owners", [])
                if owners:
                    data_html += "<p style='margin: 10px 0 5px 0;'><strong>Owners/Managers:</strong></p>"
                    for owner in owners[:3]:  # Show first 3
                        data_html += f"<p style='margin: 2px 0 2px 20px;'>• {owner.get('name', 'N/A')}</p>"
            
            # Ejari Data
            elif document_type.upper() in ["EJARI", "TENANCY"]:
                data_html += f"<p style='margin: 5px 0;'><strong>Contract Number:</strong> {extracted_data.get('contract_number', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Property Type:</strong> {extracted_data.get('property_type', 'N/A')}</p>"
                data_html += f"<p style='margin: 5px 0;'><strong>Area:</strong> {extracted_data.get('area', 'N/A')}</p>"
            
            data_html += "</div>"
        
        # Remaining documents section
        remaining_html = ""
        if remaining_documents and len(remaining_documents) > 0:
            remaining_html = f"""
            <div style='background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;'>
                <h3 style='margin: 0 0 10px 0; color: #856404;'>📝 Next Steps:</h3>
                <p style='margin: 0;'>Please submit the following documents:</p>
                <ul style='margin: 10px 0 0 20px;'>
                    {"".join([f"<li>{doc}</li>" for doc in remaining_documents])}
                </ul>
            </div>
            """
        elif is_complete:
            remaining_html = """
            <div style='background: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin: 20px 0;'>
                <h3 style='margin: 0 0 10px 0; color: #155724;'>🎉 All Documents Received!</h3>
                <p style='margin: 0;'>We'll review your documents and get back to you shortly.</p>
            </div>
            """
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 40px; text-align: center; }}
                .content {{ padding: 40px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0; font-size: 28px;">Document Verified</h1>
                </div>
                <div class="content">
                    <p style="font-size: 18px;">Dear {user_name},</p>
                    
                    <p>Great news! Your <strong>{document_type}{member_context}</strong> has been successfully verified.</p>
                    
                    {data_html}
                    {remaining_html}
                    
                    <p style="margin-top: 25px;">If you have any questions, feel free to reply to this email.</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    # ========================================================================
    # STATUS: INVALID DOCUMENT
    # ========================================================================
    elif status == "invalid":
        subject = f"⚠️ {document_type} Document Issue{member_context}"
        
        reason_display = reason or "The document could not be validated. Please ensure it's clear and readable."
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #ffc107 0%, #ff9800 100%); color: white; padding: 40px; text-align: center; }}
                .content {{ padding: 40px; }}
                .reason-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0; font-size: 28px;">⚠️ Document Needs Attention</h1>
                </div>
                <div class="content">
                    <p style="font-size: 18px;">Dear {user_name},</p>
                    
                    <p>We encountered an issue with your <strong>{document_type}{member_context}</strong> document{' (' + filename + ')' if filename else ''}.</p>
                    
                    <div class="reason-box">
                        <h3 style="margin: 0 0 10px 0; color: #856404;">📋 Issue Details:</h3>
                        <p style="margin: 0; color: #856404;">{reason_display}</p>
                    </div>
                    
                    <p><strong>💡 What to do next:</strong></p>
                    <ul style="line-height: 1.8;">
                        <li>Ensure the document is clear and all text is readable</li>
                        <li>Upload a high-quality photo or scan</li>
                        <li>Make sure all required fields are visible</li>
                        <li>Verify you're uploading the correct document type</li>
                    </ul>
                    
                    <p style="margin-top: 25px;">Please upload the document again or contact support if you need assistance.</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    # ========================================================================
    # STATUS: ERROR
    # ========================================================================
    else:  # status == "error"
        subject = f"❌ Processing Error - {document_type}{member_context}"
        
        error_message = reason or "An unexpected error occurred while processing your document."
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
                .header {{ background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color: white; padding: 40px; text-align: center; }}
                .content {{ padding: 40px; }}
                .error-box {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin: 0; font-size: 28px;">❌ Processing Error</h1>
                </div>
                <div class="content">
                    <p style="font-size: 18px;">Dear {user_name},</p>
                    
                    <p>We encountered an error processing your <strong>{document_type}{member_context}</strong> document.</p>
                    
                    <div class="error-box">
                        <h3 style="margin: 0 0 10px 0; color: #721c24;">⚠️ Error Details:</h3>
                        <p style="margin: 0; color: #721c24;">{error_message}</p>
                    </div>
                    
                    <p><strong>🔧 What to do next:</strong></p>
                    <ul style="line-height: 1.8;">
                        <li>Try uploading the document again</li>
                        <li>Try a different file format (PDF, PNG, JPG)</li>
                        <li>Contact support if the issue persists</li>
                    </ul>
                    
                    <p style="margin-top: 25px;">We apologize for the inconvenience. Please try again or contact our support team.</p>
                </div>
                <div class="footer">
                    <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                    <p style="margin: 5px 0 0 0; font-size: 14px;">📧 support@digiob.com</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    return send_email(to_email, subject, body_html, html=True)


def send_wrong_document_email(to_email: str, filename: str, summary: str, required_docs: list):
    """
    Send email when incorrect document type is uploaded
    
    Args:
        to_email: User's email
        filename: Name of uploaded file
        summary: Explanation of why document is wrong
        required_docs: List of required document types
    """
    subject = "❌ Incorrect Document Submitted"
    
    required_docs_html = "".join([f"<li style='margin: 5px 0;'>{doc}</li>" for doc in required_docs])
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f8f9fa; color: #333; }}
            .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
            .header {{ background: #dc3545; color: white; padding: 24px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ padding: 24px; }}
            .reason-box {{ background: #f1f1f1; padding: 16px; border-radius: 8px; margin: 16px 0; }}
            .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">❌ Incorrect Document Received</h2>
            </div>
            <div class="content">
                <p>Dear User,</p>
                <p>We have received the file <strong>{filename}</strong> you submitted. Upon verification, this document is not the required one.</p>
                
                <div class="reason-box">
                    <strong>Reason:</strong><br>
                    {summary}
                </div>
                
                <p><strong>📋 Please resend the correct document(s) as listed below:</strong></p>
                <ul style='margin-left: 20px;'>{required_docs_html}</ul>
                
                <p>If you have any questions, feel free to reply to this email.</p>
            </div>
            <div class="footer">
                <p style="margin: 0;"><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html, html=True)


def send_validation_pending_email(to_email: str, user_name: str):
    """
    Send email when cross-validation process starts
    """
    subject = "⏳ Document Validation In Progress"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .info-box {{ background: #e3f2fd; border-left: 4px solid #2196F3; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">⏳ Internal Validation In Progress</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <p>Thank you for submitting all required documents!</p>
                
                <div class="info-box">
                    <h3 style="margin: 0 0 10px 0; color: #1976D2;">🔍 What's happening now?</h3>
                    <p style="margin: 0;">We're cross-validating your documents to ensure all information is consistent and accurate across your submissions.</p>
                </div>
                
                <p><strong>⏱️ Timeline:</strong> This process typically takes 24-48 hours.</p>
                
                <p><strong>📧 Next Steps:</strong> We'll email you as soon as the validation is complete.</p>
                
                <p style="margin-top: 25px;">Thank you for your patience!</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html, html=True)


def send_validation_passed_email(to_email: str, user_name: str):
    """
    Send email when cross-validation passes successfully
    """
    subject = "Document Verification Complete"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .success-box {{ background: #d4edda; border-left: 4px solid #4CAF50; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .next-steps {{ background: #e3f2fd; border-left: 4px solid #2196F3; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">Document Verification Complete</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <p>Great news! 🎉 Your documents have passed internal validation.</p>
                
                <div class="success-box">
                    <h3 style="margin-top: 0; color: #155724;">All Verification Checks Passed:</h3>
                    <ul style="margin: 10px 0;">
                        <li>🏢 Company name consistency: ✓</li>
                        <li>👤 Owner information match: ✓</li>
                        <li>🌍 Nationality verification: ✓</li>
                        <li>📅 Date consistency: ✓</li>
                    </ul>
                </div>
                
                <div class="next-steps">
                    <h3 style="margin-top: 0; color: #0c5460;">🎯 Final Step:</h3>
                    <p style="margin: 0;">Please confirm your documents are correct, and we'll complete your onboarding.</p>
                </div>
                
                <p style="margin-top: 25px;">You'll receive a confirmation email shortly with all extracted information.</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html, html=True)


def send_validation_failed_email(to_email: str, user_name: str, mismatches: List[str], attempt_count: int = 1):
    """
    Send email when cross-validation fails
    
    Args:
        to_email: User's email
        user_name: User's name
        mismatches: List of inconsistencies found
        attempt_count: Number of validation attempts
    """
    subject = "⚠️ Document Verification - Inconsistencies Detected"
    
    mismatch_html = "".join([
        f"<li style='margin:10px 0;'><strong>❌ {mismatch}</strong></li>"
        for mismatch in mismatches
    ])
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .warning-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">⚠️ Document Cross-Validation Failed</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear {user_name},</p>
                
                <p>We've reviewed your submitted documents but found some inconsistencies that need to be resolved:</p>
                
                <div class="warning-box">
                    <h3 style="margin-top: 0; color: #856404;">🔍 Issues Found:</h3>
                    <ul style="margin: 10px 0;">
                        {mismatch_html}
                    </ul>
                </div>
                
                <p><strong>🔧 What to do next:</strong></p>
                <ul style="line-height: 1.8;">
                    <li>Please verify your information and re-upload the affected documents with correct details</li>
                    <li>Ensure all documents contain consistent information (names, dates, company details)</li>
                    <li>If you need assistance, reply to this email or contact support</li>
                </ul>
                
                <p style="margin-top: 25px; color: #666;"><em>Validation attempt: {attempt_count}</em></p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                <p style="margin: 5px 0 0 0; font-size: 14px;">📧 Reply to this email and our team will assist you</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html, html=True)


def send_cross_validation_error_email(to_email: str, validation_result: dict):
    """
    Send email when cross-validation detects inconsistencies
    (Alternative detailed version)
    """
    mismatches = validation_result.get("mismatches", [])
    
    mismatch_html = "".join([
        f"<li style='margin:10px 0;'><strong>❌ {mismatch}</strong></li>"
        for mismatch in mismatches
    ])
    
    subject = "⚠️ Document Verification - Inconsistencies Detected"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #ff6b6b; color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
            .content {{ background: #fff; padding: 30px; border: 1px solid #ddd; border-top: none; }}
            .warning-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; }}
            .footer {{ background: #f8f9fa; padding: 15px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">⚠️ Document Cross-Validation Failed</h2>
            </div>
            <div class="content">
                <p>Dear User,</p>
                
                <p>We've reviewed your submitted documents but found some inconsistencies that need to be resolved:</p>
                
                <div class="warning-box">
                    <h3 style="margin-top: 0; color: #856404;">🔍 Issues Found:</h3>
                    <ul style="margin: 10px 0;">
                        {mismatch_html}
                    </ul>
                </div>
                
                <p><strong>🔧 What to do next:</strong></p>
                <p>Please verify your information and re-upload the affected documents with correct details.</p>
            </div>
            <div class="footer">
                <p style="margin: 0;"><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return send_email(to_email=to_email, subject=subject, body=body_html, html=True)


def send_tampering_rejection_email(user_email: str, reason: str, test_report_id: str, doc_type: str):
    """
    Send email notification for rejected documents (tampering detected)
    
    Args:
        user_email: Recipient email
        reason: Rejection reason from LLM analysis
        test_report_id: Test report UUID for reference
        doc_type: Document type (eid, commercial, etc.)
    """
    subject = "🔒 Document Security Alert - Verification Failed"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .alert-box {{ background: #f8d7da; border-left: 4px solid #dc3545; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">🔒 Document Security Alert</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear User,</p>
                
                <p>Our automated security system has detected potential issues with your <strong>{doc_type.upper()}</strong> document.</p>
                
                <div class="alert-box">
                    <h3 style="margin: 0 0 10px 0; color: #721c24;">⚠️ Security Analysis:</h3>
                    <p style="margin: 0; color: #721c24;">{reason}</p>
                </div>
                
                <p><strong>Reference ID:</strong> <code style="background: #f8f9fa; padding: 4px 8px; border-radius: 4px;">{test_report_id}</code></p>
                
                <h3 style="color: #333;">📝 Next Steps:</h3>
                <ul style="line-height: 1.8;">
                    <li>Please ensure you are uploading the <strong>original, unmodified</strong> document</li>
                    <li>Take a clear photo or scan of the physical document</li>
                    <li>Do not edit, enhance, or modify the document in any way</li>
                    <li>Re-upload the document through our portal</li>
                </ul>
                
                <p>If you believe this rejection is in error or need assistance, please contact our support team with your reference ID.</p>
                
                <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>📞 Support Contact:</strong></p>
                    <p style="margin: 5px 0 0 0;">Email: support@digiob.com<br>Phone: +971 XXX XXXX</p>
                </div>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Security Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(user_email, subject, body_html, html=True)
    logger.info(f"Tampering rejection email sent to {user_email}")


def send_manual_review_email_tampering(user_email: str, test_report_id: str, doc_type: str):
    """
    Send email notification for documents requiring manual review (tampering escalation)
    
    Args:
        user_email: Recipient email
        test_report_id: Test report UUID for reference
        doc_type: Document type
    """
    subject = "🔍 Document Under Manual Review"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f7fa; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 40px auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%); color: white; padding: 40px; text-align: center; }}
            .content {{ padding: 40px; }}
            .info-box {{ background: #fff3cd; border-left: 4px solid #ff9800; padding: 20px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 20px; text-align: center; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 28px;">🔍 Manual Review Required</h1>
            </div>
            <div class="content">
                <p style="font-size: 18px;">Dear User,</p>
                
                <p>Your <strong>{doc_type.upper()}</strong> document requires additional verification by our security team. This is a standard procedure for certain submissions.</p>
                
                <div class="info-box">
                    <h3 style="margin: 0 0 10px 0; color: #856404;">⏱️ What's Next?</h3>
                    <p style="margin: 0;">Our team will manually review your document and contact you within <strong>24-48 hours</strong> with the results.</p>
                </div>
                
                <p><strong>Reference ID:</strong> <code style="background: #f8f9fa; padding: 4px 8px; border-radius: 4px;">{test_report_id}</code></p>
                
                <p><strong>📌 No Action Required:</strong> You don't need to do anything right now. We'll email you once the review is complete.</p>
                
                <p style="margin-top: 25px;">Thank you for your patience!</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Security Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(user_email, subject, body_html, html=True)
    logger.info(f"Manual review email sent to {user_email}")


def send_member_identification_email(to_email: str, members: List[str], 
                                     user_in_documents: bool, 
                                     user_validation: dict = None):
    """
    Send email after identifying all members from Commercial + MOA
    Shows list of managers/partners and EID requirements
    
    Args:
        to_email: User's email
        members: List of member names
        user_in_documents: Whether registered user is in company docs
        user_validation: Validation details
    """
    try:
        from app.repositories.user_repository import UserRepository
        user_response = UserRepository.get_name(to_email)
        user_name = user_response.data[0].get("name") if user_response.data else "User"
    except:
        user_name = "User"
    
    subject = "📋 Owners Identified - EID Collection Process"
    
    # Build member list HTML
    member_list_html = "".join([f"<li style='margin: 5px 0;'><strong>{member}</strong></li>" for member in members])
    
    # Dynamic message based on validation
    if user_in_documents:
        found_in = user_validation.get("found_in", "company documents") if user_validation else "company documents"
        eid_message = f"""
        <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
            <h3 style='margin:0 0 10px 0;color:#2e7d32;'>You are listed in the {found_in}</h3>
            <p style='margin:0;'>We found your name in the company documents, so we'll need your Emirates ID along with the other members.</p>
        </div>
        """
    else:
        eid_message = f"""
        <div style='background:#fff3e0;padding:15px;border-radius:5px;margin:20px 0;'>
            <h3 style='margin:0 0 10px 0;color:#e65100;'>ℹ️ EID Collection for Company Members</h3>
            <p style='margin:0;'>We need Emirates IDs for all managers/partners listed in your company documents.</p>
        </div>
        """
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
            .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ padding: 24px; }}
            .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">Company Documents Verified</h2>
            </div>
            <div class="content">
                <p>Dear {user_name},</p>
                
                <p>Great news! We've successfully processed your Commercial License and MOA.</p>
                
                {eid_message}
                
                <h3 style='color:#2196F3;margin-top:20px;'>📋 Identified Members/Partners:</h3>
                <ul style='margin-left:20px;'>{member_list_html}</ul>
                
                <p><strong>📌 Next Step:</strong> We'll request Emirates IDs for each member individually via email.</p>
                
                <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    logger.info(f"Member identification email sent to {to_email}")


def send_member_eid_request_email(to_email: str, member_name: str, 
                                  member_num: int, total_members: int):
    """
    Request EID for specific member with progress indicator
    
    Args:
        to_email: User's email
        member_name: Name of member whose EID is needed
        member_num: Current member number
        total_members: Total number of members
    """
    subject = f"📄 EID Required for {member_name} (Member {member_num}/{total_members})"
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
            .header {{ background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ padding: 24px; }}
            .progress-box {{ background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0; text-align: center; }}
            .name-box {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; text-align: center; }}
            .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">📄 EID Required for {member_name}</h2>
            </div>
            <div class="content">
                <p>Dear User,</p>
                
                <div class="progress-box">
                    <p style='margin:0;'><strong>Progress:</strong> Member {member_num} of {total_members}</p>
                </div>
                
                <p>Please submit the <strong>Emirates ID (EID)</strong> for:</p>
                
                <div class="name-box">
                    <h3 style='margin:0;color:#2196F3;'>{member_name}</h3>
                </div>
                
                <p><strong>📝 Instructions:</strong></p>
                <ul style='margin-left:20px; line-height: 1.8;'>
                    <li>Reply to this email with the EID document attached</li>
                    <li>Accepted formats: PDF, PNG, JPG, JPEG</li>
                    <li>Ensure all fields are clearly visible</li>
                    <li>Document must be unmodified and authentic</li>
                </ul>
                
                <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    logger.info(f"Sent EID request email for {member_name} (Member {member_num}/{total_members})")


def send_member_documents_confirmation_email(to_email: str, members: List[str]):
    """
    Send confirmation email with ALL member documents for verification
    Similar to single owner flow - shows all extracted data and asks for confirmation
    
    Args:
        to_email: User's email
        members: List of member names
    """
    try:
        import os
        import json
        from urllib.parse import quote
        
        # Get API base URL
        API_BASE = config.API_BASE_URL or "http://localhost:7000"
        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"
        
        # Collect all member documents from disk
        user_docs_dir = str(user_docs_path(to_email))
        all_member_docs = []
        
        for member_name in members:
            member_dir = os.path.join(user_docs_dir, member_name)
            
            if not os.path.exists(member_dir):
                continue
            
            # Find EID output.json for this member
            for item in os.listdir(member_dir):
                item_path = os.path.join(member_dir, item)
                
                if not os.path.isdir(item_path):
                    continue
                
                output_path = os.path.join(item_path, "output.json")
                
                if os.path.exists(output_path):
                    try:
                        with open(output_path, "r", encoding="utf-8") as f:
                            analysis = json.load(f)
                        
                        doc_type = analysis.get("document_type", "unknown")
                        is_valid = analysis.get("is_valid", False)
                        
                        if doc_type == "eid" and is_valid:
                            extracted = analysis.get("extracted_fields", {})
                            all_member_docs.append({
                                "member_name": member_name,
                                "extracted": extracted
                            })
                            break
                    except Exception as e:
                        logger.error(f"Failed to read {output_path}: {e}")
        
        # Build HTML for member documents
        member_docs_html = ""
        for doc in all_member_docs:
            member_name = doc["member_name"]
            extracted = doc["extracted"]
            
            member_docs_html += f"""
            <div style='background:#f8f9fa;padding:15px;border-radius:5px;margin:15px 0;border-left:3px solid #4CAF50;'>
                <h4 style='margin:0 0 10px 0;color:#2196F3;'>👤 {member_name}</h4>
                <p style='margin:5px 0;'><strong>Name:</strong> {extracted.get('Name', 'N/A')}</p>
                <p style='margin:5px 0;'><strong>ID Number:</strong> {extracted.get('ID Number', 'N/A')}</p>
                <p style='margin:5px 0;'><strong>Nationality:</strong> {extracted.get('Nationality', 'N/A')}</p>
                <p style='margin:5px 0;'><strong>Date of Birth:</strong> {extracted.get('Date of Birth', 'N/A')}</p>
            </div>
            """
        
        # Also collect main company documents
        main_docs_html = ""
        for item in os.listdir(user_docs_dir):
            item_path = os.path.join(user_docs_dir, item)
            
            # Skip member directories
            if any(item == member for member in members):
                continue
            
            if not os.path.isdir(item_path) or item == "member_progress.json":
                continue
            
            output_path = os.path.join(item_path, "output.json")
            
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    
                    doc_type = analysis.get("document_type", "unknown").upper()
                    is_valid = analysis.get("is_valid", False)
                    
                    if is_valid:
                        main_docs_html += f"""
                        <div style='background:#f8f9fa;padding:10px;margin:10px 0;border-left:3px solid #4CAF50;border-radius:3px;'>
                            <strong>{doc_type}</strong>
                        </div>
                        """
                except:
                    pass
        
        subject = "All Member Documents Received - Please Confirm"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
                .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
                .content {{ padding: 24px; }}
                .summary-box {{ background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .confirm-box {{ margin-top: 30px; text-align: center; background: #f8f9fa; padding: 20px; border-radius: 8px; }}
                .button {{ display: inline-block; padding: 14px 32px; background: #4caf50; color: #fff; border-radius: 6px; text-decoration: none; font-size: 18px; font-weight: bold; }}
                .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">All Documents Received</h2>
                </div>
                <div class="content">
                    <p>Dear User,</p>
                    
                    <p>We've successfully collected all required documents for your partnership account.</p>
                    
                    <div class="summary-box">
                        <p style='margin:0;'><strong>📊 Summary:</strong></p>
                        <ul style='margin:10px 0 0 20px;'>
                            <li>Total Members: <strong>{len(members)}</strong></li>
                            <li>Member EIDs: <strong>{len(all_member_docs)}</strong></li>
                        </ul>
                    </div>
                    
                    <h3 style='color:#1976d2;margin-top:30px;'>🏢 Company Documents</h3>
                    {main_docs_html if main_docs_html else '<p style="color:#999;">No company documents found</p>'}
                    
                    <h3 style='color:#4caf50;margin-top:30px;'>👥 Member Emirates IDs</h3>
                    {member_docs_html if member_docs_html else '<p style="color:#999;">No member EIDs found</p>'}
                    
                    <div class="confirm-box">
                        <p style='margin:0 0 15px 0;font-size:16px;'><strong>Please verify all information is correct</strong></p>
                        <a href="{confirm_link}" class="button">Confirm All Information</a>
                    </div>
                    
                    <p style='margin-top:20px;color:#666;font-size:14px;'>If any information is incorrect, please reply to this email.</p>
                    
                    <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        logger.info(f"Member documents confirmation email sent to {to_email}")
    
    except Exception as e:
        logger.error(f"Failed to send member documents confirmation email: {e}")
        import traceback
        logger.error(traceback.format_exc())


def send_all_members_complete_email(to_email: str, members: List[str]):
    """
    Send completion email after all member EIDs verified
    
    Args:
        to_email: User's email
        members: List of all member names
    """
    subject = "🎉 All Member Documents Verified - Onboarding Complete!"
    
    member_list_html = "".join([f"<li style='margin: 5px 0;'>{member}</li>" for member in members])
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
            .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 40px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ padding: 24px; }}
            .success-box {{ background: #d4edda; padding: 20px; border-radius: 5px; margin: 20px 0; text-align: center; border: 2px solid #4CAF50; }}
            .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1 style="margin: 0; font-size: 32px;">🎉 All Member Documents Verified</h1>
            </div>
            <div class="content">
                <p>Dear User,</p>
                
                <p>Great news! We've successfully verified Emirates IDs for all members:</p>
                
                <ul style='margin-left:20px; line-height: 1.8;'>{member_list_html}</ul>
                
                <div class="success-box">
                    <h3 style='margin:0 0 10px 0;color:#155724;'>Onboarding Complete</h3>
                    <p style='margin:0;'>Your account will be activated within <strong>3-4 business days</strong>.</p>
                </div>
                
                <p><strong>📧 Next Steps:</strong></p>
                <ul style='line-height: 1.8;'>
                    <li>You'll receive account details via email</li>
                    <li>All partners will get access credentials</li>
                    <li>You can start using DigiOB services once activated</li>
                </ul>
                
                <p style='margin-top:32px;'>Thank you for choosing DigiOB! 🏦</p>
                
                <p>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    logger.info(f"All members complete email sent to {to_email}")


def send_document_status_email(to_email: str, documents: List[dict], 
                               is_member: bool = False, member_name: str = None):
    """
    Send comprehensive document status email with extracted data
    Includes confirmation button for user to verify all information
    
    Args:
        to_email: User's email
        documents: List of document dictionaries with extracted data
        is_member: Whether these are member documents
        member_name: Name of member (if applicable)
    """
    try:
        import os
        from urllib.parse import quote
        
        API_BASE = config.API_BASE_URL or "http://localhost:7000"
        confirm_link = f"{API_BASE}/chat/confirm-document?email={quote(to_email)}"
        
        # Build HTML for all documents
        docs_html = ""
        for doc in documents:
            filename = doc.get("filename", "Unknown")
            doc_type = doc.get("document_type", "unknown").upper()
            extracted = doc.get("extracted_fields", {})
            
            # Build extracted fields HTML
            fields_html = ""
            field_count = 0
            for key, value in extracted.items():
                if value and value != "N/A" and field_count < 10:  # Limit to 10 fields per document
                    fields_html += f"<p style='margin:5px 0;'><strong>{key}:</strong> {value}</p>"
                    field_count += 1
            
            docs_html += f"""
            <div style='background:#f8f9fa;padding:15px;border-radius:5px;margin:15px 0;border-left:3px solid #4CAF50;'>
                <h4 style='margin:0 0 10px 0;color:#2196F3;'>{doc_type}</h4>
                <p style='margin:5px 0;color:#666;'><em>{filename}</em></p>
                <div style='margin-top:10px;'>{fields_html if fields_html else '<p style="color:#999;">No extracted data available</p>'}</div>
            </div>
            """
        
        member_context = f" for {member_name}" if member_name else ""
        subject = f"Documents Verified{member_context} - Please Confirm"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
                .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
                .content {{ padding: 24px; }}
                .confirm-box {{ margin-top: 30px; text-align: center; background: #f8f9fa; padding: 20px; border-radius: 8px; }}
                .button {{ display: inline-block; padding: 14px 32px; background: #4caf50; color: #fff; border-radius: 6px; text-decoration: none; font-size: 18px; font-weight: bold; }}
                .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">Documents Verified</h2>
                </div>
                <div class="content">
                    <p>Dear User,</p>
                    
                    <p>We've successfully processed your documents{member_context}. Please review the extracted information:</p>
                    
                    {docs_html}
                    
                    <div class="confirm-box">
                        <p style='margin:0 0 15px 0;font-size:16px;'><strong>Is all information correct?</strong></p>
                        <a href="{confirm_link}" class="button">Confirm Documents</a>
                    </div>
                    
                    <p style='margin-top:20px;color:#666;font-size:14px;'>If any information is incorrect, please reply to this email with corrections.</p>
                    
                    <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        logger.info(f"Document status email sent to {to_email}")
    
    except Exception as e:
        logger.error(f"Failed to send document status email: {e}")
        import traceback
        logger.error(traceback.format_exc())


def send_missing_documents_email(to_email: str, missing_docs: List[str], 
                                 account_type: str, invalid_reasons: dict = None):
    """
    Notify user about missing or invalid documents
    
    Args:
        to_email: User's email
        missing_docs: List of missing document types
        account_type: Account type
        invalid_reasons: Dictionary of document -> reason (optional)
    """
    if invalid_reasons is None:
        invalid_reasons = {}
    
    subject = "📋 Missing Documents - Action Required"
    
    # Format document list with reasons
    docs_html = "".join([
        f"""<li style='margin: 8px 0;'><strong>{doc}</strong>
        {f'<br><span style="color:#e53935;font-size:14px;">Reason: {invalid_reasons.get(doc, "")}</span>' 
         if invalid_reasons.get(doc) else ''}</li>"""
        for doc in missing_docs
    ])
    
    body_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: auto; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 2px 8px #eee; }}
            .header {{ background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center; }}
            .content {{ padding: 24px; }}
            .docs-box {{ background: #fff3cd; border-left: 4px solid #ff9800; padding: 15px; margin: 20px 0; border-radius: 5px; }}
            .footer {{ background: #f8f9fa; padding: 16px; text-align: center; color: #666; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2 style="margin: 0;">📋 Missing Documents</h2>
            </div>
            <div class="content">
                <p>Dear User,</p>
                
                <p>We still need the following documents to complete your onboarding:</p>
                
                <div class="docs-box">
                    <ul style='margin: 10px 0;'>{docs_html}</ul>
                </div>
                
                <p><strong>📤 How to Submit:</strong></p>
                <ul style='line-height: 1.8;'>
                    <li>Reply to this email with the documents attached, OR</li>
                    <li>Use our AI Assistant chat interface</li>
                </ul>
                
                <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(to_email=to_email, subject=subject, body=body_html, html=True)
    logger.info(f"Missing documents email sent to {to_email}")


def send_onboarding_completion_email(to_email: str, user_name: str):
    """
    Send final onboarding completion email (without PDF)
    For completion WITH PDF, use send_completion_email()
    
    Args:
        to_email: User's email
        user_name: User's name
    """
    subject = "🎉 Document Verification Stage Complete - Account Activation Pending"
    
    body_html = f"""
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
                    <h2 style="margin: 0 0 15px 0; color: #4CAF50;">Document Verification Stage Complete!</h2>
                    <p style="margin: 0; font-size: 16px;">All your documents have been successfully verified.</p>
                </div>
                
                <div class="timeline">
                    <h3 style="margin: 0 0 15px 0; color: #333;">📅 What Happens Next?</h3>
                    <ul style="list-style: none; padding: 0; margin: 0;">
                        <li style="margin: 10px 0;">✓ <strong>Account Activation:</strong> 3-4 business days</li>
                        <li style="margin: 10px 0;">✓ <strong>Welcome Package:</strong> Sent via email</li>
                        <li style="margin: 10px 0;">✓ <strong>Login Credentials:</strong> Provided once activated</li>
                    </ul>
                </div>
                
                <p style="margin-top: 25px;">We'll send you login credentials and a welcome package with detailed instructions.</p>
                
                <p style="margin-top: 30px;">Thank you for choosing DigiOB! 🏦</p>
            </div>
            <div class="footer">
                <p style="margin: 0; font-weight: 600;">DigiOB Onboarding Team</p>
                <p style="margin: 5px 0 0 0; font-size: 14px;">🚀 Building the future of banking together</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    send_email(to_email, subject, body_html, html=True)
    logger.info(f"[SUCCESS] Onboarding completion email sent to {to_email}")


def send_completion_email(to_email: str, account_type: str):
    """
    Send onboarding completion email with PDF summary attached
    FIXED: Unified path construction for all flows (email/chat/document upload)
    """
    # Fetch user details
    user_response = UserRepository.get_by_email(to_email)
    user = user_response.data[0] if user_response.data else {}

    ownership_type = user.get("ownership_type", "")
    
    # UNIFIED PATH CONSTRUCTION - Works for ALL flows
    # This module lives at backend/app/services/email_sender.py, so backend/ is
    # THREE levels up — same computation document_helpers.get_documents_base_path()
    # uses for its own local-dev fallback. A previous version went up only one
    # level (landing on backend/app/) off the back of a stale comment claiming
    # this file lived in llm_pipeline/. That silently pointed the two local-dev
    # fallbacks below at backend/app/documents and backend/app/summary, neither
    # of which exists. It never showed up in production because /app/backend
    # exists inside the image, so the absolute Docker branches always won.
    code_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Result: .../backend/

    # Config-driven (YAML / env var) base path — falls back to ref_no,
    # then legacy email-keyed folder for old data saved before the ref_no migration.
    try:
        from app.services.document_helpers import get_documents_base_path, get_document_ref_no
        _docs_base = get_documents_base_path()
        _ref_no = user.get("ref_no") or get_document_ref_no(to_email)
        user_docs_dir = str(_docs_base / _ref_no)
        if not os.path.exists(user_docs_dir):
            user_docs_dir = str(_docs_base / to_email)
    except Exception:
        # Last-resort legacy fallback if document_helpers import fails
        if os.path.exists("/app/backend"):
            user_docs_dir = str(user_docs_path(to_email))
        else:
            user_docs_dir = os.path.join(code_backend_dir, "documents", "id", to_email)

    # Use absolute path with /app/backend for Docker compatibility
    if os.path.exists("/app/backend"):
        # Docker environment
        summary_dir = "/app/backend/summary"
    else:
        # Local environment
        summary_dir = os.path.join(code_backend_dir, "summary")

    # Create summary directory with proper permissions
    os.makedirs(summary_dir, exist_ok=True)
    
    logger.debug(
        f"[PDF] paths user_docs_dir={user_docs_dir} (exists={os.path.exists(user_docs_dir)}) "
        f"summary_dir={summary_dir} (exists={os.path.exists(summary_dir)})"
    )

    # Generate PDF filename
    safe_email = to_email.replace('@', '_at_').replace('.', '_')
    pdf_filename = f"onboarding_summary_{safe_email}.pdf"
    pdf_path = os.path.join(summary_dir, pdf_filename)

    # Generate PDF
    try:
        generate_user_summary_pdf(user, user_docs_dir, pdf_path)

        # Verify PDF was created and has content
        if os.path.exists(pdf_path):
            pdf_size = os.path.getsize(pdf_path)
            if pdf_size < 1000:
                logger.warning(f"[PDF] generated {pdf_path} but it looks too small ({pdf_size} bytes) — may be empty")
            else:
                logger.info(f"[PDF] generated {pdf_filename} ({pdf_size:,} bytes) for {to_email}")
        else:
            logger.error(f"[PDF] file was not created at expected path: {pdf_path}")
            pdf_path = None

    except Exception as e:
        logger.error(f"[PDF] failed to generate for {to_email}: {e}", exc_info=True)
        pdf_path = None

    # Email body
    subject = "🎉 Onboarding Complete!"
    body_html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;'>
        <div style='max-width:600px;margin:auto;padding:24px;background:#fff;border-radius:10px;box-shadow:0 2px 8px #eee;'>
            <h2 style='color:#4CAF50;'>🎉 Onboarding Complete!</h2>
            <p>Dear {user.get('name', 'User')},</p>
            <p>Congratulations, {user.get('name', 'User')} — your onboarding is complete.</p>
            <p>Every document you submitted has been verified successfully.</p>
            
            <div style='background:#e8f5e9;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>📄 Attached Document:</strong></p>
                <p style='margin:10px 0 0 0;'>Please find your comprehensive onboarding summary attached to this email. This document contains all your submitted information and extracted document details.</p>
            </div>
            
            <div style='background:#e3f2fd;padding:15px;border-radius:5px;margin:20px 0;'>
                <p style='margin:0;'><strong>📋 Next Steps:</strong></p>
                <p style='margin:10px 0 0 0;'>Your account will be activated within <strong>3-4 business days</strong>. You will receive a confirmation email with your account details.</p>
            </div>
            
            <p>If you have any questions, feel free to reply to this email.</p>
            
            <p style='margin-top:32px;'>Best regards,<br><strong>DigiOB Onboarding Team</strong></p>
        </div>
    </body></html>
    """

    # Send email WITH PDF attachment
    try:
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            send_email(
                to_email=to_email,
                subject=subject,
                body=body_html,
                html=True,
                attachments=[{
                    'filename': pdf_filename,
                    'data': pdf_data,
                    'mime_type': 'application/pdf'
                }]
            )
            logger.info(f"[SUCCESS] Completion email sent with PDF attachment ({len(pdf_data):,} bytes) to {to_email}")
            logger.info(f"PDF saved at: {pdf_path}")
        else:
            send_email(to_email=to_email, subject=subject, body=body_html, html=True)
            logger.warning(f"Completion email sent WITHOUT PDF attachment to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send completion email: {e}")
        import traceback
        logger.error(traceback.format_exc())


def send_corporate_shareholder_request_email(
    to_email: str,
    corp_name: str,
    corp_index: int,
    total_corps: int,
) -> None:
    """
    Request a Certificate of Incorporation for a detected corporate shareholder.

    Sent after Commercial License extraction reveals a corporate entity
    in the partners list (Type-2 Multiple Owner flow).
    """
    subject = f"Action Required: Certificate of Incorporation for {corp_name}"

    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(corp_index, f"{corp_index}th")

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5; margin: 0; padding: 0;">
      <div style="max-width: 620px; margin: 32px auto; background: #fff;
                  border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
                  overflow: hidden;">

        <!-- Header -->
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                    padding: 32px 24px; text-align: center;">
          <h1 style="color: #fff; margin: 0; font-size: 22px; font-weight: 700;">
            Certificate of Incorporation Required
          </h1>
          <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0; font-size: 14px;">
            Corporate Shareholder Verification ({corp_index} of {total_corps})
          </p>
        </div>

        <!-- Body -->
        <div style="padding: 28px 24px;">
          <div style="background: #fef3c7; border: 1px solid #f59e0b;
                      border-radius: 8px; padding: 16px; margin-bottom: 20px;">
            <p style="margin: 0; font-weight: 600; color: #92400e;">
              Corporate Shareholder Detected
            </p>
            <p style="margin: 8px 0 0; color: #78350f; font-size: 14px;">
              Your Commercial License lists <strong>{corp_name}</strong> as a shareholder.
              As this is a corporate entity, we require its Certificate of Incorporation
              to verify the ultimate beneficial owners.
            </p>
          </div>

          <p style="font-size: 15px; line-height: 1.6;">
            Dear Applicant,
          </p>
          <p style="font-size: 15px; line-height: 1.6;">
            We have detected that <strong>{corp_name}</strong> holds shares in your company.
            As part of our KYC/AML compliance process, we require the Certificate of
            Incorporation (or equivalent registration document) for this corporate entity.
          </p>

          <div style="background: #f0f9ff; border-left: 4px solid #4f46e5;
                      border-radius: 4px; padding: 16px; margin: 20px 0;">
            <p style="margin: 0; font-weight: 600; color: #1e3a8a;">
              What to upload:
            </p>
            <ul style="margin: 8px 0 0; padding-left: 20px; color: #1e40af; font-size: 14px; line-height: 1.8;">
              <li>Certificate of Incorporation / Registration Certificate for <strong>{corp_name}</strong></li>
              <li>Document must show the company name, registration number, and
                  the list of directors/shareholders with ownership percentages</li>
              <li>Accepted formats: PDF, JPG, PNG</li>
            </ul>
          </div>

          <p style="font-size: 14px; color: #666; margin-top: 20px;">
            This is the <strong>{ordinal} of {total_corps}</strong> corporate shareholder document requested.
          </p>
          <p style="font-size: 14px; color: #666;">
            Please reply to this email with the document attached, or upload it directly
            through the DigiOB onboarding portal.
          </p>
        </div>

        <!-- Footer -->
        <div style="background: #f8f7ff; border-top: 1px solid #e0e7ff;
                    padding: 16px 24px; text-align: center;">
          <p style="margin: 0; font-size: 12px; color: #888;">
            DigiOB Onboarding &bull; This is an automated notification
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        logger.info(f"[SUCCESS] Corporate shareholder CoI request sent to {to_email} for {corp_name}")
    except Exception as e:
        logger.error(f"Failed to send corporate shareholder request email: {e}")


def send_ubo_identified_email(
    to_email: str,
    expanded_owners: List[dict],
    ubo_names: List[str],
) -> None:
    """
    Notify the applicant about the UBO identification results after
    Type-2 ownership expansion is complete.

    Sent just before requesting member EIDs so the applicant understands
    why those specific individuals are being asked for ID documents.
    """
    subject = "Beneficial Ownership Verified — Emirates ID Collection Starting"

    # Build ownership table rows
    rows_html = ""
    for owner in expanded_owners:
        name = owner.get("name", "")
        pct  = owner.get("effective_percentage", 0)
        src  = owner.get("source", "direct")
        parent = owner.get("corporate_parent", "")
        is_ubo = owner.get("is_ubo", False)

        badge = (
            '<span style="background:#fbbf24;color:#78350f;padding:2px 8px;'
            'border-radius:12px;font-size:11px;font-weight:700;">★ UBO</span>'
            if is_ubo else ""
        )
        source_text = (
            f"via {parent}" if src == "corporate_expansion" and parent else "Direct"
        )
        rows_html += f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e8e7ff;">{name} {badge}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e8e7ff;text-align:center;">
            {pct:.2f}%
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e8e7ff;
                     color:#6366f1;font-size:13px;">{source_text}</td>
        </tr>
        """

    ubo_list_html = "".join(f"<li><strong>{n}</strong></li>" for n in ubo_names) or "<li>None identified</li>"

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; background: #f5f5f5; margin: 0; padding: 0;">
      <div style="max-width: 660px; margin: 32px auto; background: #fff;
                  border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
                  overflow: hidden;">

        <!-- Header -->
        <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                    padding: 32px 24px; text-align: center;">
          <h1 style="color: #fff; margin: 0; font-size: 22px; font-weight: 700;">
            Beneficial Ownership Structure Verified
          </h1>
          <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0; font-size: 14px;">
            Effective ownership calculated after corporate expansion
          </p>
        </div>

        <!-- Body -->
        <div style="padding: 28px 24px;">
          <p style="font-size: 15px; line-height: 1.6;">
            Dear Applicant,
          </p>
          <p style="font-size: 15px; line-height: 1.6;">
            We have successfully verified all Certificates of Incorporation and
            calculated the effective ownership structure of your company. Below
            is the final breakdown:
          </p>

          <!-- Ownership Table -->
          <table style="width:100%;border-collapse:collapse;margin:20px 0;
                        border-radius:8px;overflow:hidden;border:1px solid #e0e7ff;">
            <thead>
              <tr style="background:#4f46e5;color:#fff;">
                <th style="padding:12px;text-align:left;">Individual</th>
                <th style="padding:12px;text-align:center;">Effective %</th>
                <th style="padding:12px;text-align:left;">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>

          <!-- UBO Summary -->
          <div style="background:#fffbeb;border:1px solid #f59e0b;
                      border-radius:8px;padding:16px;margin-top:16px;">
            <p style="margin:0;font-weight:700;color:#92400e;">
              Ultimate Beneficial Owners (UBO) — Ownership > 25%
            </p>
            <ul style="margin:8px 0 0;padding-left:20px;color:#78350f;line-height:1.8;">
              {ubo_list_html}
            </ul>
          </div>

          <div style="background:#f0fdf4;border:1px solid #22c55e;
                      border-radius:8px;padding:16px;margin-top:20px;">
            <p style="margin:0;font-weight:600;color:#15803d;">Next Step</p>
            <p style="margin:8px 0 0;font-size:14px;color:#166534;">
              We will now request an Emirates ID (EID) from each of the
              {len(expanded_owners)} individuals listed above. Please ensure
              each person has their EID ready for upload.
            </p>
          </div>
        </div>

        <!-- Footer -->
        <div style="background:#f8f7ff;border-top:1px solid #e0e7ff;
                    padding:16px 24px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#888;">
            DigiOB Onboarding &bull; This is an automated notification
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        send_email(to_email=to_email, subject=subject, body=body_html, html=True)
        logger.info(f"[SUCCESS] UBO identified email sent to {to_email} | UBOs: {ubo_names}")
    except Exception as e:
        logger.error(f"Failed to send UBO identified email: {e}")
