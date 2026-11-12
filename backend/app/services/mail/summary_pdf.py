"""
The onboarding summary PDF.

Moved verbatim from `email_sender.py` in C4. This was 353 of that file's 2,215
lines and is not email at all — it builds a document that happens to be sent as
an attachment. It is separated so that changing the PDF layout does not mean
opening the module that owns the SMTP connection.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from fpdf import FPDF

from app import config
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
)

logger = logging.getLogger(__name__)


def sanitize_pdf_text(text: str) -> str:
    """
    Remove or replace Unicode characters that FPDF can't handle
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Replace common Unicode symbols with ASCII equivalents
    replacements = {
        '✓': '[OK]',
        '✗': '[X]',
        '✅': '[OK]',
        '❌': '[X]',
        '⚠️': '[!]',
        '📋': '',
        '🔍': '',
        '💼': '',
        '🏢': '',
    }
    
    for unicode_char, replacement in replacements.items():
        text = text.replace(unicode_char, replacement)
    
    # Remove any remaining non-ASCII characters
    try:
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        return text.encode('latin-1', errors='ignore').decode('latin-1')


def generate_user_summary_pdf(user: dict, user_docs_dir: str, output_path: str):
    """
    Generate a comprehensive PDF summary with user data and all extracted document fields
    Includes member EIDs for Corporate Multiple Owners
    FIXED: Unicode character handling
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Get user account info for conditional logic
    account_type = user.get("account_type", "")
    ownership_type = user.get("ownership_type", "")

    # ===== HEADER =====
    pdf.set_font("Arial", "B", 24)
    pdf.set_text_color(65, 105, 225)
    pdf.cell(0, 15, "Onboarding Summary", ln=True, align="C")
    pdf.ln(3)
    
    pdf.set_font("Arial", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Generated on: {datetime.now().strftime('%B %d, %Y at %H:%M')}", ln=True, align="C")
    pdf.ln(8)

    # ===== USER DETAILS SECTION =====
    pdf.set_font("Arial", "B", 16)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(0, 10, " User Information", ln=True, fill=True)
    pdf.ln(3)
    
    pdf.set_font("Arial", "", 11)
    user_fields = [
        ("Name", "name"),
        ("Email", "email"),
        ("Phone", "phone_number"),
        ("Date of Birth", "dob"),
        ("Business Name", "business_name"),
        ("Account Type", "account_type"),
        ("Ownership Type", "ownership_type"),
    ]
    
    for label, key in user_fields:
        value = user.get(key, "N/A")
        if value and value != "N/A":
            pdf.set_font("Arial", "B", 11)
            pdf.cell(50, 7, f"{label}:", 0)
            pdf.set_font("Arial", "", 11)
            pdf.cell(0, 7, sanitize_pdf_text(str(value)), ln=True)
    
    pdf.ln(8)
    
    # ===== DOCUMENTS SECTION =====
    pdf.set_font("Arial", "B", 16)
    pdf.set_fill_color(255, 245, 230)
    pdf.cell(0, 10, " Submitted Documents", ln=True, fill=True)
    pdf.ln(3)

    if not os.path.exists(user_docs_dir):
        pdf.set_font("Arial", "I", 11)
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 8, f"No documents found at: {user_docs_dir}", ln=True)
    else:
        all_items = os.listdir(user_docs_dir)
        doc_count = 0
        member_dirs = []
        
        logger.debug(f"[PDF] scanning {user_docs_dir}: {len(all_items)} items")

        for item in all_items:
            item_path = os.path.join(user_docs_dir, item)

            # Skip files
            if not os.path.isdir(item_path):
                continue

            # Skip system files
            if item in ["member_progress.json", "validation_result.json"]:
                continue
            
            # Check if this is a member directory (Multiple Owners only)
            is_member_directory = False
            if account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE, "@Multiple Owners"]:
                if all(c.isalpha() or c.isspace() for c in item):
                    try:
                        for subitem in os.listdir(item_path):
                            subitem_path = os.path.join(item_path, subitem)
                            if os.path.isdir(subitem_path):
                                if os.path.exists(os.path.join(subitem_path, "output.json")):
                                    is_member_directory = True
                                    member_dirs.append(item)
                                    break
                    except:
                        pass
            
            # Skip member directories for now
            if is_member_directory:
                continue
            
            # Process DOCUMENT directories
            output_path_json = os.path.join(item_path, "output.json")
            
            if os.path.exists(output_path_json):
                try:
                    with open(output_path_json, "r", encoding="utf-8") as f:
                        analysis = json.load(f)
                    
                    doc_count += 1
                    filename = sanitize_pdf_text(analysis.get("filename", item))
                    doc_type = sanitize_pdf_text(analysis.get("document_type", "unknown")).upper()
                    is_valid = analysis.get("is_valid", False)
                    extracted = analysis.get("extracted_fields", {})

                    logger.debug(f"[PDF] document #{doc_count}: {filename} ({doc_type}) valid={is_valid}")

                    # Document Header
                    pdf.set_font("Arial", "B", 13)
                    pdf.set_text_color(40, 70, 150) if is_valid else pdf.set_text_color(200, 0, 0)
                    status_text = "[VALID]" if is_valid else "[INVALID]"
                    pdf.cell(0, 8, f"{doc_count}. {filename} ({doc_type}) {status_text}", ln=True)
                    pdf.set_text_color(0, 0, 0)
                    
                    # Extracted Fields
                    if isinstance(extracted, dict) and extracted:
                        pdf.set_font("Arial", "B", 10)
                        pdf.cell(0, 6, "Extracted Information:", ln=True)
                        pdf.set_font("Arial", "", 10)
                        
                        field_count = 0
                        for key, value in extracted.items():
                            # Skip arabic fields at root level
                            if "arabic" in key.lower():
                                continue
                            
                            # No limit on field_count anymore for main fields
                            
                            clean_key = sanitize_pdf_text(str(key))
                            
                            # Handle nested dictionaries (like "english": {...})
                            if isinstance(value, dict):
                                # Special handling for english/arabic sections
                                if clean_key.lower() in ['english', 'arabic']:
                                    # Skip arabic completely
                                    if clean_key.lower() == 'arabic':
                                        continue
                                    
                                    # For english section, show ALL fields
                                    pdf.set_font("Arial", "B", 10)
                                    pdf.cell(0, 6, f"{clean_key.title()}:", ln=True)
                                    pdf.set_font("Arial", "", 9)
                                    
                                    # Show ALL sub-fields (no limit)
                                    for sub_key, sub_value in value.items():
                                        # Skip Arabic text values
                                        if isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                            continue
                                        
                                        # Skip empty values
                                        if not sub_value or str(sub_value).strip() == "":
                                            continue
                                        
                                        clean_sub_key = sanitize_pdf_text(str(sub_key).replace('_', ' ').title())
                                        clean_sub_value = sanitize_pdf_text(str(sub_value))
                                        
                                        pdf.cell(5, 6, "", 0)  # Small indent
                                        pdf.set_font("Arial", "B", 9)
                                        pdf.cell(60, 6, f"{clean_sub_key}:", 0)
                                        pdf.set_font("Arial", "", 9)
                                        
                                        # Handle long values
                                        if len(clean_sub_value) > 60:
                                            pdf.cell(0, 6, clean_sub_value[:60] + "...", ln=True)
                                        else:
                                            pdf.cell(0, 6, clean_sub_value, ln=True)
                                else:
                                    # For other nested dicts, limit to 5
                                    pdf.set_font("Arial", "B", 10)
                                    pdf.cell(0, 6, f"{clean_key}:", ln=True)
                                    pdf.set_font("Arial", "", 10)
                                    
                                    for sub_key, sub_value in list(value.items())[:5]:
                                        if isinstance(sub_value, str) and any("\u0600" <= char <= "\u06FF" for char in sub_value):
                                            continue
                                        
                                        clean_sub_key = sanitize_pdf_text(str(sub_key))
                                        clean_sub_value = sanitize_pdf_text(str(sub_value))
                                        
                                        pdf.cell(10, 6, "", 0)
                                        pdf.cell(0, 6, f"{clean_sub_key}: {clean_sub_value}", ln=True)
                            
                            # Handle lists
                            elif isinstance(value, list):
                                pdf.set_font("Arial", "B", 10)
                                pdf.cell(0, 6, f"{clean_key}:", ln=True)
                                pdf.set_font("Arial", "", 10)
                                
                                for idx, list_item in enumerate(value[:5], 1):  # Max 5 items
                                    if isinstance(list_item, dict):
                                        pdf.cell(10, 6, "", 0)
                                        pdf.cell(0, 6, f"Item {idx}:", ln=True)
                                        for k, v in list(list_item.items())[:8]:  # Show 8 fields per item
                                            if isinstance(v, str) and any("\u0600" <= char <= "\u06FF" for char in v):
                                                continue
                                            clean_k = sanitize_pdf_text(str(k))
                                            clean_v = sanitize_pdf_text(str(v))
                                            pdf.cell(20, 6, "", 0)
                                            pdf.cell(0, 6, f"{clean_k}: {clean_v}", ln=True)
                                    else:
                                        clean_item = sanitize_pdf_text(str(list_item))
                                        pdf.cell(10, 6, "", 0)
                                        pdf.cell(0, 6, f"- {clean_item}", ln=True)
                            
                            # Handle simple values
                            else:
                                # Skip Arabic text
                                if isinstance(value, str) and any("\u0600" <= char <= "\u06FF" for char in value):
                                    clean_value = "[Arabic text omitted]"
                                else:
                                    clean_value = sanitize_pdf_text(str(value))
                                
                                pdf.set_font("Arial", "B", 10)
                                pdf.cell(50, 6, f"{clean_key}:", 0)
                                pdf.set_font("Arial", "", 10)
                                pdf.cell(0, 6, clean_value, ln=True)
                            
                            field_count += 1

                        logger.debug(f"[PDF] {filename}: added {field_count} fields")
                    else:
                        pdf.set_font("Arial", "I", 10)
                        pdf.cell(0, 6, "  No extracted data available", ln=True)
                    
                    pdf.ln(5)
                    
                except Exception as e:
                    logger.error(f"[PDF] error processing document folder {item}: {e}", exc_info=True)

                    # Still add document with error message
                    doc_count += 1
                    pdf.set_font("Arial", "B", 13)
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 8, f"{doc_count}. {item} [PROCESSING ERROR]", ln=True)
                    pdf.set_font("Arial", "I", 10)
                    pdf.cell(0, 6, f"  Error: {sanitize_pdf_text(str(e))}", ln=True)
                    pdf.ln(5)
                    pdf.set_text_color(0, 0, 0)
        
        # ===== MEMBER EIDs (Multiple Owners only) =====
        if member_dirs:
            pdf.ln(8)
            pdf.set_font("Arial", "B", 16)
            pdf.set_fill_color(230, 255, 230)
            pdf.cell(0, 10, " Member Emirates IDs", ln=True, fill=True)
            pdf.ln(3)
            
            member_count = 0
            for member_name in member_dirs:
                member_dir = os.path.join(user_docs_dir, member_name)
                
                # Find EID in member directory
                for item in os.listdir(member_dir):
                    item_path = os.path.join(member_dir, item)
                    if not os.path.isdir(item_path):
                        continue
                    
                    output_path_json = os.path.join(item_path, "output.json")
                    if os.path.exists(output_path_json):
                        try:
                            with open(output_path_json, "r", encoding="utf-8") as f:
                                analysis = json.load(f)
                            
                            doc_type = analysis.get("document_type", "unknown")
                            is_valid = analysis.get("is_valid", False)
                            
                            if doc_type == "eid" and is_valid:
                                member_count += 1
                                extracted = analysis.get("extracted_fields", {})
                                
                                # Member Header
                                pdf.set_font("Arial", "B", 13)
                                pdf.set_text_color(76, 175, 80)
                                pdf.cell(0, 8, f"{member_count}. Member: {sanitize_pdf_text(member_name)}", ln=True)
                                pdf.set_font("Arial", "", 10)
                                pdf.set_text_color(0, 0, 0)
                                
                                # Extracted EID Fields
                                if isinstance(extracted, dict) and extracted:
                                    for key, value in list(extracted.items())[:8]:
                                        if value and not isinstance(value, (dict, list)):
                                            clean_key = sanitize_pdf_text(str(key))
                                            clean_value = sanitize_pdf_text(str(value))
                                            
                                            pdf.set_font("Arial", "B", 10)
                                            pdf.cell(50, 6, f"{clean_key}:", 0)
                                            pdf.set_font("Arial", "", 10)
                                            pdf.cell(0, 6, clean_value, ln=True)
                                
                                pdf.ln(5)
                                break
                        except Exception as e:
                            logger.error(f"Failed to process member EID: {e}")
            
            if member_count == 0:
                pdf.set_font("Arial", "I", 11)
                pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 8, "No member EIDs processed.", ln=True)
        
        # Summary if no documents
        if doc_count == 0:
            pdf.set_font("Arial", "I", 11)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 8, "No valid documents processed.", ln=True)

    # ===== FOOTER =====
    pdf.ln(10)
    pdf.set_font("Arial", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "This is an automated summary generated by DigiOB Onboarding System.", ln=True, align="C")
    pdf.cell(0, 6, "For any questions, please contact support@digiob.com", ln=True, align="C")

    # Save PDF
    pdf.output(output_path)
    logger.debug(f"[PDF] written to {output_path}")
