# 🏦 Thrivv Bank AI Customer Onboarding System
# **Powered by LLAMA AI • Built with Streamlit • Secure & Scalable**

import streamlit as st

# --- PAGE SETTINGS - MUST BE FIRST ---
st.set_page_config(
    page_title="AI Customer Onboarding Agent",
    layout="wide",
    initial_sidebar_state="expanded"
)

import os
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import base64
import requests
from supabase import create_client
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import smtplib
from dotenv import load_dotenv
import imaplib
import email
from email.header import decode_header
from typing import List, Dict
import time
import plotly.express as px
import plotly.graph_objects as go
import threading
import json
import logging
import numpy as np
from email import policy
import email.utils

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- LOAD CONFIG ---
load_dotenv()

# API Configuration
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

# Database Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

# Email Configuration
FROM_EMAIL = os.getenv("FROM_EMAIL")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

# AI Configuration
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = os.getenv("LLAMA_MODEL_NAME", "qwen/qwen2.5-vl-32b-instruct:free")

# Initialize Supabase
if SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    st.error("⚠️ Supabase configuration missing. Please check your environment variables.")

# --- INITIALIZE SESSION STATE ---
if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

# --- SIDEBAR AUTHENTICATION (UPDATED FOR EMAIL SYSTEM) ---
with st.sidebar:
    
    if not st.session_state.get("admin_authenticated", False):
        st.markdown("### 🔐 Admin Login")
        st.markdown("*Required for Email System, Users, and Settings*")  # Updated
        
        with st.form("admin_login_form"):
            username = st.text_input("Username (Email)")
            password = st.text_input("Password", type="password")
            login_clicked = st.form_submit_button("🚀 Login")
            
            if login_clicked:
                if username == "Admin@thrivvai.com" and password == "Admin@123":
                    st.session_state["admin_authenticated"] = True
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error("❌ Invalid credentials")
    else:
        st.success("✅ **Admin Authenticated**")
        st.markdown(f"Welcome, Admin!")
        if st.button("🚪 Logout"):
            st.session_state["admin_authenticated"] = False
            st.rerun()


# --- API HELPER FUNCTIONS ---
def make_api_call(endpoint, method="GET", data=None, timeout=30):
    """Generic API call function with error handling"""
    try:
        url = f"{FASTAPI_BASE_URL}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        if method == "GET":
            response = requests.get(url, timeout=timeout)
        elif method == "POST":
            response = requests.post(url, json=data, headers=headers, timeout=timeout)
        elif method == "PUT":
            response = requests.put(url, json=data, headers=headers, timeout=timeout)
        elif method == "DELETE":
            response = requests.delete(url, timeout=timeout)
        else:
            return False, f"Unsupported method: {method}"
        
        if response.status_code == 200:
            return True, response.json()
        elif response.status_code == 404:
            return False, "Resource not found"
        elif response.status_code == 409:
            return False, "Conflict - resource already exists"
        else:
            return False, f"API Error {response.status_code}: {response.text}"
            
    except requests.exceptions.Timeout:
        return False, "Request timeout - API server may be down"
    except requests.exceptions.ConnectionError:
        return False, "Connection error - API server may be down"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

# --- DASHBOARD FUNCTIONS ---
def get_dashboard_stats():
    """Get dashboard statistics from API"""
    success, data = make_api_call("/dashboard/stats")
    if success:
        return data
    else:
        logger.error(f"Failed to get dashboard stats: {data}")
        return {
            "total_users": 1,
            "verified_users": 1,
            "pending_verification": 1,
            "users_registered_today": 1,
            "avg_confidence": 77.0
        }

def get_registration_trend():
    """Get 7-day registration trend"""
    success, data = make_api_call("/dashboard/registration-trend")
    if success:
        return data.get("trend_data", [])
    else:
        # Mock data matching the image
        return [
            {"date": "08/20", "registrations": 0},
            {"date": "08/21", "registrations": 0},
            {"date": "08/22", "registrations": 0},
            {"date": "08/23", "registrations": 0},
            {"date": "08/24", "registrations": 0},
            {"date": "08/25", "registrations": 0},
            {"date": "08/26", "registrations": 1}
        ]

def get_verification_status():
    """Get verification status distribution"""
    success, data = make_api_call("/dashboard/verification-status")
    if success:
        return data
    else:
        return {
            "pending": 1,
            "verified": 0,
            "pending_percentage": 100.0,
            "verified_percentage": 0.0
        }

