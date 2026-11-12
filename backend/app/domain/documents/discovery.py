"""
Finding documents on disk: locating a user's folder, resolving a document type
to a file path, enumerating what has been submitted, and deleting a document
folder.

Moved verbatim from `app/api/routes/documentpage.py` in Stage B3.

Note on `get_submitted_documents`
---------------------------------
As with `get_display_document_name`, `documentpage` imported this name from
`app.api.routes.chatupload` and then defined its own below the import — so the
local 184-line version shadowed the import and is the one that ran. That local
version moved here. `chatupload` keeps its own; the two have different
signatures (this one takes `include_all`), which is why they were never merged.
"""

from __future__ import annotations

import logging
import json
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
from app.domain.documents.normalizer import get_display_document_name, normalize_extracted_data
from app.domain.documents.status import determine_status_category, extract_pdf_metadata, get_tampering_data_for_document
from app.services.chatupload_helpers import user_docs_path
from app.services.document_helpers import get_documents_base_path

logger = logging.getLogger(__name__)

def find_user_documents_directory(email: str) -> Optional[Path]:
    """
    Find the user's documents root directory.
    Resolves ref_no from DB, then searches the standard paths.
    """
    from app.services.document_helpers import get_document_ref_no, get_documents_base_path
    ref_no = get_document_ref_no(email)

    possible_paths = [
        get_documents_base_path() / ref_no,  # ✅ config-driven (YAML / env var) — checked first
        Path(f"/app/backend/documents/id/{ref_no}"),
        Path(f"backend/documents/id/{ref_no}"),
        Path(f"documents/id/{ref_no}"),
        Path(f"./backend/documents/id/{ref_no}"),
        Path(f"../backend/documents/id/{ref_no}"),
    ]

    cwd = Path.cwd()

    for possible_path in possible_paths:
        abs_path = possible_path if possible_path.is_absolute() else (cwd / possible_path).resolve()
        if abs_path.exists():
            logger.info(f"[SUCCESS] Found directory: {abs_path}")
            return abs_path

    logger.error(f"Document directory NOT FOUND for {email} (ref_no={ref_no})")
    return None


