"""
Building the document preview payloads — the structured dict the React modal
renders from, and the standalone HTML fallback.

Moved verbatim from `app/api/routes/documentpage.py` in Stage B3.
"""

from __future__ import annotations

import logging
import json
from typing import List, Optional
from app.domain.documents.discovery import find_user_documents_directory
from app.domain.documents.normalizer import normalize_extracted_data
from app.domain.documents.status import extract_pdf_metadata
from app import config
from app.utils.pii_masker import mask_pii

logger = logging.getLogger(__name__)


def _for_log(data):
    """Mask extracted-field data before it goes into a log line. Controlled
    by config.PII_LOG_MASKING_ENABLED (see backend/docs — PII masking plan)
    so raw logging can be restored quickly while debugging extraction."""
    if not config.PII_LOG_MASKING_ENABLED:
        return data
    try:
        return mask_pii(data)
    except Exception:
        # Never let a masking bug take down the actual request — fall back
        # to omitting the payload entirely rather than risk logging it raw.
        return "<pii-masking-error: value withheld>"

def format_document_preview(doc_type: str, extracted_data: dict, member_name: Optional[str] = None, pdf_metadata: Optional[dict] = None) -> dict:
    """
    Format extracted document data for frontend preview
    ✅ FIXED: Properly handles nested structures for all document types
    """
    
    preview = {
        "document_type": doc_type,
        "member_name": member_name,
        "is_valid": True,
        "extracted_data": extracted_data,
        "pdf_metadata": pdf_metadata
    }
    
    logger.info(f"\n[DEBUG] Formatting preview for: {doc_type}")
    logger.debug(f"Extracted data keys: {list(extracted_data.keys())}")
    
    # ============================================================================
    # ✅ EID - Flat structure
    # ============================================================================
    if doc_type.lower() == "eid":
        preview["key_fields"] = {
            "Name": extracted_data.get("Name") or extracted_data.get("name", "N/A"),
            "ID Number": extracted_data.get("ID Number") or extracted_data.get("id_number", "N/A"),
            "Nationality": extracted_data.get("Nationality") or extracted_data.get("nationality", "N/A"),
            "Expiry Date": extracted_data.get("Expiry Date") or extracted_data.get("expiry_date", "N/A"),
        }
    
    # ============================================================================
    # ✅ PASSPORT - Flat structure (same pattern as EID)
    # ============================================================================
    elif doc_type.lower() == "passport":
        given_names = extracted_data.get("given_names") or extracted_data.get("given names", "")
        surname = extracted_data.get("surname", "")
        full_name = f"{given_names} {surname}".strip() if given_names or surname else "N/A"
        preview["key_fields"] = {
            "Full Name": full_name or "N/A",
            "Passport Number": extracted_data.get("passport_number", "N/A"),
            "Nationality": extracted_data.get("nationality", "N/A"),
            "Expiry Date": extracted_data.get("date_of_expiry", "N/A"),
        }
        logger.debug(f"Passport key_fields: {preview['key_fields']}")

    # ============================================================================
    # ✅ COMMERCIAL LICENSE - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() == "commercial":
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            logger.debug(f"Using nested 'english' structure")
        else:
            eng = extracted_data
            logger.warning(f"Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Company Name": eng.get("company_name_english") or eng.get("Company Name", "N/A"),
            "License Number": eng.get("license_number") or eng.get("License Number", "N/A"),
            "Status": eng.get("status") or eng.get("Status", "N/A"),
            "Expiry Date": eng.get("expiry_date") or eng.get("Expiry Date", "N/A"),
        }
        logger.debug(f"Commercial key_fields: {preview['key_fields']}")
    
    # ============================================================================
    # ✅ EJARI - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() in ["ejari", "tenancy"]:
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            logger.debug(f"Using nested 'english' structure")
        else:
            eng = extracted_data
            logger.warning(f"Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Contract Number": eng.get("contract_number", "N/A"),
            "Owner Name": eng.get("owner_name", "N/A"),
            "Tenant Company": eng.get("tenant_company", "N/A"),
            "Start Date": eng.get("start_date", "N/A"),
            "End Date": eng.get("end_date", "N/A"),
            "Property Type": eng.get("property_type", "N/A"),
            "Area": eng.get("area", "N/A"),
        }
        logger.debug(f"Ejari key_fields: {preview['key_fields']}")
    
    # ============================================================================
    # ✅ MOA - Nested in "english" object
    # ============================================================================
    elif doc_type.lower() in ["moa", "memorandum"]:
        # Check if data is nested or flat
        if "english" in extracted_data:
            eng = extracted_data["english"]
            logger.debug(f"Using nested 'english' structure")
        else:
            eng = extracted_data
            logger.warning(f"Using flat structure (no 'english' key)")
        
        preview["key_fields"] = {
            "Company Name": eng.get("company_name") or eng.get("Company Name (EN)", "N/A"),
            "Owner Name": eng.get("owner_name", "N/A"),
            "Date of Execution": eng.get("date_of_execution", "N/A"),
            "Number of Shares": eng.get("number_of_shares", "N/A"),
        }
        logger.debug(f"MOA key_fields: {preview['key_fields']}")
    
    return preview


