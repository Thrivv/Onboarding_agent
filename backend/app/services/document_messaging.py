# app/services/document_messaging.py

"""
Document messaging service for generating AI-powered messages
ALL messages use LLM with retry logic - NO fallback templates
Professional banking tone enforced throughout
"""

from typing import Optional, Dict, List
from pathlib import Path
import os
from app import config
from app.utils.pii_masker import mask_pii
from app.services.run_model import call_local_llm
from app.services.message_generator import MessageGenerator, PROFESSIONAL_BANKING_CONTEXT
from app.services.chatupload_helpers import (
    get_remaining_required_documents,
    user_docs_path,
    get_allowed_document_types,
    insert_conversation_log
)
from app.services.supabase_client import get_supabase_client
from app.repositories.tampering_repository import TamperingRepository
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# 1. CONVERSATIONAL PROMPT BUILDING
# ============================================================================

def build_conversational_prompt(
    user_message: str, 
    user_data: dict, 
    status: dict, 
    chat_history: list,
    language: str = "english"
) -> str:
    """
    Build AI prompt for conversational chat with professional banking context
    
    Args:
        user_message: User's message
        user_data: User information
        status: Onboarding status
        chat_history: Recent chat history
        language: Target language for response
        
    Returns:
        str: Complete prompt with professional context
    """
    name = user_data.get("name", "valued customer")
    account_type = user_data.get("account_type")
    ownership = user_data.get("ownership_type")
    stage = status.get("stage")
    is_complete = status.get("is_complete")
    
    # Get language instruction
    language_instruction = MessageGenerator._build_language_instruction(language)
    
    # Build context
    context = f"""You are a professional banking assistant at {config.BRAND_NAME}, a regulated financial institution.

USER INFORMATION:
- Name: {name}
- Account Type: {account_type}
- Ownership: {ownership}
- Current Stage: {stage}
- Status: {'All documents verified' if is_complete else 'Document verification in progress'}

"""

    if chat_history:
        context += "RECENT CONVERSATION:\n"
        for msg in chat_history[-5:]:
            if isinstance(msg, dict):
                role = "Customer" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")
            else:
                role = "Customer" if msg.role == "user" else "Assistant"
                content = msg.content
            context += f"{role}: {content}\n"

    context += f"\nCUSTOMER'S CURRENT MESSAGE: {user_message}\n"
    
    context += f"""
INSTRUCTIONS:
- Respond professionally as a bank representative
- Be clear, concise, and helpful
- Answer questions about the onboarding process factually
- If asked about requirements, explain what's needed for their specific account type
- Keep responses brief (2-4 sentences) unless detailed explanation is requested
- Maintain professional banking tone at all times

FORMATTING RULES:
- NO greetings ("Dear...", "Hi...", "Hello...")
- NO sign-offs ("Kind regards", "Best regards", "Sincerely")
- NO bank signature ("{config.BRAND_NAME}", "The Team")
- Start directly with the message content
- End when the message is complete

"""
    
    # Combine professional context with specific query
    full_prompt = f"{PROFESSIONAL_BANKING_CONTEXT}\n\n{language_instruction}\n\n{context}\n\nYour response:"
    
    return full_prompt


# ============================================================================
# 2. VALID DOCUMENT RESPONSE (LLM ONLY - NO FALLBACK)
# ============================================================================