def get_ai_performance():
    """Get AI performance metrics"""
    success, data = make_api_call("/dashboard/ai-performance")
    if success:
        return data
    else:
        # Mock trending data
        mock_data = []
        for i in range(30):
            date_str = f"Aug {i+1}"
            progress = i / 29.0
            mock_data.append({
                'date': date_str,
                'avg_confidence': round(77 + (progress * 3), 1),
                'auto_verified': round(60 + (progress * 20), 1),
                'avg_time': round(3.2 - (progress * 0.2), 1),
                'escalation_rate': round(5.0 - (progress * 3), 1)
            })
        
        return {
            "performance_data": mock_data,
            "summary": {"avg_confidence": 77.0, "auto_verified": 60.0, "avg_time": 3.2, "escalation_rate": 2.0}
        }

def get_customer_status():
    """Get customer onboarding status"""
    success, data = make_api_call("/dashboard/customer-status")
    if success:
        return data.get("customers", []), data.get("total", 0)
    else:
        return [], 0

# --- CHATBOT FUNCTIONS ---
def chatbot_query(query):
    """Send query to chatbot API with enhanced timeout handling"""
    try:
        # Increased timeout to match backend
        response = requests.post(
            f"{FASTAPI_BASE_URL}/chatbot/query",
            json={"query": query},
            headers={"Content-Type": "application/json"},
            timeout=150  # 150 seconds to allow for backend processing
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("response", "I apologize, but I'm experiencing technical difficulties.")
        else:
            logger.error(f"Chatbot API error: {response.status_code} - {response.text}")
            return "I apologize, but I'm experiencing technical difficulties. Please try again later."
            
    except requests.exceptions.Timeout:
        logger.error("Frontend chatbot request timeout")
        return "⏰ The request is taking longer than expected. Please try asking a shorter question or try again later."
    except Exception as e:
        logger.error(f"Chatbot query failed: {e}")
        return "I apologize, but I'm experiencing technical difficulties. Please try again later."



# --- EMAIL FUNCTIONS ---
def get_unread_emails():
    """Get unread emails from API"""
    success, data = make_api_call("/email/unread")
    if success:
        return data.get("emails", []), data.get("count", 0)
    else:
        logger.error(f"Failed to get unread emails: {data}")
        return [], 0

def send_email_api(to_email, subject, body):
    """Send email via API"""
    success, data = make_api_call("/email/send", method="POST", data={
        "to_email": to_email,
        "subject": subject,
        "body": body
    })
    return success, data

def get_email_statistics():
    """Get email statistics from API"""
    success, data = make_api_call("/email/statistics")
    if success:
        return data
    else:
        logger.error(f"Failed to get email statistics: {data}")
        return {
            "total_emails": 0,
            "sent_emails": 0,
            "received_emails": 0,
            "daily_data": []
        }

def get_email_templates():
    """Get email templates from API"""
    success, data = make_api_call("/email/templates")
    if success:
        return data.get("templates", {})
    else:
        logger.error(f"Failed to get email templates: {data}")
        return {}

# --- USER MANAGEMENT FUNCTIONS ---
def get_all_users():
    """Get all users from API"""
    success, data = make_api_call("/users/all")
    if success:
        return data.get("users", []), data.get("total", 0)
    else:
        logger.error(f"Failed to get all users: {data}")
        return [], 0

def get_user_by_id(user_id):
    """Get specific user details from API"""
    success, data = make_api_call(f"/users/{user_id}")
    if success:
        return data
    else:
        logger.error(f"Failed to get user {user_id}: {data}")
        return None

def update_user(user_id, update_data):
    """Update user via API"""
    success, data = make_api_call(f"/users/{user_id}", method="PUT", data=update_data)
    return success, data

def delete_user(user_id):
    """Delete user via API"""
    success, data = make_api_call(f"/users/{user_id}", method="DELETE")
    return success, data

# --- REGISTRATION FUNCTION ---
def register_user(user_data):
    """Register user via API"""
    success, data = make_api_call("/register", method="POST", data=user_data)
    return success, data

# --- SYSTEM FUNCTIONS ---
def get_system_status():
    """Get system status from API"""
    success, data = make_api_call("/settings/system-status")
    if success:
        return data.get("system_status", [])
    else:
        logger.error(f"Failed to get system status: {data}")
        return []

# --- ADMIN ACCESS CHECK ---
def is_admin_authenticated():
    """Simple check for admin authentication"""
    return st.session_state.get("admin_authenticated", False)

# --- UI STYLING ---
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
    }
    
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        border-left: 4px solid #667eea;
    }
    
    .status-active {
        color: #28a745;
        font-weight: bold;
    }
    
    .status-down {
        color: #dc3545;
        font-weight: bold;
    }
    
    .user-card {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 1rem;
    }
    
    .chat-message {
        padding: 0.5rem 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
    }
    
    .user-message {
        background-color: #e3f2fd;
        text-align: right;
    }
    
    .bot-message {
        background-color: #f5f5f5;
        text-align: left;
    }
    
    .access-denied {
        text-align: center;
        padding: 2rem;
        background-color: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 10px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# --- MAIN HEADER ---
st.markdown("""
<div class="main-header">
    <h1>🏦 Thrivv Bank AI Customer Onboarding System</h1>
    <p><strong>Powered by LLAMA AI • Built with Streamlit • Secure & Scalable</strong></p>
</div>
""", unsafe_allow_html=True)

# --- NAVIGATION TABS ---
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📝 Register User", 
    "📊 Dashboard", 
    "🤖 AI Chatbot", 
    "📧 Email System 🔒",  
    "👥 Users 🔒",         
    "⚙️ Settings"
])

