# app/services/supabase_client.py

import os
import json
import logging
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from supabase import Client
from app import config
from app.config import SUPABASE_URL, SUPABASE_API_KEY
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
# Load .env file from parent directory (for tampering modules)
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

# The Supabase clients themselves are constructed in app/repositories/base.py.
# They moved there in B2 so that repository modules have a client source that
# does not import this module — otherwise repositories and this file form an
# import cycle whose success depends on which route FastAPI loads first.
#
# Re-exported here unchanged: every existing
# `from app.services.supabase_client import supabase` keeps working, and both
# names refer to the same client objects as before.
from app.repositories.base import (  # noqa: E402  (must follow load_dotenv)
    SUPABASE_SERVICE_KEY,
    supabase,
    supabase_service,
)
from app.repositories.conversation_repository import ConversationRepository  # noqa: E402
from app.repositories.user_repository import UserRepository


# ========================================
# LEGACY FUNCTIONS (Original supabase_client.py)
# ========================================

import uuid

def insert_user(user_data: dict) -> dict:
    """
    Insert new user into database
    ✅ FIXED: Only generates 'id' field (not user_id)
    """
    try:
        # ✅ Generate id if not provided
        if "id" not in user_data or user_data.get("id") is None:
            user_data["id"] = str(uuid.uuid4())

        # ❌ REMOVED: Don't set user_id (column doesn't exist)
        # if "user_id" not in user_data:
        #     user_data["user_id"] = user_data["id"]

        # Convert date objects to ISO strings
        for key, value in user_data.items():
            if isinstance(value, date) and not isinstance(value, datetime):
                user_data[key] = value.isoformat()

        response = UserRepository.insert(user_data)

        if response.data and len(response.data) > 0:
            logger.info(f"[INSERT_USER] created id={user_data.get('id')} email={response.data[0].get('email')}")
            return response.data[0]
        else:
            raise Exception("No data returned from insert operation")

    except Exception as e:
        logger.error(f"[INSERT_USER] failed for email={user_data.get('email')}: {e}", exc_info=True)
        raise Exception(f"Supabase insert failed: {str(e)}")


def get_user_by_email(email: str) -> dict:
    """Get user from database with ALL fields"""
    try:
        # ✅ Make sure you're selecting ALL columns
        response = UserRepository.get_by_email(email)
        
        if response.data and len(response.data) > 0:
            user = response.data[0]

            # This runs on nearly every request (often several times per
            # request) — full detail is DEBUG-only so it doesn't flood
            # production logs. Nothing here changes often enough to warrant
            # an INFO line every call.
            logger.debug(f"[DB] Retrieved user={email} account_type={user.get('account_type')!r} columns={list(user.keys())}")

            return user
        else:
            logger.warning(f"[DB] No user found for: {email}")
            return None

    except Exception as e:
        logger.error(f"[DB] get_user_by_email failed for {email}: {e}", exc_info=True)
        return None

from typing import Optional, Dict, Any
import json
from datetime import datetime, timezone
from app import config

