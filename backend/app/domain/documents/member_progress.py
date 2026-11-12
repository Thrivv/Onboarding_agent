"""
Per-member upload progress for partnership / multiple-owner onboarding.

Moved verbatim from `app/api/routes/documentpage.py` in Stage B3.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from app.services.chatupload_helpers import member_progress_path as get_member_progress_path

# `get_submitted_documents` is the version defined in `documentpage` (now
# `discovery`), NOT the same-named function in `chatupload`. `documentpage`
# imported chatupload's and then defined its own below it, so the local one
# shadowed the import and is what actually ran here. The two are not
# interchangeable — this one takes `include_all`, chatupload's does not.
from app.domain.documents.discovery import get_submitted_documents

logger = logging.getLogger(__name__)

def update_member_progress_after_upload(
    email: str,
    member_name: str,
    status_category: str
) -> bool:
    try:
        # ✅ Use shared helper — works in Docker + local (no hardcoded path)
        progress_file = get_member_progress_path(email)

        if not progress_file.exists():
            logger.warning(f"No member progress file found for {email}")
            return False

        with open(progress_file, 'r') as f:
            progress_data = json.load(f)

        members = progress_data.get("members", [])
        current_index = progress_data.get("current_index", 0)

        logger.info(f"\n{'='*80}")
        logger.info(f"[MEMBER_PROGRESS] Updating progress for {email}")
        logger.info(f"Member: {member_name}")
        logger.info(f"Status: {status_category}")
        logger.info(f"Current Index: {current_index}")
        logger.info(f"Total Members: {len(members)}")
        logger.info(f"{'='*80}\n")

        if status_category == "approved":
            try:
                member_index = members.index(member_name)
                logger.info(f"Member '{member_name}' is at index {member_index}")
            except ValueError:
                logger.warning(f"Member '{member_name}' not found in member list")
                return False

            if member_index == current_index:
                if current_index < len(members) - 1:
                    progress_data["current_index"] = current_index + 1
                    progress_data["last_updated"] = datetime.now(timezone.utc).isoformat()
                    logger.info(f"[SUCCESS] Advanced to next member: {members[current_index + 1]}")
                else:
                    progress_data["all_members_completed"] = True
                    progress_data["completed_at"] = datetime.now(timezone.utc).isoformat()
                    logger.info(f"[SUCCESS] All member EIDs collected!")

                # ✅ Write back via same Path object (consistent encoding)
                with open(progress_file, "w", encoding="utf-8") as f:
                    json.dump(progress_data, f, indent=2, ensure_ascii=False)

                logger.info(f"[SUCCESS] Member progress saved\n")
                return True
            else:
                logger.info(f"'{member_name}' is not current member (current: {members[current_index]})")
                return False
        else:
            logger.info(f"Document not approved (status: {status_category}) — not advancing")
            return False

    except Exception as e:
        logger.error(f"Failed to update member progress: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def get_member_progress_with_status(email: str) -> dict:
    """
    Get member progress with document status for each member
    
    Returns:
    {
        "members": ["Name1", "Name2"],
        "current_index": 1,
        "total_members": 2,
        "member_statuses": {
            "Name1": {"status": "approved", "uploaded_at": "...", "version": 1},
            "Name2": {"status": "not_uploaded", "uploaded_at": None, "version": 0}
        }
    }
    """
    try:
        # ✅ FIXED: Use absolute path helper for consistency
        from app.services.chatupload_helpers import member_progress_path as get_progress_path
        
        member_progress_file = get_progress_path(email)
        
        logger.debug(f"Looking for member progress at: {member_progress_file}")
        
        if not member_progress_file.exists():
            logger.warning(f"Member progress file not found: {member_progress_file}")
            return None
        
        with open(member_progress_file, 'r') as f:
            progress_data = json.load(f)
        
        logger.info(f"[SUCCESS] Member progress loaded: {len(progress_data.get('members', []))} members")
        
        members = progress_data.get("members", [])
        
        # Get all documents for this user
        all_documents = get_submitted_documents(email, include_all=False)
        
        # Build status map for each member
        member_statuses = {}
        
        for member_name in members:
            # Find this member's EID
            member_eid = None
            for doc in all_documents:
                if (doc.get("document_type", "").lower() == "eid" and 
                    doc.get("member_name", "").lower() == member_name.lower()):
                    member_eid = doc
                    break
            
            if member_eid:
                member_statuses[member_name] = {
                    "status": member_eid.get("status_category", "unknown"),
                    "uploaded_at": member_eid.get("uploaded_at"),
                    "version": member_eid.get("version", 1),
                    "filename": member_eid.get("filename"),
                    "document_id": member_eid.get("document_id") if "document_id" in member_eid else None
                }
            else:
                member_statuses[member_name] = {
                    "status": "not_uploaded",
                    "uploaded_at": None,
                    "version": 0
                }
        
        # Add status info to progress data
        progress_data["member_statuses"] = member_statuses
        
        return progress_data
        
    except Exception as e:
        logger.error(f"get_member_progress_with_status: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None     
