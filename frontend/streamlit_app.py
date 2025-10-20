# import os
# import streamlit as st
# import requests
# import pandas as pd
# import time
# from datetime import datetime, date
# from supabase import create_client
# import plotly.express as px
# from dotenv import load_dotenv  

# # Load environment variables
# load_dotenv()

# # --- CONFIG ---
# BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
# FASTAPI_URL = f"{BACKEND_URL}/register"
# FASTAPI_URLS = BACKEND_URL
# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

# # Add error checking
# if not SUPABASE_URL or not SUPABASE_KEY:
#     st.error("Supabase configuration not found. Please check your .env file.")
#     st.stop()

# supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# # --- UTILITY FUNCTIONS ---
# def calculate_age(birth_date):
#     """Calculate age from birth date"""
#     today = date.today()
#     return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

# def generate_doc_key(idx, doc_type, filename, member_name=None):
#     """Generate unique hash-based key for document"""
#     import hashlib
#     key_string = f"{idx}_{doc_type}_{filename}_{member_name or ''}"
#     return hashlib.md5(key_string.encode()).hexdigest()[:12]

# # --- PAGE SETTINGS ---
# st.set_page_config(page_title="Onboarding Agent", layout="wide")
# st.markdown(
#     """
#     <style>
#     /* General UI tweaks */
#     .main {
#         background-color: #f8f9fa;
#     }
#     /* KPI card style */
#     .kpi-card {
#         padding: 15px;
#         border-radius: 10px;
#         color: white;
#         text-align: center;
#         font-weight: bold;
#     }
#     .kpi-number {
#         font-size: 28px;
#         font-weight: 700;
#         margin-top: 5px;
#     }
#     /* Chat message styles */
#     .user-message {
#         display: flex;
#         justify-content: flex-end;
#         margin: 10px 0;
#     }
#     .user-message-content {
#         background-color: #007bff;
#         color: white;
#         padding: 10px 15px;
#         border-radius: 20px 20px 5px 20px;
#         max-width: 70%;
#         word-wrap: break-word;
#     }
#     .assistant-message {
#         display: flex;
#         justify-content: flex-start;
#         margin: 10px 0;
#     }
#     .assistant-message-content {
#         background-color: #f1f1f1;
#         color: #333;
#         padding: 10px 15px;
#         border-radius: 20px 20px 20px 5px;
#         max-width: 80%;
#         word-wrap: break-word;
#     }
#     </style>
#     """,
#     unsafe_allow_html=True
# )

# st.title("🧾 Onboarding Agent")

# tabs = st.tabs(["Register User", "Admin Dashboard", "Chat & Upload"])

# # --- TAB 1: Register User (UNCHANGED) ---
# with tabs[0]:
#     st.header("📬 Register a New User")
    
#     # Initialize session state for dynamic flow
#     if 'registration_step' not in st.session_state:
#         st.session_state.registration_step = 'basic_info'
#     if 'user_data' not in st.session_state:
#         st.session_state.user_data = {}
    
#     # Step 1: Basic Information
#     if st.session_state.registration_step == 'basic_info':
#         with st.form("basic_info_form"):
#             st.subheader("Basic Information")
            
#             name_value = st.session_state.user_data.get('name', '')
            
#             if st.session_state.user_data.get('dob'):
#                 try:
#                     dob_value = datetime.fromisoformat(st.session_state.user_data.get('dob')).date()
#                 except:
#                     dob_value = date(2000, 1, 1)
#             else:
#                 dob_value = date(2000, 1, 1)
            
#             phone_value = st.session_state.user_data.get('phone_number', '')
#             email_value = st.session_state.user_data.get('email', '')
#             business_value = st.session_state.user_data.get('business_name', '')
            
#             name = st.text_input("Full Name", value=name_value)
#             dob = st.date_input("Date of Birth", value=dob_value, min_value=date(1900, 1, 1), max_value=date.today())
#             phone_number = st.text_input("Phone Number", value=phone_value)
#             email = st.text_input("Email", value=email_value)
#             business_name = st.text_input("Business Name", value=business_value)
            
#             submitted = st.form_submit_button("Continue")
            
#             if submitted:
#                 if not all([name, phone_number, email, business_name]):
#                     st.warning("⚠️ Please fill all required fields.")
#                     st.stop()
                
#                 st.session_state.user_data.update({
#                     'name': name,
#                     'dob': dob.isoformat(),
#                     'phone_number': phone_number,
#                     'email': email,
#                     'business_name': business_name
#                 })
#                 st.session_state.registration_step = 'account_type'
#                 st.rerun()
    
#     # Step 2: Account Type Selection
#     # Step 2: Account Type Selection
#     elif st.session_state.registration_step == 'account_type':
#         st.subheader("Account Information")
        
#         # Previously answered questions
#         with st.expander("📋 Previously Answered Questions", expanded=True):
#             st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
#             dob_str = st.session_state.user_data.get('dob', '')
#             if dob_str:
#                 try:
#                     dob_date = datetime.fromisoformat(dob_str).date()
#                     age = calculate_age(dob_date)
#                     st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
#                 except:
#                     st.write("**2. Date of Birth:** " + dob_str)
#             st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
#             st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
#             st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
        
#         # Back button (outside form)
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             if st.button("⬅️ Back", key="account_type_back_btn"):
#                 st.session_state.registration_step = 'basic_info'
#                 st.rerun()
        
#         st.write("")  # Add spacing
        
#         # Form for account type
#         with st.form("account_type_form"):
#             st.markdown("### What kind of account do you want to open?")
            
#             # Get current selection
#             current_account_type = st.session_state.user_data.get('account_type', 'Savings')
#             account_type_options = ["Savings", "Corporate"]
            
#             # Find default index
#             try:
#                 default_index = account_type_options.index(current_account_type)
#             except ValueError:
#                 default_index = 0
            
#             # Radio buttons
#             account_type = st.radio(
#                 "Select your account type:",
#                 account_type_options,
#                 index=default_index,
#                 key="account_type_selection"
#             )
              
#             # Submit button
#             col1, col2, col3 = st.columns([1, 1, 1])
#             with col2:
#                 submitted = st.form_submit_button("✅ Continue", type="primary", use_container_width=True)
            
#             # Handle submission
#             if submitted:
#                 # Save to session state
#                 st.session_state.user_data['account_type'] = account_type
                
#                 # Determine next step
#                 if account_type == "Savings":
#                     # Savings goes directly to terms & conditions
#                     st.session_state.registration_step = 'final_confirmation'
#                     st.success("✅ Account type saved! Moving to Terms & Conditions...")
#                 elif account_type == "Corporate":
#                     # Corporate needs ownership type
#                     st.session_state.registration_step = 'ownership_type'
#                     st.success("✅ Account type saved! Moving to Ownership Type...")
                
#                 # Wait a moment for user to see the success message
#                 import time
#                 time.sleep(0.5)
                
#                 # Refresh page to show next step
#                 st.rerun()
    
#     # Step 3: Ownership Type (Only for Corporate)
#     elif st.session_state.registration_step == 'ownership_type':
#         st.subheader("Ownership Details")
        
#         with st.expander("📋 Previously Answered Questions", expanded=True):
#             st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
#             dob_str = st.session_state.user_data.get('dob', '')
#             if dob_str:
#                 try:
#                     dob_date = datetime.fromisoformat(dob_str).date()
#                     age = calculate_age(dob_date)
#                     st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
#                 except:
#                     st.write("**2. Date of Birth:** " + dob_str)
#             st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
#             st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
#             st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
#             st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
        
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             if st.button("⬅️ Back"):
#                 st.session_state.registration_step = 'account_type'
#                 st.rerun()
        
