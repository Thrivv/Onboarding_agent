"""
Presentation-shaping for extracted document data: display names for document
types, human-readable field labels, and normalisation of the raw extractor
output into the shape the UI expects.

Moved verbatim from `app/api/routes/documentpage.py` in Stage B3.

Note on `get_display_document_name`
-----------------------------------
`documentpage` both imported a function of this name from
`app.services.document_helpers` AND defined its own below the import. In Python
the later definition wins, so every caller in that file was using the local one
— the import was silently dead. The local version is what moved here, because
that is what actually ran. The `document_helpers` version still exists and is
still used by its own callers; the two are NOT identical, which is exactly why
this was resolved by moving rather than by deleting one.
"""

from __future__ import annotations

import logging

from app import config
from app.utils.pii_masker import mask_pii

logger = logging.getLogger(__name__)


def _for_log(data):
    """Mask extracted-field data before it goes into a log line (see
    backend/docs — PII masking plan). Controlled by
    config.PII_LOG_MASKING_ENABLED."""
    if not config.PII_LOG_MASKING_ENABLED:
        return data
    try:
        return mask_pii(data)
    except Exception:
        return "<pii-masking-error: value withheld>"

def get_display_document_name(doc_type: str) -> str:
    """Get user-friendly document name"""
    name_mapping = {
        "eid": "Emirates ID",
        "passport": "Passport",
        "ejari": "Ejari (Tenancy Contract)",
        "commercial": "Commercial License",
        "moa": "Memorandum of Association",
        "unknown": "Unknown Document"
    }
    return name_mapping.get(doc_type.lower(), doc_type.title())


def map_fields_to_display_names(extracted_data: dict, doc_type: str) -> dict:
    """
    Convert snake_case field names to Display Names for frontend
    """
    if not extracted_data:
        logger.warning("map_fields_to_display_names: No data provided")
        return {}

    # ── Verbose per-call tracing moved to DEBUG (see task note in this file's
    # other logging changes) — this ran on every document on every request. ──
    logger.debug(f"map_fields_to_display_names called for doc_type={doc_type}")
    logger.debug(f"Input data keys: {list(extracted_data.keys())[:10]}")
    logger.debug(f"Sample input: {_for_log(dict(list(extracted_data.items())[:3]))}")
    
    # Define mappings for each document type
    mappings = {
        "eid": {
            "id_number": "ID Number",
            "ID Number": "ID Number",
            "name": "Name",
            "Name": "Name",
            "date_of_birth": "Date of Birth",
            "Date of Birth": "Date of Birth",
            "nationality": "Nationality",
            "Nationality": "Nationality",
            "issuing_date": "Issuing Date",
            "Issuing Date": "Issuing Date",
            "expiry_date": "Expiry Date",
            "Expiry Date": "Expiry Date",
            "sex": "Sex",
            "Sex": "Sex",
            "Document Type": "Document Type",
        },
        "ejari": {
            "contract_number": "Contract Number",
            "registration_date": "Registration Date",
            "owner_name": "Owner Name",
            "owner_number": "Owner Number",
            "owner_nationality": "Owner Nationality",
            "lessor_company": "Lessor Company",
            "lessor_license_number": "Lessor License Number",
            "lessor_license_issuer": "Lessor License Issuer",
            "lessor_phone": "Lessor Phone",
            "lessor_email": "Lessor Email",
            "tenant_company": "Tenant",
            "tenant_number": "Tenant Number",
            "tenant_license": "Tenant License",
            "tenant_license_issuer": "Tenant License Issuer",
            "start_date": "Start Date",
            "end_date": "End Date",
            "building_name": "Building Name",
            "area": "Area",
            "plot_number": "Plot Number",
            "makani_number": "Makani Number",
            "property_number": "Property Number",
            "property_type": "Property Type",
            "property_subtype": "Property Subtype",
            "usage": "Usage",
            "size": "Size",
        },
        "commercial": {
            "company_name_english": "Company Name",
            "company_name": "Company Name",
            "license_number": "License Number",
            "status": "Status",
            "expiry_date": "Expiry Date",
            "issue_date": "Issue Date",
            "legal_form": "Legal Form",
            "owner_name": "Owner Name",
        },
        "moa": {
            "company_name": "Company Name",
            "owner_name": "Owner Name",
            "date_of_execution": "Date of Execution",
            "number_of_shares": "Number of Shares",
            "share_value": "Share Value",
        }
    }
    
    doc_type_lower = doc_type.lower()
    if doc_type_lower in ["tenancy"]:
        doc_type_lower = "ejari"
    elif doc_type_lower in ["memorandum"]:
        doc_type_lower = "moa"
    
    mapping = mappings.get(doc_type_lower, {})
    if not mapping:
        logger.warning(f"No display-name mapping found for {doc_type_lower}, returning as-is")
        return extracted_data

    # ✅ CRITICAL FIX: Don't filter out any fields!
    display_data = {}
    for key, value in extracted_data.items():
        display_name = mapping.get(key, key)  # Use mapping or keep original key

        # ✅ Include ALL fields, even if empty - let frontend decide how to display
        display_data[display_name] = value if value is not None else "N/A"

    logger.debug(f"Mapped {len(display_data)} fields, output keys: {list(display_data.keys())[:10]}")

    return display_data


def normalize_extracted_data(data: dict, doc_type: str) -> dict:
    """
    Flatten nested extracted data for consistent display
    
    Args:
        data: Raw extracted data from output.json
        doc_type: Document type (eid, commercial, ejari, moa)
    
    Returns:
        Flattened dictionary with consistent structure
    """
    if not data or not isinstance(data, dict):
        logger.warning("normalize_extracted_data: No data provided")
        return {}

    # ── Verbose per-call tracing moved to DEBUG — this is the copy of
    # normalize_extracted_data that actually runs for this file's requests
    # (a module-level function redefined later in the file wins the name, so
    # this shadows the earlier local copies further up and the one imported
    # from app.services.data_normalizer). Not touching the shadowed dead
    # copies — out of scope here — but flagging it as worth a cleanup pass. ──
    logger.debug(f"normalize_extracted_data called for: {doc_type}")
    logger.debug(f"Raw data keys: {list(data.keys())}")

    # ✅ EID - Already flat structure
    if doc_type.lower() == "eid":
        logger.debug(f"EID: Returning flat structure with {len(data)} fields")
        return data

    # ✅ Commercial/Ejari/MOA - Extract "english" object if nested
    if doc_type.lower() in ["commercial", "ejari", "tenancy", "moa", "memorandum"]:
        # Check if data is nested in "english" key
        if "english" in data and isinstance(data["english"], dict):
            logger.debug(f"{doc_type}: Extracting nested 'english' data with {len(data['english'])} fields")
            return data["english"]

        # Check if data is nested in "extracted_fields" key
        if "extracted_fields" in data and isinstance(data["extracted_fields"], dict):
            logger.debug(f"{doc_type}: Extracting nested 'extracted_fields' data")
            return normalize_extracted_data(data["extracted_fields"], doc_type)

        # If not nested, return as-is
        logger.debug(f"{doc_type}: Using flat structure with {len(data)} fields")
        return data

    # ✅ Unknown document type - return as-is
    logger.debug(f"Unknown doc_type '{doc_type}': Returning raw data")
    return data
