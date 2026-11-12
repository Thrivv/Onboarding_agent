"""
Document Expiry Validation Service
Handles expiry date validation for all document types in the onboarding system
"""

from datetime import datetime
import json
import logging
from typing import Dict, Any, Tuple, Optional
from app import config
from app.services.run_model import call_local_llm  # ✅ CORRECT IMPORT

logger = logging.getLogger(__name__)

# Document type configuration
DOCUMENT_CONFIG = {
    "eid": {
        "expiry_field": "Expiry Date",
        "date_format": "%d/%m/%Y",
        "display_name": "Emirates ID"
    },
    "ejari": {
        "expiry_field": "end_date",
        "date_format": "%d-%m-%Y",
        "display_name": "Ejari Contract"
    },
    "commercial_license": {
        "expiry_field": "expiry_date",
        "date_format": "%d/%m/%Y",
        "display_name": "Commercial License"
    },
    "passport": {
        "expiry_field": "date_of_expiry",
        "date_format": "%d/%m/%Y",
        "display_name": "Passport"
    }
}


def extract_expiry_date(document_data: Dict[str, Any], doc_type: str) -> Optional[str]:
    """
    Extract the expiry date field from document data based on document type.
    Handles both flat and nested data structures.
    
    Args:
        document_data: Extracted document data dictionary
        doc_type: Type of document (eid, ejari, commercial_license)
    
    Returns:
        Expiry date string or None if not found
    """
    if doc_type not in DOCUMENT_CONFIG:
        logger.error(f"Unknown document type: {doc_type}")
        return None
    
    expiry_field = DOCUMENT_CONFIG[doc_type]["expiry_field"]
    
    # ✅ NEW: Handle nested structures (Ejari, Commercial)
    if doc_type in ["ejari", "commercial_license"]:
        # Check if data has nested structure
        if "english" in document_data:
            expiry_date = document_data["english"].get(expiry_field)
            if expiry_date:
                logger.info(f"Found expiry date in nested 'english' structure: {expiry_date}")
                return expiry_date
        
        # Fallback: check top level (in case structure changes)
        if expiry_field in document_data:
            expiry_date = document_data.get(expiry_field)
            logger.info(f"Found expiry date at top level: {expiry_date}")
            return expiry_date
            
        logger.warning(f"Expiry field '{expiry_field}' not found in document data (checked both nested and top level)")
        return None
    
    # ✅ EID: Flat structure
    else:
        expiry_date = document_data.get(expiry_field)
        
        if not expiry_date:
            logger.warning(f"Expiry field '{expiry_field}' not found in document data")
            return None
        
        return expiry_date


