import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from supabase import create_client
import plotly.express as px

# --- CONFIG ---
FASTAPI_URL = "http://localhost:8000/register" 
FASTAPI_URLS = "http://localhost:8000"
SUPABASE_URL="https://cjqhmjzxcglhvnjjbxcv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNqcWhtanp4Y2dsaHZuampieGN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTY3OTgwMDEsImV4cCI6MjA3MjM3NDAwMX0.m2eMshGo8_mrKpssVmmot0Q_SskDjQcLRKYHHZUqtY0"


supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- PAGE SETTINGS ---
st.set_page_config(page_title="Onboarding Agent", layout="wide")
st.markdown(
    """
    <style>
    /* General UI tweaks */
    .main {
        background-color: #f8f9fa;
    }
    /* KPI card style */
    .kpi-card {
        padding: 15px;
        border-radius: 10px;
        color: white;
        text-align: center;
        font-weight: bold;
    }
    .kpi-number {
        font-size: 28px;
        font-weight: 700;
        margin-top: 5px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🧾 Onboarding Agent")

tabs = st.tabs(["Register User", "Admin Dashboard", "Conversations"])

# --- TAB 1: Register User ---
with tabs[0]:
    st.header("📬 Register a New User")
    with st.form("register_form"):
        name = st.text_input("Full Name")
        dob = st.date_input("Date of Birth")
        phone_number = st.text_input("Phone Number")
        email = st.text_input("Email")
        business_name = st.text_input("Business Name")

        # Q1: Account type
        account_type = st.radio(
            "What kind of account do you want to open?",
            ["Savings", "Corporate"]
        )

        # Q2: Ownership type
        ownership_type = st.radio(
            "Do you want to open a single owner or partnership account?",
            ["Single Owner", "Partnership"]
        )

        # Q3: Partnership details (always visible)
        partnership_details = st.radio(
            "Are all shareholders in your business individual persons or not?",
            [
                "All shareholders are individual persons",
                "One or more shareholders are companies or other legal entities"
            ]
        )

        # Q4: Expected annual turnover
        annual_turnover = st.text_input("What is your expected annual turnover?")

        # Q5: Age confirmation
        is_above_18 = st.checkbox("Do you confirm you are above 18 years of age?")

        submitted = st.form_submit_button("Register")

        if submitted:
            if not all([name, phone_number, email, business_name, account_type, ownership_type, annual_turnover]) or (ownership_type == "Partnership" and not partnership_details) or not is_above_18:
                st.warning("⚠️ Please fill all required fields and confirm age.")
            else:
                data = {
                    "name": name,
                    "dob": dob.isoformat(),
                    "phone_number": phone_number,
                    "email": email,
                    "business_name": business_name,
                    "account_type": account_type,
                    "ownership_type": ownership_type,
                    "partnership_details": partnership_details if ownership_type == "Partnership" else None,
                    "annual_turnover": annual_turnover,
                    "is_above_18": is_above_18,
                }
                try:
                    response = requests.post(FASTAPI_URL, json=data)
                    if response.status_code == 200:
                        st.success("✅ User registered and onboarding started!")
                        st.json(response.json())
                    elif response.status_code == 409:
                        st.error("❌ Email already registered.")
                    else:
                        st.error(f"❌ Error: {response.json().get('detail')}")
                except Exception as e:
                    st.error(f"❌ Connection error: {e}")

# --- TAB 2: Admin Dashboard ---
with tabs[1]:
    st.header("📊 Admin Dashboard")

    try:
        # --- Fetch KPI Data ---
        total_users = requests.get(f"{FASTAPI_URLS}/get-total-users").json().get("total_users", 0)
        verified_users = requests.get(f"{FASTAPI_URLS}/get-verified-users-count").json().get("verified_users_count", 0)
        pending_verification = requests.get(f"{FASTAPI_URLS}/get-pending-verification-count").json().get("pending_verification_count", 0)
        registered_today = requests.get(f"{FASTAPI_URLS}/registered-today").json().get("users_registered_today", 0)
        registered_this_week = requests.get(f"{FASTAPI_URLS}/regisetered-this-week").json().get("users_registered_this_week", 0)

        # --- KPI Cards ---
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.markdown(f"<div class='kpi-card' style='background-color:#007bff;'>👥 Total Users<div class='kpi-number'>{total_users}</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='kpi-card' style='background-color:#28a745;'>✅ Verified<div class='kpi-number'>{verified_users}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='kpi-card' style='background-color:#ffc107;'>⏳ Pending<div class='kpi-number'>{pending_verification}</div></div>", unsafe_allow_html=True)
        col4.markdown(f"<div class='kpi-card' style='background-color:#17a2b8;'>📅 Today<div class='kpi-number'>{registered_today}</div></div>", unsafe_allow_html=True)
        col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>🗓️ This Week<div class='kpi-number'>{registered_this_week}</div></div>", unsafe_allow_html=True)

        # --- Graph: Total vs Verified ---
        df_chart = pd.DataFrame({
            "Metric": ["Total Users", "Verified Users"],
            "Count": [total_users, verified_users]
        })
        fig = px.bar(df_chart, x="Metric", y="Count", color="Metric", title="📈 Users vs Verified Users", color_discrete_sequence=["#007bff", "#28a745"])
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Could not fetch KPIs: {e}")

    # --- Users Table ---
    try:
        rows = supabase.table("users").select("*").execute().data
        for row in rows:
            step = row.get("onboarding_step", "welcome")
            if step == "welcome":
                status = "📩 Awaiting reply"
            elif step == "document_verification":
                status = "📁 Documents received"
            elif step == "verification_complete":
                status = "✅ Onboarding complete"
            else:
                status = "⏳ In progress"
            row["status"] = status

        df = pd.DataFrame(rows)
        st.subheader("📜 User Table")
        st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.error(f"Could not fetch users: {e}")

# --- TAB 3: Conversations Viewer ---
with tabs[2]:
    st.header("🗣️ User Conversations")
    email_filter = st.text_input("Search by Email")
    if email_filter:
        try:
            conversations = (
                supabase.table("conversations")
                .select("*")
                .eq("user_email", email_filter)
                .order("timestamp", desc=True)
                .execute()
                .data
            )
            df = pd.DataFrame(conversations)
            if df.empty:
                st.info("No conversations found for this user.")
            else:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Error fetching conversations: {e}")