def generate_dynamic_valid_document_response(
    doc_type: str,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None,
    language: str = "english",
    pending_coi_names: Optional[list] = None
) -> str:
    """
    Generate dynamic AI response for VALID document uploads
    Uses MessageGenerator with retry logic - NO fallback

    Args:
        doc_type: Type of document uploaded (eid, commercial, etc.)
        email: User email
        user_data: User data dictionary
        member_name: Optional member name if member document
        language: Target language (english/spanish)
        pending_coi_names: Optional list of corporate entity names that require CoI
                           (used in Type-2 commercial flow from documentpage)

    Returns:
        str: LLM-generated contextual response
    """

    account_type = user_data.get("account_type", "N/A")
    ownership_type = user_data.get("ownership_type", "N/A")
    user_name = user_data.get("name", "valued customer")

    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user_data)

    member_context = f" for member {member_name}" if member_name else ""
    doc_type_norm = doc_type.lower().strip()

    # Get language instruction
    language_instruction = MessageGenerator._build_language_instruction(language)

    # ========================================================================
    # SPECIAL CASE 1: MOA validated — direct to member verification stage
    # ========================================================================
    is_moa = doc_type_norm in ("moa", "memorandum", "memorandum of association")
    if is_moa and len(remaining_docs) == 0:
        prompt = f"""{language_instruction}

TASK: Generate a professional acknowledgment after the Memorandum of Association (MOA)
has been validated, informing the customer that the process is moving to the next stage
of member verification.

CONTEXT:
- Customer: {user_name}
- Document Validated: Memorandum of Association (MOA)
- Status: Successfully validated and accepted
- Next Step: Move to member verification stage — Emirates ID or Passport for all partners/owners
  will now be collected

MESSAGE REQUIREMENTS:
1. Confirm the MOA has been successfully validated and accepted
2. State that the next stage is member verification — Emirates ID or Passport will be required
   for each partner/member
3. Inform the customer that once they confirm/approve the submitted documents, the
   process will move to the member verification stage to proceed further
4. DO NOT say "all required documents have been submitted" or imply the process is
   complete — there are still Emirates ID or Passport documents to collect
5. Length: 2-3 sentences
6. Tone: Professional, clear, progress-oriented

EXAMPLE OUTPUT:
"Your Memorandum of Association has been successfully validated and accepted. Next, once
you have approved these documents, we will move to the member verification stage where
Emirates ID or Passport for all partners will be required to proceed further."

NOW GENERATE THE MESSAGE (start directly, no greeting, no sign-off):"""
        return MessageGenerator._generate_with_retry(prompt, "VALID_DOCUMENT_RESPONSE_MOA")

    # ========================================================================
    # SPECIAL CASE 2: Commercial doc with corporate shareholders (Type-2)
    # ========================================================================
    is_commercial = doc_type_norm in ("commercial", "trade_license", "commercial_license")
    if is_commercial and pending_coi_names:
        corp_list = ", ".join([f'"{n}"' for n in pending_coi_names])
        first_corp = f'"{pending_coi_names[0]}"'
        remaining_count = len(remaining_docs)
        progress_note = (
            f"{remaining_count} document(s) remain to complete the process."
            if remaining_count > 0
            else "Please proceed with uploading the Certificate of Incorporation."
        )
        prompt = f"""{language_instruction}

TASK: Generate a professional acknowledgment after a Commercial License has been
validated and corporate shareholders were identified, requesting the Certificate of
Incorporation for the detected company.

CONTEXT:
- Customer: {user_name}
- Document Validated: Commercial License
- Status: Successfully validated and accepted
- Corporate Entities Detected in Partners: {corp_list}
- First CoI Required: {first_corp}
- Remaining Documents After This: {remaining_count}

MESSAGE REQUIREMENTS:
1. Confirm the Commercial document has been successfully validated and accepted
2. State that in the commercial document, a company was identified in the partners
   section: specifically name {first_corp}
3. Explain that because {first_corp} is a registered corporate entity listed as a
   partner/shareholder, the Certificate of Incorporation (CoI) for that company must
   be submitted to verify its registration and identify the beneficial owners
4. Ask the customer to upload the Certificate of Incorporation (CoI) for {first_corp}
   to proceed further
5. State how many documents remain: {progress_note}
6. Length: 3-4 sentences
7. Tone: Professional, explanatory, compliance-focused

NOW GENERATE THE MESSAGE (start directly, no greeting, no sign-off):"""
        return MessageGenerator._generate_with_retry(prompt, "VALID_DOCUMENT_RESPONSE_COMMERCIAL_COI")

    # ========================================================================
    # STANDARD PATH
    # ========================================================================

    # Build context for LLM
    context = f"""CUSTOMER: {user_name}
ACCOUNT TYPE: {account_type}
OWNERSHIP: {ownership_type}
DOCUMENT UPLOADED: {doc_type.upper()}{member_context}
DOCUMENT STATUS: Valid and accepted
REMAINING DOCUMENTS: {', '.join(remaining_docs) if remaining_docs else 'None - all documents submitted'}
"""

    # Build prompt for LLM
    prompt = f"""{language_instruction}

TASK: Generate a professional acknowledgment for successful document upload and validation.

{context}

MESSAGE REQUIREMENTS:
1. Confirm receipt and validation of the {doc_type.upper()} document{member_context}
2. State that document details are being processed
3. If remaining documents exist, mention what's needed next (first document only)
4. Length: 2-3 sentences
5. Tone: Professional, clear, efficient
6. Structure: Natural sentences, no bullet points

❌ WRONG - DO NOT WRITE LIKE THIS:
"Dear {user_name},

Your Emirates ID has been received and validated successfully. Document details are currently being processed.

Kind regards,
{config.BRAND_NAME}"

CORRECT - WRITE LIKE THIS:
"Your Emirates ID / Passport has been received and validated successfully. Document details are currently being processed. Next, please upload your Commercial License."

NOW GENERATE THE MESSAGE (start directly, no greeting, no sign-off):"""

    # Use MessageGenerator retry logic
    response = MessageGenerator._generate_with_retry(prompt, "VALID_DOCUMENT_RESPONSE")
    return response  # Already cleaned inside _generate_with_retry!


# ============================================================================
# 3. INVALID DOCUMENT RESPONSE (LLM ONLY - NO FALLBACK)
# ============================================================================

