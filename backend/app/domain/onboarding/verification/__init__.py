"""
Verification — document processing and chat-confirmation handling.

Was a single 2,261-line module. Split into one module per function in B5;
every function moved byte-identical, proven by SHA-1 in
backend/tests/split_verification.py.

    document_processing.py   process_uploaded_document          862 lines
    latest_document.py       _find_latest_unverified_document   118 lines
    response_handling.py     handle_verification_response      1181 lines

The import path is unchanged — `from app.domain.onboarding.verification
import process_uploaded_document` still resolves — so nothing that imported
the old module needed touching.

WHAT B5 DID NOT DO

The two large functions were moved, not decomposed. Each is dominated by a
single 825-line block, and splitting those bodies is a rewrite rather than a
move. Two reasons it was left:

  1. `move verbatim first, tidy second, never both in one step` — the rule
     that held through Stages A and B.
  2. Nothing covers it. The 709-case golden corpus exercises
     get_onboarding_status; neither of these functions is in it. A body-level
     split today would be an unprotected rewrite, the same objection that
     stopped C3.

`handle_verification_response` additionally may not survive at all — see the
header of response_handling.py and domain/onboarding/hvr_audit.py.
"""

from app.domain.onboarding.verification.document_processing import (
    process_uploaded_document,
)
from app.domain.onboarding.verification.latest_document import (
    _find_latest_unverified_document,
)
from app.domain.onboarding.verification.response_handling import (
    handle_verification_response,
)

__all__ = [
    "process_uploaded_document",
    "_find_latest_unverified_document",
    "handle_verification_response",
]
