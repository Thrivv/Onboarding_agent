# app/api/routes/register.py

from fastapi import APIRouter, HTTPException
from app.models.user import UserRegisterRequest
from app.services.supabase_client import insert_user, get_user_by_email
from app.services.email_sender import send_welcome_email
from app.services.supabase_client import insert_conversation_log, get_total_users, get_verified_users_count, get_users_registered_today, get_users_registered_this_week
from app.models.conversation import ConversationLog
from datetime import datetime


router = APIRouter()

@router.post("/register")
def register_user(user: UserRegisterRequest):
    try:
        # Duplicate check
        if get_user_by_email(user.email):
            raise HTTPException(status_code=409, detail="Email already registered")

        user_dict = user.dict()
        inserted_user = insert_user(user_dict)

        # 1️⃣ Send Welcome Email
        send_welcome_email(user.email, user.name)

        # 2️⃣ Log Welcome Message to conversations table
        convo = ConversationLog(
            user_email=user.email,
            role="agent",
            message="Welcome to Thrivv! Please reply with 'Continue' or 'Exit'.",
            timestamp=datetime.utcnow()
        )
        insert_conversation_log(convo.dict())

        return {"message": "User registered successfully", "user": inserted_user}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/get-total-users")
def total_users():
    try:
        total_users = get_total_users()
        return {"total_users": total_users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/get-verified-users-count")
def verfied_user_count():
    try:
        verfied_user_count= get_verified_users_count()
        return {"verified_users_count": verfied_user_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/get-pending-verification-count")
def pending_verification_count():
    try:
        total_users = get_total_users()
        verified_users = get_verified_users_count()
        pending_users = total_users - verified_users
        return {"pending_verification_count": pending_users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registered-today")
def users_registered_today():
    try:
        users_today = get_users_registered_today()
        return {"users_registered_today": users_today}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/regisetered-this-week")
def users_registered_this_week():
    try:
        users_this_week = get_users_registered_this_week()
        return {"users_registered_this_week": users_this_week}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 
    




