import os
import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, date
from supabase import create_client
import plotly.express as px
from dotenv import load_dotenv  

# Load environment variables
load_dotenv()

# --- CONFIG ---
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FASTAPI_URL = f"{BACKEND_URL}/register"
FASTAPI_URLS = BACKEND_URL
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

# Add error checking
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase configuration not found. Please check your .env file.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILITY FUNCTIONS ---
def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

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
    /* Chat message styles */
    .user-message {
        display: flex;
        justify-content: flex-end;
        margin: 10px 0;
    }
    .user-message-content {
        background-color: #007bff;
        color: white;
        padding: 10px 15px;
        border-radius: 20px 20px 5px 20px;
        max-width: 70%;
        word-wrap: break-word;
    }
    .assistant-message {
        display: flex;
        justify-content: flex-start;
        margin: 10px 0;
    }
    .assistant-message-content {
        background-color: #f1f1f1;
        color: #333;
        padding: 10px 15px;
        border-radius: 20px 20px 20px 5px;
        max-width: 80%;
        word-wrap: break-word;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🧾 Onboarding Agent")

tabs = st.tabs(["Register User", "Admin Dashboard", "Conversations", "Chat Assistant", "Document Upload"])

# --- TAB 1: Register User (UNCHANGED) ---
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
            
            name_value = st.session_state.user_data.get('name', '')
            
            if st.session_state.user_data.get('dob'):
                try:
                    dob_value = datetime.fromisoformat(st.session_state.user_data.get('dob')).date()
                except:
                    dob_value = date(2000, 1, 1)
            else:
                dob_value = date(2000, 1, 1)
            
            phone_value = st.session_state.user_data.get('phone_number', '')
            email_value = st.session_state.user_data.get('email', '')
            business_value = st.session_state.user_data.get('business_name', '')
            
            name = st.text_input("Full Name", value=name_value)
            dob = st.date_input("Date of Birth", value=dob_value, min_value=date(1900, 1, 1), max_value=date.today())
            phone_number = st.text_input("Phone Number", value=phone_value)
            email = st.text_input("Email", value=email_value)
            business_name = st.text_input("Business Name", value=business_value)
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                if not all([name, phone_number, email, business_name]):
                    st.warning("⚠️ Please fill all required fields.")
                    st.stop()
                
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
    # Step 2: Account Type Selection
    elif st.session_state.registration_step == 'account_type':
        st.subheader("Account Information")
        
        # Previously answered questions
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            dob_str = st.session_state.user_data.get('dob', '')
            if dob_str:
                try:
                    dob_date = datetime.fromisoformat(dob_str).date()
                    age = calculate_age(dob_date)
                    st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
                except:
                    st.write("**2. Date of Birth:** " + dob_str)
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
        
        # Back button (outside form)
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back", key="account_type_back_btn"):
                st.session_state.registration_step = 'basic_info'
                st.rerun()
        
        st.write("")  # Add spacing
        
        # Form for account type
        with st.form("account_type_form"):
            st.markdown("### What kind of account do you want to open?")
            
            # Get current selection
            current_account_type = st.session_state.user_data.get('account_type', 'Savings')
            account_type_options = ["Savings", "Corporate"]
            
            # Find default index
            try:
                default_index = account_type_options.index(current_account_type)
            except ValueError:
                default_index = 0
            
            # Radio buttons
            account_type = st.radio(
                "Select your account type:",
                account_type_options,
                index=default_index,
                key="account_type_selection"
            )
              
            # Submit button
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                submitted = st.form_submit_button("✅ Continue", type="primary", use_container_width=True)
            
            # Handle submission
            if submitted:
                # Save to session state
                st.session_state.user_data['account_type'] = account_type
                
                # Determine next step
                if account_type == "Savings":
                    # Savings goes directly to terms & conditions
                    st.session_state.registration_step = 'final_confirmation'
                    st.success("✅ Account type saved! Moving to Terms & Conditions...")
                elif account_type == "Corporate":
                    # Corporate needs ownership type
                    st.session_state.registration_step = 'ownership_type'
                    st.success("✅ Account type saved! Moving to Ownership Type...")
                
                # Wait a moment for user to see the success message
                import time
                time.sleep(0.5)
                
                # Refresh page to show next step
                st.rerun()
    
    # Step 3: Ownership Type (Only for Corporate)
    elif st.session_state.registration_step == 'ownership_type':
        st.subheader("Ownership Details")
        
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            dob_str = st.session_state.user_data.get('dob', '')
            if dob_str:
                try:
                    dob_date = datetime.fromisoformat(dob_str).date()
                    age = calculate_age(dob_date)
                    st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
                except:
                    st.write("**2. Date of Birth:** " + dob_str)
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'account_type'
                st.rerun()
        
        with st.form("ownership_type_form"):
            current_ownership_type = st.session_state.user_data.get('ownership_type', 'Single Owner')
            ownership_options = ["Single Owner", "Partnership"]
            default_index = ownership_options.index(current_ownership_type) if current_ownership_type in ownership_options else 0
            
            ownership_type = st.radio("Do you want to open a single owner or partnership account?", ownership_options, index=default_index)
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['ownership_type'] = ownership_type
                if ownership_type == "Single Owner":
                    st.session_state.registration_step = 'annual_turnover'
                else:
                    st.session_state.registration_step = 'partnership_details'
                st.rerun()
    
    # Step 4: Partnership Details
    elif st.session_state.registration_step == 'partnership_details':
        st.subheader("Partnership Information")
        
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            dob_str = st.session_state.user_data.get('dob', '')
            if dob_str:
                try:
                    dob_date = datetime.fromisoformat(dob_str).date()
                    age = calculate_age(dob_date)
                    st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
                except:
                    st.write("**2. Date of Birth:** " + dob_str)
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'ownership_type'
                st.rerun()
        
        with st.form("partnership_details_form"):
            current_partnership = st.session_state.user_data.get('partnership_details', 'All shareholders are individual persons')
            partnership_options = [
                "All shareholders are individual persons",
                "One or more shareholders are companies or other legal entities"
            ]
            default_index = partnership_options.index(current_partnership) if current_partnership in partnership_options else 0
            
            partnership_details = st.radio("Are all shareholders in your business individual persons or not?", partnership_options, index=default_index)
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['partnership_details'] = partnership_details
                st.session_state.registration_step = 'annual_turnover'
                st.rerun()
    
    # Step 5: Annual Turnover
    elif st.session_state.registration_step == 'annual_turnover':
        st.subheader("Financial Information")
        
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            dob_str = st.session_state.user_data.get('dob', '')
            if dob_str:
                try:
                    dob_date = datetime.fromisoformat(dob_str).date()
                    age = calculate_age(dob_date)
                    st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
                except:
                    st.write("**2. Date of Birth:** " + dob_str)
            st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
            st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
            st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            if st.session_state.user_data.get('ownership_type'):
                st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
            if st.session_state.user_data.get('partnership_details'):
                st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
        
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
                    st.session_state.registration_step = 'final_confirmation'
                    st.rerun()
    
    # Step 6: Final Confirmation
    elif st.session_state.registration_step == 'final_confirmation':
        st.subheader("Final Confirmation")
        
        with st.expander("📋 Previously Answered Questions", expanded=True):
            st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
            dob_str = st.session_state.user_data.get('dob', '')
            if dob_str:
                try:
                    dob_date = datetime.fromisoformat(dob_str).date()
                    age = calculate_age(dob_date)
                    st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
                except:
                    st.write("**2. Date of Birth:** " + dob_str)
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
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                if st.session_state.user_data.get('account_type') == 'Savings':
                    st.session_state.registration_step = 'account_type'
                else:
                    st.session_state.registration_step = 'annual_turnover'
                st.rerun()
        
        st.info("Please review your information before completing registration.")
        
        try:
            terms_file_path = os.path.join(os.path.dirname(__file__), "Terms&Conditions.txt")
            with open(terms_file_path, "r", encoding="utf-8") as f:
                terms_content = f.read()
        except:
            terms_content = "Terms and Conditions file not found. Please contact support."

        if 'terms_accepted' not in st.session_state:
            st.session_state.terms_accepted = False

        with st.expander("📋 Terms and Conditions For Data Sharing and Privacy", expanded=False):
            st.markdown(terms_content)
            st.markdown("---")
            st.session_state.terms_accepted = st.checkbox(
                "✅ I have read and agree to the Terms and Conditions and Privacy Policy",
                value=st.session_state.terms_accepted
            )
        
        if st.button("Complete Registration", type="primary", disabled=not st.session_state.terms_accepted):
            if not st.session_state.terms_accepted:
                st.error("⚠️ You must accept the Terms and Conditions.")
                st.stop()
            
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
                "terms_accepted": st.session_state.terms_accepted,
            }
            
            try:
                response = requests.post(FASTAPI_URL, json=final_data)
                if response.status_code == 200:
                    st.success("✅ User registered and onboarding started!")
                    st.json(response.json())
                    st.session_state.registration_step = 'basic_info'
                    st.session_state.user_data = {}
                    st.session_state.terms_accepted = False
                elif response.status_code == 409:
                    st.error("❌ Email already registered.")
                else:
                    st.error(f"❌ Error: {response.json().get('detail')}")
            except Exception as e:
                st.error(f"❌ Connection error: {e}")

