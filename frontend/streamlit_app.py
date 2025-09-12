
import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from supabase import create_client
import plotly.express as px

# --- CONFIG ---
FASTAPI_URL = "http://localhost:8000/register" 
FASTAPI_URLS = "http://localhost:8000"
SUPABASE_URL="https://lerdhpeicsxnxlkzkfmq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxlcmRocGVpY3N4bnhsa3prZm1xIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTM5Nzc0OTQsImV4cCI6MjA2OTU1MzQ5NH0.KX11c-T-Q-o5QO754yet8dlGLEKXv3BlVvaIpb-Q1ig"


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
    
    # Initialize session state for dynamic flow
    if 'registration_step' not in st.session_state:
        st.session_state.registration_step = 'basic_info'
    if 'user_data' not in st.session_state:
        st.session_state.user_data = {}
    
    # Step 1: Basic Information
    if st.session_state.registration_step == 'basic_info':
        with st.form("basic_info_form"):
            st.subheader("Basic Information")
            
            # Pre-fill form with existing data if returning from a later step
            name_value = st.session_state.user_data.get('name', '')
            dob_value = datetime.fromisoformat(st.session_state.user_data.get('dob', str(datetime.now().date()))) if st.session_state.user_data.get('dob') else datetime.now().date()
            phone_value = st.session_state.user_data.get('phone_number', '')
            email_value = st.session_state.user_data.get('email', '')
            business_value = st.session_state.user_data.get('business_name', '')
            
            name = st.text_input("Full Name", value=name_value)
            dob = st.date_input("Date of Birth", value=dob_value)
            phone_number = st.text_input("Phone Number", value=phone_value)
            email = st.text_input("Email", value=email_value)
            business_name = st.text_input("Business Name", value=business_value)
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                if not all([name, phone_number, email, business_name]):
                    st.warning("⚠️ Please fill all required fields.")
                else:
                    # Store basic info
                    st.session_state.user_data.update({
                        'name': name,
                        'dob': dob.isoformat(),
                        'phone_number': phone_number,
                        'email': email,
                        'business_name': business_name
                    })
                    st.session_state.registration_step = 'account_type'
                    st.rerun()
    
    # Step 2: Account Type Selection
    elif st.session_state.registration_step == 'account_type':
        st.subheader("Account Information")
        
        # Display previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            st.write("**2. Date of Birth:** " + st.session_state.user_data.get('dob', ''))
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'basic_info'
                st.rerun()
        
        with st.form("account_type_form"):
            # Pre-select the current value if returning from a later step
            current_account_type = st.session_state.user_data.get('account_type', 'Savings')
            account_type_options = ["Savings", "Corporate"]
            default_index = account_type_options.index(current_account_type) if current_account_type in account_type_options else 0
            
            account_type = st.radio(
                "What kind of account do you want to open?",
                account_type_options,
                index=default_index
            )
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['account_type'] = account_type
                
                if account_type == "Savings":
                    # For Savings, skip to age confirmation
                    st.session_state.registration_step = 'age_confirmation'
                else:  # Corporate
                    st.session_state.registration_step = 'ownership_type'
                st.rerun()
    
    # Step 3: Ownership Type (Only for Corporate)
    elif st.session_state.registration_step == 'ownership_type':
        st.subheader("Ownership Details")
        
        # Display previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            st.write("**2. Date of Birth:** " + st.session_state.user_data.get('dob', ''))
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'account_type'
                st.rerun()
        
        with st.form("ownership_type_form"):
            # Pre-select the current value if returning from a later step
            current_ownership_type = st.session_state.user_data.get('ownership_type', 'Single Owner')
            ownership_options = ["Single Owner", "Partnership"]
            default_index = ownership_options.index(current_ownership_type) if current_ownership_type in ownership_options else 0
            
            ownership_type = st.radio(
                "Do you want to open a single owner or partnership account?",
                ownership_options,
                index=default_index
            )
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['ownership_type'] = ownership_type
                
                if ownership_type == "Single Owner":
                    # Skip to annual turnover
                    st.session_state.registration_step = 'annual_turnover'
                else:  # Partnership
                    st.session_state.registration_step = 'partnership_details'
                st.rerun()
    
    # Step 4: Partnership Details (Only for Partnership)
    elif st.session_state.registration_step == 'partnership_details':
        st.subheader("Partnership Information")
        
        # Display previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            st.write("**2. Date of Birth:** " + st.session_state.user_data.get('dob', ''))
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'ownership_type'
                st.rerun()
        
        with st.form("partnership_details_form"):
            # Pre-select the current value if returning from a later step
            current_partnership = st.session_state.user_data.get('partnership_details', 'All shareholders are individual persons')
            partnership_options = [
                "All shareholders are individual persons",
                "One or more shareholders are companies or other legal entities"
            ]
            default_index = partnership_options.index(current_partnership) if current_partnership in partnership_options else 0
            
            partnership_details = st.radio(
                "Are all shareholders in your business individual persons or not?",
                partnership_options,
                index=default_index
            )
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['partnership_details'] = partnership_details
                st.session_state.registration_step = 'annual_turnover'
                st.rerun()
    
    # Step 5: Annual Turnover (For Corporate accounts)
    elif st.session_state.registration_step == 'annual_turnover':
        st.subheader("Financial Information")
        
        # Display previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            st.write("**2. Date of Birth:** " + st.session_state.user_data.get('dob', ''))
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            if st.session_state.user_data.get('ownership_type'):
                st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
            if st.session_state.user_data.get('partnership_details'):
                st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
        
        # Back button - determine where to go back based on the flow
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                if st.session_state.user_data.get('ownership_type') == 'Partnership':
                    st.session_state.registration_step = 'partnership_details'
                else:
                    st.session_state.registration_step = 'ownership_type'
                st.rerun()
        
        with st.form("annual_turnover_form"):
            annual_turnover = st.text_input("What is your expected annual turnover?", value=st.session_state.user_data.get('annual_turnover', ''))
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                if not annual_turnover:
                    st.warning("⚠️ Please provide your expected annual turnover.")
                else:
                    st.session_state.user_data['annual_turnover'] = annual_turnover
                    st.session_state.registration_step = 'age_confirmation'
                    st.rerun()
    
    # Step 6: Age Confirmation (Final step)
    elif st.session_state.registration_step == 'age_confirmation':
        st.subheader("Final Confirmation")
        
        # Display previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            st.write("**2. Date of Birth:** " + st.session_state.user_data.get('dob', ''))
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            if st.session_state.user_data.get('ownership_type'):
                st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
            if st.session_state.user_data.get('partnership_details'):
                st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
            if st.session_state.user_data.get('annual_turnover'):
                st.write("**9. Expected Annual Turnover:** " + st.session_state.user_data.get('annual_turnover', ''))
        
        # Back button - determine where to go back based on the flow
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                if st.session_state.user_data.get('account_type') == 'Savings':
                    st.session_state.registration_step = 'account_type'
                else:  # Corporate
                    st.session_state.registration_step = 'annual_turnover'
                st.rerun()
        
        with st.form("age_confirmation_form"):
            is_above_18 = st.checkbox("Do you confirm you are above 18 years of age?")
            
            submitted = st.form_submit_button("Complete Registration")
            
            if submitted:
                if not is_above_18:
                    st.warning("⚠️ You must be above 18 years of age to register.")
                else:
                    # Prepare final data with NULL values for non-applicable fields
                    final_data = {
                        "name": st.session_state.user_data['name'],
                        "dob": st.session_state.user_data['dob'],
                        "phone_number": st.session_state.user_data['phone_number'],
                        "email": st.session_state.user_data['email'],
                        "business_name": st.session_state.user_data['business_name'],
                        "account_type": st.session_state.user_data['account_type'],
                        "ownership_type": st.session_state.user_data.get('ownership_type'),
                        "partnership_details": st.session_state.user_data.get('partnership_details'),
                        "annual_turnover": st.session_state.user_data.get('annual_turnover'),
                        "is_above_18": is_above_18,
                    }
                    
                    try:
                        response = requests.post(FASTAPI_URL, json=final_data)
                        if response.status_code == 200:
                            st.success("✅ User registered and onboarding started!")
                            st.json(response.json())
                            
                            # Reset session state for next registration
                            st.session_state.registration_step = 'basic_info'
                            st.session_state.user_data = {}
                            
                        elif response.status_code == 409:
                            st.error("❌ Email already registered.")
                        else:
                            st.error(f"❌ Error: {response.json().get('detail')}")
                    except Exception as e:
                        st.error(f"❌ Connection error: {e}")
    
