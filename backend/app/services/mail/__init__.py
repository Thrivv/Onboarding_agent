"""
Email delivery, split out of the 2,215-line `email_sender.py` in Stage C4.

Named `mail` and not `email` on purpose: `app/services/email/` would sit one
ambiguous import away from the standard library's `email` package, which this
code uses heavily (`email.mime.text`, `email.utils`, `email.header`). Absolute
imports would in fact resolve correctly, but the name would invite exactly the
sort of confusion this refactor exists to remove.

| Module | Holds |
|---|---|
| `transport.py`  | SMTP configuration and `send_email` — the only socket in here |
| `summary_pdf.py`| `generate_user_summary_pdf` and its text sanitiser |
| `messages.py`   | The 19 `send_*_email` composers |

`app/services/email_sender.py` remains as a re-export shim. Fourteen modules
import from it, several inside function bodies, so the old path keeps working
and no call site had to change in C4.
"""