#         with st.form("ownership_type_form"):
#             current_ownership_type = st.session_state.user_data.get('ownership_type', 'Single Owner')
#             ownership_options = ["Single Owner", "Partnership"]
#             default_index = ownership_options.index(current_ownership_type) if current_ownership_type in ownership_options else 0
            
#             ownership_type = st.radio("Do you want to open a single owner or partnership account?", ownership_options, index=default_index)
#             submitted = st.form_submit_button("Continue")
            
#             if submitted:
#                 st.session_state.user_data['ownership_type'] = ownership_type
#                 if ownership_type == "Single Owner":
#                     st.session_state.registration_step = 'annual_turnover'
#                 else:
#                     st.session_state.registration_step = 'partnership_details'
#                 st.rerun()
    
#     # Step 4: Partnership Details
#     elif st.session_state.registration_step == 'partnership_details':
#         st.subheader("Partnership Information")
        
#         with st.expander("📋 Previously Answered Questions", expanded=True):
#             st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
#             dob_str = st.session_state.user_data.get('dob', '')
#             if dob_str:
#                 try:
#                     dob_date = datetime.fromisoformat(dob_str).date()
#                     age = calculate_age(dob_date)
#                     st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
#                 except:
#                     st.write("**2. Date of Birth:** " + dob_str)
#             st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
#             st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
#             st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
#             st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
#             st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
        
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             if st.button("⬅️ Back"):
#                 st.session_state.registration_step = 'ownership_type'
#                 st.rerun()
        
#         with st.form("partnership_details_form"):
#             current_partnership = st.session_state.user_data.get('partnership_details', 'All shareholders are individual persons')
#             partnership_options = [
#                 "All shareholders are individual persons",
#                 "One or more shareholders are companies or other legal entities"
#             ]
#             default_index = partnership_options.index(current_partnership) if current_partnership in partnership_options else 0
            
#             partnership_details = st.radio("Are all shareholders in your business individual persons or not?", partnership_options, index=default_index)
#             submitted = st.form_submit_button("Continue")
            
#             if submitted:
#                 st.session_state.user_data['partnership_details'] = partnership_details
#                 st.session_state.registration_step = 'annual_turnover'
#                 st.rerun()
    
#     # Step 5: Annual Turnover
#     elif st.session_state.registration_step == 'annual_turnover':
#         st.subheader("Financial Information")
        
#         with st.expander("📋 Previously Answered Questions", expanded=True):
#             st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
#             dob_str = st.session_state.user_data.get('dob', '')
#             if dob_str:
#                 try:
#                     dob_date = datetime.fromisoformat(dob_str).date()
#                     age = calculate_age(dob_date)
#                     st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
#                 except:
#                     st.write("**2. Date of Birth:** " + dob_str)
#             st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
#             st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
#             st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
#             st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
#             if st.session_state.user_data.get('ownership_type'):
#                 st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
#             if st.session_state.user_data.get('partnership_details'):
#                 st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
        
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             if st.button("⬅️ Back"):
#                 if st.session_state.user_data.get('ownership_type') == 'Partnership':
#                     st.session_state.registration_step = 'partnership_details'
#                 else:
#                     st.session_state.registration_step = 'ownership_type'
#                 st.rerun()
        
#         with st.form("annual_turnover_form"):
#             annual_turnover = st.text_input("What is your expected annual turnover?", value=st.session_state.user_data.get('annual_turnover', ''))
#             submitted = st.form_submit_button("Continue")
            
#             if submitted:
#                 if not annual_turnover:
#                     st.warning("⚠️ Please provide your expected annual turnover.")
#                 else:
#                     st.session_state.user_data['annual_turnover'] = annual_turnover
#                     st.session_state.registration_step = 'final_confirmation'
#                     st.rerun()
    
#     # Step 6: Final Confirmation
#     elif st.session_state.registration_step == 'final_confirmation':
#         st.subheader("Final Confirmation")
        
#         with st.expander("📋 Previously Answered Questions", expanded=True):
#             st.write("**1. Full Name:** " + st.session_state.user_data.get('name', ''))
#             dob_str = st.session_state.user_data.get('dob', '')
#             if dob_str:
#                 try:
#                     dob_date = datetime.fromisoformat(dob_str).date()
#                     age = calculate_age(dob_date)
#                     st.write(f"**2. Date of Birth:** {dob_str} (Age: {age} years)")
#                 except:
#                     st.write("**2. Date of Birth:** " + dob_str)
#             st.write("**3. Phone Number:** " + st.session_state.user_data.get('phone_number', ''))
#             st.write("**4. Email:** " + st.session_state.user_data.get('email', ''))
#             st.write("**5. Business Name:** " + st.session_state.user_data.get('business_name', ''))
#             st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
#             if st.session_state.user_data.get('ownership_type'):
#                 st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
#             if st.session_state.user_data.get('partnership_details'):
#                 st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
#             if st.session_state.user_data.get('annual_turnover'):
#                 st.write("**9. Expected Annual Turnover:** " + st.session_state.user_data.get('annual_turnover', ''))
        
#         col1, col2 = st.columns([1, 4])
#         with col1:
#             if st.button("⬅️ Back"):
#                 if st.session_state.user_data.get('account_type') == 'Savings':
#                     st.session_state.registration_step = 'account_type'
#                 else:
#                     st.session_state.registration_step = 'annual_turnover'
#                 st.rerun()
        
#         st.info("Please review your information before completing registration.")
        
#         try:
#             terms_file_path = os.path.join(os.path.dirname(__file__), "Terms&Conditions.txt")
#             with open(terms_file_path, "r", encoding="utf-8") as f:
#                 terms_content = f.read()
#         except:
#             terms_content = "Terms and Conditions file not found. Please contact support."

#         if 'terms_accepted' not in st.session_state:
#             st.session_state.terms_accepted = False

#         with st.expander("📋 Terms and Conditions For Data Sharing and Privacy", expanded=False):
#             st.markdown(terms_content)
#             st.markdown("---")
#             st.session_state.terms_accepted = st.checkbox(
#                 "✅ I have read and agree to the Terms and Conditions and Privacy Policy",
#                 value=st.session_state.terms_accepted
#             )
        
#         if st.button("Complete Registration", type="primary", disabled=not st.session_state.terms_accepted):
#             if not st.session_state.terms_accepted:
#                 st.error("⚠️ You must accept the Terms and Conditions.")
#                 st.stop()
            
#             final_data = {
#                 "name": st.session_state.user_data['name'],
#                 "dob": st.session_state.user_data['dob'],
#                 "phone_number": st.session_state.user_data['phone_number'],
#                 "email": st.session_state.user_data['email'],
#                 "business_name": st.session_state.user_data['business_name'],
#                 "account_type": st.session_state.user_data['account_type'],
#                 "ownership_type": st.session_state.user_data.get('ownership_type'),
#                 "partnership_details": st.session_state.user_data.get('partnership_details'),
#                 "annual_turnover": st.session_state.user_data.get('annual_turnover'),
#                 "terms_accepted": st.session_state.terms_accepted,
#             }
            