# --- TAB 2: Admin Dashboard (UNCHANGED) ---
with tabs[1]:
    st.header("📊 Admin Dashboard")

    try:
        total_users = requests.get(f"{FASTAPI_URLS}/get-total-users").json().get("total_users", 0)
        verified_users = requests.get(f"{FASTAPI_URLS}/get-verified-users-count").json().get("verified_users_count", 0)
        pending_verification = requests.get(f"{FASTAPI_URLS}/get-pending-verification-count").json().get("pending_verification_count", 0)
        registered_today = requests.get(f"{FASTAPI_URLS}/registered-today").json().get("users_registered_today", 0)
        registered_this_week = requests.get(f"{FASTAPI_URLS}/regisetered-this-week").json().get("users_registered_this_week", 0)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.markdown(f"<div class='kpi-card' style='background-color:#007bff;'>👥 Total Users<div class='kpi-number'>{total_users}</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='kpi-card' style='background-color:#28a745;'>✅ Verified<div class='kpi-number'>{verified_users}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='kpi-card' style='background-color:#ffc107;'>⏳ Pending<div class='kpi-number'>{pending_verification}</div></div>", unsafe_allow_html=True)
        col4.markdown(f"<div class='kpi-card' style='background-color:#17a2b8;'>📅 Today<div class='kpi-number'>{registered_today}</div></div>", unsafe_allow_html=True)
        col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>🗓️ This Week<div class='kpi-number'>{registered_this_week}</div></div>", unsafe_allow_html=True)

        df_chart = pd.DataFrame({"Metric": ["Total Users", "Verified Users"], "Count": [total_users, verified_users]})
        fig = px.bar(df_chart, x="Metric", y="Count", color="Metric", title="📈 Users vs Verified Users", color_discrete_sequence=["#007bff", "#28a745"])
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Could not fetch KPIs: {e}")

    try:
        rows = supabase.table("users").select("*").execute().data
        for row in rows:
            step = row.get("onboarding_step", "welcome")
            if step == "welcome":
                status = "📩 Awaiting reply"
            elif step == "document_verification":
                status = "📄 Documents received"
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