def get_document_file_path(email: str, doc_type: str, member_name: Optional[str] = None):
    """Helper to get document file path with PDF metadata extraction"""
    try:
        base_path = find_user_documents_directory(email)
        if not base_path:
            logger.error(f"Could not locate documents directory for {email}")
            return None
        
        search_path = base_path / member_name if member_name else base_path
        
        if not search_path.exists():
            logger.warning(f"Search path does not exist: {search_path}")
            return None
        
        for item in search_path.rglob("*"):
            if not item.is_file():
                continue
            
            if item.name == "output.json":
                continue
            
            if not item.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.pdf']:
                continue
            
            output_json = item.parent / "output.json"
            if not output_json.exists():
                continue
            
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stored_doc_type = data.get("document_type", "").lower().strip()
                search_doc_type = doc_type.lower().strip()
                
                match = False
                if stored_doc_type == search_doc_type:
                    match = True
                elif stored_doc_type in ["tenancy", "ejari"] and search_doc_type in ["tenancy", "ejari"]:
                    match = True
                elif stored_doc_type in ["moa", "memorandum"] and search_doc_type in ["moa", "memorandum"]:
                    match = True
                
                if match:
                    if item.suffix.lower() == '.pdf':
                        pdf_metadata = extract_pdf_metadata(str(item))
                        data["pdf_metadata"] = pdf_metadata
                        
                        with open(output_json, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"[SUCCESS] Found document file: {item}")
                    return str(item)
                    
            except Exception as e:
                logger.warning(f"Error reading {output_json}: {e}")
                continue
        
        logger.warning(f"No matching document found for '{doc_type}'")
        return None
        
    except Exception as e:
        logger.error(f"get_document_file_path: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def delete_document_completely(email: str, document_id: str, member_name: Optional[str] = None):
    """
    Robust deletion that removes entire document folder
    Returns: (success: bool, error_message: str)
    """
    try:
        base_path = user_docs_path(email)
        
        if member_name:
            doc_folder = base_path / member_name / document_id
        else:
            doc_folder = base_path / document_id
        
        if doc_folder.exists():
            logger.info(f"[DELETE] Removing folder: {doc_folder}")
            shutil.rmtree(doc_folder)
            logger.info(f"[DELETE] Successfully deleted: {doc_folder}")
            return True, None
        else:
            logger.warning(f"[DELETE] Folder not found (may be already deleted): {doc_folder}")
            return True, None  # Consider it success if already gone
            
    except Exception as e:
        error_msg = f"Failed to delete document folder: {str(e)}"
        logger.error(f"[DELETE] Error: {error_msg}")
        import traceback
        logger.error(traceback.format_exc())
        return False, error_msg


def get_submitted_documents(email: str, include_all: bool = False) -> List[dict]:
    """
    Get all submitted documents with complete status information
    ✅ UPDATED: Works with unified path structure (no /members/ subfolder)
    ✅ Member EIDs stored at: {email}/{member_name}/{document_id}/
    ✅ Regular docs stored at: {email}/{document_id}/
    
    Args:
        email: User email
        include_all: If False, only return current documents. If True, return all.
    
    Returns:
        List of document objects with merged tampering data
    """
    try:
        base_path = find_user_documents_directory(email)

        if not base_path or not base_path.exists():
            logger.debug(f"[get_submitted_documents] no documents directory for {email}")
            return []

        documents = []
        logger.debug(f"[get_submitted_documents] scanning {email} include_all={include_all}")

        # ── Helper: parse one document folder → dict ─────────────────────────
        def _parse_doc_folder(doc_folder: Path, member_name_val: Optional[str] = None):
            """Read output.json from a document folder and build a document object."""
            output_file = doc_folder / "output.json"
            if not output_file.exists():
                return None
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                filename = data.get("filename", doc_folder.name)
                doc_type = data.get("document_type", "unknown")
                is_valid = data.get("is_valid", False)
                is_current = data.get("is_current", True)
                version = data.get("version", 1)

                if not include_all and not is_current:
                    return None

                raw_extracted_data = (data.get("extracted_fields") or
                                      data.get("extracted_data") or {})
                extracted_data = normalize_extracted_data(raw_extracted_data, doc_type)

                actual_file_path = None
                file_size = None
                file_type = None
                for f in doc_folder.iterdir():
                    if f.name != "output.json" and f.is_file():
                        actual_file_path = str(f.absolute())
                        try:
                            file_size = f.stat().st_size
                            ext = f.suffix.lower()
                            file_type = {
                                '.pdf': 'application/pdf',
                                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                                '.png': 'image/png', '.webp': 'image/webp',
                            }.get(ext, 'application/octet-stream')
                        except Exception:
                            pass
                        break

                tampering_data = None
                if actual_file_path:
                    tampering_data = get_tampering_data_for_document(actual_file_path)

                status_category = determine_status_category(is_valid, tampering_data)

                uploaded_at = None
                for field in ["uploaded_at", "created_at", "upload_date", "timestamp"]:
                    if data.get(field):
                        uploaded_at = data[field]
                        break
                if not uploaded_at and actual_file_path:
                    try:
                        stat_info = Path(actual_file_path).stat()
                        uploaded_at = datetime.fromtimestamp(
                            stat_info.st_mtime, tz=timezone.utc
                        ).isoformat()
                    except Exception:
                        pass

                _display_name = (
                    f"{get_display_document_name(doc_type)} (Member)"
                    if member_name_val else get_display_document_name(doc_type)
                )

                doc_obj = {
                    "filename": filename,
                    "document_type": doc_type,
                    "display_name": _display_name,
                    "is_valid": is_valid,
                    "extracted_data": extracted_data,
                    "status_category": status_category,
                    "uploaded_at": uploaded_at,
                    "file_path": actual_file_path,
                    "file_size": file_size,
                    "file_type": file_type,
                    "version": version,
                    "is_current": is_current,
                }
                if member_name_val:
                    doc_obj["member_name"] = (
                        data.get("member_name") or member_name_val
                    )
                if tampering_data:
                    doc_obj["tampering"] = {
                        "decision": tampering_data.get("decision"),
                        "status": tampering_data.get("status"),
                        "score": tampering_data.get("score"),
                        "test_report_id": tampering_data.get("test_report_id"),
                        "case_id": tampering_data.get("case_id"),
                        "llm_analysis": tampering_data.get("llm_analysis"),
                        "module_results": tampering_data.get("module_results", []),
                        "checked_at": tampering_data.get("checked_at"),
                    }
                else:
                    doc_obj["tampering"] = None
                if not is_valid or doc_type == "unknown":
                    reasoning = data.get("ai_reasoning") or data.get("status_message")
                    if reasoning:
                        doc_obj["ai_reasoning"] = reasoning
                if data.get("expiry_validation"):
                    doc_obj["expiry_validation"] = data["expiry_validation"]
                if data.get("pdf_metadata"):
                    doc_obj["pdf_metadata"] = data["pdf_metadata"]
                if data.get("supersedes"):
                    doc_obj["supersedes"] = data["supersedes"]
                if data.get("superseded_by"):
                    doc_obj["superseded_by"] = data["superseded_by"]

                return doc_obj
            except Exception as e:
                logger.warning(f"[get_submitted_documents] failed to parse {output_file}: {e}")
                return None

        # ── Scan root-level document folders ─────────────────────────────────
        for item in base_path.iterdir():
            if not item.is_dir():
                continue

            # ── CASE: members/ subfolder — scan all member doc folders inside ──
            if item.name == "members":
                for member_doc_folder in item.iterdir():
                    if not member_doc_folder.is_dir():
                        continue
                    doc_obj = _parse_doc_folder(member_doc_folder, member_name_val=member_doc_folder.name)
                    if doc_obj:
                        documents.append(doc_obj)
                continue

            # Skip non-document files/dirs
            if item.name in ("member_progress.json",):
                continue

            # ── CASE 1: Regular main-user document folder ─────────────────────
            # Use the shared helper — all building / tampering / status logic lives there.
            _doc_obj = _parse_doc_folder(item, member_name_val=None)
            if _doc_obj:
                documents.append(_doc_obj)

            # (Old CASE 1 and CASE 2 bodies replaced by _parse_doc_folder above)

        # Count by status
        approved = sum(1 for d in documents if d["status_category"] == "approved")
        tampered = sum(1 for d in documents if d["status_category"] == "tampered")
        rejected = sum(1 for d in documents if d["status_category"] == "rejected")
        current = sum(1 for d in documents if d.get("is_current", True))
        member_docs = sum(1 for d in documents if d.get("member_name"))

        logger.debug(
            f"[get_submitted_documents] {email} found={len(documents)} approved={approved} "
            f"tampered={tampered} rejected={rejected} current={current} "
            f"superseded={len(documents) - current} member_docs={member_docs}"
        )

        return documents

    except Exception as e:
        logger.error(f"[get_submitted_documents] failed for {email}: {e}", exc_info=True)
        return []


def _find_commercial_output(email: str):
    """Scan all subfolders for the commercial license output.json.
    Returns (path, data) for the MOST RECENTLY created commercial document
    (determined by the 'created_at' field inside output.json).
    This prevents stale documents from previous test runs being picked up.

    BUGFIX: this module previously returned the FIRST match found, in whatever
    order the filesystem happened to yield directories. chatupload.py's copy of
    the same helper had already been fixed to pick the most recent — so after a
    customer re-uploaded a commercial licence, the document preview served by
    this module and the onboarding flow driven by chatupload.py could disagree
    about which licence was current. The two are now identical.
    (See docs/duplication-audit.md.)"""
    base = user_docs_path(email)
    if not base.exists():
        return None, {}
    best_path, best_data, best_ts = None, {}, ""
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        out = folder / "output.json"
        if out.exists():
            try:
                with open(out, "r", encoding="utf-8") as _f:
                    data = json.load(_f)
                doc_type = data.get("document_type", "").lower()
                if doc_type in ("commercial", "trade_license", "commercial_license"):
                    ts = data.get("created_at", "")
                    if ts > best_ts:
                        best_ts, best_path, best_data = ts, out, data
            except Exception:
                pass
    if best_path is not None:
        logger.info(f"[COMMERCIAL] Most recent commercial found: {best_path} (created_at={best_ts})")
    return best_path, best_data
