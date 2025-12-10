# backend/app/middleware/auth_middleware.py

from functools import wraps
from fastapi import HTTPException, Header
from typing import Optional
from app.services.session_service import SessionService

def require_auth(func):
    """
    Decorator to require authentication for endpoints
    Usage: @require_auth
    """
    @wraps(func)
    async def wrapper(*args, session_id: Optional[str] = Header(None, alias="X-Session-ID"), **kwargs):
        if not session_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Please login."
            )
        
        user_data = SessionService.validate_session(session_id)
        
        if not user_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session. Please login again."
            )
        
        # Add user data to kwargs
        kwargs['current_user'] = user_data
        
        return await func(*args, **kwargs)
    
    return wrapper


def require_admin(func):
    """
    Decorator to require admin role
    Usage: @require_admin
    """
    @wraps(func)
    async def wrapper(*args, session_id: Optional[str] = Header(None, alias="X-Session-ID"), **kwargs):
        if not session_id:
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Please login."
            )
        
        user_data = SessionService.validate_session(session_id)
        
        if not user_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session. Please login again."
            )
        
        if user_data.get('role') != 'admin':
            raise HTTPException(
                status_code=403,
                detail="Admin access required. Insufficient permissions."
            )
        
        # Add user data to kwargs
        kwargs['current_user'] = user_data
        
        return await func(*args, **kwargs)
    
    return wrapper