def generate_dynamic_invalid_document_response(
    uploaded_doc_type: str,
    allowed_info: dict,
    email: str,
    user_data: dict,
    member_name: Optional[str] = None,
    tampering_data: Optional[dict] = None,
    language: str = "english"
) -> str:
    """
    Generate dynamic AI response for INVALID/WRONG document uploads OR TAMPERING cases
    Uses MessageGenerator with retry logic - NO fallback
    
    Args:
        uploaded_doc_type: Type of document that was uploaded
        allowed_info: Dictionary with allowed_types, required_docs, etc.
        email: User email
        user_data: User data dictionary
        member_name: Optional member name if member document
        tampering_data: Optional dict with tampering detection results
        language: Target language (english/spanish)
    
    Returns:
        str: LLM-generated explanation
    """
    
    # ========================================================================
    # TAMPERING CASE - Use MessageGenerator for tampering explanation
    # ========================================================================
    if tampering_data:
        logger.info(f"Generating tampering reasoning with LLM...")
        
        user_name = user_data.get("name", "valued customer")
        account_type = user_data.get("account_type", "Unknown")
        decision = tampering_data.get("decision", "UNKNOWN")
        tampering_score = tampering_data.get("tampering_score", 0)
        test_report_id = tampering_data.get("test_report_id")
        
        # Get detailed tampering information
        tampering_details = _get_tampering_details_for_reasoning(test_report_id) if test_report_id else {}
        
        member_context = f" for member {member_name}" if member_name else ""
        
        # Simplify technical test names
        failed_tests = tampering_details.get("failed_tests", [])
        simplified_issues = []
        for test in failed_tests:
            if "jpeg" in test.lower() or "quantization" in test.lower():
                simplified_issues.append("image compression analysis")
            elif "ela" in test.lower() or "error level" in test.lower():
                simplified_issues.append("modification detection")
            elif "noise" in test.lower():
                simplified_issues.append("noise pattern analysis")
            elif "edge" in test.lower():
                simplified_issues.append("edge consistency check")
            elif "metadata" in test.lower():
                simplified_issues.append("file properties verification")
            else:
                simplified_issues.append("security verification")
        
        simplified_issues = list(set(simplified_issues))
        issues_text = ", ".join(simplified_issues) if simplified_issues else "multiple security checks"
        
        # Get language instruction
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        # Build LLM prompt for tampering explanation
        prompt = f"""{language_instruction}

TASK: Generate a professional security verification failure message.

CUSTOMER CONTEXT:
- Name: {user_name}
- Account Type: {account_type}
- Document: {uploaded_doc_type.upper()}{member_context}

SECURITY CHECK RESULTS:
- Decision: {decision}
- Confidence Score: {tampering_score}%
- Issues Detected: {issues_text}

SYSTEM ANALYSIS SUMMARY:
{tampering_details.get('summary', 'Document failed security verification')}

TECHNICAL FORENSIC FINDINGS:
{tampering_details.get('technical_details', 'Detailed analysis unavailable')}

MESSAGE REQUIREMENTS:
1. First 2 sentences: Explain the security issue in simple, user-friendly terms
   - Be professional and factual, not accusatory
   - State clearly the document could not be verified
   
2. Next 2-3 sentences: Include relevant technical details for transparency
   - Reference specific forensic findings listed above
   - Use professional language like "Our forensic analysis detected..." or "Security verification identified..."
   - Explain significance of findings briefly
   
3. Final sentence: Clear action - request upload of original, unmodified {uploaded_doc_type.upper()}
4. Include Reference ID: {test_report_id}

FORMATTING RULES:
- NO greetings ("Dear...", "Hi...", "Hello...")
- NO sign-offs ("Kind regards", "Best regards", "Sincerely")
- NO bank signature ("{config.BRAND_NAME}", "The Team")
- Start directly with the message content
- End when the message is complete

LENGTH: 5-6 sentences
TONE: Professional, transparent, factual (not accusatory)
STYLE: Mix simple explanation with technical transparency
FORMAT: Flowing paragraphs, no bullet points

CRITICAL: Professional banking tone. Factual and security-focused. No emojis.

Generate the security failure message:"""

        return MessageGenerator._generate_with_retry(prompt, "TAMPERING_RESPONSE")
    
    # ========================================================================
    # WRONG DOCUMENT CASE - Use MessageGenerator
    # ========================================================================
    member_context = f" for member {member_name}" if member_name else ""
    
    # Get remaining documents
    remaining_docs = get_remaining_required_documents(email, user_data)
    
    # Get language instruction
    language_instruction = MessageGenerator._build_language_instruction(language)
    
    # Build prompt
    required_docs_list = "\n".join([f"  - {doc}" for doc in allowed_info["required_docs"]])
    remaining_docs_list = "\n".join([f"  - {doc}" for doc in remaining_docs]) if remaining_docs else "None"
    
    prompt = f"""{language_instruction}

TASK: Generate a professional message for incorrect document type upload.

CONTEXT:
- Document Uploaded: {uploaded_doc_type.upper()}{member_context}
- Account Configuration: {allowed_info['stage_description']}
- Required Documents for This Account:
{required_docs_list}
- Remaining Documents to Upload:
{remaining_docs_list}

MESSAGE REQUIREMENTS:
1. State the uploaded document ({uploaded_doc_type.upper()}) is not required for this account type
2. List the required documents clearly (you may use bullet points for the list)
3. Request upload of one of the required documents
4. Length: 4-5 sentences
5. Tone: Professional, clear, directive - like a bank compliance officer

FORMATTING RULES:
- NO greetings ("Dear...", "Hi...", "Hello...")
- NO sign-offs ("Kind regards", "Best regards", "Sincerely")
- NO bank signature ("{config.BRAND_NAME}", "The Team")
- Start directly with the message content
- End when the message is complete

CRITICAL: Professional banking tone. Clear and helpful. No emojis.

Generate the wrong document type message:"""

    return MessageGenerator._generate_with_retry(prompt, "WRONG_DOCUMENT_TYPE")


# ============================================================================
# 4. WELCOME MESSAGE GENERATION (Uses MessageGenerator)
# ============================================================================

def generate_welcome_message(
    email: str, 
    user_data: dict, 
    doc_status: dict, 
    stage: str, 
    pending: list, 
    next_required: dict, 
    is_complete: bool, 
    members_info: Optional[dict],
    language: str = "english"
) -> str:
    """
    Generate AI welcome/status message using MessageGenerator
    NO fallback - uses retry logic
    """
    
    # Delegate to MessageGenerator
    return MessageGenerator.generate_welcome_message(user_data, language)


# ============================================================================
# 5. AI REASONING FOR INVALID DOCUMENTS (LLM ONLY - NO FALLBACK)
# ============================================================================