def insert_conversation_log(
    user_email: str, 
    role: str, 
    message: str, 
    channel: str = "chat",
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Insert conversation log with optional metadata
    
    Args:
        user_email: User's email
        role: 'user', 'assistant', or 'agent'
        message: Text message
        channel: Communication channel (default: 'chat')
        metadata: Optional structured data (documents, extractions, tables)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        log_entry = {
            "user_email": user_email,
            "role": role,
            "message": message,
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Add metadata if provided
        if metadata:
            log_entry["metadata"] = metadata if isinstance(metadata, dict) else json.loads(metadata)
        
        response = ConversationRepository.insert(log_entry)
        
        if response.data:
            has_metadata = bool(metadata)
            logger.info(f"[SUCCESS] Conversation logged (channel: {channel}, has_metadata: {has_metadata})")
            return True
        
        logger.warning(f"No data returned from conversation log insert")
        return False
        
    except Exception as e:
        logger.error(f"Failed to insert conversation log: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def get_conversation_history(user_email: str, limit: int = 100, channel: str = None) -> list:
    """
    Get conversation history with metadata
    
    Args:
        user_email: User's email
        limit: Maximum number of messages to retrieve (default: 100)
        channel: Optional channel filter
        
    Returns:
        List of conversation messages with metadata in chronological order
    """
    try:
        # `channel=None` means "no channel filter" — the repository applies the
        # link only when a channel is given, matching the conditional chain this
        # replaced. Chronological order (oldest first).
        response = ConversationRepository.list_for_channel(
            user_email, channel or None, limit=limit
        )
        
        messages = []
        for log in response.data:
            message = {
                "role": log.get("role"),
                "message": log.get("message"),
                "timestamp": log.get("timestamp"),
            }
            
            # Parse metadata if exists
            if log.get("metadata"):
                try:
                    # Metadata is already parsed as dict by Supabase JSONB
                    if isinstance(log["metadata"], dict):
                        message["metadata"] = log["metadata"]
                    elif isinstance(log["metadata"], str):
                        # Fallback: parse if it's a JSON string
                        message["metadata"] = json.loads(log["metadata"])
                    else:
                        message["metadata"] = None
                except Exception as parse_error:
                    logger.warning(f"Failed to parse metadata: {parse_error}")
                    message["metadata"] = None
            
            messages.append(message)
        
        logger.info(f"[SUCCESS] Retrieved {len(messages)} messages")
        return messages
        
    except Exception as e:
        logger.error(f"Failed to get conversation history: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def clear_conversation_history(user_email: str) -> bool:
    """
    Clear all conversation history for a user
    
    Args:
        user_email: User's email
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        response = ConversationRepository.delete_for_user(user_email)

        deleted_count = len(response.data) if response.data else 0
        logger.info(f"[SUCCESS] Cleared {deleted_count} messages for {user_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to clear conversation history: {e}")
        return False


def get_latest_conversation_message(user_email: str) -> dict:
    """
    Get the most recent conversation message for a user
    
    Args:
        user_email: User's email
        
    Returns:
        dict: Latest message or None if no messages exist
    """
    try:
        response = ConversationRepository.latest(user_email)

        if response.data and len(response.data) > 0:
            log = response.data[0]
            message = {
                "role": log.get("role"),
                "message": log.get("message"),
                "timestamp": log.get("timestamp"),
            }
            
            if log.get("metadata"):
                try:
                    if isinstance(log["metadata"], dict):
                        message["metadata"] = log["metadata"]
                    elif isinstance(log["metadata"], str):
                        message["metadata"] = json.loads(log["metadata"])
                except:
                    message["metadata"] = None
            
            return message
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get latest message: {e}")
        return None


# ========================================
# TAMPERING DETECTION FUNCTIONS
# ========================================

def get_supabase_client():
    """Returns the standard Supabase client"""
    return supabase

def update_user_ai_welcome_flag(user_email: str) -> bool:
    """Mark user as having seen AI welcome"""
    try:
        response = (
            UserRepository.update_by_email(user_email, {"has_seen_ai_welcome": True})
        )
        
        if response.data:
            logger.info(f"[SUCCESS] Updated AI welcome flag for {user_email}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to update flag: {e}")
        return False

def get_tampering_table(table_name: str):
    """
    Returns a Supabase table reference for tampering detection.
    Tables are in the public schema with 'tampering_' prefix.
    
    Args:
        table_name: Base table name (e.g., 'test_reports', 'module_results')
    
    Returns:
        Supabase table reference
    """
    # Add tampering_ prefix to table names
    prefixed_table = f"tampering_{table_name}"
    return supabase_service.from_(prefixed_table)


def _make_json_serializable(obj):
    """Convert objects to JSON-serializable format"""
    if isinstance(obj, bool):
        return obj
    elif isinstance(obj, (int, float, str, type(None))):
        return obj
    elif isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    else:
        return str(obj)


def save_test_report(
    file_path: str, 
    decision: dict, 
    test_results: list, 
    processing_time: float, 
    forensic_report: dict = None,
    user_email: str = None,
    document_type: str = None
) -> str:
    """
    Save tampering test report to database.
    Returns test_report_id on success, None on failure.
    """
    try:
        document_name = os.path.basename(file_path)
        file_type = os.path.splitext(file_path)[1].lower()
        
        # Extract case_id from forensic_report if available
        case_id = forensic_report.get("case_id", "") if forensic_report else ""
        
        report_data = {
            "document_name": document_name,
            "file_path": file_path,
            "file_type": file_type,
            "user_email": user_email,
            "document_type": document_type,
            "overall_score": float(decision.get("overall_tampering_score", 0.0)),
            "decision": decision.get("decision", "UNKNOWN"),
            "status": decision.get("status", "UNKNOWN"),
            "processing_time": float(processing_time),
            "reason": decision.get("reason", "")[:500] if decision.get("reason") else None,
            "case_id": case_id if case_id else None
        }
        
        # Insert into tampering_test_reports table (public schema)
        result = get_tampering_table("test_reports").insert(report_data).execute()
        test_report_id = result.data[0]["id"]
        
        logger.info(f"[SUCCESS] Test report saved with ID: {test_report_id}")
        
        # Save structured data to proper tables
        save_module_results(test_report_id, test_results)
        save_tampered_regions(test_report_id, test_results)
        
        return test_report_id
    except Exception as e:
        logger.error(f"Error saving test report: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def save_module_results(test_report_id: str, test_results: list):
    """Save individual module test results to tampering_module_results"""
    try:
        module_data = []
        for test in test_results:
            # Convert evidence to JSON-serializable format
            evidence = test.get("evidence", {})
            evidence_serializable = _make_json_serializable(evidence)
            
            module_data.append({
                "test_report_id": test_report_id,
                "module_name": test.get("test", "Unknown"),
                "status": test.get("status", "PASS"),
                "score": float(test.get("tampering_score", 0.0)),
                "reason": test.get("reason", "")[:500] if test.get("reason") else None,
                "evidence": evidence_serializable
            })
        
        if module_data:
            get_tampering_table("module_results").insert(module_data).execute()
            logger.info(f"[SUCCESS] Saved {len(module_data)} module results")
    except Exception as e:
        logger.error(f"Error saving module results: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def save_tampered_regions(test_report_id: str, test_results: list):
    """Save detected tampered regions to tampering_tampered_regions"""
    try:
        regions_data = []
        
        for test in test_results:
            evidence = test.get("evidence", {})
            doc_analysis = evidence.get("document_analysis", {})
            
            if doc_analysis:
                region_results = doc_analysis.get("region_results", [])
                for region in region_results:
                    if region.get("status") == "FAIL":
                        regions_data.append({
                            "test_report_id": test_report_id,
                            "module_name": test.get("test", "Unknown"),
                            "region_coordinates": region.get("position", {}),
                            "confidence": float(test.get("tampering_score", 0.0)),
                            "tampering_type": "quantization_anomaly"
                        })
        
        if regions_data:
            get_tampering_table("tampered_regions").insert(regions_data).execute()
            logger.info(f"[SUCCESS] Saved {len(regions_data)} tampered regions")
    except Exception as e:
        logger.error(f"Error saving tampered regions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def update_user_tampering_status(
    user_email: str,
    report_id: str,
    score: float,
    decision: str,
    requires_review: bool
):
    """
    Update user's tampering status in public.users table.
    Maps decision to document_status.
    """
    try:
        # Map decision to document_status (must match DB constraint exactly)
        status_mapping = {
            "ACCEPT": "verified",
            "ESCALATE": "manual_review",  # Changed from 'manual_review_required'
            "REJECT": "rejected"
        }
        document_status = status_mapping.get(decision, "pending")
        
        update_data = {
            "tampering_report_id": report_id,
            "tampering_score": float(score),
            "document_status": document_status,
            "requires_manual_review": requires_review,
            "tampering_checked_at": datetime.now().isoformat()
        }
        
        response = (
            UserRepository.update_by_email(user_email, update_data)
        )
        
        if response.data:
            logger.info(f"[SUCCESS] Updated user tampering status for {user_email}")
            return True
        else:
            logger.warning(f"No user found with email: {user_email}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating user tampering status: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def get_pending_manual_reviews(limit: int = 50):
    """
    Get all documents pending manual review from tampering_test_reports.
    """
    try:
        response = (
            get_tampering_table("test_reports")
            .select("*")
            .eq("decision", "ESCALATE")
            .is_("review_status", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data
    except Exception as e:
        logger.error(f"Error fetching pending reviews: {str(e)}")
        return []


def update_manual_review(
    test_report_id: str,
    review_status: str,
    reviewed_by: str,
    review_notes: str = None
):
    """
    Update manual review status for a test report.
    review_status: 'approved' or 'rejected'
    """
    try:
        update_data = {
            "review_status": review_status,
            "reviewed_by": reviewed_by,
            "reviewed_at": datetime.now().isoformat(),
            "review_notes": review_notes
        }
        
        response = (
            get_tampering_table("test_reports")
            .update(update_data)
            .eq("id", test_report_id)
            .execute()
        )
        
        if response.data:
            logger.info(f"[SUCCESS] Manual review updated for report {test_report_id}")
            return True
        return False
        
    except Exception as e:
        logger.error(f"Error updating manual review: {str(e)}")
        return False


def get_user_tampering_history(user_email: str, limit: int = 10):
    """
    Get tampering check history for a specific user.
    """
    try:
        response = (
            get_tampering_table("test_reports")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data
    except Exception as e:
        logger.error(f"Error fetching user tampering history: {str(e)}")
        return []


def save_llm_analysis(
    test_report_id: str,
    analysis_text: str,
    tampered_sections: dict = None,
    recommendations: str = None
):
    """
    Save LLM analysis results to tampering_llm_analysis table.
    """
    try:
        analysis_data = {
            "test_report_id": test_report_id,
            "analysis_text": analysis_text,
            "tampered_sections": _make_json_serializable(tampered_sections) if tampered_sections else None,
            "recommendations": recommendations
        }
        
        response = get_tampering_table("llm_analysis").insert(analysis_data).execute()
        
        if response.data:
            logger.info(f"[SUCCESS] LLM analysis saved for report {test_report_id}")
            return response.data[0]["id"]
        return None
        
    except Exception as e:
        logger.error(f"Error saving LLM analysis: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def get_tampering_statistics(days: int = 30):
    """
    Get tampering detection statistics for the last N days.
    """
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        response = (
            get_tampering_table("test_reports")
            .select("decision, status, overall_score")
            .gte("created_at", cutoff_date)
            .execute()
        )
        
        if not response.data:
            return {
                "total": 0,
                "accepted": 0,
                "escalated": 0,
                "rejected": 0,
                "average_score": 0.0
            }
        
        data = response.data
        total = len(data)
        accepted = len([r for r in data if r["decision"] == "ACCEPT"])
        escalated = len([r for r in data if r["decision"] == "ESCALATE"])
        rejected = len([r for r in data if r["decision"] == "REJECT"])
        avg_score = sum(r["overall_score"] for r in data) / total if total > 0 else 0.0
        
        return {
            "total": total,
            "accepted": accepted,
            "escalated": escalated,
            "rejected": rejected,
            "average_score": round(avg_score, 2)
        }
        
    except Exception as e:
        logger.error(f"Error fetching tampering statistics: {str(e)}")
        return None


# ========================================
# EXPORTS
# ========================================

__all__ = [
    # Legacy functions
    'supabase',
    'supabase_service',
    'insert_user',
    'get_user_by_email',
    'insert_conversation_log',
    # Tampering detection functions
    'get_supabase_client',
    'get_tampering_table',
    'save_test_report',
    'save_module_results',
    'save_tampered_regions',
    'update_user_tampering_status',
    'get_pending_manual_reviews',
    'update_manual_review',
    'get_user_tampering_history',
    'save_llm_analysis',
    'get_tampering_statistics',
]