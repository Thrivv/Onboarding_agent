# backend/llm_pipeline/reply_loop.py
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
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
                try:
                    print(f"[INFO] Processing email from {email_data['from']}")
                    process_user_reply(
                        from_email=email_data["from"],
                        body=email_data["body"],
                        attachments=email_data.get("attachments", []),
                    )
                    print(
                        f"[INFO] Successfully processed email from {email_data['from']}"
                    )
                except Exception as e:
                    print(
                        f"[ERROR] Failed to process email from {email_data.get('from', 'unknown')}: {e}"
                    )
                    import traceback

                    traceback.print_exc()

        except Exception as e:
            print(f"[ERROR] Exception in reply loop: {e}")
            import traceback

            traceback.print_exc()

        time.sleep(poll_interval)


if __name__ == "__main__":
    run_reply_loop(poll_interval=10)