def generate_ai_reasoning_for_invalid_document(
    raw_text: str,
    doc_type: str,
    validation_result: dict,
    extracted_fields: dict = None,
    expected_fields: list = None,
    member_name: str = None,
    language: str = "english"
) -> str:
    """
    Generate AI reasoning for invalid documents with comprehensive context
    Uses MessageGenerator retry logic - NO fallback
    """
    logger.info(f"Generating AI reasoning for invalid {doc_type} document")
    
    # Get language instruction
    language_instruction = MessageGenerator._build_language_instruction(language)
    
    # Build comprehensive context
    context_parts = []
    
    # 1. Document Type and Member Context
    if member_name:
        context_parts.append(f"DOCUMENT TYPE: {doc_type.upper()} for member '{member_name}'")
    else:
        context_parts.append(f"DOCUMENT TYPE: {doc_type.upper()}")
    
    # 2. Extracted Text Sample
    # PII MASKING (prompt-remediation Phase 1, item #1): this reasoning call
    # only needs to explain what's missing/wrong with the document, not see
    # the real EID/phone/email/MRZ values embedded in it -- mask_pii() runs
    # its free-text regex pass over the sample before it enters the prompt.
    text_sample = raw_text[:1500] if len(raw_text) > 1500 else raw_text
    text_sample = mask_pii(text_sample)
    context_parts.append(f"\nEXTRACTED TEXT FROM DOCUMENT:\n{text_sample}")
    
    # 3. Validation Results
    if validation_result:
        context_parts.append("\nVALIDATION RESULTS:")
        context_parts.append(f"Valid: {validation_result.get('is_valid', False)}")
        
        missing = validation_result.get('missing_fields', [])
        if missing:
            context_parts.append(f"Missing Required Fields: {', '.join(missing)}")
        
        issues = validation_result.get('issues', [])
        if issues:
            context_parts.append(f"Issues Found: {', '.join(issues)}")
        
        present = validation_result.get('present_fields', [])
        if present:
            context_parts.append(f"Fields Present: {', '.join(present)}")
        
        val_reason = validation_result.get('validation_reason', '')
        if val_reason:
            context_parts.append(f"Validation Reason: {val_reason}")
    
    # 4. Extracted vs Expected Fields
    # PII MASKING: extracted_fields is the structured output of a prior
    # extraction call -- mask_pii() here masks by field name (email, phone,
    # dob, personal names) while preserving business identifiers, dates,
    # and structural fields, so the reasoning explanation still names which
    # FIELDS were missing/invalid without repeating their real values.
    if extracted_fields:
        extracted_fields = mask_pii(extracted_fields)
        context_parts.append("\nEXTRACTED FIELDS:")
        for key, value in extracted_fields.items():
            if isinstance(value, dict):
                context_parts.append(f"{key}:")
                for sub_key, sub_value in value.items():
                    context_parts.append(f"  - {sub_key}: {sub_value}")
            else:
                context_parts.append(f"{key}: {value}")
    
    if expected_fields:
        context_parts.append(f"\nEXPECTED FIELDS:\n{', '.join(expected_fields)}")
    
    full_context = "\n".join(context_parts)
    
    # Create LLM prompt
    prompt = f"""{language_instruction}

TASK: Generate a professional explanation for document validation failure.

{full_context}

MESSAGE REQUIREMENTS:
Based on the validation logs above, generate a clear explanation of why this document is invalid.

1. Identify specific issues (missing fields, incorrect format, unreadable sections, etc.)
2. Explain what was expected versus what was found
3. Provide actionable guidance on what needs to be corrected
4. Length: 3-5 sentences
5. Tone: Professional, helpful, clear - like a bank document verification officer
6. Structure: Natural flowing sentences, no bullet points

FORMATTING RULES:
- NO greetings ("Dear...", "Hi...", "Hello...")
- NO sign-offs ("Kind regards", "Best regards", "Sincerely")
- NO bank signature ("{config.BRAND_NAME}", "The Team")
- Start directly with the message content
- End when the message is complete

CRITICAL: Professional banking tone. Be specific and actionable. No emojis.

Generate the validation failure explanation:"""

    return MessageGenerator._generate_with_retry(prompt, "INVALID_DOCUMENT_REASONING")


# ============================================================================
# 6. UNKNOWN DOCUMENT REASONING (LLM ONLY - NO FALLBACK)
# ============================================================================

def generate_unknown_document_reasoning(
    raw_text: str,
    file_path: str,
    user_data: dict,
    allowed_info: dict,
    member_name: Optional[str] = None,
    language: str = "english"
) -> str:
    """
    Universal document reasoning for unrecognized documents
    Uses MessageGenerator retry logic - NO fallback
    
    Args:
        raw_text: Extracted text from the document
        file_path: Path to uploaded file
        user_data: User information from database
        allowed_info: Dictionary with allowed document types
        member_name: Optional member name
        language: Target language
    
    Returns:
        str: LLM-generated explanation
    """
    
    # Get context
    required_docs = allowed_info.get("required_docs", [])
    account_type = user_data.get("account_type", "account")
    ownership_type = user_data.get("ownership_type", "")
    user_name = user_data.get("name", "valued customer")
    
    member_context = f" for member {member_name}" if member_name else ""
    
    # Get file information
    file_ext = os.path.splitext(file_path)[1].lower() if file_path else "unknown"
    file_size_mb = 0
    if file_path and os.path.exists(file_path):
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    
    # Check if text was extracted
    # PII MASKING (prompt-remediation Phase 1, item #1): this call only
    # needs to recognize what TYPE of document was uploaded (structural
    # cues -- headers, labels, document titles), not the real values of any
    # ID numbers, phone numbers, emails, or MRZ lines that happen to be
    # printed on it. mask_pii()'s free-text regex pass targets exactly
    # those value-shaped substrings and leaves the surrounding prose (the
    # part that actually identifies the document type) untouched.
    has_text = bool(raw_text and raw_text.strip() and len(raw_text.strip()) > 20)
    text_sample = mask_pii(raw_text[:1200]) if has_text else "[No readable text extracted]"
    
    # Get language instruction
    language_instruction = MessageGenerator._build_language_instruction(language)
    
    # Build prompt
    prompt = f"""{language_instruction}

TASK: Analyze uploaded document and explain why it's not a required document.

CUSTOMER CONTEXT:
- Name: {user_name}
- Account Type: {account_type}{f' ({ownership_type})' if ownership_type else ''}
- Required Documents: {', '.join(required_docs)}
- Member Context: {member_context if member_name else "Main account holder"}

FILE INFORMATION:
- File Type: {file_ext}
- File Size: {file_size_mb:.2f} MB
- Text Extracted: {'Yes' if has_text else 'No'}

EXTRACTED TEXT FROM UPLOADED DOCUMENT:
```
{text_sample}
```

MESSAGE REQUIREMENTS:
Generate a professional message (3-4 sentences) that:

1. IDENTIFY what this document actually is
   - If text is clear: "This appears to be a [document type]" with specific identification
   - If no text: "The uploaded document could not be identified as no readable text was extracted"
   - Be specific based on actual content visible in extracted text

2. EXPLAIN why it's not required
   - "However, for your {account_type} account, we require: {', '.join(required_docs[:2])}"
   - Reference what was detected if possible

3. REQUEST correct document
   - Name the FIRST required document from list: {required_docs[0] if required_docs else 'required document'}
   - Brief description of what it should contain

FORMATTING RULES:
- NO greetings ("Dear...", "Hi...", "Hello...")
- NO sign-offs ("Kind regards", "Best regards", "Sincerely")
- NO bank signature ("{config.BRAND_NAME}", "The Team")
- Start directly with the message content
- End when the message is complete

TONE: Professional, clear, helpful - like a bank document verification officer
STRUCTURE: Natural flowing sentences
SPECIFICITY: Reference actual content from extracted text when possible

CRITICAL: Professional banking tone. No emojis. Be specific about what was detected.

Generate the message:"""

    return MessageGenerator._generate_with_retry(prompt, "UNKNOWN_DOCUMENT_REASONING")