# with tabs[0]:
#     st.header("📬 Register a New User")
#     with st.form("register_form"):
#         name = st.text_input("Full Name")
#         dob = st.date_input("Date of Birth")
#         phone_number = st.text_input("Phone Number")
#         email = st.text_input("Email")
#         business_name = st.text_input("Business Name")

#         # Q1: Account type
#         account_type = st.radio(
#             "What kind of account do you want to open?",
#             ["Savings", "Corporate"]
#         )

#         # Q2: Ownership type
#         ownership_type = st.radio(
#             "Do you want to open a single owner or partnership account?",
#             ["Single Owner", "Partnership"]
#         )

#         # Q3: Partnership details (always visible)
#         partnership_details = st.radio(
#             "Are all shareholders in your business individual persons or not?",
#             [
#                 "All shareholders are individual persons",
#                 "One or more shareholders are companies or other legal entities"
#             ]
#         )

#         # Q4: Expected annual turnover
#         annual_turnover = st.text_input("What is your expected annual turnover?")

#         # Q5: Age confirmation
#         is_above_18 = st.checkbox("Do you confirm you are above 18 years of age?")

#         submitted = st.form_submit_button("Register")

#         if submitted:
#             if not all([name, phone_number, email, business_name, account_type, ownership_type, annual_turnover]) or (ownership_type == "Partnership" and not partnership_details) or not is_above_18:
#                 st.warning("⚠️ Please fill all required fields and confirm age.")
#             else:
#                 data = {
#                     "name": name,
#                     "dob": dob.isoformat(),
#                     "phone_number": phone_number,
#                     "email": email,
#                     "business_name": business_name,
#                     "account_type": account_type,
#                     "ownership_type": ownership_type,
#                     "partnership_details": partnership_details if ownership_type == "Partnership" else None,
#                     "annual_turnover": annual_turnover,
#                     "is_above_18": is_above_18,
#                 }
#                 try:
#                     response = requests.post(FASTAPI_URL, json=data)
#                     if response.status_code == 200:
#                         st.success("✅ User registered and onboarding started!")
#                         st.json(response.json())
#                     elif response.status_code == 409:
#                         st.error("❌ Email already registered.")
#                     else:
#                         st.error(f"❌ Error: {response.json().get('detail')}")
#                 except Exception as e:
#                     st.error(f"❌ Connection error: {e}")

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

