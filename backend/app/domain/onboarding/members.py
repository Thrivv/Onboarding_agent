"""
Member upload progress for partnership / multiple-owner onboarding.

Moved verbatim from `app/api/routes/chatupload.py` in Stage B4.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from app.services.chatupload_helpers import (
    user_docs_path,
    member_progress_path,
    get_display_document_name,
    get_allowed_document_types,
    check_documents_status,
    should_request_document,
    load_member_progress,
    get_remaining_required_documents,
    insert_conversation_log,
    
)

logger = logging.getLogger(__name__)

def save_member_progress(
    email: str,
    members: list,
    current_index: int = 0,
    ubo_names: list = None,
    expanded_members: list = None,   # TYPE-2: full expanded owner list
    pending_coi: list = None,        # TYPE-2: corps still awaiting CoI
) -> bool:
    """Save member progress to JSON file - STANDARDIZED FORMAT (TYPE-2 extended)

    Reconciles `verified_members` on every call instead of resetting it to
    empty. This closes a real bug: a member's identity document uploaded
    before this function's very first call for them (e.g. an EID bulk-
    uploaded alongside Ejari, before the Commercial License / MOA / CoI had
    finished establishing who the members even are) had nowhere to be
    attributed to yet, so it was saved as a plain top-level document. Once
    the member list was created here, that already-valid document was never
    checked for — `verified_members` always started at [], so the person got
    asked for their ID again even though it was already accepted.

    Two things happen now, every time this is called:
      1. Any member already recorded as verified by a PREVIOUS call is kept
         (this function used to silently wipe that out on every re-save —
         e.g. when a Type-2 flow calls this again as more CoIs come in).
      2. Every member not already verified is checked against documents
         already on disk via reconcile_unclaimed_identity_docs() — the
         account owner's identity doc (kept at the document root) via a
         direct check, everyone else via fuzzy name-matching against
         unclaimed identity documents sitting at the document root. Matches
         are moved into members/ and added to verified_members immediately.

    Best-effort: if reconciliation fails for any reason, this falls back to
    the previous behaviour (member stays pending, gets asked normally) —
    it never blocks the save itself.
    """
    try:
        p = member_progress_path(email)
        p.parent.mkdir(parents=True, exist_ok=True)

        previously_verified = []
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    previously_verified = (json.load(f) or {}).get("verified_members", []) or []
            except Exception as e:
                logger.warning(f"save_member_progress: could not read previous verified_members: {e}")

        verified_members = [m for m in previously_verified if m in members]

        still_unverified = [m for m in members if m not in verified_members]
        if still_unverified:
            try:
                from app.services.member_reconciliation import reconcile_unclaimed_identity_docs
                newly_matched = reconcile_unclaimed_identity_docs(email, still_unverified)
                for m in newly_matched:
                    if m not in verified_members:
                        verified_members.append(m)
            except Exception as e:
                logger.warning(f"save_member_progress: reconciliation skipped ({e})")

        data = {
            "members": members,
            "current_index": current_index,
            "verified_members": verified_members,
            "ubo_names": ubo_names or [],
            "expanded_members": expanded_members or [],   # TYPE-2
            "pending_coi": pending_coi or [],             # TYPE-2
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(
            f"Member progress saved with {len(members)} members "
            f"({len(verified_members)} already verified), "
            f"{len(ubo_names or [])} UBOs, {len(pending_coi or [])} pending CoIs"
        )
        return True
    except Exception as e:
        logger.error(f"save_member_progress: {e}")
        return False