# ============================================================================
# 7. EXTRACTION MESSAGE FORMATTING (Professional Tone)
# ============================================================================

def format_extraction_message(doc_type: str, extracted_data: dict, member_name: Optional[str]) -> str:
    """
    Format extracted data into structured message for verification
    Professional formatting - no emojis, no greetings, ONLY data
    """

    # EMIRATES ID DETAILS
    if doc_type.lower() == "eid":
        msg = f"Emirates ID processed successfully"
        if member_name:
            msg += f" for {member_name}"
        msg += ".\n\n"

        msg += "Personal Information\n"
        msg += f"- Name: {extracted_data.get('Name') or extracted_data.get('name', 'N/A')}\n"
        msg += f"- ID Number: {extracted_data.get('ID Number') or extracted_data.get('id_number', 'N/A')}\n"
        msg += f"- Nationality: {extracted_data.get('Nationality') or extracted_data.get('nationality', 'N/A')}\n"
        msg += f"- Sex: {extracted_data.get('Sex') or extracted_data.get('sex', 'N/A')}\n\n"

        msg += "Date Information\n"
        msg += f"- Date of Birth: {extracted_data.get('Date of Birth') or extracted_data.get('date_of_birth', 'N/A')}\n"
        msg += f"- Issuing Date: {extracted_data.get('Issuing Date') or extracted_data.get('issuing_date', 'N/A')}\n"
        msg += f"- Expiry Date: {extracted_data.get('Expiry Date') or extracted_data.get('expiry_date', 'N/A')}\n"

        return msg

    # PASSPORT DETAILS
    elif doc_type.lower() == "passport":
        msg = f"Passport processed successfully"
        if member_name:
            msg += f" for {member_name}"
        msg += ".\n\n"

        given_names = extracted_data.get('given_names') or extracted_data.get('Given Names', '')
        surname = extracted_data.get('surname') or extracted_data.get('Surname', '')
        full_name = f"{given_names} {surname}".strip() or 'N/A'

        msg += "Personal Information\n"
        msg += f"- Full Name: {full_name}\n"
        msg += f"- Passport Number: {extracted_data.get('passport_number') or extracted_data.get('Passport Number', 'N/A')}\n"
        msg += f"- Nationality: {extracted_data.get('nationality') or extracted_data.get('Nationality', 'N/A')}\n"
        msg += f"- Sex: {extracted_data.get('sex') or extracted_data.get('Sex', 'N/A')}\n\n"

        msg += "Date Information\n"
        msg += f"- Date of Birth: {extracted_data.get('date_of_birth') or extracted_data.get('Date of Birth', 'N/A')}\n"
        msg += f"- Date of Issue: {extracted_data.get('date_of_issue') or extracted_data.get('Date of Issue', 'N/A')}\n"
        msg += f"- Date of Expiry: {extracted_data.get('date_of_expiry') or extracted_data.get('Date of Expiry', 'N/A')}\n"

        return msg

    # COMMERCIAL LICENSE DETAILS
    elif doc_type.lower() == "commercial":
        msg = "Commercial License processed successfully.\n\n"
        
        # Get nested english data
        eng = extracted_data.get("english", {})
        
        # Company Information
        msg += "Company Information\n"
        msg += f"- Company Name (EN): {eng.get('company_name_english') or eng.get('Company Name', 'N/A')}\n"
        msg += f"- Trade Name (EN): {eng.get('trade_name_english') or eng.get('Trade Name', 'N/A')}\n"
        msg += f"- License Number: {eng.get('license_number') or eng.get('License Number', 'N/A')}\n"
        msg += f"- Legal Type: {eng.get('legal_type') or eng.get('Legal Type', 'N/A')}\n"
        msg += f"- Issue Date: {eng.get('issue_date') or eng.get('Issue Date', 'N/A')}\n"
        msg += f"- Expiry Date: {eng.get('expiry_date') or eng.get('Expiry Date', 'N/A')}\n"
        
        # Registration Details
        msg += f"- Commercial Register No.: {eng.get('commercial_register_number', 'N/A')}\n"
        msg += f"- DCCI Number: {eng.get('dcci_number', 'N/A')}\n"
        msg += f"- Status: {eng.get('status', 'Active')}\n\n"
        
        # Contact Information
        msg += "Contact Information\n"
        msg += f"- Phone: {eng.get('phone') or 'N/A'}\n"
        msg += f"- Mobile: {eng.get('mobile') or 'N/A'}\n"
        msg += f"- Email: {eng.get('email') or 'N/A'}\n\n"
        
        # Address Information
        msg += "Address Information\n"
        msg += f"- License Address: {eng.get('license_address') or 'N/A'}\n"
        msg += f"- Parcel ID: {eng.get('parcel_id') or 'N/A'}\n\n"
        
        # Capital Information
        msg += "Capital Information\n"
        msg += f"- Nominated Capital: {eng.get('nominated_capital') or 'N/A'} {eng.get('currency', 'AED')}\n"
        msg += f"- Paid Capital: {eng.get('paid_capital') or 'N/A'} {eng.get('currency', 'AED')}\n"
        msg += f"- Number of Shares: {eng.get('number_of_shares') or 'N/A'}\n\n"

        # Business Activities
        msg += "Business Activities\n"
        activities = []
        if eng.get('activity_1'):
            activities.append(eng.get('activity_1'))
        if eng.get('activity_2'):
            activities.append(eng.get('activity_2'))
        if eng.get('activity_3'):
            activities.append(eng.get('activity_3'))
        if eng.get('activity_4'):
            activities.append(eng.get('activity_4'))
        
        if activities:
            for i, act in enumerate(activities, 1):
                msg += f"{i}. {act}\n"
        else:
            msg += "No activities found.\n"
        msg += "\n"

        # Owner Information (from extracted_data.owner)
        owner = extracted_data.get("owner", {})
        if owner:
            msg += "Owner / Manager\n"
            msg += f"- Name: {owner.get('name_english') or owner.get('Name (EN)', 'N/A')}\n"
            msg += f"- Nationality: {owner.get('nationality_english') or owner.get('Nationality (EN)', 'N/A')}\n"
            msg += f"- Role: {owner.get('role', 'N/A')}\n"
            msg += f"- Share: {owner.get('share_percentage', 'N/A')}\n"
            
            # Optional owner details if available
            if owner.get('passport_number'):
                msg += f"- Passport: {owner.get('passport_number')}\n"
            if owner.get('date_of_birth'):
                msg += f"- Date of Birth: {owner.get('date_of_birth')}\n"
        
        # Check for separate managers array (for multi-owner companies)
        managers = extracted_data.get("managers", [])
        if managers:
            msg += "\nManagers\n"
            for i, mgr in enumerate(managers, 1):
                name = mgr.get('name_english') or mgr.get('Name (EN)', 'N/A')
                role = mgr.get('role') or mgr.get('Role', 'N/A')
                nationality = mgr.get('nationality_english') or mgr.get('Nationality (EN)', 'N/A')
                msg += f"{i}. {name} ({role}) - {nationality}\n"

        # Check for partners/shareholders array (for partnerships)
        partners = extracted_data.get("partners", [])
        if partners:
            msg += "\nPartners / Shareholders\n"
            for i, p in enumerate(partners, 1):
                name = p.get('name_english') or p.get('Name (EN)', 'N/A')
                share = p.get('share') or p.get('Share', 'N/A')
                share_pct = p.get('share_percentage') or p.get('Share Percentage', 'N/A')
                msg += f"{i}. {name} - Share: {share} ({share_pct}%)\n"
        
        return msg

    # EJARI / TENANCY DETAILS
    elif doc_type.lower() in ("ejari", "tenancy"):
        msg = f"{doc_type.upper()} processed successfully.\n\n"
        
        eng = extracted_data.get("english", {})
        
        # Contract Information
        msg += "Contract Information\n"
        msg += f"- Contract Number: {eng.get('contract_number', 'N/A')}\n"
        msg += f"- Registration Date: {eng.get('registration_date', 'N/A')}\n"
        msg += f"- Start Date: {eng.get('start_date', 'N/A')}\n"
        msg += f"- End Date: {eng.get('end_date', 'N/A')}\n"
        msg += f"- Contract Type: {eng.get('contract_type', 'N/A')}\n"
        msg += f"- Contract Value: {eng.get('contract_value', 'N/A')}\n"
        msg += f"- Payment Method: {eng.get('payment_method', 'N/A')}\n"
        msg += f"- Number of Payments: {eng.get('number_of_payments', 'N/A')}\n\n"

        # Property Information
        msg += "Property Information\n"
        msg += f"- Property Type: {eng.get('property_type', 'N/A')}\n"
        msg += f"- Property Subtype: {eng.get('property_subtype', 'N/A')}\n"
        msg += f"- Usage: {eng.get('usage', 'N/A')}\n"
        msg += f"- Size: {eng.get('size', 'N/A')}\n"
        msg += f"- Property Number: {eng.get('property_number', 'N/A')}\n"
        msg += f"- Makani Number: {eng.get('makani_number', 'N/A')}\n"
        msg += f"- Plot Number: {eng.get('plot_number', 'N/A')}\n"
        msg += f"- Building Number: {eng.get('building_number', 'N/A')}\n\n"

        # Property Location
        msg += "Property Location\n"
        msg += f"- Building Name: {eng.get('building_name', 'N/A')}\n"
        msg += f"- Area / Community: {eng.get('area') or eng.get('community', 'N/A')}\n"
        msg += f"- Emirates: {eng.get('emirates', 'N/A')}\n\n"

        # Parties - Lessor
        msg += "Lessor (Owner)\n"
        msg += f"- Name: {eng.get('owner_name') or eng.get('lessor_name', 'N/A')}\n"
        msg += f"- Company: {eng.get('lessor_company', 'N/A')}\n"
        msg += f"- License: {eng.get('lessor_license_number', 'N/A')}\n"
        msg += f"- Phone: {eng.get('lessor_phone', 'N/A')}\n"
        msg += f"- Email: {eng.get('lessor_email', 'N/A')}\n\n"

        # Parties - Tenant
        msg += "Tenant\n"
        msg += f"- Company: {eng.get('tenant_company', 'N/A')}\n"
        msg += f"- License: {eng.get('tenant_license', 'N/A')}\n"
        msg += f"- Tenant Number: {eng.get('tenant_number', 'N/A')}\n"

        return msg

    # MEMORANDUM OF ASSOCIATION
    elif doc_type.lower() in ("moa", "memorandum"):
        msg = "Memorandum of Association processed successfully.\n\n"
        
        eng = extracted_data.get("english", {})
        
        # Company Information
        msg += "Company Information\n"
        msg += f"- Company Name (EN): {eng.get('company_name') or eng.get('Company Name (EN)', 'N/A')}\n"
        msg += f"- Company Name (AR): {eng.get('company_name_ar') or eng.get('Company Name (AR)', 'N/A')}\n"
        msg += f"- Owner Name (EN): {eng.get('owner_name') or eng.get('Owner Name (EN)', 'N/A')}\n"
        msg += f"- Manager Name (EN): {eng.get('manager_name') or eng.get('Manager Name (EN)', 'N/A')}\n"
        msg += f"- Execution Date: {eng.get('execution_date') or eng.get('Execution Date', 'N/A')}\n\n"

        # Share Information
        msg += "Share Information\n"
        msg += f"- Number of Shares: {eng.get('number_of_shares') or eng.get('Number of Shares', 'N/A')}\n"
        msg += f"- Value per Share: {eng.get('value_per_share') or eng.get('Value per Share', 'N/A')}\n"
        msg += f"- Share Type: {eng.get('share_type') or eng.get('Share Type', 'N/A')}\n\n"

        # Additional Information
        msg += "Additional Information\n"
        msg += f"- Company Duration: {eng.get('company_duration') or eng.get('Company Duration', 'N/A')}\n"
        msg += f"- Capital: {eng.get('capital') or eng.get('Capital', 'N/A')}\n"
        
        return msg

    # Default for unknown document types
    else:
        return f"{doc_type.upper()} document has been processed."