#             try:
#                 response = requests.post(FASTAPI_URL, json=final_data)
#                 if response.status_code == 200:
#                     st.success("✅ User registered and onboarding started!")
#                     st.json(response.json())
#                     st.session_state.registration_step = 'basic_info'
#                     st.session_state.user_data = {}
#                     st.session_state.terms_accepted = False
#                 elif response.status_code == 409:
#                     st.error("❌ Email already registered.")
#                 else:
#                     st.error(f"❌ Error: {response.json().get('detail')}")
#             except Exception as e:
#                 st.error(f"❌ Connection error: {e}")

# # --- TAB 2: Admin Dashboard (UNCHANGED) ---
# with tabs[1]:
#     st.header("📊 Admin Dashboard")

#     try:
#         total_users = requests.get(f"{FASTAPI_URLS}/get-total-users").json().get("total_users", 0)
#         verified_users = requests.get(f"{FASTAPI_URLS}/get-verified-users-count").json().get("verified_users_count", 0)
#         pending_verification = requests.get(f"{FASTAPI_URLS}/get-pending-verification-count").json().get("pending_verification_count", 0)
#         registered_today = requests.get(f"{FASTAPI_URLS}/registered-today").json().get("users_registered_today", 0)
#         registered_this_week = requests.get(f"{FASTAPI_URLS}/regisetered-this-week").json().get("users_registered_this_week", 0)

#         col1, col2, col3, col4, col5 = st.columns(5)
#         col1.markdown(f"<div class='kpi-card' style='background-color:#007bff;'>👥 Total Users<div class='kpi-number'>{total_users}</div></div>", unsafe_allow_html=True)
#         col2.markdown(f"<div class='kpi-card' style='background-color:#28a745;'>✅ Verified<div class='kpi-number'>{verified_users}</div></div>", unsafe_allow_html=True)
#         col3.markdown(f"<div class='kpi-card' style='background-color:#ffc107;'>⏳ Pending<div class='kpi-number'>{pending_verification}</div></div>", unsafe_allow_html=True)
#         col4.markdown(f"<div class='kpi-card' style='background-color:#17a2b8;'>📅 Today<div class='kpi-number'>{registered_today}</div></div>", unsafe_allow_html=True)
#         col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>🗓️ This Week<div class='kpi-number'>{registered_this_week}</div></div>", unsafe_allow_html=True)

#         df_chart = pd.DataFrame({"Metric": ["Total Users", "Verified Users"], "Count": [total_users, verified_users]})
#         fig = px.bar(df_chart, x="Metric", y="Count", color="Metric", title="📈 Users vs Verified Users", color_discrete_sequence=["#007bff", "#28a745"])
#         st.plotly_chart(fig, use_container_width=True)
#     except Exception as e:
#         st.error(f"Could not fetch KPIs: {e}")

#     try:
#         rows = supabase.table("users").select("*").execute().data
#         for row in rows:
#             step = row.get("onboarding_step", "welcome")
#             if step == "welcome":
#                 status = "📩 Awaiting reply"
#             elif step == "document_verification":
#                 status = "📄 Documents received"
#             elif step == "verification_complete":
#                 status = "✅ Onboarding complete"
#             else:
#                 status = "⏳ In progress"
#             row["status"] = status
#         df = pd.DataFrame(rows)
#         st.subheader("📜 User Table")
#         st.dataframe(df, use_container_width=True)
#     except Exception as e:
#         st.error(f"Could not fetch users: {e}")
        
# # --- TAB 3: CONVERSATIONAL AI ONBOARDING ---
# with tabs[2]:
#     st.header("💬 AI Onboarding Assistant")
    
#     # ============================================================================
#     # CUSTOM CSS
#     # ============================================================================
#     st.markdown("""
#     <style>
#     .user-message {
#         background: #007bff;
#         color: white;
#         padding: 12px 16px;
#         border-radius: 18px 18px 5px 18px;
#         margin: 10px 0 10px auto;
#         max-width: 65%;
#         display: block;
#         text-align: left;
#         word-wrap: break-word;
#         margin-left: 35%;
#     }
#     .assistant-message {
#         background: #e9ecef;
#         color: #333;
#         padding: 12px 16px;
#         border-radius: 18px 18px 18px 5px;
#         margin: 10px 0;
#         max-width: 65%;
#         display: block;
#         word-wrap: break-word;
#         white-space: pre-wrap;
#         margin-right: 35%;
#     }
#     .system-message {
#         background: #d4edda;
#         color: #155724;
#         border: 1px solid #c3e6cb;
#         padding: 12px 16px;
#         border-radius: 8px;
#         margin: 10px 15%;
#         text-align: center;
#         clear: both;
#     }
#     .file-upload-message {
#         background: #fff3cd;
#         color: #856404;
#         border: 1px solid #ffeaa7;
#         padding: 12px 16px;
#         border-radius: 18px 18px 5px 18px;
#         margin: 10px 0 10px auto;
#         max-width: 65%;
#         display: block;
#         margin-left: 35%;
#     }
#     </style>
#     """, unsafe_allow_html=True)
    
#     # ============================================================================
#     # SESSION STATE INITIALIZATION
#     # ============================================================================
#     ss = st.session_state
#     ss.setdefault("cu_auth", False)
#     ss.setdefault("cu_email", None)
#     ss.setdefault("cu_user", {})
#     ss.setdefault("cu_msgs", [])
#     ss.setdefault("cu_ready", False)
#     ss.setdefault("cu_processing", False)
#     ss.setdefault("cu_chat_key", 0)
#     ss.setdefault("cu_awaiting_verification", False)
#     ss.setdefault("cu_last_uploaded_doc", None)
#     ss.setdefault("cu_conversation_started", False)
#     ss.setdefault("cu_member_name_input", "")  # ✅ ADDED THIS LINE

#     # ============================================================================
#     # STEP 1: USER AUTHENTICATION
#     # ============================================================================
#     if not ss.cu_auth:
#         st.subheader("🔐 User Authentication")
#         st.info("✉️ Enter your registered email to continue")
        
#         col1, col2 = st.columns([3, 1])
#         with col1:
#             email_in = st.text_input(
#                 "📧 Email", 
#                 key="cu_email_input", 
#                 placeholder="your.email@example.com"
#             )
#         with col2:
#             st.markdown("<br>", unsafe_allow_html=True)
#             go = st.button("✅ Verify", type="primary", use_container_width=True)
        
#         if go and email_in:
#             try:
#                 r = supabase.table("users").select("*").eq("email", email_in).execute()
#                 if r.data:
#                     ss.cu_auth = True
#                     ss.cu_email = email_in
#                     ss.cu_user = r.data[0]
#                     st.success(f"✅ Welcome, {ss.cu_user.get('name','User')}!")
#                     time.sleep(0.6)
#                     st.rerun()
#                 else:
#                     st.error("❌ Email not found")
#             except Exception as e:
#                 st.error(f"❌ Error: {e}")
#         elif go:
#             st.warning("⚠️ Please enter your email")
#         st.stop()

#     # ============================================================================
#     # STEP 2: AUTHENTICATED USER INTERFACE
#     # ============================================================================
    
#     # Header
#     colh1, colh2 = st.columns([3, 1])
#     with colh1:
#         st.subheader(f"👤 {ss.cu_user.get('name','User')} - AI Onboarding")
#     with colh2:
#         if st.button("🔄 Switch User", key="cu_switch_user"):
#             for key in list(ss.keys()):
#                 if key.startswith('cu_'):
#                     del ss[key]
#             st.rerun()

