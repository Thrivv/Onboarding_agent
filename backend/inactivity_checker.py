#!/usr/bin/env python3
"""
Background task to check for inactive sessions and send emails.
This can be run as a cron job or scheduled task.

Setup:
1. Run every 5 minutes: */5 * * * * python inactivity_checker.py
2. Or use APScheduler for Python-based scheduling
"""

import os
import sys
import requests
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
INACTIVITY_THRESHOLD_MINUTES = int(os.getenv("INACTIVITY_THRESHOLD_MINUTES"))


def check_inactive_sessions():
    """Call backend API to check for inactive sessions"""
    try:
        print(f"[{datetime.now()}] Checking for inactive sessions...")
        
        response = requests.post(
            f"{BACKEND_URL}/chatupload/check-inactive-sessions",
            params={"inactivity_minutes": INACTIVITY_THRESHOLD_MINUTES},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Found {data['inactive_sessions_found']} inactive sessions")
            print(f"📧 Sent {data['emails_sent']} notification emails")
            return True
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Inactivity Session Checker - Started")
    print("=" * 60)
    
    success = check_inactive_sessions()
    
    print("=" * 60)
    print(f"Status: {'SUCCESS' if success else 'FAILED'}")
    print("=" * 60)
    
    sys.exit(0 if success else 1)