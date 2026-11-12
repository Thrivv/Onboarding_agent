"""
Document status derivation: PDF metadata, tampering verdicts, and the mapping
from a raw verdict to the category the UI renders.

Moved verbatim from `app/api/routes/documentpage.py` in Stage B3. No logic
changed — these three functions were already self-contained, they simply had no
module of their own.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional
from app.repositories.tampering_repository import TamperingRepository

logger = logging.getLogger(__name__)

def extract_pdf_metadata(file_path: str) -> dict:
    """Extract text and metadata from PDF file"""
    try:
        import PyPDF2
        
        pdf_metadata = {
            "num_pages": 0,
            "text_preview": "",
            "title": ""
        }
        
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            pdf_metadata["num_pages"] = len(pdf_reader.pages)
            
            try:
                first_page = pdf_reader.pages[0]
                text = first_page.extract_text()
                pdf_metadata["text_preview"] = text[:500] if text else ""
            except:
                pdf_metadata["text_preview"] = "Preview not available"
            
            if pdf_reader.metadata:
                pdf_metadata["title"] = pdf_reader.metadata.get("/Title", "").strip() or Path(file_path).stem
        
        logger.info(f"PDF metadata extracted: {pdf_metadata['num_pages']} pages")
        return pdf_metadata
        
    except ImportError:
        logger.warning(f"PyPDF2 not installed, returning basic metadata")
        return {
            "num_pages": 1,
            "text_preview": "PDF document - view full content by downloading",
            "title": Path(file_path).stem
        }
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
        return {
            "num_pages": 0,
            "text_preview": "Could not extract preview",
            "title": Path(file_path).stem
        }


def get_tampering_data_for_document(file_path: str) -> Optional[dict]:
    """
    Fetch tampering detection results for a specific document
    
    Args:
        file_path: Path to the document file
    
    Returns:
        Dictionary with tampering data or None if not found
    """
    try:
        # ✅ FIXED: Use correct table name
        test_report_response = TamperingRepository.latest_report_for_file(file_path)
        
        if not test_report_response.data:
            # ── Downgraded to DEBUG ────────────────────────────────────────────
            # This fires once per document on every status/history load — for an
            # account whose docs predate tampering checks it repeats on every
            # single request, which was a big share of the "repeating logs"
            # noise. It's still worth investigating separately whether tampering
            # records are actually being persisted for these documents (see the
            # determine_status_category() warning below), but printing it at
            # INFO on every page load isn't the right way to track that.
            logger.debug(f"No tampering data found for: {file_path}")
            return None
        
        test_report = test_report_response.data[0]
        test_report_id = test_report["id"]
        
        # ✅ FIXED: Use correct table name
        llm_response = TamperingRepository.latest_llm_analysis(test_report_id)
        
        llm_analysis = llm_response.data[0] if llm_response.data else None
        
        # ✅ CRITICAL FIX: Use 'score' not 'tampering_score'
        module_response = TamperingRepository.module_summaries(test_report_id)
        
        module_results = module_response.data if module_response.data else []
        
        return {
            "decision": test_report.get("decision"),
            "status": test_report.get("status"),
            "score": test_report.get("overall_score", 0),
            "test_report_id": test_report_id,
            "case_id": test_report.get("case_id"),
            "llm_analysis": llm_analysis.get("analysis_text") if llm_analysis else None,
            "tampered_sections": llm_analysis.get("tampered_sections") if llm_analysis else [],
            "module_results": module_results,
            "checked_at": test_report.get("created_at")
        }
        
    except Exception as e:
        logger.error(f"Failed to fetch tampering data: {e}")
        return None


def determine_status_category(is_valid: bool, tampering_data: Optional[dict]) -> str:
    """
    Determine the overall status category for a document
    
    Args:
        is_valid: Whether document passed OCR validation
        tampering_data: Tampering detection results
    
    Returns:
        One of: "approved", "tampered", "rejected"
    """
    # If document is invalid (OCR/extraction failed)
    if not is_valid:
        return "rejected"
    
    # ✅ IMPROVED: If no tampering check was performed
    if not tampering_data:
        # Downgraded to DEBUG — see note in get_tampering_data_for_document()
        # above. This condition repeats per-document on every request for any
        # account whose docs don't have a tampering_test_reports row, which was
        # flooding the docker logs. Still worth a one-off data audit (are these
        # rows actually missing, or is file_path mismatching?) rather than
        # relying on this line firing at INFO/WARNING on every page load.
        logger.debug("No tampering data found for document — check if tampering ran / file_path matches")
        # ✅ Safer default: only mark as approved if explicitly is_valid
        return "approved" if is_valid else "rejected"
    
    # Map tampering decision to status category
    decision = tampering_data.get("decision", "").upper()
    
    if decision == "ACCEPT":
        return "approved"
    elif decision == "ESCALATE":
        return "tampered"  # Under review
    elif decision == "REJECT":
        return "rejected"
    else:
        # ✅ Unknown decision - be conservative and log
        logger.warning(f"Unknown tampering decision: {decision}")
        return "approved" if is_valid else "rejected"
