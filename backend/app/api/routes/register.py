# app/api/routes/register.py

from fastapi import APIRouter, HTTPException
from app.models.user import UserRegisterRequest
from app.services.supabase_client import insert_user, get_user_by_email
from app.services.email_sender import send_welcome_email
from app.services.supabase_client import (
    insert_conversation_log,
    get_total_users,
    get_verified_users_count,
    get_users_registered_today,
    get_users_registered_this_week,
)
from app.models.conversation import ConversationLog
from datetime import datetime

router = APIRouter()


def get_document_requirements_message(
    account_type: str, ownership_type: str = None
) -> str:
    """
    Get document requirements message based on account flow
    """
    if account_type == "Savings":
        return """
<strong>📋 Required Documents:</strong>
<ul style='margin-left:20px;'>
    <li>Emirates ID (EID)</li>
    <li>Ejari (Tenancy Contract)</li>
</ul>
<p>Please reply to this email with both documents attached to continue your onboarding.</p>
"""

    elif account_type == "Corporate":
        if ownership_type == "Single Owner":
            return """
<strong>📋 Required Documents:</strong>
<ul style='margin-left:20px;'>
    <li>Commercial/Trade License</li>
    <li>Emirates ID (EID)</li>
    <li>Ejari (Tenancy Contract)</li>
</ul>
<p>Please reply to this email with all three documents attached to continue your onboarding.</p>
"""

        elif ownership_type in ["Partnership", "@Multiple Owners"]:
            return """
<strong>📋 Initial Documents Required:</strong>
<p>To identify all owners/members, please first submit:</p>
<ul style='margin-left:20px;'>
    <li>Commercial License (Trade License)</li>
    <li>MOA (Memorandum of Association)</li>
</ul>
<p>After we identify all owners, we will request Emirates ID (EID) for each member individually.</p>
<p style='background:#e3f2fd;padding:12px;border-left:4px solid #2196F3;margin:15px 0;'>
    <strong>Note:</strong> The number of EIDs required will depend on the number of owners listed in your Commercial License.
</p>
"""

    return "<p>Please submit the required documents to continue your onboarding.</p>"


@router.post("/register")
def register_user(user: UserRegisterRequest):
    try:
        # Duplicate check
        if get_user_by_email(user.email):
            raise HTTPException(status_code=409, detail="Email already registered")

        user_dict = user.dict()

        # Add initial document stage for multiple owners
        if user.account_type == "Corporate" and user.ownership_type in [
            "Partnership",
            "@Multiple Owners",
        ]:
            user_dict["document_stage"] = "identification"

        inserted_user = insert_user(user_dict)

        # Build welcome email with registration details
        doc_requirements = get_document_requirements_message(
            user.account_type, user.ownership_type
        )

        details = f"""
<p>Welcome to Thrivv, <strong>{user.name}</strong>!</p>

<div style='background:#f8f9fa;padding:15px;border-radius:5px;margin:15px 0;'>
    <p style='margin:0;'><strong>📝 Your Registration Details:</strong></p>
    <ul style='margin:10px 0 0 20px;'>
        <li>Name: {user.name}</li>
        <li>Date of Birth: {user.dob}</li>
        <li>Phone Number: {user.phone_number}</li>
        <li>Email: {user.email}</li>
        <li>Business Name: {user.business_name}</li>
        <li>Account Type: {user.account_type}</li>
        {f'<li>Ownership Type: {user.ownership_type}</li>' if user.ownership_type else ''}
        {f'<li>Partnership Details: {user.partnership_details}</li>' if user.partnership_details else ''}
        {f'<li>Expected Annual Turnover: {user.annual_turnover}</li>' if user.annual_turnover else ''}
    </ul>
</div>

{doc_requirements}

<p>If you have any questions, feel free to reply to this email.</p>
"""

        send_welcome_email(user.email, details)

        # Log Welcome Message to conversations table
        convo = ConversationLog(
            user_email=user.email,
            role="agent",
            message=f"Registration completed. Account Type: {user.account_type}. {doc_requirements}",
            timestamp=datetime.utcnow(),
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
        verfied_user_count = get_verified_users_count()
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