# --- TAB 1: REGISTER USER ---
with tab1:
    st.header("📬 Register a New User")
    
    with st.form("register_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("Full Name *")
            dob = st.date_input(
                "Date of Birth *", 
                value=date(1990, 1, 1), 
                min_value=date(1920, 1, 1), 
                max_value=date(2006, 12, 31)
            )
            email = st.text_input("Email *")
        
        with col2:
            phone_number = st.text_input("Phone Number *")
            business_name = st.text_input("Business Name *")
            
        submitted = st.form_submit_button("🚀 Register User", use_container_width=True)
        
        if submitted:
            if not all([name, phone_number, email, business_name]):
                st.error("⚠️ Please fill all required fields.")
            else:
                with st.spinner("Registering user..."):
                    user_data = {
                        "name": name,
                        "dob": dob.isoformat(),
                        "phone_number": phone_number,
                        "email": email,
                        "business_name": business_name,
                    }
                    
                    success, result = register_user(user_data)
                    
                    if success:
                        st.success("✅ User registered successfully and onboarding email sent!")
                        st.json(result)
                    else:
                        if "already registered" in str(result).lower():
                            st.error("❌ Email already registered.")
                        else:
                            st.error(f"❌ Registration failed: {result}")

# --- TAB 2: DASHBOARD ---
with tab2:
    st.header("📊 Dashboard")
    
    # Auto-refresh button
    col1, col2, col3 = st.columns([1, 1, 8])
    with col1:
        if st.button("🔄 Refresh Dashboard"):
            st.rerun()
    
    # Get real-time data
    with st.spinner("Loading dashboard data..."):
        stats = get_dashboard_stats()
        
    # ROW 1: KPI Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="👥 Total Customers",
            value=stats["total_users"],
            delta="No change"
        )
    
    with col2:
        st.metric(
            label="⏳ Pending Verification",
            value=stats["pending_verification"],
            delta="All up to date"
        )
    
    with col3:
        st.metric(
            label="✅ Verified Today",
            value=stats["users_registered_today"],
            delta="0% verification rate"
        )
    
    with col4:
        st.metric(
            label="🤖 Average AI Confidence",
            value=f"{stats['avg_confidence']}%",
            delta="No issues"
        )
    
    # ROW 2: 7-Day Registration Trend
    st.subheader("📈 7-Day Registration Trend")
    
    trend_data = get_registration_trend()
    if trend_data:
        df_trend = pd.DataFrame(trend_data)
        
        fig_trend = px.line(
            df_trend, 
            x='date', 
            y='registrations',
            title='7-Day Registration Trend'
        )
        fig_trend.update_traces(line_color='#667eea')
        fig_trend.update_layout(
            showlegend=False,
            height=300,
            xaxis_title="Date",
            yaxis_title="Registrations"
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    
    # ROW 3: User Verification Status + AI Performance
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 User Verification Status")
        
        verification_data = get_verification_status()
        
        # Create donut chart
        fig_donut = go.Figure(data=[go.Pie(
            labels=['Pending', 'Verified'],
            values=[verification_data['pending'], verification_data['verified']],
            hole=.6,
            marker_colors=['#FFA500', '#28a745']  # Orange and Green like in image
        )])
        
        fig_donut.update_layout(
            showlegend=True,
            height=400,
            annotations=[dict(text=f"{verification_data['pending_percentage']:.0f}%", 
                            x=0.5, y=0.5, font_size=24, showarrow=False)]
        )
        st.plotly_chart(fig_donut, use_container_width=True)
    
    with col2:
        st.subheader("📊 AI Verification Performance - Last 30 Days")
        
        ai_performance = get_ai_performance()
        performance_data = ai_performance['performance_data'][-30:]  # Last 30 days
        summary = ai_performance['summary']
        
        # Create multi-line chart
        df_performance = pd.DataFrame(performance_data)
        
        fig_performance = go.Figure()
        
        # Add traces for each metric
        fig_performance.add_trace(go.Scatter(
            x=df_performance['date'], 
            y=df_performance['avg_confidence'],
            mode='lines',
            name='Avg. Confidence (%)',
            line=dict(color='#FF6B6B')
        ))
        
        fig_performance.add_trace(go.Scatter(
            x=df_performance['date'], 
            y=df_performance['auto_verified'],
            mode='lines',
            name='Auto-verified (%)',
            line=dict(color='#4ECDC4')
        ))
        
        fig_performance.add_trace(go.Scatter(
            x=df_performance['date'], 
            y=df_performance['avg_time'],
            mode='lines',
            name='Avg. Time (h)',
            line=dict(color='#45B7D1'),
            yaxis='y2'
        ))
        
        fig_performance.add_trace(go.Scatter(
            x=df_performance['date'], 
            y=df_performance['escalation_rate'],
            mode='lines',
            name='Escalation Rate (%)',
            line=dict(color='#96CEB4'),
            yaxis='y2'
        ))
        
        fig_performance.update_layout(
            height=350,
            xaxis_title="Date",
            yaxis=dict(title="Percentage (%)", side="left"),
            yaxis2=dict(title="Time (h) / Rate (%)", side="right", overlaying="y"),
            legend=dict(x=0, y=1, bgcolor='rgba(255,255,255,0.8)')
        )
        
        st.plotly_chart(fig_performance, use_container_width=True)
        
        # Summary metrics
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("Avg. Confidence", f"{summary['avg_confidence']}%")
        with col_b:
            st.metric("Auto-verified", f"{summary['auto_verified']}%")
        with col_c:
            st.metric("Avg. Time", f"{summary['avg_time']}h")
        with col_d:
            st.metric("Escalation Rate", f"{summary['escalation_rate']}%")
    
    # ROW 4: Customer Onboarding Status
    st.subheader("👥 Customer Onboarding Status")
    
    customers, total_customers = get_customer_status()
    
    if customers:
        # Filter options
        col1, col2 = st.columns([1, 3])
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                options=["All (1)", "Docs Pending (1)"],
                key="dashboard_status_filter"
            )
        
        # Pagination
        st.write("Page")
        page_selector = st.selectbox("", options=[1], key="dashboard_page")
        
        # Customer table
        for customer in customers[:10]:  # Show first 10 customers
            col1, col2, col3, col4, col5, col6 = st.columns([1, 2, 1.5, 1, 1.5, 1])
            
            with col1:
                # Avatar
                st.image(customer['avatar'], width=50)
            
            with col2:
                st.markdown(f"**{customer['customer']}**")
                st.markdown(f"📧 {customer['email']}")
            
            with col3:
                status_color = "🟡" if customer['status'] == 'Docs Pending' else "🟢"
                st.markdown(f"{status_color} **{customer['status']}**")
            
            with col4:
                # AI Confidence progress bar
                confidence = customer['ai_confidence']
                st.progress(confidence / 100)
                st.text(f"{confidence}%")
            
            with col5:
                # Document flags
                if customer['flags']:
                    st.text("⚠️ " + ", ".join(customer['flags']))
                else:
                    st.text("✅ No flags")
            
            with col6:
                st.text(f"⏱️ {customer['time_in_stage']}")
                # Action buttons
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("👁️", key=f"view_{customer['email'][:5]}"):
                        pass
                with col_b:
                    if st.button("🗑️", key=f"delete_{customer['email'][:5]}"):
                        pass
            
            st.divider()
        
        st.text(f"Showing 1 of 1 customers (Page 1 of 1)")
    else:
        st.info("No customers found. Register your first customer in the Registration tab.")

