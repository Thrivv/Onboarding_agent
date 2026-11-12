# backend/app/services/reply_loop.py
#
# Entrypoint for the OnboardLG-reply-loop container. Run it as a module so the
# package root resolves without path juggling:
#     python -u -m app.services.reply_loop
# (PYTHONPATH=/app is set in the Dockerfile; the previous sys.path.append of
# the parent directory is no longer needed and pointed at the wrong level
# once this file moved into app/services/.)
import logging
import time
import traceback

from app import config
from app.logging_config import setup_logging
from app.services.email_listener import get_unread_emails
from app.services.handle_reply import process_user_reply

logger = logging.getLogger(__name__)


def run_reply_loop(poll_interval=10):
    logger.info("Starting reply loop...")
    while True:
        try:
            unread_emails = get_unread_emails()
            if unread_emails:
                logger.info(f"Found {len(unread_emails)} unread email(s)")

            for email_data in unread_emails:
                try:
                    logger.info(f"Processing email from {email_data['from']}")
                    process_user_reply(
                        from_email=email_data["from"],
                        body=email_data["body"],
                        attachments=email_data.get("attachments", []),
                    )
                    logger.info(
                        f"Successfully processed email from {email_data['from']}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to process email from "
                        f"{email_data.get('from', 'unknown')}: {e}"
                    )
                    logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"Exception in reply loop: {e}")
            logger.error(traceback.format_exc())

        time.sleep(poll_interval)


if __name__ == "__main__":
    # This process does NOT import app.main, so nothing else configures
    # logging here. Without this call every logger.info/debug in this process
    # — including the ~525 statements in handle_reply, ocr_service,
    # document_helpers, email_sender and supabase_client — would be discarded
    # silently by the unconfigured root logger.
    setup_logging()
    # This container depends on IMAP_* to poll for replies at all. Warn loudly
    # at boot if they are unset, instead of looping silently forever.
    config.validate_startup_config()
    run_reply_loop(poll_interval=10)