def get_document_preview_data(email: str, doc_type: str, member_name: Optional[str] = None) -> dict:
    """
    Get complete preview data for a document including bytes for frontend display
    ✅ FIXED: Properly extracts and normalizes extracted_fields from output.json
    """
    try:
        base_path = find_user_documents_directory(email)
        
        if not base_path:
            logger.error(f"Document directory not found for {email}")
            return {"success": False, "error": "Document directory not found"}
        
        search_path = base_path / member_name if member_name else base_path
        
        if not search_path.exists():
            logger.error(f"Search path does not exist: {search_path}")
            return {"success": False, "error": "Search path not found"}
        
        logger.info(f"\n{'='*80}")
        logger.debug(f"SEARCHING FOR DOCUMENT")
        logger.debug(f"Email: {email}")
        logger.debug(f"Doc Type: {doc_type}")
        logger.debug(f"Search Path: {search_path}")
        logger.info(f"{'='*80}\n")
        
        # ✅ Scan folders directly (same pattern as get_submitted_documents())
        for item in search_path.iterdir():
            logger.debug(f"Checking directory: {item.name}")
            
            if not item.is_dir():
                logger.debug(f"⏭Skipping - not a directory")
                continue
            
            # Skip members folder
            if item.name == "members":
                logger.debug(f"⏭Skipping - members folder")
                continue
            
            output_file = item / "output.json"
            
            if not output_file.exists():
                logger.debug(f"⏭Skipping {item.name} - no output.json")
                continue
            
            try:
                logger.debug(f"Found output.json in: {item.name}")
                logger.debug(f"Reading: {output_file}")
                
                with open(output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_doc_type = data.get("document_type", "").lower().strip()
                search_doc_type = doc_type.lower().strip()
                
                logger.debug(f"Document type in file: '{stored_doc_type}'")
                logger.debug(f"Searching for type: '{search_doc_type}'")
                
                # Check match
                match = False
                if stored_doc_type == search_doc_type:
                    match = True
                    logger.debug(f"Exact match!")
                elif stored_doc_type in ["tenancy", "ejari"] and search_doc_type in ["tenancy", "ejari"]:
                    match = True
                    logger.debug(f"Alias match (tenancy/ejari)!")
                elif stored_doc_type in ["moa", "memorandum"] and search_doc_type in ["moa", "memorandum"]:
                    match = True
                    logger.debug(f"Alias match (moa/memorandum)!")
                
                if not match:
                    logger.debug(f"⏭Skipping - type mismatch")
                    continue
                
                logger.info(f"\n{'='*80}")
                logger.debug(f"MATCH FOUND!")
                logger.debug(f"Folder: {item.name}")
                logger.debug(f"Type: {stored_doc_type}")
                logger.info(f"{'='*80}\n")
                
                # ✅ Find the actual document file in this folder
                document_file = None
                for file_item in item.iterdir():
                    if file_item.is_file() and file_item.name != "output.json":
                        if file_item.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']:
                            document_file = file_item
                            logger.debug(f"Found document file: {document_file.name}")
                            break
                
                # ============================================================================
                # ✅ CRITICAL: Extract data from output.json
                # ============================================================================
                
                logger.info(f"\n[DEBUG] EXTRACTING DATA FROM output.json")
                logger.debug(f"Available keys in output.json: {list(data.keys())}")
                
                extracted_data = None
                
                # Location 1: extracted_fields (most common for chat uploads)
                if "extracted_fields" in data:
                    extracted_data = data["extracted_fields"]
                    logger.debug(f"Found 'extracted_fields' key")
                    logger.debug(f"Data type: {type(extracted_data)}")
                    logger.debug(f"Number of fields: {len(extracted_data) if isinstance(extracted_data, dict) else 'N/A'}")
                    if isinstance(extracted_data, dict):
                        logger.debug(f"Field keys: {list(extracted_data.keys())[:5]}")  # Show first 5 keys
                
                # Location 2: extracted_data (alternative format)
                elif "extracted_data" in data:
                    extracted_data = data["extracted_data"]
                    logger.debug(f"Found 'extracted_data' key")
                    logger.debug(f"Data type: {type(extracted_data)}")
                
                # Location 3: result.extracted_fields (email upload format)
                elif "result" in data and isinstance(data["result"], dict):
                    result = data["result"]
                    if "extracted_fields" in result:
                        extracted_data = result["extracted_fields"]
                        logger.debug(f"Found 'result.extracted_fields'")
                    elif "extracted_data" in result:
                        extracted_data = result["extracted_data"]
                        logger.debug(f"Found 'result.extracted_data'")
                
                # ============================================================================
                # ✅ NORMALIZE THE DATA
                # ============================================================================
                
                if not extracted_data or not isinstance(extracted_data, dict):
                    logger.error(f"No valid extracted data found!")
                    logger.debug(f"extracted_data value: {_for_log(extracted_data)}")
                    extracted_data = {}
                else:
                    logger.info(f"\n[DEBUG] BEFORE NORMALIZATION:")
                    logger.debug(f"Type: {type(extracted_data)}")
                    logger.debug(f"Keys: {list(extracted_data.keys())[:5]}")
                    logger.debug(f"Sample data: {_for_log(dict(list(extracted_data.items())[:2]))}")
                    
                    # ✅ Call normalize function
                    extracted_data = normalize_extracted_data(extracted_data, stored_doc_type)
                    
                    logger.info(f"\n[DEBUG] AFTER NORMALIZATION:")
                    logger.debug(f"Type: {type(extracted_data)}")
                    logger.debug(f"Keys: {list(extracted_data.keys())[:5]}")
                    logger.debug(f"Sample data: {_for_log(dict(list(extracted_data.items())[:2]))}")
                    logger.debug(f"Total fields: {len(extracted_data)}")
                
                # ============================================================================
                # ✅ HANDLE FILE DATA
                # ============================================================================
                
                file_bytes = None
                mime_type = None
                file_ext = None
                pdf_metadata = None
                
                if document_file:
                    logger.info(f"\n[DEBUG] Reading file bytes from: {document_file}")
                    with open(document_file, 'rb') as f:
                        file_bytes = f.read()
                    
                    logger.debug(f"Read {len(file_bytes)} bytes")
                    
                    file_ext = document_file.suffix.lower()
                    mime_type = "application/pdf" if file_ext == ".pdf" else f"image/{file_ext.lstrip('.')}"
                    
                    if file_ext == ".pdf":
                        pdf_metadata = extract_pdf_metadata(str(document_file))
                        logger.debug(f"PDF metadata: {pdf_metadata.get('num_pages', 0)} pages")
                
                # ============================================================================
                # ✅ RETURN COMPLETE DATA
                # ============================================================================
                
                result_data = {
                    "success": True,
                    "filename": document_file.name if document_file else data.get("filename", "Document"),
                    "file_path": str(document_file) if document_file else None,
                    "file_bytes": file_bytes,
                    "mime_type": mime_type,
                    "file_ext": file_ext,
                    "pdf_metadata": pdf_metadata,
                    "extracted_data": extracted_data,
                    "document_type": data.get("document_type", ""),
                    "is_valid": data.get("is_valid", False),
                    "human_verified": data.get("human_verified", False)
                }
                
                logger.info(f"\n{'='*80}")
                logger.debug(f"RETURNING DATA:")
                logger.debug(f"Success: {result_data['success']}")
                logger.debug(f"Extracted data present: {bool(result_data['extracted_data'])}")
                logger.debug(f"Extracted data keys: {list(result_data['extracted_data'].keys())[:5] if result_data['extracted_data'] else 'None'}")
                logger.info(f"{'='*80}\n")
                
                return result_data
            
            except Exception as e:
                logger.error(f"Error processing {output_file}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                continue
        
        logger.error(f"No matching document found for type: {doc_type}")
        logger.debug(f"Searched in: {search_path}")
        return {"success": False, "error": f"No document found for type: {doc_type}"}
    
    except Exception as e:
        logger.error(f"get_document_preview_data failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}


def get_document_preview_html(preview_data: dict) -> str:
    """
    Generate clean HTML preview for document display
    ✅ FIXED: Shows proper preview cards instead of raw metadata
    """
    if not preview_data.get("success"):
        return f"<p>❌ Error: {preview_data.get('error', 'Unknown error')}</p>"
    
    filename = preview_data.get("filename", "Document")
    mime_type = preview_data.get("mime_type")
    file_ext = preview_data.get("file_ext")
    pdf_metadata = preview_data.get("pdf_metadata")
    extracted_data = preview_data.get("extracted_data", {})
    
    # ============================================================================
    # ✅ EMAIL UPLOADS (No file available)
    # ============================================================================
    if not mime_type:
        return """
        <div style='
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
            border: 2px dashed #2196f3;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            margin: 15px 0;
        '>
            <div style='font-size: 48px; margin-bottom: 10px;'>📧</div>
            <div style='
                font-size: 16px;
                font-weight: 700;
                color: #1565c0;
            '>Document Verified via Email</div>
            <div style='
                font-size: 12px;
                color: #1976d2;
                margin: 8px 0;
            '>Extracted data available below</div>
        </div>
        """
    
    # ============================================================================
    # ✅ IMAGE FILES - Display actual image
    # ============================================================================
    if mime_type.startswith("image/"):
        file_bytes = preview_data.get("file_bytes")
        if file_bytes:
            import base64
            base64_data = base64.b64encode(file_bytes).decode('utf-8')
            return f'''
            <div style="
                text-align: center; 
                padding: 10px;
                background: #f8f9fa;
                border-radius: 8px;
                border: 1px solid #dee2e6;
            ">
                <img src="data:{mime_type};base64,{base64_data}" 
                     alt="{filename}" 
                     style="
                         max-width: 100%; 
                         max-height: 600px; 
                         border: 1px solid #ddd; 
                         border-radius: 8px;
                         box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                     " />
                <p style="
                    margin-top: 10px; 
                    font-size: 12px; 
                    color: #6c757d;
                ">{filename}</p>
            </div>
            '''
    
    # ============================================================================
    # ✅ PDF FILES - Show clean metadata card
    # ============================================================================
    elif mime_type == "application/pdf":
        num_pages = pdf_metadata.get('num_pages', 'N/A') if pdf_metadata else 'N/A'
        
        html = f"""
        <div style='
            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
            border: 2px solid #ffc107;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            margin: 15px 0;
            box-shadow: 0 4px 12px rgba(255, 193, 7, 0.2);
        '>
            <div style='font-size: 64px; margin-bottom: 15px; opacity: 0.9;'>📄</div>
            <div style='
                font-size: 18px;
                font-weight: 700;
                color: #856404;
                margin-bottom: 10px;
            '>{filename}</div>
            <div style='
                font-size: 14px;
                color: #856404;
                margin: 8px 0;
            '>📊 {num_pages} page(s) • PDF Document</div>
            <div style='
                background: white;
                padding: 12px;
                border-radius: 8px;
                margin-top: 15px;
                border-left: 4px solid #ffc107;
            '>
                <p style='
                    margin: 0;
                    color: #856404;
                    font-size: 13px;
                '>💡 <strong>Tip:</strong> Use the download button below to view the full PDF document</p>
            </div>
        </div>
        """
        return html
    
    return f"<p>📄 Document: {filename} ({mime_type})</p>"
