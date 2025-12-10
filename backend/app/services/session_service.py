# backend/app/services/session_service.py

from datetime import datetime, timedelta
from typing import Optional, Dict
import uuid
from app.services.supabase_client import supabase

class SessionService:
    """
    Session management service
    """
    
    @staticmethod
    def create_session(user_id: str, user_data: Dict, timeout_minutes: int = 300) -> str:
        """
        Create a new session
        Returns session_id
        """
        session_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(minutes=timeout_minutes)
        
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "email": user_data.get("email"),
            "created_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at.isoformat(),
            "is_active": True,
            "last_activity": datetime.utcnow().isoformat()
        }
        
        try:
            supabase.table("sessions").insert(session_data).execute()
            return session_id
        except Exception as e:
            print(f"[ERROR] Failed to create session: {e}")
            raise
    
    @staticmethod
    def validate_session(session_id: str) -> Optional[Dict]:
        """
        Validate session and return user data
        Returns None if invalid
        """
        try:
            result = supabase.table("sessions").select("*, users(*)").eq("session_id", session_id).eq("is_active", True).execute()
            
            if not result.data:
                return None
            
            session = result.data[0]
            
            # Check if expired
            expires_at = datetime.fromisoformat(session["expires_at"].replace('Z', '+00:00'))
            if datetime.utcnow() > expires_at.replace(tzinfo=None):
                SessionService.invalidate_session(session_id)
                return None
            
            # Update last activity
            supabase.table("sessions").update({
                "last_activity": datetime.utcnow().isoformat()
            }).eq("session_id", session_id).execute()
            
            # Return user data
            user = session.get("users", {})
            return {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role", "user"),
                "account_type": user.get("account_type"),
            }
            
        except Exception as e:
            print(f"[ERROR] Session validation error: {e}")
            return None
    
    @staticmethod
    def invalidate_session(session_id: str):
        """
        Invalidate a session (logout)
        """
        try:
            supabase.table("sessions").update({
                "is_active": False
            }).eq("session_id", session_id).execute()
        except Exception as e:
            print(f"[ERROR] Failed to invalidate session: {e}")
            raise
    
    @staticmethod
    def cleanup_expired_sessions():
        """
        Remove expired sessions (can be run as a scheduled job)
        """
        try:
            now = datetime.utcnow().isoformat()
            supabase.table("sessions").delete().lt("expires_at", now).execute()
        except Exception as e:
            print(f"[ERROR] Failed to cleanup sessions: {e}")