# --- TAB 3: AI CHATBOT ---

with tab3:
    st.header("🤖 AI Banking Assistant")
    st.markdown("Ask me anything about Thrivv Bank account opening, documents, or banking services!")
    
    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # File uploader for image attachments
    st.subheader("📎 Attach Images (Optional)")
    uploaded_files = st.file_uploader(
        "Upload images for document analysis (PNG, JPG, JPEG, WEBP)", 
        type=["png", "jpg", "jpeg", "webp"], 
        accept_multiple_files=True,
        key="chatbot_file_uploader",
        help="Upload Emirates ID, Trade License, or other banking documents for analysis"
    )
    
    # Display uploaded files info
    if uploaded_files:
        st.info(f"📁 {len(uploaded_files)} file(s) selected: {', '.join([f.name for f in uploaded_files])}")
    
    # Chat interface 
    with st.container():
        # Display chat history
        for i, message in enumerate(st.session_state.chat_history):
            if message["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(message["content"])
            else:
                with st.chat_message("assistant"):
                    st.markdown(message["content"])
    
    # Chat input
    with st.form("chat_form_with_attachments", clear_on_submit=True):
        user_input = st.text_input(
            "Type your question here...", 
            placeholder="e.g., What documents do I need for a corporate account?",
            key="chatbot_input_with_files"
        )
        
        col1, col2 = st.columns([4, 1])
        
        with col1:
            submitted = st.form_submit_button("Send 📤", use_container_width=True)
        
        with col2:
            if st.form_submit_button("Clear Chat 🗑️"):
                st.session_state.chat_history = []
                st.rerun()
    
    # Process input and attachments
    if submitted:
        if not user_input.strip() and not uploaded_files:
            st.warning("⚠️ Please enter a message or upload at least one image.")
        else:
            # Add user message to history
            if user_input.strip():
                st.session_state.chat_history.append({"role": "user", "content": user_input})
            
            # Add file attachment info
            if uploaded_files:
                for file in uploaded_files:
                    st.session_state.chat_history.append({
                        "role": "user", 
                        "content": f"📎 Attached: {file.name}"
                    })
            
            # FIXED API Call
            with st.spinner("🤖 Processing..."):
                try:
                    api_url = f"{FASTAPI_BASE_URL}/chatbot/query"
                    
                    if uploaded_files:
                        # Use multipart/form-data for file uploads
                        files_for_api = []
                        for file in uploaded_files:
                            files_for_api.append(
                                ("files", (file.name, file.getvalue(), file.type))
                            )
                        
                        # Send as form data
                        data = {"query": user_input.strip() or "Please analyze the attached images"}
                        response = requests.post(api_url, data=data, files=files_for_api, timeout=60)
                    else:
                        # Use JSON for text-only requests
                        headers = {"Content-Type": "application/json"}
                        payload = {"query": user_input.strip()}
                        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
                    
                    if response.status_code == 200:
                        result = response.json()
                        ai_response = result.get("response", "Sorry, I couldn't process your request.")
                    elif response.status_code == 422:
                        ai_response = "❌ Request format error. Please try again."
                    else:
                        ai_response = f"❌ Error ({response.status_code}): Please try again."
                        
                except requests.exceptions.Timeout:
                    ai_response = "⏰ Request timed out. Please try again."
                except Exception as e:
                    ai_response = f"❌ Connection error: {str(e)}"
            
            # Add AI response
            st.session_state.chat_history.append({"role": "assistant", "content": ai_response})
            st.rerun()
    
    # Quick questions - ENHANCED
    st.subheader("💡 Quick Questions")
    quick_questions = [
        "What types of corporate accounts do you offer?",
        "What documents do I need for account opening?",
        "How long does account approval take?",
        "What are the minimum balance requirements?",
        "Can non-residents open corporate accounts?",
        "What is a board resolution and why is it needed?"
    ]
    
    cols = st.columns(3)  # Changed to 3 columns for better layout
    for i, question in enumerate(quick_questions):
        col_idx = i % 3
        with cols[col_idx]:
            if st.button(question, key=f"chatbot_quick_{i}", use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": question})
                with st.spinner("🤖 Thinking..."):
                    try:
                        # Make simple API call for quick questions
                        headers = {"Content-Type": "application/json"}
                        response = requests.post(
                            f"{FASTAPI_BASE_URL}/chatbot/query", 
                            json={"query": question}, 
                            headers=headers,
                            timeout=30
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            ai_response = result.get("response", "I apologize, but I couldn't process your request.")
                        else:
                            ai_response = "Unable to get response. Please try again."
                    except Exception as e:
                        ai_response = "Connection error. Please check your internet connection."
                
                st.session_state.chat_history.append({"role": "assistant", "content": ai_response})
                st.rerun()
    
    # Help section - ADDED
    with st.expander("ℹ️ How to use the AI Assistant"):
        st.markdown("""
        **Text Questions:**
        - Ask any question about corporate banking in the UAE
        - Get information about account types, requirements, and procedures
        
        **Image Attachments:**
        - Upload Emirates ID, Trade License, or other banking documents
        - Get document analysis and verification guidance
        - Supported formats: PNG, JPG, JPEG, WEBP
        - Maximum file size: 10MB per image
        
        **Tips:**
        - Be specific in your questions for better answers
        - Upload clear, readable images for accurate analysis
        - You can ask follow-up questions based on previous responses
        """)

# --- ADDITIONAL HELPER FUNCTION (ADD AFTER THE CHATBOT FUNCTIONS) ---
def chatbot_query_with_files(query, files=None):
    """Enhanced chatbot query function that supports file attachments"""
    try:
        api_url = f"{FASTAPI_BASE_URL}/chatbot/query"
        
        if files:
            # Use form data for file uploads
            files_for_api = []
            for file in files:
                files_for_api.append(
                    ("files", (file.name, file.getvalue(), file.type))
                )
            
            data = {"query": query}
            response = requests.post(api_url, data=data, files=files_for_api, timeout=60)
        else:
            # Use JSON for text-only queries
            headers = {"Content-Type": "application/json"}
            response = requests.post(api_url, json={"query": query}, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "I apologize, but I couldn't process your request.")
        else:
            return f"API Error ({response.status_code}): Unable to get response."
            
    except Exception as e:
        logger.error(f"Chatbot query with files failed: {e}")
        return f"Error: {str(e)}"

# --- TAB 4: EMAIL SYSTEM ---
with tab4:
    if is_admin_authenticated():  
        st.header("📧 Email Management System")
        
        # Email statistics
        with st.spinner("Loading email statistics..."):
            email_stats = get_email_statistics()
        
        st.subheader("📊 Email Statistics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Emails", email_stats["total_emails"])
        with col2:
            st.metric("Sent Emails", email_stats["sent_emails"])
        with col3:
            st.metric("Received Emails", email_stats["received_emails"])
        
        # Email activity chart
        if email_stats["daily_data"]:
            df_emails = pd.DataFrame(email_stats["daily_data"])
            fig = px.bar(
                df_emails, 
                x='date', 
                y=['sent', 'received'],
                title='Daily Email Activity (Last 7 Days)',
                barmode='group'
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Unread emails
        st.subheader("📬 Unread Emails")
        with st.spinner("Fetching unread emails..."):
            unread_emails, count = get_unread_emails()
        
        if count > 0:
            st.success(f"Found {count} unread emails")
            
            for i, email_item in enumerate(unread_emails):
                with st.expander(f"From: {email_item['from']} - {email_item['subject'][:50]}..."):
                    st.markdown(f"**From:** {email_item['from']}")
                    st.markdown(f"**Subject:** {email_item['subject']}")
                    st.markdown(f"**Date:** {email_item.get('timestamp', 'Unknown')}")
                    st.markdown("**Message:**")
                    st.text(email_item['body'])
        else:
            st.info("📭 No unread emails found")
        
        # Send email interface
        st.subheader("✉️ Send Email")
        
        # Email templates
        templates = get_email_templates()
        
        with st.form("send_email_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                to_email = st.text_input("To Email")
                template_choice = st.selectbox(
                    "Use Template", 
                    options=["Custom"] + list(templates.keys())
                )
            
            with col2:
                subject = st.text_input("Subject")
                if template_choice != "Custom" and template_choice in templates:
                    st.info(f"Template: {template_choice}")
            
            # Email body
            if template_choice != "Custom" and template_choice in templates:
                body = st.text_area(
                    "Message", 
                    value=templates[template_choice]["body"], 
                    height=200
                )
            else:
                body = st.text_area("Message", height=200)
            
            if st.form_submit_button("📤 Send Email"):
                if to_email and subject and body:
                    with st.spinner("Sending email..."):
                        success, result = send_email_api(to_email, subject, body)
                    
                    if success:
                        st.success("✅ Email sent successfully!")
                    else:
                        st.error(f"❌ Failed to send email: {result}")
                else:
                    st.error("Please fill all fields")
    else:
        # Access denied message for Email System
        st.markdown("""
        <div class="access-denied">
            <h3>🔒 Admin Access Required</h3>
            <p>Please login using the sidebar to access the Email Management System.</p>
            <p>Email management contains sensitive customer communication data and requires administrative privileges.</p>
            <p><strong>Why Admin Access?</strong></p>
            <ul style="text-align: left; display: inline-block;">
                <li>🔐 Access to customer email conversations</li>
                <li>📧 Ability to send emails on behalf of the bank</li>
                <li>📊 View email statistics and analytics</li>
                <li>👀 Read unread customer communications</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)


# --- TAB 5: USERS (ADMIN ONLY) ---
with tab5:
    if is_admin_authenticated():
        st.header("👥 Customer Management")
        
        # Get all users
        with st.spinner("Loading users..."):
            all_users, total_count = get_all_users()
        
        st.subheader(f"📋 All Users ({total_count})")
        
        if all_users:
            # Search and filter
            col1, col2, col3 = st.columns(3)
            
            with col1:
                search_users = st.text_input(
                    "🔍 Search users", 
                    placeholder="Name or email..."
                )
            
            with col2:
                status_filter = st.selectbox(
                    "Filter by Status", 
                    options=["All"] + list(set([user["onboarding_step"] for user in all_users]))
                )
            
            with col3:
                sort_by = st.selectbox(
                    "Sort by", 
                    options=["created_at", "name", "onboarding_step"]
                )
            
            # Filter users
            filtered_users = all_users
            
            if search_users:
                filtered_users = [
                    user for user in filtered_users
                    if search_users.lower() in user["name"].lower() or 
                       search_users.lower() in user["email"].lower()
                ]
            
            if status_filter != "All":
                filtered_users = [
                    user for user in filtered_users 
                    if user["onboarding_step"] == status_filter
                ]
            
            # Display users
            for i, user in enumerate(filtered_users):
                with st.expander(f"{user['name']} - {user['email']} - {user['onboarding_step']}"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"**Name:** {user['name']}")
                        st.markdown(f"**Email:** {user['email']}")
                        st.markdown(f"**Phone:** {user['phone_number']}")
                        st.markdown(f"**Business:** {user['business_name']}")
                        st.markdown(f"**DOB:** {user['dob']}")
                    
                    with col2:
                        st.markdown(f"**Status:** {user['onboarding_step']}")
                        st.markdown(f"**Created:** {user['created_at'][:10]}")
                        st.markdown(f"**Conversations:** {user['conversation_count']}")
                        st.markdown(f"**Documents:** {'✅' if user['has_documents'] else '❌'}")
                        st.markdown(f"**Last Activity:** {user['last_activity'][:10] if user['last_activity'] else 'N/A'}")
                    
                    # User actions
                    action_col1, action_col2, action_col3 = st.columns(3)
                    
                    with action_col1:
                        if st.button(f"View Details", key=f"users_view_{user['id']}_{i}"):
                            st.session_state.selected_user_id = user['id']
                            st.rerun()
                    
                    with action_col2:
                        new_status = st.selectbox(
                            "Update Status", 
                            options=["welcome", "document_verification", "verification_complete"],
                            index=["welcome", "document_verification", "verification_complete"].index(user['onboarding_step']),
                            key=f"users_status_{user['id']}_{i}"
                        )
                        
                        if st.button(f"Update", key=f"users_update_{user['id']}_{i}"):
                            success, result = update_user(user['id'], {"onboarding_step": new_status})
                            if success:
                                st.success("User updated!")
                                st.rerun()
                            else:
                                st.error(f"Update failed: {result}")
                    
                    with action_col3:
                        if st.button(f"🗑️ Delete", key=f"users_delete_{user['id']}_{i}"):
                            if st.checkbox(f"Confirm delete {user['name']}", key=f"users_confirm_{user['id']}_{i}"):
                                success, result = delete_user(user['id'])
                                if success:
                                    st.success("User deleted!")
                                    st.rerun()
                                else:
                                    st.error(f"Delete failed: {result}")
        else:
            st.info("No users found.")
        
        # Show detailed user view if selected
        if hasattr(st.session_state, 'selected_user_id'):
            st.subheader("👤 User Details")
            user_details = get_user_by_id(st.session_state.selected_user_id)
            
            if user_details:
                user = user_details["user"]
                conversations = user_details["conversations"]
                documents = user_details["documents"]
                
                # User info
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### Basic Information")
                    st.json(user)
                
                with col2:
                    st.markdown("### Statistics")
                    st.metric("Conversations", len(conversations))
                    st.metric("Documents", len(documents))
                
                # Conversations
                if conversations:
                    st.markdown("### Conversation History")
                    for j, conv in enumerate(conversations[-10:]):  # Last 10 conversations
                        role_icon = "👤" if conv["role"] == "user" else "🤖"
                        st.markdown(f"**{role_icon} {conv['role'].title()}** ({conv['timestamp'][:19]})")
                        st.text(conv["message"][:200] + "..." if len(conv["message"]) > 200 else conv["message"])
                        st.divider()
                
                # Documents
                if documents:
                    st.markdown("### Documents")
                    for k, doc in enumerate(documents):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.text(doc["filename"])
                        with col2:
                            st.text(f"{doc['size']} bytes")
                        with col3:
                            st.text(doc["type"])
    else:
        st.markdown("""
        <div class="access-denied">
            <h3>🔒 Admin Access Required</h3>
            <p>Please login using the sidebar to access Customer Management.</p>
            <p>Only administrators can view and manage customer data for security and privacy reasons.</p>
        </div>
        """, unsafe_allow_html=True)

# --- TAB 6: SETTINGS ---
with tab6:
    st.header("⚙️ Settings")
    
    # System Health Monitor (moved from Dashboard)
    st.subheader("🔧 System Health Monitor")
    
    with st.spinner("Checking system status..."):
        system_status = get_system_status()
    
    if system_status:
        for item in system_status:
            component = item["component"]
            status = item["status"]
            message = item["message"]
            details = item.get("details", "")
            
            with st.container():
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    if status == "Active":
                        st.success(f"**{component}**: {message}")
                        if details:
                            st.text(f"Details: {details}")
                    else:
                        st.error(f"**{component}**: {message}")
                        if details:
                            st.text(f"Details: {details}")
                
                with col2:
                    status_color = "🟢" if status == "Active" else "🔴"
                    st.markdown(f"<h3 style='text-align: center;'>{status_color}</h3>", unsafe_allow_html=True)
    else:
        st.error("Failed to get system status")
    
    st.divider()
    
    # Configuration view
    st.subheader("📋 System Configuration")
    
    with st.spinner("Loading configuration..."):
        success, config_data = make_api_call("/settings/configuration")
    
    if success:
        config = config_data.get("configuration", {})
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Database & API Settings")
            st.text(f"Supabase URL: {config.get('supabase_url', 'Not set')}")
            st.text(f"LLAMA Model: {config.get('llama_model', 'Not set')}")
            st.text(f"Documents Root: {config.get('documents_root', 'Not set')}")
        
        with col2:
            st.markdown("### Email Settings")
            st.text(f"SMTP Server: {config.get('smtp_server', 'Not set')}")
            st.text(f"SMTP Port: {config.get('smtp_port', 'Not set')}")
            st.text(f"IMAP Host: {config.get('imap_host', 'Not set')}")
            st.text(f"IMAP Port: {config.get('imap_port', 'Not set')}")
        
        st.markdown("### API Keys Status")
        api_keys = config.get('api_keys_configured', {})
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            status = "✅ Configured" if api_keys.get('supabase') else "❌ Not Set"
            st.markdown(f"**Supabase API Key:** {status}")
        
        with col2:
            status = "✅ Configured" if api_keys.get('openrouter') else "❌ Not Set"
            st.markdown(f"**OpenRouter API Key:** {status}")
        
        with col3:
            status = "✅ Configured" if api_keys.get('smtp_password') else "❌ Not Set"
            st.markdown(f"**SMTP Password:** {status}")
    else:
        st.error(f"Failed to load configuration: {config_data}")
    
    st.divider()
    
    # API Connection Test
    st.subheader("🧪 Connection Tests")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Test Database Connection"):
            with st.spinner("Testing database..."):
                if supabase:
                    try:
                        response = supabase.table("users").select("count", count="exact").execute()
                        st.success(f"✅ Database connected! Found {response.count or 0} users.")
                    except Exception as e:
                        st.error(f"❌ Database test failed: {str(e)}")
                else:
                    st.error("❌ Supabase not configured")
    
    with col2:
        if st.button("Test Email Service"):
            with st.spinner("Testing email..."):
                success, result = make_api_call("/settings/system-status")
                if success:
                    email_status = next((item for item in result["system_status"] 
                                       if "Email" in item["component"]), None)
                    if email_status:
                        if email_status["status"] == "Active":
                            st.success("✅ Email service working!")
                        else:
                            st.error(f"❌ {email_status['message']}")
                else:
                    st.error("❌ Could not test email service")
    
    with col3:
        if st.button("Test AI API"):
            with st.spinner("Testing AI API..."):
                test_response = chatbot_query("Hello, this is a test.")
                if "technical difficulties" not in test_response:
                    st.success("✅ AI API working!")
                else:
                    st.error("❌ AI API test failed")
    
    # System Information
    st.divider()
    st.subheader("ℹ️ System Information")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Application Info")
        st.text(f"FastAPI Base URL: {FASTAPI_BASE_URL}")
        st.text(f"Streamlit Version: {st.__version__}")
        st.text(f"Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    with col2:
        st.markdown("### Environment")
        st.text(f"SUPABASE_URL: {'✓ Set' if SUPABASE_URL else '✗ Not Set'}")
        st.text(f"OPENROUTER_API_KEY: {'✓ Set' if LLAMA_API_KEY else '✗ Not Set'}")
        st.text(f"SMTP Configuration: {'✓ Set' if all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD]) else '✗ Incomplete'}")

# --- FOOTER ---
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; padding: 1rem;'>
    <p>🏦 <strong>Thrivv Bank AI Customer Onboarding System</strong> | Built with ❤️ using Streamlit & LLAMA AI</p>
    <p>© 2025 Thrivv Bank. All rights reserved.</p>
</div>
""", unsafe_allow_html=True)