# --- TAB 3: Conversations (UNCHANGED) ---
with tabs[2]:
    st.header("🗣️ User Conversations")
    email_filter = st.text_input("Search by Email")
    if email_filter:
        try:
            conversations = supabase.table("conversations").select("*").eq("user_email", email_filter).order("timestamp", desc=True).execute().data
            df = pd.DataFrame(conversations)
            if df.empty:
                st.info("No conversations found for this user.")
            else:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Error fetching conversations: {e}")

# --- TAB 4: Chat Assistant (NEW - INTEGRATED) ---
with tabs[3]:
    st.header("💬 Smart Chat Assistant")
    
    if 'chat_user_verified' not in st.session_state:
        st.session_state.chat_user_verified = False
    if 'chat_user_email' not in st.session_state:
        st.session_state.chat_user_email = ""
    if 'chat_messages' not in st.session_state:
        st.session_state.chat_messages = []
    if 'chat_input_key' not in st.session_state:
        st.session_state.chat_input_key = 0
    
    if not st.session_state.chat_user_verified:
        st.subheader("User Verification")
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                email_input = st.text_input("Enter your registered email address", key="chat_email_input")
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                verify_clicked = st.button("Verify", type="primary", key="chat_verify_btn")
            
            if verify_clicked and email_input:
                try:
                    response = requests.post(f"{FASTAPI_URLS}/chat/verify-user", json={"email": email_input})
                    if response.status_code == 200:
                        st.session_state.chat_user_verified = True
                        st.session_state.chat_user_email = email_input
                        st.session_state.chat_user_name = response.json().get("user_name", "User")
                        st.success(f"✅ Welcome, {st.session_state.chat_user_name}!")
                        
                        try:
                            history_response = requests.get(f"{FASTAPI_URLS}/chat/chat-history/{email_input}")
                            if history_response.status_code == 200:
                                conversations = history_response.json().get("conversations", [])
                                st.session_state.chat_messages = []
                                for conv in conversations:
                                    role = "user" if conv.get("role") == "user" else "assistant"
                                    message = conv.get("message", "")
                                    if message.startswith("[CHAT] "):
                                        message = message[7:]
                                    st.session_state.chat_messages.append({"role": role, "content": message})
                        except Exception as e:
                            st.warning(f"Could not load chat history: {e}")
                        
                        st.rerun()
                    else:
                        st.error("❌ Email not found. Please register first.")
                except Exception as e:
                    st.error(f"❌ Connection error: {e}")
            elif verify_clicked and not email_input:
                st.warning("Please enter your email address")
    
    else:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader(f"Chat with Thrivv Assistant")
        with col2:
            if st.button("🔄 New Session", key="new_chat_session"):
                st.session_state.chat_user_verified = False
                st.session_state.chat_messages = []
                st.session_state.chat_input_key += 1
                st.rerun()
        
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.chat_messages:
                if message["role"] == "user":
                    st.markdown(f'<div class="user-message"><div class="user-message-content">{message["content"]}</div></div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="assistant-message"><div class="assistant-message-content">{message["content"]}</div></div>', unsafe_allow_html=True)
        
        st.markdown("---")
        
        with st.form(key=f"chat_form_{st.session_state.chat_input_key}", clear_on_submit=True):
            user_input = st.text_input("Ask me anything about your onboarding...", placeholder="e.g., What documents do I need to submit?", key=f"chat_input_{st.session_state.chat_input_key}")
            
            col1, col2, col3 = st.columns([3, 1, 1])
            with col2:
                send_clicked = st.form_submit_button("Send", type="primary")
            
            if send_clicked and user_input.strip():
                st.session_state.chat_messages.append({"role": "user", "content": user_input})
                
                try:
                    with st.spinner("🤖 Thinking..."):
                        chat_response = requests.post(f"{FASTAPI_URLS}/chat/chat", json={"email": st.session_state.chat_user_email, "message": user_input})
                    
                    if chat_response.status_code == 200:
                        bot_response = chat_response.json().get("response", "")
                        st.session_state.chat_messages.append({"role": "assistant", "content": bot_response})
                        st.session_state.chat_input_key += 1
                        st.rerun()
                    else:
                        st.error(f"❌ Error: {chat_response.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    st.error(f"❌ Connection error: {e}")
        
        st.markdown("### Quick Questions")
        quick_questions = [
            "What documents do I need to submit?",
            "How long does verification take?",
            "Is a tenancy contract required?",
            "What are the account requirements?"
        ]
        
        cols = st.columns(2)
        for i, question in enumerate(quick_questions):
            with cols[i % 2]:
                if st.button(question, key=f"quick_{i}_{st.session_state.chat_input_key}"):
                    st.session_state.chat_messages.append({"role": "user", "content": question})
                    
                    try:
                        with st.spinner("🤖 Getting answer..."):
                            chat_response = requests.post(f"{FASTAPI_URLS}/chat/chat", json={"email": st.session_state.chat_user_email, "message": question})
                        
                        if chat_response.status_code == 200:
                            bot_response = chat_response.json().get("response", "")
                            st.session_state.chat_messages.append({"role": "assistant", "content": bot_response})
                            st.session_state.chat_input_key += 1
                            st.rerun()
                    except Exception as e:
                        st.error(f"Connection error: {e}")

# --- TAB 5: Document Upload (NEW - INTEGRATED) ---
with tabs[4]:
    st.header("📄 Document Upload")
    
    if 'doc_user_verified' not in st.session_state:
        st.session_state.doc_user_verified = False
    if 'doc_user_email' not in st.session_state:
        st.session_state.doc_user_email = ""
    if 'upload_success_message' not in st.session_state:
        st.session_state.upload_success_message = ""
    
    if not st.session_state.doc_user_verified:
        st.subheader("User Verification")
        with st.container():
            col1, col2 = st.columns([3, 1])
            with col1:
                email_input = st.text_input("Enter your registered email address", key="doc_email_input")
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                verify_clicked = st.button("Verify", type="primary", key="doc_verify_btn")
            
            if verify_clicked and email_input:
                try:
                    response = requests.post(f"{FASTAPI_URLS}/chat/verify-user", json={"email": email_input})
                    if response.status_code == 200:
                        st.session_state.doc_user_verified = True
                        st.session_state.doc_user_email = email_input
                        st.session_state.doc_user_name = response.json().get("user_name", "User")
                        st.success(f"✅ Welcome, {st.session_state.doc_user_name}!")
                        st.rerun()
                    else:
                        st.error("❌ Email not found. Please register first.")
                except Exception as e:
                    st.error(f"❌ Connection error: {e}")
            elif verify_clicked and not email_input:
                st.warning("Please enter your email address")
    
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader(f"Document Upload - {st.session_state.doc_user_name}")
        with col2:
            if st.button("🔄 Switch User", key="switch_doc_user"):
                st.session_state.doc_user_verified = False
                st.session_state.upload_success_message = ""
                st.rerun()
        
        if st.session_state.upload_success_message:
            st.success(st.session_state.upload_success_message)
            st.session_state.upload_success_message = ""
        
        with st.expander("📋 Current Document Status", expanded=True):
            try:
                status_response = requests.get(f"{FASTAPI_URLS}/chat/document-status/{st.session_state.doc_user_email}")
                if status_response.status_code == 200:
                    documents = status_response.json().get("documents", [])
                    
                    if documents:
                        for doc in documents:
                            status = doc.get("status", "unknown")
                            summary = doc.get("summary", "No summary available")
                            filename = doc.get("filename", "Unknown file")
                            
                            if status == "valid":
                                st.success(f"✅ **{filename}** - {summary}")
                                extracted = doc.get("extracted_fields", {})
                                if extracted:
                                    with st.expander(f"ℹ️ Information from {filename}"):
                                        for field, value in list(extracted.items())[:8]:
                                            st.write(f"**{field}:** {value}")
                            elif status == "warning":
                                st.warning(f"⚠️ **{filename}** - {summary}")
                                validation = doc.get("validation", {})
                                missing_fields = validation.get("missing_fields", [])
                                if missing_fields:
                                    st.write(f"Missing fields: {', '.join(missing_fields)}")
                            else:
                                st.error(f"❌ **{filename}** - {summary}")
                    else:
                        st.info("📥 No documents uploaded yet.")
            except Exception as e:
                st.error(f"Error loading document status: {e}")
        
        st.markdown("---")
        st.subheader("📤 Upload New Documents")
        
        st.info("""
📋 **Required Documents (All 4 needed):**
- Emirates ID (Resident Identity Card)
- Commercial Registration Document
- Tenancy Contract (Ejari)
- Memorandum of Association (MOA)

📸 **Upload Requirements:**
- Image files: PNG, JPG, JPEG, WEBP
- Or document files: PDF, DOCX
- Clear and readable
- All required fields visible

📧 **Email Notification:** You'll receive detailed results after processing
        """)
        
        uploaded_files = st.file_uploader("Choose document files", type=['png', 'jpg', 'jpeg', 'webp', 'pdf', 'docx'], accept_multiple_files=True, key="doc_uploader")
        
        if uploaded_files:
            st.write(f"📂 **Selected {len(uploaded_files)} file(s):**")
            for file in uploaded_files:
                file_size = file.size / 1024
                st.write(f"• {file.name} ({file_size:.1f} KB)")
            
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🚀 Upload and Process Documents", type="primary", key="upload_docs_btn"):
                    try:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        status_text.text("📤 Uploading documents...")
                        progress_bar.progress(25)
                        
                        files_data = []
                        for uploaded_file in uploaded_files:
                            files_data.append(("files", (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)))
                        
                        status_text.text("📄 Processing documents with OCR...")
                        progress_bar.progress(50)
                        
                        upload_response = requests.post(f"{FASTAPI_URLS}/chat/upload-documents", params={"email": st.session_state.doc_user_email}, files=files_data, timeout=300)
                        
                        progress_bar.progress(75)
                        status_text.text("📧 Sending email notification...")
                        
                        if upload_response.status_code == 200:
                            progress_bar.progress(100)
                            status_text.text("✅ Processing complete!")
                            
                            response_data = upload_response.json()
                            results = response_data.get("results", [])
                            
                            progress_bar.empty()
                            status_text.empty()
                            
                            st.subheader("📊 Upload Results")
                            
                            success_count = sum(1 for r in results if r.get("status") == "success")
                            warning_count = sum(1 for r in results if r.get("status") == "warning")
                            error_count = sum(1 for r in results if r.get("status") == "error")
                            
                            for result in results:
                                status = result.get("status", "unknown")
                                filename = result.get("filename", "Unknown")
                                summary = result.get("summary", "No summary")
                                
                                if status == "success":
                                    st.success(f"✅ **{filename}** - {summary}")
                                elif status == "warning":
                                    st.warning(f"⚠️ **{filename}** - {summary}")
                                else:
                                    st.error(f"❌ **{filename}** - {summary}")
                            
                            st.markdown("---")
                            st.info(f"📧 **Email notification sent!** Check your inbox for detailed status.")
                            st.write(f"**Summary:** {success_count} verified, {warning_count} need review, {error_count} rejected")
                            
                            st.session_state.upload_success_message = f"Documents processed! {success_count} verified, {warning_count} warnings, {error_count} errors"
                            
                            time.sleep(2)
                            st.rerun()
                        else:
                            progress_bar.empty()
                            status_text.empty()
                            st.error(f"❌ Upload failed: {upload_response.json().get('detail', 'Unknown error')}")
                    except requests.exceptions.Timeout:
                        st.error("❌ Upload timed out. Please try again with smaller files.")
                    except Exception as e:
                        st.error(f"❌ Upload error: {e}")