#     # User info cards
#     c1, c2, c3 = st.columns(3)
#     c1.info(f"💼 Account: {ss.cu_user.get('account_type','N/A')}")
#     c2.info(f"👥 Ownership: {ss.cu_user.get('ownership_type','N/A')}")
#     c3.info(f"🏢 Business: {ss.cu_user.get('business_name','N/A')}")

#     st.markdown("---")

#     # ============================================================================
#     # STEP 3: INITIALIZE CONVERSATION (ONCE)
#     # ============================================================================
#     if not ss.cu_conversation_started:
#         try:
#             # Get initial status and welcome message
#             status_resp = requests.post(
#                 f"{BACKEND_URL}/chatupload/start-conversation",
#                 json={"email": ss.cu_email},
#                 timeout=10
#             )
            
#             if status_resp.status_code == 200:
#                 data = status_resp.json()
#                 welcome_msg = data.get("welcome_message", "Welcome! Let's start your onboarding.")
                
#                 ss.cu_msgs.append({
#                     "role": "assistant",
#                     "content": welcome_msg,
#                     "timestamp": datetime.now().isoformat()
#                 })
#                 ss.cu_conversation_started = True
#                 ss.cu_ready = True
#             else:
#                 st.error("❌ Could not start conversation")
#                 st.stop()
                
#         except Exception as e:
#             st.error(f"❌ Connection error: {e}")
#             st.stop()

#     # ============================================================================
#     # STEP 4: CHAT DISPLAY (FULL WIDTH)
#     # ============================================================================
    
#     st.markdown("### 💬 Conversation")
    
#     chat_container = st.container(height=500)
#     with chat_container:
#         for msg in ss.cu_msgs:
#             role = msg.get("role")
#             content = msg.get("content", "")
            
#             if role == "user":
#                 st.markdown(f"<div class='user-message'>{content}</div>", unsafe_allow_html=True)
            
#             elif role == "assistant":
#                 # Clean HTML tags if present
#                 if "<" in content and ">" in content:
#                     import re
#                     content = re.sub('<[^<]+?>', '', content)
#                 st.markdown(f"<div class='assistant-message'>{content}</div>", unsafe_allow_html=True)
            
#             elif role == "system":
#                 st.markdown(f"<div class='system-message'>{content}</div>", unsafe_allow_html=True)
            
#             elif role == "file_upload":
#                 st.markdown(f"<div class='file-upload-message'>📎 {content}</div>", unsafe_allow_html=True)
        
#         # Clear floats
#         st.markdown("<div style='clear:both;'></div>", unsafe_allow_html=True)

#     st.markdown("---")

#     # ============================================================================
#     # STEP 5: FILE UPLOAD SECTION
#     # ============================================================================
    
#     st.markdown("### 📤 Upload Document")
    
#     col1, col2 = st.columns([3, 1])
    
#     with col1:
#         uploaded_file = st.file_uploader(
#             "📎 Select document to upload",
#             type=["pdf", "png", "jpg", "jpeg", "webp", "docx"],
#             key=f"cu_file_uploader_{ss.cu_chat_key}",
#             disabled=ss.cu_processing,
#             label_visibility="collapsed"
#         )
    
#     with col2:
#         upload_btn = st.button(
#             "🚀 Upload",
#             type="primary",
#             use_container_width=True,
#             disabled=not uploaded_file or ss.cu_processing
#         )
    
#     # Handle file upload
#     if upload_btn and uploaded_file and not ss.cu_processing:
#         ss.cu_processing = True
        
#         # Add file upload message to chat
#         ss.cu_msgs.append({
#             "role": "file_upload",
#             "content": f"Uploaded: {uploaded_file.name}",
#             "timestamp": datetime.now().isoformat()
#         })
        
#         with st.spinner("⏳ Processing document..."):
#             try:
#                 # Prepare upload with member_name if applicable
#                 files = [("files", (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type))]
#                 data = {"email": ss.cu_email}
                
#                 # CRITICAL: Include member_name from session state
#                 if ss.cu_member_name_input:
#                     data["member_name"] = ss.cu_member_name_input
#                     print(f"[DEBUG] Uploading for member: {ss.cu_member_name_input}")
                
#                 # Upload to backend
#                 upload_resp = requests.post(
#                     f"{BACKEND_URL}/chatupload/upload-conversational",
#                     data=data,
#                     files=files,
#                     timeout=600
#                 )
                
#                 if upload_resp.status_code == 200:
#                     result = upload_resp.json()
                    
#                     # Get AI response with extracted data
#                     ai_response = result.get("message", "Document processed successfully!")
#                     is_complete = result.get("is_complete", False)
#                     awaiting_verification = result.get("awaiting_verification", False)
                    
#                     # Add AI response to chat
#                     ss.cu_msgs.append({
#                         "role": "assistant",
#                         "content": ai_response,
#                         "timestamp": datetime.now().isoformat()
#                     })
                    
#                     # Update state
#                     ss.cu_awaiting_verification = awaiting_verification
#                     ss.cu_last_uploaded_doc = result.get("document_type")
                    
#                     # Check if onboarding complete
#                     if is_complete:
#                         st.balloons()
#                         ss.cu_msgs.append({
#                             "role": "system",
#                             "content": "🎉 Onboarding Complete! Your account will be activated within 3-4 business days.",
#                             "timestamp": datetime.now().isoformat()
#                         })
                    
#                     ss.cu_processing = False
#                     ss.cu_chat_key += 1
#                     time.sleep(0.5)
#                     st.rerun()
                
#                 else:
#                     ss.cu_processing = False
#                     error_msg = upload_resp.json().get("detail", "Upload failed")
#                     st.error(f"❌ {error_msg}")
                    
#                     ss.cu_msgs.append({
#                         "role": "assistant",
#                         "content": f"Sorry, there was an error processing your document: {error_msg}\n\nPlease try uploading again or contact support.",
#                         "timestamp": datetime.now().isoformat()
#                     })
                    
#             except Exception as e:
#                 ss.cu_processing = False
#                 st.error(f"❌ Error: {e}")
                
#                 ss.cu_msgs.append({
#                     "role": "assistant",
#                     "content": f"Sorry, I encountered an error: {str(e)}\n\nPlease try again.",
#                     "timestamp": datetime.now().isoformat()
#                 })

#     st.markdown("---")

#     # ============================================================================
#     # STEP 6: CHAT INPUT (TEXT MESSAGES)
#     # ============================================================================
    
#     st.markdown("### 💬 Send Message")
    
#     with st.form(key=f"cu_chat_form_{ss.cu_chat_key}", clear_on_submit=True):
#         col1, col2 = st.columns([5, 1])
        
#         with col1:
#             user_input = st.text_input(
#                 "Type your message...",
#                 key=f"cu_chat_input_{ss.cu_chat_key}",
#                 placeholder="Type 'verified' to confirm, or ask me anything...",
#                 label_visibility="collapsed",
#                 disabled=ss.cu_processing
#             )
        
#         with col2:
#             send_btn = st.form_submit_button(
#                 "📤 Send",
#                 type="primary",
#                 use_container_width=True,
#                 disabled=ss.cu_processing
#             )
    
#     # Handle chat message
#     if send_btn and user_input.strip() and not ss.cu_processing:
#         ss.cu_processing = True
        
#         # Add user message to chat
#         ss.cu_msgs.append({
#             "role": "user",
#             "content": user_input,
#             "timestamp": datetime.now().isoformat()
#         })
        
