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
import base64
from io import BytesIO
from PIL import Image
import PyPDF2
import docx

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

# --- DOCUMENT TEXT EXTRACTION FUNCTIONS ---
def extract_text_from_pdf(file_bytes):
    """Extract text from PDF file bytes"""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(file_bytes))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"[Error extracting PDF text: {str(e)}]"


def extract_text_from_docx(file_bytes):
    """Extract text from DOCX file bytes"""
    try:
        doc = docx.Document(BytesIO(file_bytes))
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        return f"[Error extracting DOCX text: {str(e)}]"


def extract_text_from_txt(file_bytes):
    """Extract text from TXT file bytes"""
    try:
        return file_bytes.decode("utf-8")
    except Exception as e:
        return f"[Error extracting TXT text: {str(e)}]"


def extract_document_text(file_bytes, filename):
    """Extract text based on file type"""
    file_type = filename.split(".")[-1].lower()
    
    try:
        if file_type == "pdf":
            return extract_text_from_pdf(file_bytes)
        elif file_type == "docx":
            return extract_text_from_docx(file_bytes)
        elif file_type == "txt":
            return extract_text_from_txt(file_bytes)
        elif file_type in ["jpg", "jpeg", "png", "gif", "bmp", "webp"]:
            return "[Image uploaded - Visual content]"
        else:
            return "[Unsupported file type]"
    except Exception as e:
        return f"[Error: {str(e)}]"


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
    
    /* Document preview container */
    .document-preview {
        margin: 10px 0 10px auto;
        max-width: 65%;
        margin-left: 35%;
    }
    
    /* Optimize loading */
    .stApp {
        transition: none !important;
    }
    
    .document-preview img {
    max-width: 300px;  /* Adjust this value */
    height: auto;
    border-radius: 8px;
    }

    /* Or for all images in chat */
    [data-testid="stChatMessageContent"] img {
        max-width: 400px;
        height: auto;
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
        'cu_completion_email_sent': False,
        'cu_document_context': ""  # NEW: Store document context for chat
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
                    st.warning("⚙️ Please fill all required fields.")
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
                    st.warning("⚙️ Please provide your expected annual turnover.")
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
                st.error("⚙️ You must accept the Terms and Conditions.")
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

    metrics = fetch_dashboard_metrics()
    
    if metrics:
        st.markdown("### 📈 Key Metrics")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.markdown(f"<div class='kpi-card' style='background-color:#007bff;'>👥 Total Users<div class='kpi-number'>{metrics['total_users']}</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='kpi-card' style='background-color:#28a745;'>✅ Verified<div class='kpi-number'>{metrics['verified_users']}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='kpi-card' style='background-color:#ffc107;'>⏳ Pending<div class='kpi-number'>{metrics['pending_verification']}</div></div>", unsafe_allow_html=True)
        col4.markdown(f"<div class='kpi-card' style='background-color:#17a2b8;'>📅 Today<div class='kpi-number'>{metrics['registered_today']}</div></div>", unsafe_allow_html=True)
        col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>🗓️ This Week<div class='kpi-number'>{metrics['registered_this_week']}</div></div>", unsafe_allow_html=True)

        st.markdown("---")
        
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

    st.markdown("### 📋 User Management")
    
    rows = fetch_users_data()
    
    if rows:
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
        st.dataframe(df, use_container_width=True, height=400)
        
    else:
        st.error("Could not fetch users data")
    
    st.markdown("---")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# --- AI ASSISTANT PAGE (WITH DOCUMENT PREVIEW) ---

elif page == "💬 AI Assistant":
    st.title("💬 AI Onboarding Assistant")
    
    # Add chat message styling only (remove container CSS since we'll use st.container)
    st.markdown(
        """
        <style>
        /* User message styling */
        .user-message {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 14px 18px;
            border-radius: 18px 18px 5px 18px;
            margin: 12px 0 12px auto;
            max-width: 70%;
            display: block;
            margin-left: 30%;
            word-wrap: break-word;
            white-space: pre-wrap;
            box-shadow: 0 2px 6px rgba(102, 126, 234, 0.3);
            animation: slideInRight 0.3s ease-out;
        }
        
        /* Assistant message styling */
        .assistant-message {
            background: #f8f9fa;
            color: #2c3e50;
            padding: 14px 18px;
            border-radius: 18px 18px 18px 5px;
            margin: 12px 30% 12px 0;
            max-width: 70%;
            word-wrap: break-word;
            white-space: pre-wrap;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            border-left: 4px solid #667eea;
            animation: slideInLeft 0.3s ease-out;
        }
        
        /* System message styling */
        .system-message {
            background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
            color: #155724;
            border: 2px solid #28a745;
            padding: 14px 18px;
            border-radius: 10px;
            margin: 15px 10%;
            text-align: center;
            clear: both;
            font-weight: 500;
            box-shadow: 0 2px 6px rgba(40, 167, 69, 0.2);
            animation: fadeIn 0.4s ease-out;
        }
        
        /* File upload message styling */
        .file-upload-message {
            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
            color: #856404;
            border: 2px solid #ffc107;
            padding: 14px 18px;
            border-radius: 18px 18px 5px 18px;
            margin: 12px 0 12px auto;
            max-width: 70%;
            display: block;
            margin-left: 30%;
            font-weight: 500;
            box-shadow: 0 2px 6px rgba(255, 193, 7, 0.3);
            animation: slideInRight 0.3s ease-out;
        }
        
        /* Document preview container */
        .document-preview {
            margin: 15px 0 15px auto;
            max-width: 70%;
            margin-left: 30%;
            animation: fadeIn 0.4s ease-out;
        }
        
        .document-preview img {
            max-width: 350px;
            height: auto;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            border: 3px solid #e0e0e0;
            transition: transform 0.2s ease;
        }
        
        .document-preview img:hover {
            transform: scale(1.02);
            box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        }
        
        /* Animations */
        @keyframes slideInRight {
            from {
                opacity: 0;
                transform: translateX(30px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        @keyframes slideInLeft {
            from {
                opacity: 0;
                transform: translateX(-30px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
            }
            to {
                opacity: 1;
            }
        }
        
        /* Clear floats */
        .clearfix {
            clear: both;
            height: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
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
    
    # INITIALIZE CONVERSATION (ONCE) - WITH HISTORY LOADING
    if not st.session_state.cu_conversation_started:
        try:
            history_resp = requests.get(
                f"{BACKEND_URL}/chatupload/conversation-logs/{st.session_state.cu_email}",
                params={"limit": 50, "channel": "chat"},
                timeout=10
            )
            
            if history_resp.status_code == 200:
                history_data = history_resp.json()
                logs = history_data.get("logs", [])
                
                for log in reversed(logs):
                    role = "assistant" if log.get("role") == "agent" else "user"
                    st.session_state.cu_msgs.append({
                        "role": role,
                        "content": log.get("message", ""),
                        "timestamp": log.get("timestamp", "")
                    })
                
                if logs:
                    st.info(f"📜 Loaded {len(logs)} previous messages")
            
            status_resp = requests.post(
                f"{BACKEND_URL}/chatupload/start-conversation",
                json={"email": st.session_state.cu_email},
                timeout=10
            )
            
            if status_resp.status_code == 200:
                data = status_resp.json()
                welcome_msg = data.get("welcome_message", "Welcome! Let's start your onboarding.")
                
                if not logs:
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
    
    # ============================================================================
    # CHAT DISPLAY - USING STREAMLIT'S NATIVE CONTAINER (RESIZABLE)
    # ============================================================================
    st.markdown("### 💬 Conversation")
    
    # ✅ USE STREAMLIT'S NATIVE CONTAINER WITH HEIGHT
    chat_container = st.container(height=600, border=True)
    
    with chat_container:
        # Render all messages
        for msg in st.session_state.cu_msgs:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                st.markdown(
                    f"<div class='user-message'>{content}</div>", 
                    unsafe_allow_html=True
                )
            
            # Handle document preview
            elif role == "document":
                filename = msg.get("filename", "Document")
                file_data = msg.get("file_data", {})
                file_type = file_data.get("type", "")
                file_bytes = file_data.get("bytes")
                
                # Document header
                st.markdown(
                    f"""
                    <div class='document-preview'>
                        <div style='
                            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
                            border: 2px solid #ffc107;
                            border-radius: 12px 12px 0 0;
                            padding: 12px 16px;
                            color: #856404;
                            font-weight: 600;
                            box-shadow: 0 2px 6px rgba(255, 193, 7, 0.2);
                        '>
                            📄 Document: {filename}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                # Display based on file type
                if file_bytes:
                    if file_type == "application/pdf":
                        # PDF Preview
                        base64_pdf = base64.b64encode(file_bytes).decode('utf-8')
                        pdf_display = f'''
                        <div class='document-preview'>
                            <iframe 
                                src="data:application/pdf;base64,{base64_pdf}" 
                                width="100%" 
                                height="600" 
                                type="application/pdf"
                                style="border: 2px solid #ffc107; border-top: none; border-radius: 0 0 12px 12px;">
                            </iframe>
                        </div>
                        '''
                        st.markdown(pdf_display, unsafe_allow_html=True)
                        
                    elif file_type in ["image/jpeg", "image/jpg", "image/png", "image/gif", "image/bmp", "image/webp"]:
                        # Image Preview - RIGHT ALIGNED
                        st.markdown("<div class='document-preview'>", unsafe_allow_html=True)
                        
                        # Create columns for right alignment
                        col1, col2 = st.columns([2, 1])
                        
                        with col2:
                            image = Image.open(BytesIO(file_bytes))
                            
                            # Resize image
                            max_width = 350
                            if image.width > max_width:
                                ratio = max_width / image.width
                                new_height = int(image.height * ratio)
                                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
                            
                            st.image(image, caption=None)
                        
                        st.markdown("</div>", unsafe_allow_html=True)    
                        
                    elif file_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                        # DOCX Preview
                        st.markdown("<div class='document-preview'>", unsafe_allow_html=True)
                        with st.expander("📖 View Document Content", expanded=True):
                            doc_text = msg.get("content", "")
                            st.text_area(
                                "Document",
                                doc_text,
                                height=400,
                                disabled=True,
                                label_visibility="collapsed"
                            )
                        st.markdown("</div>", unsafe_allow_html=True)
                        
                    elif file_type == "text/plain":
                        # TXT Preview
                        st.markdown("<div class='document-preview'>", unsafe_allow_html=True)
                        with st.expander("📖 View Document Content", expanded=True):
                            doc_text = msg.get("content", "")
                            st.text_area(
                                "Document",
                                doc_text,
                                height=400,
                                disabled=True,
                                label_visibility="collapsed"
                            )
                        st.markdown("</div>", unsafe_allow_html=True)
            
            elif role == "assistant":
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
        
        # Add clearfix
        st.markdown("<div class='clearfix'></div>", unsafe_allow_html=True)

    st.markdown("---")
    # COMBINED UPLOAD AND SEND MESSAGE SECTION
    st.markdown("### 📤 Upload & Send")

    ownership_type = st.session_state.cu_user.get("ownership_type")
    doc_stage = st.session_state.cu_user.get("document_stage", "identification")

    show_member_input = False
    if ownership_type in ["Partnership", "Multiple Owners"] and doc_stage == "member_eids":
        show_member_input = True

    if show_member_input:
        st.warning("⚠️ **MEMBER EID COLLECTION MODE**")
        
        try:
            progress_resp = requests.get(f"{BACKEND_URL}/chatupload/member-progress/{st.session_state.cu_email}")
            if progress_resp.status_code == 200:
                progress_data = progress_resp.json()
                current_member = progress_data.get("current_member")
                all_members = progress_data.get("members", [])
                current_index = progress_data.get("current_index", 0)
                total_members = len(all_members)
                
                if isinstance(current_member, dict):
                    current_member_name = current_member.get("name")
                else:
                    current_member_name = current_member
                
                if current_member_name:
                    st.info(f"👤 **Currently collecting EID for:** {current_member_name}\n\n📊 Progress: Member {current_index + 1} of {total_members}")
                    
                    if not st.session_state.cu_member_name_input:
                        st.session_state.cu_member_name_input = current_member_name
        except Exception as e:
            st.error(f"⚠️ Could not retrieve member information. Please refresh the page.")
        
        st.markdown("👥 **Enter the member's full name (as shown in documents):**")
        member_name = st.text_input(
            "Member Name",
            value=st.session_state.cu_member_name_input,
            placeholder="e.g., John Doe",
            key="cu_member_name_field",
            help="Enter the exact full name of the partner/shareholder for this EID",
            label_visibility="collapsed"
        )
        
        st.session_state.cu_member_name_input = member_name
        
        if member_name:
            st.success(f"✅ Member name set: **{member_name}**")
        else:
            st.warning("⚠️ Please enter the member's name before uploading")

    # SIMPLIFIED UPLOAD AND SEND SECTION
    st.markdown("""
        <style>
        [data-testid="stFileUploader"] { width: 100%; }
        [data-testid="stFileUploader"] section { padding: 0; }
        [data-testid="stFileUploader"] section > div { display: none; }
        [data-testid="stFileUploader"] section button { display: block !important; width: 100%; height: 42px; }
        [data-testid="stTextInput"] > div > div > input { height: 42px; }
        [data-testid="stButton"] > button { height: 42px; }
        </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([0.6, 5, 1.5])

    with col1:
        uploaded_file = st.file_uploader(
            "📤 Upload",
            type=["pdf", "png", "jpg", "jpeg", "docx", "txt"],
            key=f"cu_file_uploader_{st.session_state.cu_chat_key}",
            disabled=st.session_state.cu_processing,
            label_visibility="collapsed"
        )

    with col2:
        user_input = st.text_input(
            "💬 Message",
            key=f"cu_text_input_{st.session_state.cu_chat_key}",
            placeholder="Ask me anything about your documents...",
            label_visibility="collapsed",
            disabled=st.session_state.cu_processing
        )

    with col3:
        button_disabled = st.session_state.cu_processing or (not user_input and not uploaded_file)
        
        if uploaded_file and user_input:
            button_text = "📤 Send & Upload"
            button_action = "both"
        elif uploaded_file:
            button_text = "📤 Upload"
            button_action = "upload"
        elif user_input:
            button_text = "📤 Send"
            button_action = "send"
        else:
            button_text = "📤 Send & Upload"
            button_action = None
        
        action_btn = st.button(
            button_text,
            type="primary",
            use_container_width=True,
            disabled=button_disabled
        )

    # HANDLE COMBINED BUTTON ACTION
    if action_btn:
        # Handle document upload with preview
        if button_action in ["upload", "both"] and uploaded_file:
            st.session_state.cu_processing = True
            
            if show_member_input:
                member_name_value = st.session_state.cu_member_name_input.strip() if st.session_state.cu_member_name_input else ""
                
                if not member_name_value:
                    st.error("⚠️ **Please enter the member's name before uploading their EID**")
                    st.session_state.cu_processing = False
                    st.stop()
            
            # Extract text from document for context
            file_bytes = uploaded_file.getvalue()
            document_text = extract_document_text(file_bytes, uploaded_file.name)
            
            # Store document context for use in chat
            st.session_state.cu_document_context = document_text
            
            # Add document message with preview data
            st.session_state.cu_msgs.append({
                "role": "document",
                "content": document_text,
                "filename": uploaded_file.name,
                "file_data": {
                    "bytes": file_bytes,
                    "type": uploaded_file.type
                },
                "timestamp": datetime.now().isoformat()
            })
            
            with st.spinner("⏳ Processing document..."):
                try:
                    files = [(
                        "files", 
                        (uploaded_file.name, file_bytes, uploaded_file.type)
                    )]
                    
                    data = {"email": st.session_state.cu_email}
                    
                    if show_member_input and st.session_state.cu_member_name_input:
                        member_name_to_send = st.session_state.cu_member_name_input.strip()
                        
                        if member_name_to_send:
                            data["member_name"] = member_name_to_send
                    
                    upload_resp = requests.post(
                        f"{BACKEND_URL}/chatupload/upload-conversational",
                        data=data,
                        files=files,
                        timeout=600
                    )
                    
                    if upload_resp.status_code == 200:
                        result = upload_resp.json()
                        
                        wrong_doc_type = result.get("wrong_document_type", False)
                        
                        if wrong_doc_type:
                            if st.session_state.cu_msgs and st.session_state.cu_msgs[-1]["role"] == "document":
                                st.session_state.cu_msgs.pop()
                            
                            error_message = result.get("message", "Wrong document type uploaded")
                            remaining_docs = result.get("remaining_documents", [])
                            
                            st.session_state.cu_msgs.append({
                                "role": "assistant",
                                "content": error_message,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            st.error(f"❌ Wrong Document Type: {result.get('document_type', 'Unknown').upper()}")
                            
                            if remaining_docs:
                                remaining_text = "\n• ".join(remaining_docs)
                                st.warning(f"⚠️ **Remaining Documents to Upload:**\n• {remaining_text}")
                            else:
                                st.warning("⚠️ The uploaded document has been removed. Please upload the correct document type.")
                            
                            if show_member_input:
                                st.session_state.cu_member_name_input = ""
                            
                            st.session_state.cu_processing = False
                        
                        else:
                            acknowledgment = result.get("acknowledgment", "")
                            full_message = result.get("message", "Document processed successfully!")
                            is_complete = result.get("is_complete", False)
                            awaiting_verification = result.get("awaiting_verification", False)
                            remaining_docs = result.get("remaining_documents", [])
                            
                            if acknowledgment:
                                st.session_state.cu_msgs.append({
                                    "role": "assistant",
                                    "content": acknowledgment,
                                    "timestamp": datetime.now().isoformat()
                                })
                            
                            if "\n\n" in full_message:
                                parts = full_message.split("\n\n", 1)
                                if len(parts) > 1:
                                    extracted_info = parts[1]
                                    st.session_state.cu_msgs.append({
                                        "role": "assistant",
                                        "content": extracted_info,
                                        "timestamp": datetime.now().isoformat()
                                    })
                            
                            if remaining_docs and not is_complete:
                                remaining_text = ", ".join(remaining_docs[:2])
                                if len(remaining_docs) > 2:
                                    remaining_text += f", and {len(remaining_docs) - 2} more"
                                
                                st.info(f"📋 **Remaining documents:** {remaining_text}")
                            elif is_complete:
                                st.success("🎉 All documents submitted!")
                            
                            st.session_state.cu_awaiting_verification = awaiting_verification
                            st.session_state.cu_last_uploaded_doc = result.get("document_type")
                            
                            if show_member_input:
                                st.session_state.cu_member_name_input = ""
                            
                            st.session_state.cu_processing = False
                    
                    else:
                        st.session_state.cu_processing = False
                        error_msg = upload_resp.json().get("detail", "Upload failed")
                        st.error(f"❌ Error: {error_msg}")
                        
                        st.session_state.cu_msgs.append({
                            "role": "assistant",
                            "content": f"Sorry, there was an error processing your document: {error_msg}",
                            "timestamp": datetime.now().isoformat()
                        })
                        
                except Exception as e:
                    st.session_state.cu_processing = False
                    st.error(f"❌ Error: {e}")
                    
                    st.session_state.cu_msgs.append({
                        "role": "assistant",
                        "content": f"Sorry, I encountered an error: {str(e)}",
                        "timestamp": datetime.now().isoformat()
                    })
            
            st.session_state.cu_chat_key += 1
            time.sleep(0.5)
            st.rerun()
        
        # Handle chat message
        if button_action in ["send", "both"] and user_input.strip():
            if not st.session_state.cu_processing:
                st.session_state.cu_processing = True
            
            st.session_state.cu_msgs.append({
                "role": "user",
                "content": user_input,
                "timestamp": datetime.now().isoformat()
            })
            
            try:
                with st.spinner("💭 Thinking..."):
                    clean_history = []
                    for msg in st.session_state.cu_msgs[-10:]:
                        if msg.get("role") == "document":
                            continue
                        
                        clean_msg = {
                            "role": msg.get("role"),
                            "content": msg.get("content"),
                            "timestamp": msg.get("timestamp")
                        }
                        clean_history.append(clean_msg)
                    
                    chat_data = {
                        "email": st.session_state.cu_email,
                        "message": user_input,
                        "chat_history": clean_history
                    }
                    
                    if st.session_state.cu_document_context:
                        chat_data["document_context"] = st.session_state.cu_document_context[:4000]
                    
                    chat_resp = requests.post(
                        f"{BACKEND_URL}/chatupload/chat-conversational",
                        json=chat_data,
                        timeout=45
                    )
                    
                    if chat_resp.status_code == 200:
                        data = chat_resp.json()
                        ai_response = data.get("response", "")
                        is_complete = data.get("is_complete", False)
                        verification_accepted = data.get("verification_accepted", False)
                        
                        st.session_state.cu_msgs.append({
                            "role": "assistant",
                            "content": ai_response,
                            "timestamp": datetime.now().isoformat()
                        })
                        
                        if verification_accepted:
                            st.session_state.cu_awaiting_verification = False
                            st.session_state.cu_last_uploaded_doc = None
                        
                        st.session_state.cu_processing = False
                    
                    else:
                        st.session_state.cu_processing = False
                        st.error(f"❌ Chat error: {chat_resp.status_code}")
                        
            except requests.exceptions.Timeout:
                st.session_state.cu_processing = False
                st.error("⏰ Request timed out. Please try again.")
            except Exception as e:
                st.session_state.cu_processing = False
                st.error(f"❌ Error: {e}")
                import traceback
                print(traceback.format_exc())
            
            st.session_state.cu_chat_key += 1
            time.sleep(0.5)
            st.rerun()

    # ACTION BUTTONS
    st.markdown("---")

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button(
            "🗑️ Clear", 
            key="cu_clear_button",
            use_container_width=True, 
            disabled=st.session_state.cu_processing,
            help="Clear chat history and document context"
        ):
            st.session_state.cu_msgs = []
            st.session_state.cu_conversation_started = False
            st.session_state.cu_awaiting_verification = False
            st.session_state.cu_last_uploaded_doc = None
            st.session_state.cu_member_name_input = ""
            st.session_state.cu_document_context = ""
            st.session_state.cu_chat_key += 1
            st.rerun()

    with col2:
        if st.button(
            "🔄 Refresh", 
            key="cu_refresh_button",
            use_container_width=True, 
            disabled=st.session_state.cu_processing,
            help="Refresh the page"
        ):
            st.cache_data.clear()
            st.rerun()