# ============================================================================
# 8. TAMPERING DETECTION HELPERS
# ============================================================================

def _get_tampering_details_for_reasoning(test_report_id: str) -> dict:
    """
    Fetch and format tampering details for reasoning model
    Includes technical forensic language for transparency
    
    Returns:
        dict: {
            "summary": "User-friendly summary",
            "confidence": "High/Medium/Low",
            "failed_tests": [...],
            "technical_details": "Detailed forensic analysis",
            "forensic_findings": {...}
        }
    """
    try:
        client = get_supabase_client()
        
        # Fetch test report
        report_response = TamperingRepository.get_report(test_report_id, client=client)
        
        if not report_response.data:
            return {
                "summary": "Document failed security verification",
                "failed_tests": [],
                "technical_details": "No detailed forensic data available"
            }
        
        report = report_response.data[0]
        decision_data = report.get("decision", {})
        
        # FIX: Parse JSON string if needed
        if isinstance(decision_data, str):
            import json
            try:
                decision_data = json.loads(decision_data)
            except json.JSONDecodeError:
                logger.warning(f"Could not parse decision JSON: {decision_data}")
                decision_data = {}
        
        # Extract key information
        failed_tests = decision_data.get("failed_tests", [])
        escalated_tests = decision_data.get("escalated_tests", [])
        flags = decision_data.get("flags", [])
        overall_score = decision_data.get("overall_tampering_score", 0)
        module_scores = decision_data.get("module_scores", {})
        
        # Fetch module results for detailed analysis
        module_results_response = TamperingRepository.module_results(test_report_id, client=client)
        
        module_results = module_results_response.data if module_results_response.data else []
        
        # Build user-friendly summary
        issues = []
        if "multiple_edits" in flags:
            issues.append("multiple editing sessions detected")
        if "region_inconsistency" in flags:
            issues.append("inconsistent image regions found")
        if "metadata_anomaly" in flags:
            issues.append("unusual file properties detected")
        if "compression_anomaly" in flags:
            issues.append("unusual compression patterns detected")
        if "noise_pattern_anomaly" in flags:
            issues.append("inconsistent noise patterns detected")
        if "edge_manipulation" in flags:
            issues.append("edge manipulation detected")
        
        if not issues:
            issues.append("security verification checks did not pass")
        
        summary = f"Security analysis detected: {', '.join(issues)}"
        
        # Build technical forensic details
        technical_details = []
        
        technical_details.append(f"Overall Tampering Score: {overall_score:.1f}%")
        
        # Failed tests with specific findings
        if failed_tests:
            technical_details.append("\nFailed Security Tests:")
            for test in failed_tests:
                test_result = next((m for m in module_results if m.get("module_name") == test), None)
                
                if test_result:
                    score = test_result.get("tampering_score", 0)
                    status = test_result.get("status", "UNKNOWN")
                    evidence = test_result.get("evidence", {})
                    
                    # FIX: Parse evidence JSON if needed
                    if isinstance(evidence, str):
                        import json
                        try:
                            evidence = json.loads(evidence)
                        except json.JSONDecodeError:
                            evidence = {}
                    
                    technical_details.append(f"  - {test}: {status} (Score: {score:.1f}%)")
                    
                    # Add specific evidence details
                    if "JPEG" in test or "Quantization" in test:
                        if evidence.get("document_analysis"):
                            doc_analysis = evidence["document_analysis"]
                            technical_details.append(f"    Print/Scan Confidence: {doc_analysis.get('print_scan_confidence', 0):.1f}%")
                            technical_details.append(f"    Editing Boundaries: {doc_analysis.get('editing_boundaries_count', 0)}")
                    
                    elif "ELA" in test or "Error Level" in test:
                        if evidence.get("high_variance_regions"):
                            technical_details.append(f"    High Variance Regions: {evidence['high_variance_regions']}")
                    
                    elif "Noise" in test:
                        if evidence.get("noise_inconsistency"):
                            technical_details.append(f"    Noise Inconsistency: {evidence['noise_inconsistency']:.2f}")
                    
                    elif "Metadata" in test:
                        if evidence.get("metadata_issues"):
                            for issue in evidence["metadata_issues"]:
                                technical_details.append(f"    - {issue}")
                else:
                    technical_details.append(f"  - {test}: FAILED")
        
        # Escalated tests
        if escalated_tests:
            technical_details.append("\nTests Requiring Manual Review:")
            for test in escalated_tests:
                technical_details.append(f"  - {test}")
        
        # Module scores
        if module_scores:
            technical_details.append("\nModule Scores:")
            for module, score in module_scores.items():
                technical_details.append(f"  - {module}: {score:.1f}%")
        
        technical_details_text = "\n".join(technical_details)
        
        # Determine confidence
        if overall_score >= 70:
            confidence = "High"
        elif overall_score >= 40:
            confidence = "Medium"
        else:
            confidence = "Low"
        
        return {
            "summary": summary,
            "confidence": confidence,
            "failed_tests": failed_tests + escalated_tests,
            "technical_details": technical_details_text,
            "forensic_findings": {
                "overall_score": overall_score,
                "failed_count": len(failed_tests),
                "escalated_count": len(escalated_tests),
                "flags": flags,
                "module_scores": module_scores
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch tampering details: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "summary": "document failed security verification",
            "failed_tests": [],
            "technical_details": "Unable to retrieve detailed forensic analysis"
        }


# ============================================================================
# 9. TEXT EXTRACTION FOR REASONING
# ============================================================================

def extract_document_text_for_reasoning(file_path: str, file_type: str) -> str:
    """
    Extract raw text from document for reasoning analysis
    Supports PDF, Images (OCR), DOCX
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()
        
        # PDF EXTRACTION
        if ext == '.pdf':
            import fitz
            doc = fitz.open(file_path)
            raw_text = ""
            for i in range(min(5, doc.page_count)):
                page = doc.load_page(i)
                raw_text += page.get_text()
            doc.close()
            logger.info(f"Extracted {len(raw_text)} characters from PDF")
            return raw_text
            
        # IMAGE EXTRACTION (OCR)
        elif ext in ['.png', '.jpg', '.jpeg', '.webp']:
            from app.services.ocr_service import run_ocr
            from app.services.llm_client import VISION_PRIMARY
            model = VISION_PRIMARY
            raw_text = run_ocr(file_path, model)
            logger.info(f"OCR extracted {len(raw_text)} characters from image")
            return raw_text
            
        # DOCX EXTRACTION
        elif ext in ['.docx', '.doc']:
            from app.services.specialized_ocr.ejari_extractor import EjariExtractor
            with open(file_path, 'rb') as f:
                doc_bytes = f.read()
            extractor = EjariExtractor()
            raw_text = extractor.extract_text_from_docx(doc_bytes)
            logger.info(f"Extracted {len(raw_text)} characters from DOCX")
            return raw_text
            
        else:
            logger.warning(f"Unsupported file format: {ext}")
            return "[UNSUPPORTED FILE FORMAT]"
            
    except Exception as e:
        logger.error(f"Failed to extract text: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return "[TEXT EXTRACTION FAILED]"


# ============================================================================
# 10. UNIFIED ERROR NOTIFICATION (Uses MessageGenerator)
# ============================================================================

def send_unified_document_error_notification(
    to_email: str,
    user_name: str,
    reasoning_result: dict,
    member_name: Optional[str] = None
):
    """
    Send unified error notification using reasoning result
    Delegates to email_sender with professional message
    """
    try:
        from app.services.email_sender import send_document_verification_email
        
        error_type = reasoning_result.get("error_type", "UNKNOWN")
        doc_type = reasoning_result.get("document_type", "Unknown")
        chat_message = reasoning_result.get("chat_message", "Document processing failed")
        remaining_docs = reasoning_result.get("remaining_documents", [])
        
        logger.info(f"Sending unified error notification for: {error_type}")
        
        # Send email
        send_document_verification_email(
            to_email=to_email,
            user_name=user_name,
            document_type=doc_type.upper(),
            status="invalid",
            filename=None,
            reason=chat_message,
            extracted_data=None,
            is_complete=False,
            remaining_documents=remaining_docs,
            member_name=member_name
        )
        logger.info(f"[SUCCESS] Error email sent to {to_email}")
        
        # Log to chat
        insert_conversation_log(
            user_email=to_email,
            role="agent",
            message=chat_message,
            channel="chat"
        )
        logger.info(f"[SUCCESS] Error logged to conversation history")
        
    except Exception as e:
        logger.error(f"Failed to send unified notification: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ========================================================================
# 11. TAMPERING REJECTION MESSAGE (UNIFIED - NO FALLBACK)
# ========================================================================

@staticmethod
# NOTE (prompt-remediation Phase 2): this module used to define its own
# generate_tampering_rejection_message() here -- a near-duplicate of
# MessageGenerator.generate_tampering_rejection_message() in
# message_generator.py (same forensic-detail lookup via
# _get_tampering_details_for_reasoning, same simplified-findings mapping,
# a differently-worded but equivalent prompt). Every real caller
# (app/api/routes/onboarding/upload.py,
# app/domain/onboarding/verification/document_processing.py) already
# calls the MessageGenerator version; this module's copy had no callers
# anywhere in the codebase or tests, so it was dead code. Removed rather
# than merged, since there was nothing live to merge it with. Use
# MessageGenerator.generate_tampering_rejection_message() (and its
# sibling generate_tampering_escalation_message()) for this.

# ============================================================================
# 11. DOCUMENT PROCESSING TO CONVERSATION LOG
# ============================================================================

def log_document_processing_to_conversation(
    email: str,
    filename: str,
    doc_type: str,
    is_valid: bool,
    ai_reasoning: str = None,
    channel: str = "chat"
):
    """
    Log document processing results to conversation
    """
    try:
        from datetime import datetime, timezone
        
        # User message (upload action)
        user_message = f"Uploaded document: {filename} ({doc_type.upper()})"
        insert_conversation_log(
            user_email=email,
            role="user",
            message=user_message,
            channel=channel
        )
        
        # Agent response (validation result)
        if is_valid:
            agent_message = f"{doc_type.upper()} validated successfully."
        else:
            if ai_reasoning:
                agent_message = f"Validation failed for {doc_type.upper()}\n\n{ai_reasoning}"
            else:
                agent_message = f"Failed to validate {doc_type.upper()} document."
        
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=agent_message,
            channel=channel
        )
        
        logger.info(f"Document processing logged to conversation history")
        
    except Exception as e:
        logger.error(f"Failed to log to conversation: {e}")