#         try:
#             with st.spinner("💭 Thinking..."):
#                 # Send message to backend
#                 chat_resp = requests.post(
#                     f"{BACKEND_URL}/chatupload/chat-conversational",
#                     json={
#                         "email": ss.cu_email,
#                         "message": user_input,
#                         "chat_history": ss.cu_msgs[-10:]
#                     },
#                     timeout=45
#                 )
                
#                 if chat_resp.status_code == 200:
#                     data = chat_resp.json()
#                     ai_response = data.get("response", "")
#                     is_complete = data.get("is_complete", False)
#                     verification_accepted = data.get("verification_accepted", False)
                    
#                     # Add AI response
#                     ss.cu_msgs.append({
#                         "role": "assistant",
#                         "content": ai_response,
#                         "timestamp": datetime.now().isoformat()
#                     })
                    
#                     # Update verification state
#                     if verification_accepted:
#                         ss.cu_awaiting_verification = False
#                         ss.cu_last_uploaded_doc = None
                    
#                     # Check if complete
#                     if is_complete:
#                         st.balloons()
#                         ss.cu_msgs.append({
#                             "role": "system",
#                             "content": "🎉 Onboarding Complete! Your account will be activated within 3-4 business days.",
#                             "timestamp": datetime.now().isoformat()
#                         })
                    
#                     ss.cu_processing = False
#                     ss.cu_chat_key += 1
#                     st.rerun()
                
#                 else:
#                     ss.cu_processing = False
#                     st.error(f"❌ Chat error: {chat_resp.status_code}")
                    
#         except requests.exceptions.Timeout:
#             ss.cu_processing = False
#             st.error("⏰ Request timed out. Please try again.")
#         except Exception as e:
#             ss.cu_processing = False
#             st.error(f"❌ Error: {e}")

#     # ============================================================================
#     # STEP 7: ACTION BUTTONS
#     # ============================================================================
    
#     st.markdown("---")
    
#     col1, col2, col3 = st.columns(3)
    
#     with col1:
#         if st.button("🗑️ Clear Chat", use_container_width=True, disabled=ss.cu_processing):
#             ss.cu_msgs = []
#             ss.cu_conversation_started = False
#             ss.cu_awaiting_verification = False
#             ss.cu_last_uploaded_doc = None
#             ss.cu_chat_key += 1
#             st.rerun()
    
#     with col2:
#         if st.button("🔄 Refresh", use_container_width=True, disabled=ss.cu_processing):
#             st.rerun()
    
#     with col3:
#         if st.button("❓ Help", use_container_width=True, disabled=ss.cu_processing):
#             help_msg = """I can help you with:
            
# • Uploading documents (EID, Commercial License, MOA, Ejari)
# • Verifying extracted information
# • Answering questions about your onboarding
# • Tracking your progress

# Just upload a document or ask me anything!"""
            
#             ss.cu_msgs.append({
#                 "role": "assistant",
#                 "content": help_msg,
#                 "timestamp": datetime.now().isoformat()
#             })
#             st.rerun()

## ------------Pages Method--------------##

import os
import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, date
from supabase import create_client
import plotly.express as px
from dotenv import load_dotenv
import hashlib
import re

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

