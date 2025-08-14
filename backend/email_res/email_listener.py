# backend/email_reciever/email_listener.py

import imaplib
import email
from email.header import decode_header
from typing import List, Dict
import os
from dotenv import load_dotenv

load_dotenv()

IMAP_HOST = os.getenv("IMAP_HOST")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

def get_unread_emails() -> List[Dict]:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(IMAP_USER, IMAP_PASSWORD)
    mail.select("inbox")

    status, messages = mail.search(None, 'UNSEEN')
    email_ids = messages[0].split()

    emails = []
    for eid in email_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")

                from_email = email.utils.parseaddr(msg.get("From"))[1]

                body = ""
                attachments = []
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            body = part.get_payload(decode=True).decode()
                        elif "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename:
                                filedata = part.get_payload(decode=True)
                                attachments.append({
                                    "filename": filename,
                                    "data": filedata
                                })
                else:
                    body = msg.get_payload(decode=True).decode()

                emails.append({
                    "from": from_email,
                    "subject": subject,
                    "body": body.strip(),
                    "attachments": attachments
                })

    mail.logout()
    return emails
