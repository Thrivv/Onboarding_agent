"""
Data normalization utilities for document processing
Shared between chatupload and documentpage
"""
import logging

logger = logging.getLogger(__name__)


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

    # ── Verbose per-call tracing moved to DEBUG ───────────────────────────────
    # This function runs once per document on every status/history load, so at
    # INFO level it was printing 2-3 lines per document per request — a large
    # share of the "repeating logs" noise. Set LOG_LEVEL=DEBUG in .env.docker
    # to see this trace again when actively troubleshooting field mapping.
    logger.debug(f"normalize_extracted_data called for: {doc_type}")
    logger.debug(f"Raw data keys: {list(data.keys())}")

    # ✅ EID - Already flat structure
    if doc_type.lower() == "eid":
        logger.debug(f"EID: Returning flat structure with {len(data)} fields")
        return data

    # ✅ Passport - Extract "extracted_fields" flat dict
    if doc_type.lower() == "passport":
        if "extracted_fields" in data and isinstance(data["extracted_fields"], dict):
            logger.debug(f"Passport: Extracting 'extracted_fields' with {len(data['extracted_fields'])} fields")
            return data["extracted_fields"]
        # Already flat (no extracted_fields wrapper)
        logger.debug(f"Passport: Using flat structure with {len(data)} fields")
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
