# backend/llm_pipeline/reply_loop.py
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import time
from email_res.email_listener import get_unread_emails
from llm_pipeline.handle_reply import process_user_reply


def run_reply_loop(poll_interval=10):
    print("[INFO] Starting reply loop...")
    while True:
        try:
            unread_emails = get_unread_emails()
            if unread_emails:
                print(f"[INFO] Found {len(unread_emails)} unread email(s)")
            for email_data in unread_emails:
                process_user_reply(
                    from_email=email_data["from"],
                    body=email_data["body"],
                    attachments=email_data.get("attachments", [])
                )
        except Exception as e:
            print(f"[ERROR] Exception in reply loop: {e}")
        
        time.sleep(poll_interval)  # Wait 30 seconds before checking again


if __name__ == "__main__":
    run_reply_loop()