def normalize_date(date_string: str, date_format: str) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Convert date string to datetime object.
    Tries the primary format first, then falls back to common passport/document date formats.

    Args:
        date_string: Date string to parse
        date_format: Expected format (e.g., "%d/%m/%Y")

    Returns:
        Tuple of (datetime object, error message if failed)
    """
    if not date_string:
        return None, "Date string is empty"

    date_string = date_string.strip()

    # Try the primary format first
    try:
        parsed_date = datetime.strptime(date_string, date_format)
        return parsed_date, None
    except ValueError:
        pass

    # Fallback formats — covers passports and other documents where OCR
    # may return dates in different formats (DD MMM YYYY, YYYY-MM-DD, etc.)
    FALLBACK_FORMATS = [
        "%d/%m/%Y",    # 31/12/2030
        "%d-%m-%Y",    # 31-12-2030
        "%Y-%m-%d",    # 2030-12-31 (ISO)
        "%d %b %Y",    # 31 Dec 2030
        "%d %B %Y",    # 31 December 2030
        "%d/%m/%y",    # 31/12/30 (2-digit year)
        "%d-%m-%y",    # 31-12-30
        "%d.%m.%Y",    # 31.12.2030
        "%Y/%m/%d",    # 2030/12/31
    ]

    for fmt in FALLBACK_FORMATS:
        if fmt == date_format:
            continue  # Already tried
        try:
            parsed_date = datetime.strptime(date_string, fmt)
            logger.info(f"Parsed date '{date_string}' using fallback format '{fmt}'")
            return parsed_date, None
        except ValueError:
            continue

    logger.error(f"Failed to parse date '{date_string}' with any known format")
    return None, f"Invalid date format: {date_string}"


def calculate_expiry_status(expiry_date: datetime, current_date: datetime) -> Dict[str, Any]:
    """
    Calculate whether document is valid or expired.
    
    Args:
        expiry_date: Document expiry date
        current_date: Current system date
    
    Returns:
        Dictionary with status and details
    """
    is_valid = expiry_date >= current_date
    
    if is_valid:
        days_until_expiry = (expiry_date - current_date).days
        return {
            "status": "VALID",
            "reason": f"Valid for {days_until_expiry} more days"
        }
    else:
        days_expired = (current_date - expiry_date).days
        return {
            "status": "EXPIRED",
            "reason": f"Document expired {days_expired} days ago"
        }


def validate_document_expiry(document_data: Dict[str, Any], doc_type: str) -> Dict[str, Any]:
    """
    Main validation function for document expiry.
    
    Args:
        document_data: Extracted document data
        doc_type: Document type (eid, ejari, commercial_license)
    
    Returns:
        Dictionary with validation results and metadata
    """
    current_date = datetime.now()
    
    # Extract expiry date
    expiry_date_str = extract_expiry_date(document_data, doc_type)
    
    # Handle missing expiry date
    if not expiry_date_str:
        return {
            "status": "EXPIRED",
            "validation": {
                "document_status": "EXPIRED",
                "expiry_checked_on": current_date.isoformat(),
                "expiry_date_found": None,
                "current_date": current_date.strftime("%d/%m/%Y"),
                "expiry_reason": "Expiry date not found in document"
            }
        }
    
    # Normalize date
    date_format = DOCUMENT_CONFIG[doc_type]["date_format"]
    expiry_date, parse_error = normalize_date(expiry_date_str, date_format)
    
    # Handle invalid date format
    if not expiry_date:
        return {
            "status": "EXPIRED",
            "validation": {
                "document_status": "EXPIRED",
                "expiry_checked_on": current_date.isoformat(),
                "expiry_date_found": expiry_date_str,
                "current_date": current_date.strftime("%d/%m/%Y"),
                "expiry_reason": parse_error
            }
        }
    
    # Calculate expiry status
    expiry_status = calculate_expiry_status(expiry_date, current_date)
    
    # Build validation metadata
    validation_metadata = {
        "document_status": expiry_status["status"],
        "expiry_checked_on": current_date.isoformat(),
        "expiry_date_found": expiry_date_str,
        "expiry_date_parsed": expiry_date.strftime("%d/%m/%Y"),
        "current_date": current_date.strftime("%d/%m/%Y"),
        "expiry_reason": expiry_status["reason"]
    }
    
    return {
        "status": expiry_status["status"],
        "validation": validation_metadata
    }


def generate_expiry_failure_message(
    doc_type: str,
    expiry_date_found: Optional[str],
    current_date: str,
    reason: str
) -> str:
    """
    Generate professional AI message for expired/invalid documents.
    
    Args:
        doc_type: Type of document
        expiry_date_found: The expiry date that was found (if any)
        current_date: Current system date
        reason: Reason for failure
    
    Returns:
        AI-generated professional message
    """
    display_name = DOCUMENT_CONFIG.get(doc_type, {}).get("display_name", "document")
    
    # Build context for LLM
    if not expiry_date_found:
        context = f"missing expiry date on {display_name}"
    elif "Invalid" in reason or "format" in reason:
        context = f"invalid expiry date format on {display_name}"
    else:
        context = f"{display_name} expired on {expiry_date_found}"
    
    # Create prompt for LLM.
    # ARCHITECTURE FIX (prompt-remediation Phase 2): the assistant-identity
    # line now goes through the model's system role instead of being
    # textually embedded as the first line of the user prompt -- see
    # call_local_llm(prompt, system_prompt=..., temperature=...) below.
    _system_prompt = f"You are a professional banking assistant for {config.BRAND_NAME}."
    prompt = f"""Document Type: {display_name}
Issue: {context}
Current Date: {current_date}
Reason: {reason}

Generate a professional, concise message (2-3 sentences maximum) explaining:
1. The specific issue with the document
2. Request to upload a valid, non-expired document

Requirements:
- Professional banking tone
- No greetings or closings
- No emojis
- Direct and clear
- Focus on solution (uploading valid document)

Message:"""

    try:
        # Call LLM with retry logic (your existing function). Lower
        # temperature (0.3, down from the shared 0.7 default) -- this output
        # is a short, format-locked message (2-3 sentences, no greeting/
        # closing), which benefits from lower variance the same way
        # message_generator.py's prompts do.
        ai_message = call_local_llm(prompt, system_prompt=_system_prompt, temperature=0.3)
        
        if not ai_message or len(ai_message.strip()) < 20:
            logger.error("LLM returned insufficient message")
            raise ValueError("Insufficient LLM response")
        
        return ai_message.strip()
        
    except Exception as e:
        logger.error(f"Failed to generate expiry failure message: {str(e)}")
        # Re-raise to trigger retry logic in call_local_llm
        raise


def save_validation_to_json(json_file_path: str, validation_data: Dict[str, Any]) -> bool:
    """
    Save validation metadata to the existing JSON file.
    
    Args:
        json_file_path: Path to the JSON file
        validation_data: Validation metadata to add
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Read existing JSON
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Add validation metadata
        data['validation'] = validation_data
        
        # Write back to file
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Validation metadata saved to {json_file_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save validation metadata: {str(e)}")
        return False