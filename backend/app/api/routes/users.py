# app/api/routes/users.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app.services.supabase_client import supabase
from datetime import datetime, timezone
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

class UserUpdate(BaseModel):
    name: str = None
    onboarding_step: str = None

@router.get("/users/all")
def get_all_users():
    """Get all users with their details"""
    try:
        # Get all users
        users_response = supabase.table("users").select("*").execute()
        users_data = users_response.data if users_response.data else []
        
        # Get all conversations for context
        convos_response = supabase.table("conversations").select("*").execute()
        convos_data = convos_response.data if convos_response.data else []
        
        processed_users = []
        for user in users_data:
            # Get user conversations
            user_convos = [c for c in convos_data if c.get('user_email') == user.get('email')]
            
            # Get document info
            user_folder = os.path.join("documents", user.get('email', ''))
            has_documents = os.path.exists(user_folder) and len([f for f in os.listdir(user_folder) 
                                                                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]) > 0
            
            processed_users.append({
                "id": user.get("id"),
                "name": user.get("name", "Unknown"),
                "email": user.get("email", ""),
                "phone_number": user.get("phone_number", ""),
                "business_name": user.get("business_name", ""),
                "dob": user.get("dob", ""),
                "onboarding_step": user.get("onboarding_step", "welcome"),
                "created_at": user.get("created_at", ""),
                "updated_at": user.get("updated_at", ""),
                "conversation_count": len(user_convos),
                "has_documents": has_documents,
                "last_activity": user_convos[-1].get("timestamp") if user_convos else user.get("created_at")
            })
        
        return {"users": processed_users, "total": len(processed_users)}
        
    except Exception as e:
        logger.error(f"Failed to get users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}")
def get_user_details(user_id: int):
    """Get detailed information for a specific user"""
    try:
        # Get user
        user_response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = user_response.data[0]
        
        # Get user conversations
        convos_response = supabase.table("conversations").select("*").eq("user_email", user["email"]).order("timestamp").execute()
        conversations = convos_response.data if convos_response.data else []
        
        # Get document info
        user_folder = os.path.join("documents", user["email"])
        documents = []
        if os.path.exists(user_folder):
            for filename in os.listdir(user_folder):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.txt')):
                    file_path = os.path.join(user_folder, filename)
                    file_size = os.path.getsize(file_path)
                    documents.append({
                        "filename": filename,
                        "size": file_size,
                        "type": "image" if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) else "text"
                    })
        
        return {
            "user": user,
            "conversations": conversations,
            "documents": documents,
            "conversation_count": len(conversations),
            "document_count": len([d for d in documents if d["type"] == "image"])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{user_id}")
def update_user(user_id: int, user_update: UserUpdate):
    """Update user information"""
    try:
        # Prepare update data
        update_data = {}
        if user_update.name is not None:
            update_data["name"] = user_update.name
        if user_update.onboarding_step is not None:
            update_data["onboarding_step"] = user_update.onboarding_step
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Update user
        response = supabase.table("users").update(update_data).eq("id", user_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User updated successfully", "user": response.data[0]}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/users/{user_id}")
def delete_user(user_id: int):
    """Delete a user and their associated data"""
    try:
        # Get user first
        user_response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = user_response.data[0]
        user_email = user["email"]
        
        # Delete conversations
        supabase.table("conversations").delete().eq("user_email", user_email).execute()
        
        # Delete user documents
        user_folder = os.path.join("documents", user_email)
        if os.path.exists(user_folder):
            import shutil
            shutil.rmtree(user_folder)
        
        # Delete user
        supabase.table("users").delete().eq("id", user_id).execute()
        
        return {"message": "User deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/conversations")
def get_user_conversations(user_id: int):
    """Get all conversations for a specific user"""
    try:
        # Get user first
        user_response = supabase.table("users").select("email").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_email = user_response.data[0]["email"]
        
        # Get conversations
        convos_response = supabase.table("conversations").select("*").eq("user_email", user_email).order("timestamp").execute()
        conversations = convos_response.data if convos_response.data else []
        
        return {
            "conversations": conversations,
            "total": len(conversations)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))