# --- PAGE SETTINGS ---
st.set_page_config(
    page_title="Onboarding Agent",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CUSTOM CSS ---
st.markdown(
    """
    <style>
    /* General UI tweaks */
    .main {
        background-color: #f8f9fa;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #2c3e50;
    }
    
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: white;
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
        background: #007bff;
        color: white;
        padding: 12px 16px;
        border-radius: 18px 18px 5px 18px;
        margin: 10px 0 10px auto;
        max-width: 65%;
        display: block;
        text-align: left;
        word-wrap: break-word;
        margin-left: 35%;
    }
    .assistant-message {
        background: #e9ecef;
        color: #333;
        padding: 12px 16px;
        border-radius: 18px 18px 18px 5px;
        margin: 10px 0;
        max-width: 65%;
        display: block;
        word-wrap: break-word;
        white-space: pre-wrap;
        margin-right: 35%;
    }
    .system-message {
        background: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
        padding: 12px 16px;
        border-radius: 8px;
        margin: 10px 15%;
        text-align: center;
        clear: both;
    }
    .file-upload-message {
        background: #fff3cd;
        color: #856404;
        border: 1px solid #ffeaa7;
        padding: 12px 16px;
        border-radius: 18px 18px 5px 18px;
        margin: 10px 0 10px auto;
        max-width: 65%;
        display: block;
        margin-left: 35%;
    }
    
    /* Document details card */
    .doc-details-card {
        background: #fafafa;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
    }
    
    /* Optimize loading */
    .stApp {
        transition: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- UTILITY FUNCTIONS ---
@st.cache_data(ttl=600)
def calculate_age(birth_date):
    """Calculate age from birth date"""
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

def generate_doc_key(idx, doc_type, filename, member_name=None):
    """Generate unique hash-based key for document"""
    key_string = f"{idx}_{doc_type}_{filename}_{member_name or ''}"
    return hashlib.md5(key_string.encode()).hexdigest()[:12]

@st.cache_data(ttl=60)
def fetch_dashboard_metrics():
    """Fetch dashboard metrics with caching"""
    try:
        metrics = {}
        metrics['total_users'] = requests.get(f"{FASTAPI_URLS}/get-total-users").json().get("total_users", 0)
        metrics['verified_users'] = requests.get(f"{FASTAPI_URLS}/get-verified-users-count").json().get("verified_users_count", 0)
        metrics['pending_verification'] = requests.get(f"{FASTAPI_URLS}/get-pending-verification-count").json().get("pending_verification_count", 0)
        metrics['registered_today'] = requests.get(f"{FASTAPI_URLS}/registered-today").json().get("users_registered_today", 0)
        metrics['registered_this_week'] = requests.get(f"{FASTAPI_URLS}/regisetered-this-week").json().get("users_registered_this_week", 0)
        return metrics
    except:
        return None

@st.cache_data(ttl=60)
def fetch_users_data():
    """Fetch users data with caching"""
    try:
        return supabase.table("users").select("*").execute().data
    except:
        return []

# --- SESSION STATE INITIALIZATION ---
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'registration_step': 'basic_info',
        'user_data': {},
        'terms_accepted': False,
        'cu_auth': False,
        'cu_email': None,
        'cu_user': {},
        'cu_msgs': [],
        'cu_ready': False,
        'cu_processing': False,
        'cu_chat_key': 0,
        'cu_awaiting_verification': False,
        'cu_last_uploaded_doc': None,
        'cu_conversation_started': False,
        'cu_member_name_input': "",
        'cu_completion_email_sent': False
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Initialize session state
init_session_state()

# --- SIDEBAR NAVIGATION ---
st.sidebar.title("🧾 Onboarding Agent")
st.sidebar.markdown("---")

# Navigation
page = st.sidebar.radio(
    "Navigate to:",
    ["📬 Register User", "📊 Admin Dashboard", "💬 AI Assistant"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

# --- REGISTER USER PAGE ---
if page == "📬 Register User":
    st.title("📬 Register a New User")
    
    # STEP 1: BASIC INFORMATION
    if st.session_state.registration_step == 'basic_info':
        with st.form("basic_info_form"):
            st.subheader("Basic Information")
            
            # Get existing values from session state
            name_value = st.session_state.user_data.get('name', '')
            
            if st.session_state.user_data.get('dob'):
                try:
                    dob_value = datetime.fromisoformat(
                        st.session_state.user_data.get('dob')
                    ).date()
                except:
                    dob_value = date(2000, 1, 1)
            else:
                dob_value = date(2000, 1, 1)
            
            phone_value = st.session_state.user_data.get('phone_number', '')
            email_value = st.session_state.user_data.get('email', '')
            business_value = st.session_state.user_data.get('business_name', '')
            
            # Form inputs
            name = st.text_input("Full Name", value=name_value)
            dob = st.date_input(
                "Date of Birth", 
                value=dob_value, 
                min_value=date(1900, 1, 1), 
                max_value=date.today()
            )
            phone_number = st.text_input("Phone Number", value=phone_value)
            email = st.text_input("Email", value=email_value)
            business_name = st.text_input("Business Name", value=business_value)
            
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                if not all([name, phone_number, email, business_name]):
                    st.warning("⚠️ Please fill all required fields.")
                    st.stop()
                
                # Save to session state
                st.session_state.user_data.update({
                    'name': name,
                    'dob': dob.isoformat(),
                    'phone_number': phone_number,
                    'email': email,
                    'business_name': business_name
                })
                st.session_state.registration_step = 'account_type'
                st.rerun()

    # STEP 2: ACCOUNT TYPE SELECTION
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
                submitted = st.form_submit_button(
                    "✅ Continue", 
                    type="primary", 
                    use_container_width=True
                )
            
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
                time.sleep(0.5)
                
                # Refresh page to show next step
                st.rerun()
    
    # STEP 3: OWNERSHIP TYPE (ONLY FOR CORPORATE)
    elif st.session_state.registration_step == 'ownership_type':
        st.subheader("Ownership Details")
        
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
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'account_type'
                st.rerun()
        
        # Form for ownership type
        with st.form("ownership_type_form"):
            current_ownership_type = st.session_state.user_data.get(
                'ownership_type', 
                'Single Owner'
            )
            ownership_options = ["Single Owner", "Partnership"]
            default_index = ownership_options.index(
                current_ownership_type
            ) if current_ownership_type in ownership_options else 0
            
            ownership_type = st.radio(
                "Do you want to open a single owner or partnership account?", 
                ownership_options, 
                index=default_index
            )
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                st.session_state.user_data['ownership_type'] = ownership_type
                if ownership_type == "Single Owner":
                    st.session_state.registration_step = 'annual_turnover'
                else:
                    st.session_state.registration_step = 'partnership_details'
                st.rerun()
    
    # STEP 4: PARTNERSHIP DETAILS
    elif st.session_state.registration_step == 'partnership_details':
        st.subheader("Partnership Information")
        
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
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                st.session_state.registration_step = 'ownership_type'
                st.rerun()
        
        # Form for partnership details
        with st.form("partnership_details_form"):
            current_partnership = st.session_state.user_data.get(
                'partnership_details', 
                'All shareholders are individual persons'
            )
            partnership_options = [
                "All shareholders are individual persons",
                "One or more shareholders are companies or other legal entities"
            ]
            default_index = partnership_options.index(
                current_partnership
            ) if current_partnership in partnership_options else 0
            
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
    
    # STEP 5: ANNUAL TURNOVER
    elif st.session_state.registration_step == 'annual_turnover':
        st.subheader("Financial Information")
        
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
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            
            if st.session_state.user_data.get('ownership_type'):
                st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
            if st.session_state.user_data.get('partnership_details'):
                st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                if st.session_state.user_data.get('ownership_type') == 'Partnership':
                    st.session_state.registration_step = 'partnership_details'
                else:
                    st.session_state.registration_step = 'ownership_type'
                st.rerun()
        
        # Form for annual turnover
        with st.form("annual_turnover_form"):
            annual_turnover = st.text_input(
                "What is your expected annual turnover?", 
                value=st.session_state.user_data.get('annual_turnover', '')
            )
            submitted = st.form_submit_button("Continue")
            
            if submitted:
                if not annual_turnover:
                    st.warning("⚠️ Please provide your expected annual turnover.")
                else:
                    st.session_state.user_data['annual_turnover'] = annual_turnover
                    st.session_state.registration_step = 'final_confirmation'
                    st.rerun()
    
    # STEP 6: FINAL CONFIRMATION
    elif st.session_state.registration_step == 'final_confirmation':
        st.subheader("Final Confirmation")
        
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
            st.write("**6. Account Type:** " + st.session_state.user_data.get('account_type', ''))
            
            if st.session_state.user_data.get('ownership_type'):
                st.write("**7. Ownership Type:** " + st.session_state.user_data.get('ownership_type', ''))
            if st.session_state.user_data.get('partnership_details'):
                st.write("**8. Partnership Details:** " + st.session_state.user_data.get('partnership_details', ''))
            if st.session_state.user_data.get('annual_turnover'):
                st.write("**9. Expected Annual Turnover:** " + st.session_state.user_data.get('annual_turnover', ''))
        
        # Back button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back"):
                if st.session_state.user_data.get('account_type') == 'Savings':
                    st.session_state.registration_step = 'account_type'
                else:
                    st.session_state.registration_step = 'annual_turnover'
                st.rerun()
        
        st.info("Please review your information before completing registration.")
        
        # Load terms and conditions
        try:
            terms_file_path = os.path.join(
                os.path.dirname(__file__), 
                "Terms&Conditions.txt"
            )
            with open(terms_file_path, "r", encoding="utf-8") as f:
                terms_content = f.read()
        except:
            terms_content = "Terms and Conditions file not found. Please contact support."

        # Terms and conditions expander
        with st.expander("📋 Terms and Conditions For Data Sharing and Privacy", expanded=False):
            st.markdown(terms_content)
            st.markdown("---")
            st.session_state.terms_accepted = st.checkbox(
                "✅ I have read and agree to the Terms and Conditions and Privacy Policy",
                value=st.session_state.terms_accepted
            )
        
        # Complete registration button
        if st.button(
            "Complete Registration", 
            type="primary", 
            disabled=not st.session_state.terms_accepted
        ):
            if not st.session_state.terms_accepted:
                st.error("⚠️ You must accept the Terms and Conditions.")
                st.stop()
            
            # Prepare final data
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
            
            # Submit to backend
            try:
                response = requests.post(FASTAPI_URL, json=final_data)
                
                if response.status_code == 200:
                    st.success("✅ User registered and onboarding started!")
                    st.json(response.json())
                    
                    # Reset form
                    st.session_state.registration_step = 'basic_info'
                    st.session_state.user_data = {}
                    st.session_state.terms_accepted = False
                    
                elif response.status_code == 409:
                    st.error("❌ Email already registered.")
                else:
                    st.error(f"❌ Error: {response.json().get('detail')}")
                    
            except Exception as e:
                st.error(f"❌ Connection error: {e}")                       

# --- ADMIN DASHBOARD PAGE ---
elif page == "📊 Admin Dashboard":
    st.title("📊 Admin Dashboard")

    # Fetch metrics with caching
    metrics = fetch_dashboard_metrics()
    
    if metrics:
        # KPI Cards
        st.markdown("### 📈 Key Metrics")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.markdown(f"<div class='kpi-card' style='background-color:#007bff;'>👥 Total Users<div class='kpi-number'>{metrics['total_users']}</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='kpi-card' style='background-color:#28a745;'>✅ Verified<div class='kpi-number'>{metrics['verified_users']}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='kpi-card' style='background-color:#ffc107;'>⏳ Pending<div class='kpi-number'>{metrics['pending_verification']}</div></div>", unsafe_allow_html=True)
        col4.markdown(f"<div class='kpi-card' style='background-color:#17a2b8;'>📅 Today<div class='kpi-number'>{metrics['registered_today']}</div></div>", unsafe_allow_html=True)
        col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>🗓️ This Week<div class='kpi-number'>{metrics['registered_this_week']}</div></div>", unsafe_allow_html=True)

        st.markdown("---")
        
        # Chart
        st.markdown("### 📊 Users Overview")
        df_chart = pd.DataFrame({
            "Metric": ["Total Users", "Verified Users", "Pending Verification"], 
            "Count": [metrics['total_users'], metrics['verified_users'], metrics['pending_verification']]
        })
        fig = px.bar(
            df_chart, 
            x="Metric", 
            y="Count", 
            color="Metric", 
            title="Users vs Verified Users vs Pending", 
            color_discrete_sequence=["#007bff", "#28a745", "#ffc107"]
        )
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
    else:
        st.error("Could not fetch KPIs")

    # User Table
    st.markdown("### 📜 User Management")
    
    # Fetch users data with caching
    rows = fetch_users_data()
    
    if rows:
        # Add status column
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
        
        # Display the table directly without filters
        st.dataframe(df, use_container_width=True, height=400)
        
    else:
        st.error("Could not fetch users data")
    
    # Refresh button
    st.markdown("---")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
        
        
# --- AI ASSISTANT PAGE ---
elif page == "💬 AI Assistant":
    st.title("💬 AI Onboarding Assistant")
    
    # USER AUTHENTICATION
    if not st.session_state.cu_auth:
        st.subheader("🔐 User Authentication")
        st.info("✉️ Enter your registered email to continue")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            email_in = st.text_input(
                "📧 Email", 
                key="cu_email_input", 
                placeholder="your.email@example.com"
            )
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            go = st.button("✅ Verify", type="primary", use_container_width=True)
        
        if go and email_in:
            try:
                r = supabase.table("users").select("*").eq("email", email_in).execute()
                if r.data:
                    st.session_state.cu_auth = True
                    st.session_state.cu_email = email_in
                    st.session_state.cu_user = r.data[0]
                    st.success(f"✅ Welcome, {st.session_state.cu_user.get('name','User')}!")
                    time.sleep(0.6)
                    st.rerun()
                else:
                    st.error("❌ Email not found")
            except Exception as e:
                st.error(f"❌ Error: {e}")
        elif go:
            st.warning("⚠️ Please enter your email")
        st.stop()
    
    # AUTHENTICATED USER INTERFACE
    
    # Header
    colh1, colh2 = st.columns([3, 1])
    with colh1:
        st.subheader(f"👤 {st.session_state.cu_user.get('name','User')} - AI Onboarding")
    with colh2:
        if st.button("🔄 Switch User", key="cu_switch_user"):
            for key in list(st.session_state.keys()):
                if key.startswith('cu_'):
                    del st.session_state[key]
            st.rerun()

    # User info cards
    c1, c2, c3 = st.columns(3)
    c1.info(f"💼 Account: {st.session_state.cu_user.get('account_type','N/A')}")
    c2.info(f"👥 Ownership: {st.session_state.cu_user.get('ownership_type','N/A')}")
    c3.info(f"🏢 Business: {st.session_state.cu_user.get('business_name','N/A')}")

    st.markdown("---")
    
    # INITIALIZE CONVERSATION (ONCE)
    if not st.session_state.cu_conversation_started:
        try:
            # Get initial status and welcome message
            status_resp = requests.post(
                f"{BACKEND_URL}/chatupload/start-conversation",
                json={"email": st.session_state.cu_email},
                timeout=10
            )
            
            if status_resp.status_code == 200:
                data = status_resp.json()
                welcome_msg = data.get("welcome_message", "Welcome! Let's start your onboarding.")
                
                st.session_state.cu_msgs.append({
                    "role": "assistant",
                    "content": welcome_msg,
                    "timestamp": datetime.now().isoformat()
                })
                st.session_state.cu_conversation_started = True
                st.session_state.cu_ready = True
            else:
                st.error("❌ Could not start conversation")
                st.stop()
                
        except Exception as e:
            st.error(f"❌ Connection error: {e}")
            st.stop()
    
    # CHAT DISPLAY (FULL WIDTH)
    st.markdown("### 💬 Conversation")
    
    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.cu_msgs:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                st.markdown(
                    f"<div class='user-message'>{content}</div>", 
                    unsafe_allow_html=True
                )
            
            elif role == "assistant":
                # Clean HTML tags if present
                if "<" in content and ">" in content:
                    content = re.sub('<[^<]+?>', '', content)
                st.markdown(
                    f"<div class='assistant-message'>{content}</div>", 
                    unsafe_allow_html=True
                )
            
            elif role == "system":
                st.markdown(
                    f"<div class='system-message'>{content}</div>", 
                    unsafe_allow_html=True
                )
            
            elif role == "file_upload":
                st.markdown(
                    f"<div class='file-upload-message'>📎 {content}</div>", 
                    unsafe_allow_html=True
                )
        
        # Clear floats
        st.markdown("<div style='clear:both;'></div>", unsafe_allow_html=True)

    st.markdown("---")
    
    # COMBINED UPLOAD AND SEND MESSAGE SECTION
    st.markdown("### 📤 Upload Document & Send Message")

    # Check if user needs to provide member name
    ownership_type = st.session_state.cu_user.get("ownership_type")
    doc_stage = st.session_state.cu_user.get("document_stage", "identification")

    # Member name input for partnerships uploading member EIDs
    show_member_input = False
    if ownership_type in ["Partnership", "Multiple Owners"] and doc_stage == "member_eids":
        show_member_input = True

    # Display member input section if needed
    if show_member_input:
        st.warning("⚠️ **MEMBER EID COLLECTION MODE**")
        
        # Get current member from backend
        current_member_name = None
        total_members = 0
        current_index = 0
        
        try:
            progress_resp = requests.get(f"{BACKEND_URL}/chatupload/member-progress/{st.session_state.cu_email}")
            if progress_resp.status_code == 200:
                progress_data = progress_resp.json()
                current_member = progress_data.get("current_member")
                all_members = progress_data.get("members", [])
                current_index = progress_data.get("current_index", 0)
                total_members = len(all_members)
                
                # Extract member name (could be dict or string)
                if isinstance(current_member, dict):
                    current_member_name = current_member.get("name")
                else:
                    current_member_name = current_member
                
                if current_member_name:
                    st.info(f"👤 **Currently collecting EID for:** {current_member_name}\n\n📊 Progress: Member {current_index + 1} of {total_members}")
                    
                    # Auto-fill the member name if empty
                    if not st.session_state.cu_member_name_input:
                        st.session_state.cu_member_name_input = current_member_name
        except Exception as e:
            st.error(f"⚠️ Could not retrieve member information. Please refresh the page.")
        
        # Member name input field
        st.markdown("👥 **Enter the member's full name (as shown in documents):**")
        member_name = st.text_input(
            "Member Name",
            value=st.session_state.cu_member_name_input,
            placeholder="e.g., John Doe",
            key="cu_member_name_field",
            help="Enter the exact full name of the partner/shareholder for this EID",
            label_visibility="collapsed"
        )
        
        # Update session state immediately
        st.session_state.cu_member_name_input = member_name
        
        # Show what's stored
        if member_name:
            st.success(f"✅ Member name set: **{member_name}** (Length: {len(member_name)} characters)")
        else:
            st.warning("⚠️ Please enter the member's name before uploading")
    else:
        # Show info about current stage
        st.caption(f"ℹ️  Stage: {doc_stage} | Ownership: {ownership_type}")

    # SINGLE ROW FOR UPLOAD AND SEND MESSAGE
    col1, col2, col3, col4 = st.columns([2, 1, 2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "📎 Upload Document",
            type=["pdf", "png", "jpg", "jpeg", "webp", "docx"],
            key=f"cu_file_uploader_{st.session_state.cu_chat_key}",
            disabled=st.session_state.cu_processing,
            label_visibility="visible"
        )

    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        upload_btn = st.button(
            "🚀 Upload",
            type="primary",
            use_container_width=True,
            disabled=not uploaded_file or st.session_state.cu_processing
        )

    with col3:
        user_input = st.text_input(
            "💬 Send Message",
            key=f"cu_text_input_{st.session_state.cu_chat_key}",
            placeholder="Type 'verified' to confirm, or ask me anything...",
            label_visibility="visible",
            disabled=st.session_state.cu_processing
        )

    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        send_btn = st.button(
            "📤 Send",
            type="primary",
            use_container_width=True,
            disabled=not user_input or st.session_state.cu_processing
        )

    # HANDLE FILE UPLOAD
    if upload_btn and uploaded_file and not st.session_state.cu_processing:
        st.session_state.cu_processing = True
        
        # Validate member name if in member mode
        if show_member_input:
            member_name_value = st.session_state.cu_member_name_input.strip() if st.session_state.cu_member_name_input else ""
            
            if not member_name_value:
                st.error("⚠️ **Please enter the member's name before uploading their EID**")
                st.session_state.cu_processing = False
                st.stop()
        
        # Add file upload message to chat
        st.session_state.cu_msgs.append({
            "role": "file_upload",
            "content": f"Uploaded: {uploaded_file.name}",
            "timestamp": datetime.now().isoformat()
        })
        
        with st.spinner("⏳ Processing document..."):
            try:
                # Prepare upload
                files = [(
                    "files", 
                    (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)
                )]
                data = {"email": st.session_state.cu_email}
                
                # Add member_name if in member mode
                if show_member_input and st.session_state.cu_member_name_input:
                    member_name_to_send = st.session_state.cu_member_name_input.strip()
                    
                    if member_name_to_send:
                        data["member_name"] = member_name_to_send
                
                # Upload to backend
                upload_resp = requests.post(
                    f"{BACKEND_URL}/chatupload/upload-conversational",
                    data=data,
                    files=files,
                    timeout=600
                )
                
                if upload_resp.status_code == 200:
                    result = upload_resp.json()
                    
                    # Get AI response with extracted data
                    ai_response = result.get("message", "Document processed successfully!")
                    is_complete = result.get("is_complete", False)
                    awaiting_verification = result.get("awaiting_verification", False)
                    
                    # Add AI response to chat
                    st.session_state.cu_msgs.append({
                        "role": "assistant",
                        "content": ai_response,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    # Update state
                    st.session_state.cu_awaiting_verification = awaiting_verification
                    st.session_state.cu_last_uploaded_doc = result.get("document_type")
                    
                    # Clear member name input after successful upload
                    if show_member_input:
                        st.session_state.cu_member_name_input = ""
                    
                    # Check if onboarding complete
                    if is_complete:
                        st.balloons()
                        st.session_state.cu_msgs.append({
                            "role": "system",
                            "content": "🎉 Onboarding Complete! Your account will be activated within 3-4 business days.",
                            "timestamp": datetime.now().isoformat()
                        })
                    
                    st.session_state.cu_processing = False
                    st.session_state.cu_chat_key += 1
                    time.sleep(0.5)
                    st.rerun()
                
                else:
                    st.session_state.cu_processing = False
                    error_msg = upload_resp.json().get("detail", "Upload failed")
                    st.error(f"❌ {error_msg}")
                    
                    st.session_state.cu_msgs.append({
                        "role": "assistant",
                        "content": f"Sorry, there was an error processing your document: {error_msg}\n\nPlease try uploading again or contact support.",
                        "timestamp": datetime.now().isoformat()
                    })
                    
            except Exception as e:
                st.session_state.cu_processing = False
                st.error(f"❌ Error: {e}")
                
                st.session_state.cu_msgs.append({
                    "role": "assistant",
                    "content": f"Sorry, I encountered an error: {str(e)}\n\nPlease try again.",
                    "timestamp": datetime.now().isoformat()
                })

    # HANDLE CHAT MESSAGE
    if send_btn and user_input.strip() and not st.session_state.cu_processing:
        st.session_state.cu_processing = True
        
        # Add user message to chat
        st.session_state.cu_msgs.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        
        try:
            with st.spinner("💭 Thinking..."):
                # Send message to backend
                chat_resp = requests.post(
                    f"{BACKEND_URL}/chatupload/chat-conversational",
                    json={
                        "email": st.session_state.cu_email,
                        "message": user_input,
                        "chat_history": st.session_state.cu_msgs[-10:]
                    },
                    timeout=45
                )
                
                if chat_resp.status_code == 200:
                    data = chat_resp.json()
                    ai_response = data.get("response", "")
                    is_complete = data.get("is_complete", False)
                    verification_accepted = data.get("verification_accepted", False)
                    
                    # Add AI response
                    st.session_state.cu_msgs.append({
                        "role": "assistant",
                        "content": ai_response,
                        "timestamp": datetime.now().isoformat()
                    })
                    
                    # Update verification state
                    if verification_accepted:
                        st.session_state.cu_awaiting_verification = False
                        st.session_state.cu_last_uploaded_doc = None
                    
                    # Check if complete
                    if is_complete:
                        st.balloons()
                        st.session_state.cu_msgs.append({
                            "role": "system",
                            "content": "🎉 Onboarding Complete! Your account will be activated within 3-4 business days.",
                            "timestamp": datetime.now().isoformat()
                        })
                    
                    st.session_state.cu_processing = False
                    st.session_state.cu_chat_key += 1
                    st.rerun()
                
                else:
                    st.session_state.cu_processing = False
                    st.error(f"❌ Chat error: {chat_resp.status_code}")
                    
        except requests.exceptions.Timeout:
            st.session_state.cu_processing = False
            st.error("⏰ Request timed out. Please try again.")
        except Exception as e:
            st.session_state.cu_processing = False
            st.error(f"❌ Error: {e}")
    
    # ACTION BUTTONS
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button(
            "🗑️ Clear Chat", 
            use_container_width=True, 
            disabled=st.session_state.cu_processing
        ):
            st.session_state.cu_msgs = []
            st.session_state.cu_conversation_started = False
            st.session_state.cu_awaiting_verification = False
            st.session_state.cu_last_uploaded_doc = None
            st.session_state.cu_member_name_input = ""
            st.session_state.cu_chat_key += 1
            st.rerun()
    
    with col2:
        if st.button(
            "🔄 Refresh", 
            use_container_width=True, 
            disabled=st.session_state.cu_processing
        ):
            st.cache_data.clear()
            st.rerun()
    
    with col3:
        if st.button(
            "❓ Help", 
            use_container_width=True, 
            disabled=st.session_state.cu_processing
        ):
            help_msg = """I can help you with:
            
- Uploading documents (EID, Commercial License, MOA, Ejari)
- Verifying extracted information
- Answering questions about your onboarding
- Tracking your progress

Just upload a document or ask me anything!"""
            
            st.session_state.cu_msgs.append({
                "role": "assistant",
                "content": help_msg,
                "timestamp": datetime.now().isoformat()
            })
            st.rerun()