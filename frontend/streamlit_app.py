# Frontend/Streamlit_app.py
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
import os

# Load environment variables
load_dotenv()

try:
    # For Docker: Use service name 'backend' instead of 'localhost'
    BACKEND_URL = st.secrets.get("BACKEND_URL", os.getenv("BACKEND_URL", "http://backend:8080"))
    SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL"))
    SUPABASE_KEY = st.secrets.get("SUPABASE_API_KEY", os.getenv("SUPABASE_API_KEY"))
except:
    # Docker default: use service name
    BACKEND_URL = os.getenv("BACKEND_URL", "https://docile-jamari-responsibly.ngrok-free.dev")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
    
FASTAPI_URL = f"{BACKEND_URL}/register"
FASTAPI_URLS = BACKEND_URL

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
    max-width: 300px;
    height: auto;
    border-radius: 8px;
    }

    [data-testid="stChatMessageContent"] img {
        max-width: 400px;
        height: auto;
    }
    
    /* Document Upload Page Styles */
    .doc-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 20px;
        border-radius: 12px;
        margin: 10px 0;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
    }
    
    .status-badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        margin: 5px 5px 5px 0;
    }
    
    .status-submitted {
        background: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }
    
    .status-required {
        background: #fff3cd;
        color: #856404;
        border: 1px solid #ffeaa7;
    }
    
    .status-optional {
        background: #e2e3e5;
        color: #383d41;
        border: 1px solid #d6d8db;
    }
    
    .extracted-info {
        background: #e7f3ff;
        border-left: 4px solid #2196F3;
        padding: 15px;
        border-radius: 5px;
        margin: 15px 0;
    }
    
    .progress-bar-container {
        background: #e9ecef;
        border-radius: 10px;
        overflow: hidden;
        margin: 15px 0;
        height: 25px;
    }
    
    .progress-bar-fill {
        height: 100%;
        background: linear-gradient(90deg, #28a745 0%, #20c997 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 600;
        font-size: 12px;
    }
    
    .member-card {
        background: white;
        border: 1px solid #dee2e6;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        transition: all 0.3s ease;
    }
    
    .member-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        border-color: #667eea;
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
        'cu_document_context': "",
        # Document Upload Page States
        'doc_auth': False,
        'doc_email': None,
        'doc_user': {},
        'doc_uploading': False,
        'doc_uploaded': False,
        'doc_upload_result': None,
        'doc_requirements': None,
        'doc_status': None,
        'doc_member_name': "",
        'doc_selected_member': None,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Initialize session state
init_session_state()

# --- SIDEBAR NAVIGATION ---
st.sidebar.title("🧾 Onboarding Agent")
st.sidebar.markdown("---")

# Navigation - ADDED DOCUMENT UPLOAD
page = st.sidebar.radio(
    "Navigate to:",
    ["📋 Register User", "📊 Admin Dashboard", "💬 AI Assistant", "📄 Document Upload"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

# ============================================================================
# REGISTER USER PAGE - UNCHANGED
# ============================================================================
if page == "📋 Register User":
    st.title("📋 Register a New User")
    
    # STEP 1: BASIC INFORMATION
    if st.session_state.registration_step == 'basic_info':
        with st.form("basic_info_form"):
            st.subheader("Basic Information")
            
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
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("⬅️ Back", key="account_type_back_btn"):
                st.session_state.registration_step = 'basic_info'
                st.rerun()
        
        st.write("")
        
        with st.form("account_type_form"):
            st.markdown("### What kind of account do you want to open?")
            
            current_account_type = st.session_state.user_data.get('account_type', 'Savings')
            account_type_options = ["Savings", "Corporate"]
            
            try:
                default_index = account_type_options.index(current_account_type)
            except ValueError:
                default_index = 0
            
            account_type = st.radio(
                "Select your account type:",
                account_type_options,
                index=default_index,
                key="account_type_selection"
            )
              
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                submitted = st.form_submit_button(
                    "✅ Continue", 
                    type="primary", 
                    use_container_width=True
                )
            
            if submitted:
                st.session_state.user_data['account_type'] = account_type
                
                if account_type == "Savings":
                    st.session_state.registration_step = 'final_confirmation'
                    st.success("✅ Account type saved! Moving to Terms & Conditions...")
                elif account_type == "Corporate":
                    st.session_state.registration_step = 'ownership_type'
                    st.success("✅ Account type saved! Moving to Ownership Type...")
                
                time.sleep(0.5)
                st.rerun()
    
    # STEP 3: OWNERSHIP TYPE
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

        with st.expander("📋 Terms and Conditions For Data Sharing and Privacy", expanded=False):
            st.markdown(terms_content)
            st.markdown("---")
            st.session_state.terms_accepted = st.checkbox(
                "✅ I have read and agree to the Terms and Conditions and Privacy Policy",
                value=st.session_state.terms_accepted
            )
        
        if st.button("Complete Registration", type="primary", disabled=not st.session_state.terms_accepted):
            if not st.session_state.terms_accepted:
                st.error("⚙️ You must accept the Terms and Conditions.")
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
        col5.markdown(f"<div class='kpi-card' style='background-color:#6f42c1;'>📋️ This Week<div class='kpi-number'>{metrics['registered_this_week']}</div></div>", unsafe_allow_html=True)

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
    
    st.markdown(
        """
        <style>
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
        
        @keyframes slideInRight {
            from { opacity: 0; transform: translateX(30px); }
            to { opacity: 1; transform: translateX(0); }
        }
        
        @keyframes slideInLeft {
            from { opacity: 0; transform: translateX(-30px); }
            to { opacity: 1; transform: translateX(0); }
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
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
        st.subheader("🔓 User Authentication")
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
    colh1, colh2 = st.columns([3, 1])
    with colh1:
        st.subheader(f"👤 {st.session_state.cu_user.get('name','User')} - AI Onboarding")
    with colh2:
        if st.button("🔄 Switch User", key="cu_switch_user"):
            for key in list(st.session_state.keys()):
                if key.startswith('cu_'):
                    del st.session_state[key]
            st.rerun()

    c1, c2, c3 = st.columns(3)
    c1.info(f"💼 Account: {st.session_state.cu_user.get('account_type','N/A')}")
    c2.info(f"👥 Ownership: {st.session_state.cu_user.get('ownership_type','N/A')}")
    c3.info(f"🏢 Business: {st.session_state.cu_user.get('business_name','N/A')}")

    st.markdown("---")
    
    # INITIALIZE CONVERSATION (ONCE)
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
    
    # CHAT DISPLAY
    st.markdown("### 💬 Conversation")
    chat_container = st.container(height=600, border=True)
    
    with chat_container:
        for msg in st.session_state.cu_msgs:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                st.markdown(
                    f"<div class='user-message'>{content}</div>", 
                    unsafe_allow_html=True
                )
            
            elif role == "document":
                filename = msg.get("filename", "Document")
                file_data = msg.get("file_data", {})
                file_type = file_data.get("type", "")
                file_bytes = file_data.get("bytes")
                
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
                
                if file_bytes:
                    if file_type == "application/pdf":
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
                        st.markdown("<div class='document-preview'>", unsafe_allow_html=True)
                        col1, col2 = st.columns([2, 1])
                        
                        with col2:
                            image = Image.open(BytesIO(file_bytes))
                            max_width = 350
                            if image.width > max_width:
                                ratio = max_width / image.width
                                new_height = int(image.height * ratio)
                                image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)
                            
                            st.image(image, caption=None)
                        
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
                    f"<div class='file-upload-message'>📋 {content}</div>", 
                    unsafe_allow_html=True
                )
        
        st.markdown("<div class='clearfix'></div>", unsafe_allow_html=True)

    st.markdown("---")
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
        if button_action in ["upload", "both"] and uploaded_file:
            st.session_state.cu_processing = True
            
            if show_member_input:
                member_name_value = st.session_state.cu_member_name_input.strip() if st.session_state.cu_member_name_input else ""
                
                if not member_name_value:
                    st.error("⚠️ **Please enter the member's name before uploading their EID**")
                    st.session_state.cu_processing = False
                    st.stop()
            
            file_bytes = uploaded_file.getvalue()
            document_text = extract_document_text(file_bytes, uploaded_file.name)
            
            st.session_state.cu_document_context = document_text
            
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
                st.error("⏱ Request timed out. Please try again.")
            except Exception as e:
                st.session_state.cu_processing = False
                st.error(f"❌ Error: {e}")
            
            st.session_state.cu_chat_key += 1
            time.sleep(0.5)
            st.rerun()

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

# ============================================================================
# DOCUMENT UPLOAD PAGE
# ============================================================================

elif page == "📄 Document Upload":
    st.title("📄 Document Upload Center")
    
    # Enhanced CSS with all styling
    st.markdown("""
    <style>
    /* Info Cards */
    .info-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        margin: 10px 0;
    }
    .info-card-label {
        font-size: 14px;
        opacity: 0.9;
        margin-bottom: 8px;
        font-weight: 600;
    }
    .info-card-value {
        font-size: 20px;
        font-weight: 700;
    }
    
    /* Status Cards */
    .stat-card {
        background: white;
        border: 2px solid #e0e0e0;
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        transition: all 0.3s ease;
    }
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }
    .stat-icon {
        font-size: 32px;
        margin-bottom: 12px;
    }
    .stat-value {
        font-size: 36px;
        font-weight: 700;
        color: #2c3e50;
        margin: 8px 0;
    }
    .stat-label {
        font-size: 14px;
        color: #7f8c8d;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stat-card.complete {
        border-color: #28a745;
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
    }
    .stat-card.complete .stat-value {
        color: #155724;
    }
    .stat-card.complete .stat-label {
        color: #155724;
    }
    .stat-card.pending {
        border-color: #ffc107;
        background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
    }
    .stat-card.pending .stat-value {
        color: #856404;
    }
    .stat-card.pending .stat-label {
        color: #856404;
    }
    .stat-card.submitted {
        border-color: #007bff;
        background: linear-gradient(135deg, #cfe2ff 0%, #b6d4fe 100%);
    }
    .stat-card.submitted .stat-value {
        color: #004085;
    }
    .stat-card.submitted .stat-label {
        color: #004085;
    }
    
    /* Progress Bar */
    .progress-bar-container {
        background: #e9ecef;
        border-radius: 10px;
        height: 30px;
        margin: 20px 0;
        overflow: hidden;
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);
    }
    .progress-bar-fill {
        background: linear-gradient(90deg, #28a745 0%, #20c997 100%);
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 600;
        font-size: 13px;
        transition: width 0.3s ease;
    }
    
    /* Success Card */
    .success-card {
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
        border: 3px solid #28a745;
        border-radius: 16px;
        padding: 30px;
        margin: 20px 0;
        text-align: center;
        box-shadow: 0 4px 12px rgba(40, 167, 69, 0.2);
    }
    .success-icon {
        font-size: 72px;
        margin-bottom: 20px;
    }
    .success-title {
        font-size: 28px;
        font-weight: 700;
        color: #155724;
        margin-bottom: 15px;
    }
    .success-message {
        font-size: 16px;
        color: #155724;
        margin-bottom: 20px;
        line-height: 1.8;
    }
    
    /* Validation Progress Card */
    .validation-card {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border: 3px solid #2196f3;
        border-radius: 16px;
        padding: 40px;
        margin: 20px 0;
        text-align: center;
        box-shadow: 0 4px 12px rgba(33, 150, 243, 0.3);
    }
    .validation-icon {
        font-size: 72px;
        margin-bottom: 20px;
        animation: pulse 2s ease-in-out infinite;
    }
    .validation-title {
        font-size: 28px;
        font-weight: 700;
        color: #1565c0;
        margin-bottom: 15px;
    }
    .validation-message {
        font-size: 16px;
        color: #1976d2;
        margin-bottom: 20px;
        line-height: 1.8;
    }
    
    /* Pulse Animation */
    @keyframes pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.7; transform: scale(1.05); }
    }
    
    /* Member Card */
    .member-item {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.3s ease;
    }
    .member-item:hover {
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-color: #667eea;
    }
    .member-name {
        font-weight: 600;
        color: #2c3e50;
    }
    
    /* Document Header */
    .doc-header {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        border-left: 4px solid #667eea;
        border-radius: 8px;
        padding: 15px;
        margin: 15px 0;
    }
    .doc-type {
        font-size: 18px;
        font-weight: 700;
        color: #2c3e50;
    }
    .doc-meta {
        font-size: 12px;
        color: #6c757d;
        margin-top: 8px;
    }
    
    /* Error Card */
    .error-card {
        background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
        border: 3px solid #dc3545;
        border-radius: 16px;
        padding: 30px;
        margin: 20px 0;
        text-align: center;
        box-shadow: 0 4px 12px rgba(220, 53, 69, 0.2);
    }
    .error-icon {
        font-size: 72px;
        margin-bottom: 20px;
    }
    .error-title {
        font-size: 28px;
        font-weight: 700;
        color: #721c24;
        margin-bottom: 15px;
    }
    .error-message {
        font-size: 16px;
        color: #721c24;
        margin-bottom: 20px;
        line-height: 1.8;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ============================================================================
    # AUTHENTICATION
    # ============================================================================
    if not st.session_state.doc_auth:
        st.subheader("🔐 User Authentication")
        st.info("✉️ Enter your registered email to access the document upload portal")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            email_input = st.text_input(
                "Email",
                placeholder="your.email@example.com",
                label_visibility="collapsed"
            )
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            verify_btn = st.button("✅ Verify", use_container_width=True, type="primary")
        
        if verify_btn and email_input:
            try:
                req_url = f"{BACKEND_URL}/documentupload/get-document-requirements"
                response = requests.post(req_url, json={"email": email_input}, timeout=10)
                
                if response.status_code == 200:
                    st.session_state.doc_auth = True
                    st.session_state.doc_email = email_input
                    st.session_state.doc_requirements = response.json()
                    st.success(f"✅ Welcome back!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ Email not found. Please register first.")
            except Exception as e:
                st.error(f"❌ Connection error: {e}")
        elif verify_btn:
            st.warning("⚠️ Please enter your email address")
        
        st.stop()

    # ============================================================================
    # AUTHENTICATED USER INTERFACE
    # ============================================================================
    
    col1, col2 = st.columns([4, 1])
    with col1:
        account_info = st.session_state.doc_requirements.get("account_type", "User")
        st.subheader(f"👤 {account_info} Account")
        st.caption(f"📧 {st.session_state.doc_email}")
    with col2:
        if st.button("🔄 Switch User", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key.startswith('doc_'):
                    del st.session_state[key]
            st.rerun()

    st.markdown("---")

    # Load current status
    try:
        status_response = requests.get(
            f"{BACKEND_URL}/documentupload/document-status/{st.session_state.doc_email}",
            timeout=10
        )
        
        if status_response.status_code == 200:
            st.session_state.doc_status = status_response.json()
    except Exception as e:
        st.error(f"⚠️ Error loading status: {e}")

    # ============================================================================
    # CHECK IF ALREADY VERIFIED COMPLETE
    # ============================================================================
    if st.session_state.doc_status:
        stage = st.session_state.doc_status.get("stage", "")
        is_complete = st.session_state.doc_status.get("is_complete", False)
        
        if stage == "complete" and is_complete:
            st.markdown("""
            <div class="success-card">
                <div class="success-icon">🎉</div>
                <div class="success-title">Document Verification Complete!</div>
                <div class="success-message">
                    ✅ All your documents have been verified<br>
                    ⏰ Account activation within 3-4 business days<br>
                    📧 You will receive account details via email
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.info("💡 Your onboarding is complete. You can close this page now.")
            
            if st.button("🔄 Back to Home", use_container_width=True):
                for key in list(st.session_state.keys()):
                    if key.startswith('doc_'):
                        del st.session_state[key]
                st.rerun()
            
            st.stop()

    # Get user requirements
    ownership_type = st.session_state.doc_requirements.get("ownership_type", "")
    account_type = st.session_state.doc_requirements.get("account_type", "")
    
    # Get stage from latest status
    if st.session_state.doc_status:
        stage = st.session_state.doc_status.get("stage", "identification")
        
        if stage == "member_eids":
            stage_desc = "Partnership Member EID Collection"
        elif stage == "identification":
            stage_desc = "Partnership Identification Stage"
        elif stage == "complete":
            stage_desc = "Verification Complete"
        else:
            stage_desc = st.session_state.doc_requirements.get("stage_description", "General Account")
    else:
        stage = st.session_state.doc_requirements.get("stage", "identification")
        stage_desc = st.session_state.doc_requirements.get("stage_description", "")
    
    # ============================================================================
    # ACCOUNT INFO CARDS
    # ============================================================================
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div class="info-card">
            <div class="info-card-label">📊 Account Type</div>
            <div class="info-card-value">{account_type}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="info-card">
            <div class="info-card-label">👥 Ownership</div>
            <div class="info-card-value">{ownership_type or 'N/A'}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="info-card">
            <div class="info-card-label">📋 Current Stage</div>
            <div class="info-card-value">{stage_desc}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ============================================================================
    # STATUS METRICS
    # ============================================================================
    if st.session_state.doc_status:
        submitted_docs = st.session_state.doc_status.get("documents", [])
        remaining_docs = st.session_state.doc_status.get("remaining_documents", [])
        is_complete = st.session_state.doc_status.get("is_complete", False)
        members_info = st.session_state.doc_status.get("members_info")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="stat-card submitted">
                <div class="stat-icon">📄</div>
                <div class="stat-value">{len(submitted_docs)}</div>
                <div class="stat-label">Submitted</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="stat-card pending">
                <div class="stat-icon">📋</div>
                <div class="stat-value">{len(remaining_docs)}</div>
                <div class="stat-label">Remaining</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            status_class = "complete" if is_complete else "pending"
            status_icon = "✅" if is_complete else "⏳"
            status_text = "Complete" if is_complete else "In Progress"
            
            st.markdown(f"""
            <div class="stat-card {status_class}">
                <div class="stat-icon">{status_icon}</div>
                <div class="stat-value" style="font-size: 24px;">{status_text}</div>
                <div class="stat-label">Status</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # ============================================================================
        # SUBMITTED DOCUMENTS WITH PDF PREVIEW
        # ============================================================================
        if submitted_docs:
            st.markdown("### 📊 Submitted Documents")
            
            for idx, doc in enumerate(submitted_docs):
                doc_type = doc.get("document_type", "unknown")
                filename = doc.get("filename", "Unknown")
                is_valid = doc.get("is_valid", False)
                member_name = doc.get("member_name")
                display_name = doc.get("display_name", doc_type.upper())
                
                col_header, col_status = st.columns([3, 1])
                
                with col_header:
                    st.markdown(f"""
                    <div class="doc-header">
                        <div class="doc-type">📄 {display_name}</div>
                        <div class="doc-meta">📁 {filename}</div>
                        {f'<div class="doc-meta">👤 Member: {member_name}</div>' if member_name else ''}
                    </div>
                    """, unsafe_allow_html=True)
                
                with col_status:
                    if is_valid:
                        st.success("✅ Valid")
                    else:
                        st.warning("⚠️ Invalid")
                
                # Display preview in expander
                with st.expander(f"👁️ View Details - {display_name}", expanded=False):
                    try:
                        preview_response = requests.get(
                            f"{BACKEND_URL}/documentupload/get-document-preview/{st.session_state.doc_email}/{doc_type.lower()}",
                            params={"member_name": member_name} if member_name else {},
                            timeout=10
                        )
                        
                        if preview_response.status_code == 200:
                            preview_info = preview_response.json()
                            
                            col_left, col_right = st.columns([1, 1])
                            
                            # LEFT: Document Preview Display
                            with col_left:
                                st.markdown("**🖼️ Document Preview**")
                                
                                if preview_info.get("mime_type") == "application/pdf":
                                    pdf_meta = preview_info.get("pdf_metadata", {})
                                    
                                    st.markdown(f"""
                                    <div style='
                                        background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
                                        border: 2px solid #ffc107;
                                        border-radius: 12px;
                                        padding: 20px;
                                        text-align: center;
                                        margin: 10px 0;
                                    '>
                                        <div style='font-size: 48px; margin-bottom: 10px;'>📄</div>
                                        <div style='font-size: 16px; font-weight: 700; color: #856404;'>
                                            {preview_info.get('filename', 'Document')}
                                        </div>
                                        <div style='font-size: 12px; color: #856404; margin-top: 8px;'>
                                            📊 {pdf_meta.get('num_pages', 'N/A')} pages • PDF Document
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                    
                                    if st.button(
                                        "📥 Download PDF",
                                        key=f"pdf_download_{idx}",
                                        use_container_width=True,
                                        type="primary"
                                    ):
                                        try:
                                            download_response = requests.get(
                                                f"{BACKEND_URL}/documentupload/download-document/{st.session_state.doc_email}/{doc_type.lower()}",
                                                params={"member_name": member_name} if member_name else {},
                                                timeout=30
                                            )
                                            
                                            if download_response.status_code == 200:
                                                st.download_button(
                                                    label="💾 Save PDF",
                                                    data=download_response.content,
                                                    file_name=preview_info.get("filename", f"{doc_type}.pdf"),
                                                    mime="application/pdf",
                                                    use_container_width=True,
                                                    key=f"dl_pdf_{idx}"
                                                )
                                        except Exception as e:
                                            st.error(f"❌ Error downloading: {e}")
                                
                                elif preview_info.get("mime_type", "").startswith("image/"):
                                    try:
                                        download_response = requests.get(
                                            f"{BACKEND_URL}/documentupload/download-document/{st.session_state.doc_email}/{doc_type.lower()}",
                                            params={"member_name": member_name} if member_name else {},
                                            timeout=30
                                        )
                                        
                                        if download_response.status_code == 200:
                                            from PIL import Image
                                            from io import BytesIO
                                            
                                            image = Image.open(BytesIO(download_response.content))
                                            st.image(
                                                image,
                                                caption=preview_info.get("filename", "Document"),
                                                use_column_width=True
                                            )
                                    except Exception as e:
                                        st.warning("⚠️ Could not display image")
                                
                                elif preview_info.get("is_email_upload"):
                                    st.info("📧 Document uploaded via email - preview not available")
                                
                                else:
                                    st.warning("⚠️ Preview not available")

                            # RIGHT COLUMN: Extracted Information
                            with col_right:
                                st.markdown("**📋 Extracted Information**")
                                extracted_data = preview_info.get("extracted_data", {})
                                
                                if extracted_data:
                                    if display_name == "Emirates ID (EID)":
                                        st.write("**👤 Personal Information:**")
                                        st.write(f"• **Name:** {extracted_data.get('Name') or extracted_data.get('name', 'N/A')}")
                                        st.write(f"• **ID Number:** {extracted_data.get('ID Number') or extracted_data.get('id_number', 'N/A')}")
                                        st.write(f"• **Nationality:** {extracted_data.get('Nationality') or extracted_data.get('nationality', 'N/A')}")
                                        st.write(f"• **Expiry:** {extracted_data.get('Expiry Date') or extracted_data.get('expiry_date', 'N/A')}")
                                    
                                    elif display_name == "Commercial License":
                                        eng = extracted_data.get("english", {})
                                        st.write("**🏢 Company Information:**")
                                        st.write(f"• **Company:** {eng.get('company_name_english', 'N/A')}")
                                        st.write(f"• **License:** {eng.get('license_number', 'N/A')}")
                                        st.write(f"• **Status:** {eng.get('status', 'N/A')}")
                                        st.write(f"• **Expiry:** {eng.get('expiry_date', 'N/A')}")
                                    
                                    elif display_name == "Ejari (Tenancy Contract)":
                                        eng = extracted_data.get("english", {})
                                        st.write("**🏠 Tenancy Information:**")
                                        st.write(f"• **Contract Number:** {eng.get('contract_number', 'N/A')}")
                                        st.write(f"• **Owner:** {eng.get('owner_name', 'N/A')}")
                                        st.write(f"• **Tenant:** {eng.get('tenant_company', 'N/A')}")
                                        st.write(f"• **Start Date:** {eng.get('start_date', 'N/A')}")
                                        st.write(f"• **End Date:** {eng.get('end_date', 'N/A')}")
                                        st.write(f"• **Property:** {eng.get('property_type', 'N/A')}")
                                        st.write(f"• **Area:** {eng.get('area', 'N/A')}")
                                    
                                    elif display_name == "Memorandum of Association (MOA)":
                                        eng = extracted_data.get("english", {})
                                        st.write("**📜 MOA Information:**")
                                        st.write(f"• **Company:** {eng.get('company_name', 'N/A')}")
                                        st.write(f"• **Owner:** {eng.get('owner_name', 'N/A')}")
                                        st.write(f"• **Date:** {eng.get('date_of_execution', 'N/A')}")
                                        st.write(f"• **Shares:** {eng.get('number_of_shares', 'N/A')}")
                                else:
                                    st.info("ℹ️ No extracted data available")
                        
                        else:
                            st.warning("⚠️ Preview not available")
                    
                    except Exception as e:
                        st.error(f"Error loading preview: {e}")
                        
                st.markdown("<br>", unsafe_allow_html=True)
            
            st.markdown("---")
        
        # ============================================================================
        # MEMBER PROGRESS FOR PARTNERSHIPS
        # ============================================================================
        if members_info:
            st.markdown("### 👥 Member Progress")
            
            total = members_info.get("total", 0)
            verified = members_info.get("verified", 0)
            all_members = members_info.get("all_members", [])
            verified_members = members_info.get("verified_members", [])
            
            progress_pct = (verified / total * 100) if total > 0 else 0
            st.markdown(f"""
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" style="width: {progress_pct}%;">
                        {verified}/{total} EIDs Verified
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            for member_name in all_members:
                is_verified = member_name in verified_members
                status_icon = "✅" if is_verified else "⏳"
                status_text = "Verified" if is_verified else "Pending"
                status_color = "#28a745" if is_verified else "#ffc107"
                
                st.markdown(f"""
                <div class="member-item">
                    <span class="member-name">👤 {member_name}</span>
                    <span style="color: {status_color}; font-weight: 600;">{status_icon} {status_text}</span>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
    # ============================================================================
    # FINAL CONFIRMATION WITH AUTO-START VALIDATION
    # ============================================================================
    if is_complete:
        st.markdown("---")
        st.markdown("### ✅ Final Confirmation")
        
        # Initialize session states
        if "doc_confirmation_sent" not in st.session_state:
            st.session_state.doc_confirmation_sent = False
        
        if "validation_in_progress" not in st.session_state:
            st.session_state.validation_in_progress = False
        
        if "validation_failed" not in st.session_state:
            st.session_state.validation_failed = False
        
        if "validation_error_message" not in st.session_state:
            st.session_state.validation_error_message = ""
        
        if "validation_mismatches" not in st.session_state:
            st.session_state.validation_mismatches = []
        
        # Check backend confirmation status
        try:
            confirmation_response = requests.get(
                f"{BACKEND_URL}/documentupload/check-confirmation-status/{st.session_state.doc_email}",
                timeout=10
            )
            
            if confirmation_response.status_code == 200:
                confirmation_data = confirmation_response.json()
                db_confirmation_sent = confirmation_data.get("confirmation_sent", False)
                
                if db_confirmation_sent and not st.session_state.doc_confirmation_sent:
                    st.session_state.doc_confirmation_sent = True
                    st.session_state.validation_in_progress = False
            else:
                db_confirmation_sent = False
        except Exception as e:
            db_confirmation_sent = False
        
        # ============================================================================
        # SHOW SUCCESS CARD IF ALREADY CONFIRMED
        # ============================================================================
        if st.session_state.doc_confirmation_sent or db_confirmation_sent:
            st.markdown("""
            <div class="success-card">
                <div class="success-icon">🎉</div>
                <div class="success-title">Document Verification Complete!</div>
                <div class="success-message">
                    ✅ Confirmation email has been sent<br>
                    ⏰ Account activation within 3-4 business days<br>
                    📧 Check your inbox for further updates
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.info("💡 You can now close this page. We'll contact you via email once your account is activated.")
            
            if st.button("🔄 Refresh Page", use_container_width=True):
                st.rerun()
            
            st.stop()
        
        # ============================================================================
        # SHOW VALIDATION IN PROGRESS
        # ============================================================================
        if st.session_state.validation_in_progress:
            st.markdown("""
            <div class="validation-card">
                <div class="validation-icon">⏳</div>
                <div class="validation-title">Validation In Progress</div>
                <div class="validation-message">
                    🔍 Running cross-validation checks<br>
                    🏛️ Verifying documents with government database<br>
                    ⏱️ This may take 30-60 seconds...<br><br>
                    <em>Please do not close this page</em>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Auto-refresh to check status
            time.sleep(3)
            
            try:
                # Check if validation completed
                status_check = requests.get(
                    f"{BACKEND_URL}/documentupload/check-confirmation-status/{st.session_state.doc_email}",
                    timeout=10
                )
                
                if status_check.status_code == 200:
                    data = status_check.json()
                    if data.get("confirmation_sent"):
                        st.session_state.validation_in_progress = False
                        st.session_state.doc_confirmation_sent = True
                        st.rerun()
            except Exception as e:
                # Keep showing progress on error
                pass
            
            st.rerun()
        
        # ============================================================================
        # SHOW VALIDATION FAILED ERROR
        # ============================================================================
        if st.session_state.validation_failed:
            st.markdown(f"""
            <div class="error-card">
                <div class="error-icon">❌</div>
                <div class="error-title">Validation Failed</div>
                <div class="error-message">
                    {st.session_state.validation_error_message}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.session_state.validation_mismatches:
                st.error("**❌ Please fix the following issues:**")
                for mismatch in st.session_state.validation_mismatches:
                    st.write(f"• {mismatch}")
                
                st.info("💡 Please review your documents and upload corrected versions, then try again.")
            
            # Reset button
            if st.button("🔄 Try Again", use_container_width=True, type="primary"):
                st.session_state.validation_failed = False
                st.session_state.validation_error_message = ""
                st.session_state.validation_mismatches = []
                st.rerun()
            
            st.stop()
        
        # ============================================================================
        # SHOW CONFIRMATION CHECKBOX - AUTO-START ON CHECK
        # ============================================================================
        st.write("Please confirm that all document information is correct:")
        
        confirm_checkbox = st.checkbox(
            "✅ I confirm that all document information is correct and want to proceed with verification",
            key="final_confirmation"
        )
        
        # ✅ AUTO-START VALIDATION WHEN CHECKBOX IS CHECKED
        if confirm_checkbox:
            # Immediately set validation in progress
            st.session_state.validation_in_progress = True
            st.session_state.validation_failed = False
            st.session_state.validation_error_message = ""
            st.session_state.validation_mismatches = []
            
            # Trigger backend validation
            try:
                completion_response = requests.post(
                    f"{BACKEND_URL}/documentupload/send-completion-email",
                    json={"email": st.session_state.doc_email},
                    timeout=120  # 2 minutes timeout for validation
                )
                
                if completion_response.status_code == 200:
                    result = completion_response.json()
                    
                    if result.get("success"):
                        # Validation passed
                        st.session_state.validation_in_progress = False
                        st.session_state.doc_confirmation_sent = True
                        st.rerun()
                    else:
                        # Validation failed
                        st.session_state.validation_in_progress = False
                        st.session_state.validation_failed = True
                        st.session_state.validation_error_message = result.get('message', 'Validation failed. Please check your documents.')
                        st.session_state.validation_mismatches = result.get("mismatches", [])
                        st.rerun()
                else:
                    # HTTP error
                    st.session_state.validation_in_progress = False
                    st.session_state.validation_failed = True
                    
                    try:
                        error_data = completion_response.json()
                        error_detail = error_data.get('detail', 'Validation failed')
                    except:
                        error_detail = f"Server error (Status {completion_response.status_code})"
                    
                    st.session_state.validation_error_message = error_detail
                    st.rerun()
            
            except requests.exceptions.Timeout:
                st.session_state.validation_in_progress = False
                st.session_state.validation_failed = True
                st.session_state.validation_error_message = "⏱️ Validation timed out. Please try again or contact support if the issue persists."
                st.rerun()
            
            except requests.exceptions.ConnectionError:
                st.session_state.validation_in_progress = False
                st.session_state.validation_failed = True
                st.session_state.validation_error_message = "🔌 Connection error. Please check your internet connection and try again."
                st.rerun()
            
            except Exception as e:
                st.session_state.validation_in_progress = False
                st.session_state.validation_failed = True
                st.session_state.validation_error_message = f"❌ Unexpected error: {str(e)}"
                st.rerun()
        
        st.stop()
    
    # ============================================================================
    # CORPORATE MULTIPLE OWNERS - STAGE 1
    # ============================================================================
    if (account_type == "Corporate" and 
        ownership_type in ["Partnership", "Multiple Owners"] and 
        stage == "identification"):
        
        st.markdown("### 📤 Stage 1: Upload Commercial License & MOA")
        st.info("✅ Upload both documents: Commercial License and MOA")
        
        uploaded_files = st.file_uploader(
            "📎 Upload Commercial License & MOA (2 files)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="stage1_uploader"
        )
        
        if uploaded_files:
            if len(uploaded_files) == 2:
                st.success("✅ 2 files selected!")
                
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    if st.button("📤 Upload & Process", type="primary", use_container_width=True):
                        success_count = 0
                        
                        try:
                            for idx, file in enumerate(uploaded_files):
                                with st.spinner(f"Processing {file.name}..."):
                                    upload_response = requests.post(
                                        f"{BACKEND_URL}/documentupload/upload-document",
                                        data={"email": st.session_state.doc_email},
                                        files=[("files", (file.name, file.getvalue(), file.type))],
                                        timeout=600
                                    )
                                
                                if upload_response.status_code == 200:
                                    st.success(f"✅ {file.name} uploaded successfully")
                                    success_count += 1
                                else:
                                    st.error(f"❌ Failed to upload {file.name}")
                            
                            if success_count == 2:
                                st.success("🎉 Both documents uploaded!")
                                
                                with st.spinner("🔄 Processing stage transition..."):
                                    time.sleep(3)
                                    
                                    try:
                                        status_check = requests.get(
                                            f"{BACKEND_URL}/documentupload/document-status/{st.session_state.doc_email}",
                                            timeout=10
                                        )
                                        
                                        if status_check.status_code == 200:
                                            new_status = status_check.json()
                                            
                                            st.cache_data.clear()
                                            
                                            req_response = requests.post(
                                                f"{BACKEND_URL}/documentupload/get-document-requirements",
                                                json={"email": st.session_state.doc_email},
                                                timeout=10
                                            )
                                            
                                            if req_response.status_code == 200:
                                                st.session_state.doc_requirements = req_response.json()
                                                st.session_state.doc_status = new_status
                                    
                                    except Exception as e:
                                        pass
                                
                                st.success("✅ Ready for Stage 2!")
                                time.sleep(2)
                                st.rerun()
                        
                        except Exception as e:
                            st.error(f"❌ Error: {e}")
            else:
                st.warning(f"⚠️ Please upload exactly 2 files. You've selected {len(uploaded_files)}.")

    # ============================================================================
    # CORPORATE MULTIPLE OWNERS - STAGE 2
    # ============================================================================
    elif (account_type == "Corporate" and 
        ownership_type in ["Partnership", "Multiple Owners"] and 
        stage == "member_eids"):
        
        st.markdown("### 👥 Stage 2: Upload Member EIDs")
        
        # Get member list from backend
        try:
            members_response = requests.get(
                f"{BACKEND_URL}/documentupload/member-list/{st.session_state.doc_email}",
                timeout=10
            )
            
            if members_response.status_code == 200:
                members_data = members_response.json()
                all_members = members_data.get("members", [])
                
                # Get verification status from document_status
                if st.session_state.doc_status:
                    submitted_docs = st.session_state.doc_status.get("documents", [])
                    members_info = st.session_state.doc_status.get("members_info", {})
                    
                    # Get verified member names from submitted EIDs
                    verified_member_names = set()
                    for doc in submitted_docs:
                        if (doc.get("document_type", "").lower() == "eid" and 
                            doc.get("is_valid") and 
                            doc.get("member_name")):
                            verified_member_names.add(doc.get("member_name"))
                    
                    verified_count = len(verified_member_names)
                    total_count = len(all_members)
                    pending_members = [m for m in all_members if m not in verified_member_names]
                else:
                    verified_count = 0
                    total_count = len(all_members)
                    pending_members = all_members
                
                # Show progress
                st.info(f"📊 Progress: {verified_count}/{total_count} members completed")
                
                progress_pct = (verified_count / total_count * 100) if total_count > 0 else 0
                st.progress(progress_pct / 100, text=f"{verified_count}/{total_count} EIDs Verified")
                
                # Check if all done
                if len(pending_members) == 0:
                    st.success("✅ All member EIDs verified!")
                    st.info("Click 'Refresh Status' below to proceed to confirmation.")
                    st.stop()
                
                # Show current member
                current_member = pending_members[0]
                st.markdown(f"### 👤 Current Member: **{current_member}**")
                st.markdown(f"📤 Upload Emirates ID for {current_member}")
                
                # Show all members status
                with st.expander("👥 View All Members Status"):
                    for member_name in all_members:
                        is_verified = member_name in verified_member_names
                        status_icon = "✅" if is_verified else "⏳"
                        status_text = "Verified" if is_verified else "Pending"
                        st.write(f"{status_icon} **{member_name}** - {status_text}")
                
                # File uploader
                pending_count = len(pending_members)
                uploaded_eids = st.file_uploader(
                    f"📎 Upload EID(s) for {pending_count} remaining member(s)",
                    type=["pdf", "png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key="stage2_uploader",
                    help=f"Upload {current_member}'s EID first, then other pending members."
                )
                
                if uploaded_eids and len(uploaded_eids) > 0:
                    st.info(f"📎 {len(uploaded_eids)} file(s) selected")
                    
                    col1, col2, col3 = st.columns([1, 2, 1])
                    with col2:
                        if st.button("📤 Upload EID(s)", type="primary", use_container_width=True):
                            try:
                                success_count = 0
                                
                                # Process each file
                                for idx, file in enumerate(uploaded_eids):
                                    # Assign to pending members in order
                                    if idx < len(pending_members):
                                        member_name = pending_members[idx]
                                    else:
                                        st.warning(f"⚠️ More files than pending members. Skipping {file.name}")
                                        continue
                                    
                                    st.write(f"📤 Uploading **{file.name}** for {member_name}...")
                                    
                                    with st.spinner(f"Processing {file.name}..."):
                                        upload_response = requests.post(
                                            f"{BACKEND_URL}/documentupload/upload-document",
                                            data={
                                                "email": st.session_state.doc_email,
                                                "member_name": member_name
                                            },
                                            files=[("files", (file.name, file.getvalue(), file.type))],
                                            timeout=600
                                        )
                                    
                                    if upload_response.status_code == 200:
                                        st.success(f"✅ {member_name} - {file.name} uploaded successfully")
                                        success_count += 1
                                    else:
                                        error_data = upload_response.json()
                                        error_msg = error_data.get("detail", "Unknown error")
                                        st.error(f"❌ Failed to upload {file.name}: {error_msg}")
                                
                                if success_count > 0:
                                    st.success(f"✅ {success_count} file(s) uploaded successfully!")
                                    st.info("🔄 Refreshing status...")
                                    time.sleep(2)
                                    st.rerun()
                            
                            except Exception as e:
                                st.error(f"❌ Error uploading: {str(e)}")
                                import traceback
                                st.text(traceback.format_exc())
                else:
                    st.info(f"👆 Select {current_member}'s Emirates ID to continue")
            
            else:
                st.error("❌ Failed to load member list")
                st.text(f"Status Code: {members_response.status_code}")
        
        except Exception as e:
            st.error(f"❌ Error loading member information: {str(e)}")
            import traceback
            st.text(traceback.format_exc())

    # ============================================================================
    # ALL OTHER ACCOUNT TYPES - BULK UPLOAD
    # ============================================================================
    else:
        st.markdown("### 📤 Upload Your Documents")
        
        required_docs = st.session_state.doc_requirements.get("required_documents", [])
        st.info(f"📋 Required: {', '.join(required_docs)}")
        
        uploaded_files = st.file_uploader(
            f"📎 Upload all {len(required_docs)} document(s)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="bulk_uploader"
        )
        
        if uploaded_files:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("📤 Upload All Documents", type="primary", use_container_width=True):
                    try:
                        for idx, file in enumerate(uploaded_files):
                            with st.spinner(f"Processing {file.name}..."):
                                upload_response = requests.post(
                                    f"{BACKEND_URL}/documentupload/upload-document",
                                    data={"email": st.session_state.doc_email},
                                    files=[("files", (file.name, file.getvalue(), file.type))],
                                    timeout=600
                                )
                            
                            if upload_response.status_code == 200:
                                st.success(f"✅ {file.name} uploaded")
                            else:
                                st.error(f"❌ Failed to upload {file.name}")
                        
                        st.info("🔄 Refreshing status...")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
    
    # ============================================================================
    # HELP SECTION
    # ============================================================================
    st.markdown("---")

    if st.button("🔄 Refresh Status", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
