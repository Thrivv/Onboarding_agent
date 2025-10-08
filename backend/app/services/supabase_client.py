# app/services/supabase_client.py

from datetime import date, timedelta,datetime # ✅ Add this
from app.config import SUPABASE_URL, SUPABASE_API_KEY
from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_API_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

def insert_user(user_data: dict) -> dict:
    try:
        # Convert date objects to ISO strings
        for key, value in user_data.items():
            if isinstance(value, date):
                user_data[key] = value.isoformat()

        response = supabase.table("users").insert(user_data).execute()
        return response.data[0]

    except Exception as e:
        raise Exception(f"Supabase insert failed: {str(e)}")


def get_user_by_email(email: str) -> dict | None:
    try:
        response = supabase.table("users").select("*").eq("email", email).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        raise Exception(f"Supabase select failed: {str(e)}")

# app/services/supabase_client.py

def insert_conversation_log(log: dict) -> dict:
    try:
        log["timestamp"] = log["timestamp"].isoformat()  # Serialize datetime
        response = supabase.table("conversations").insert(log).execute()
        return response.data[0]
    except Exception as e:
        raise Exception(f"Supabase insert conversation failed: {str(e)}")

#Total users function
def get_total_users() -> int:
    try:
        response = supabase.table("users").select("*").execute()
        return len(response.data)   
    except Exception as e:
        raise Exception(f"Supabase get total users failed: {str(e)}")
    
#Total number of verified users (where onboarding_step is verfication_complete
def get_verified_users_count() -> int:
    try:
        response = supabase.table("users").select("*").eq("onboarding_step", "verification_complete").execute()
        return len(response.data)
    except Exception as e:
        raise Exception(f"Supabase get verified users count failed: {str(e)}")
    
#Total number of users that are registered today current date
def get_users_registered_today() -> int:
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

        response = (
            supabase.table("users")
            .select("*")
            .gte("created_at", today_start)
            .lte("created_at", today_end)
            .execute()
        )
        return len(response.data)
    except Exception as e:
        raise Exception(f"Supabase get users registered today failed: {str(e)}")


#Total number of users that are registered this week
from datetime import datetime, timedelta

def get_users_registered_this_week() -> int:
    try:
        today = datetime.now()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_week_iso = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        response = (
            supabase.table("users")
            .select("*")
            .gte("created_at", start_of_week_iso)
            .execute()
        )
        return len(response.data)
    except Exception as e:
        raise Exception(f"Supabase get users registered this week failed: {str(e)}")

