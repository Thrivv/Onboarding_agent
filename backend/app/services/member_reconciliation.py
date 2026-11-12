"""
Reconcile an about-to-be-created member list against identity documents that
were already uploaded before that list existed.

Why this exists
----------------
An Emirates ID / Passport can legally only be routed to a specific member's
folder once a member list exists (member_progress.json). Before that — e.g.
a user who bulk-uploads Ejari + EID together, or an EID uploaded any time
before the Commercial License / MOA / CoI have finished establishing who the
owners or partners actually are — the identity document has nowhere to be
attributed to yet. Where it lands while unclaimed depends on ownership type:
Single Owner accounts save it as a plain top-level document (same place as
the Commercial License, Ejari, MOA); Partnership/Multiple Owner accounts
save it under members/ as an index-less placeholder (MEID-{ref_no} /
MPP-{ref_no}, see process_uploaded_document's rename step). Either way it is
fully valid and sitting on disk — just not linked to anyone yet.

The bug this closes: every place that creates member_progress.json for the
first time (`save_member_progress`) used to start `verified_members` at an
empty list unconditionally, with no check for whether some of those
documents already existed. The next status check would then report the
owner/member as still pending and the chat would ask for their ID again,
even though it was already accepted and verified moments earlier.

This module is the check that was missing: given the member names about to
be tracked, look for a document that already satisfies each one, and — for
anyone other than the account owner — physically move it into `members/` so
every other part of the system (which only ever looks under `members/` for
non-owner identity documents) sees it too.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

# Canonical identity document types, plus the raw OCR labels
# check_documents_status() already normalizes from — kept in sync with that
# function's own mapping so this module recognizes the same documents it does.
_IDENTITY_TYPES = {
    "eid", "passport",
    "emirates id", "emirates_id", "identity card",
    "travel_document", "travel document", "intl_id",
}

# ── TESTING-ONLY BYPASS ─────────────────────────────────────────────────────
# When set, orphaned identity docs are matched to pending members by
# encounter order instead of requiring the OCR'd name to match the member's
# name. Exists because test EIDs are frequently stock/dummy images that don't
# belong to whoever is "playing" the member in a given test run, so real name
# matching always fails and blocks the flow. Off by default — production
# must keep real name matching, since this is what stops an EID from being
# attributed to the wrong person. Flip RECONCILE_SKIP_NAME_MATCH off (or
# unset it) once real documents are back in use.
_SKIP_NAME_MATCH = os.getenv("RECONCILE_SKIP_NAME_MATCH", "false").strip().lower() in ("1", "true", "yes", "on")


def reconcile_unclaimed_identity_docs(email: str, member_names: List[str]) -> List[str]:
    """
    Return the subset of `member_names` who already have a valid identity
    document sitting on disk, matching them up and (for non-owners) moving
    the file into members/ so it's visible to the normal verification path.

    Two cases, checked in order:
      1. The account owner (Single Owner accounts) — their identity document
         is saved at the document root permanently (see is_account_owner()),
         never under members/, so this is a straight boolean check via
         check_documents_status().
      2. Everyone else (Partnership / Multiple Owners members) — any identity
         document sitting at the document root is an "orphan": it was
         uploaded before this member's slot existed, so it was saved next to
         the Commercial License / Ejari / MOA instead of under members/. Each
         orphan's OCR'd name is fuzzy-matched against the still-unmatched
         member names, one orphan per member, first-come first-served.

    Best-effort throughout — any failure here should never block the caller
    from saving member progress; it only means a document that could have
    been auto-matched will instead be (correctly, just less conveniently)
    asked for again.
    """
    if not member_names:
        return []

    matched: List[str] = []
    remaining = list(member_names)

    try:
        from app.services.key_individual_service import is_account_owner
        from app.services.chatupload_helpers import check_documents_status, user_docs_path

        # ── 1. Account owner ────────────────────────────────────────────
        if remaining and is_account_owner(email, remaining[0]):
            try:
                status = check_documents_status(email)
                if status.get("eid") or status.get("passport"):
                    matched.append(remaining[0])
                    remaining = remaining[1:]
                    logger.info(
                        f"[RECONCILE] {email}: owner '{matched[-1]}' already has a "
                        f"verified identity document on file — not re-requesting it"
                    )
            except Exception as e:
                logger.warning(f"[RECONCILE] owner check failed for {email}: {e}")

        if not remaining:
            return matched

        # ── 2. Everyone else — scan for orphaned IDs ────────────────────
        # Two places to look now:
        #   - the document root (legacy/Single-Owner-adjacent location — an
        #     unclaimed EID/Passport used to always land here regardless of
        #     ownership type)
        #   - members/, specifically placeholder-named folders (MEID-{ref_no}
        #     or MPP-{ref_no}, optionally with a random 6-hex collision
        #     suffix — see process_uploaded_document's rename step). Those
        #     are Multiple Owner/Partnership uploads that were routed
        #     straight into members/ at upload time, with no member index
        #     yet since the member it belongs to wasn't known. A REAL,
        #     already-assigned member folder (MEID-{ref_no}-1, -2, ...) is
        #     never touched here — only the index-less placeholder names are
        #     treated as orphans.
        root = user_docs_path(email)
        if not root.exists():
            return matched

        member_names_lower = {m.lower() for m in member_names}

        from app.services.document_helpers import (
            get_document_ref_no, build_document_id, get_member_index,
            get_user_documents_path_by_ref,
        )

        ref_no = get_document_ref_no(email)
        _eid_placeholder_base = build_document_id("eid", ref_no, True, None)
        _pp_placeholder_base = build_document_id("passport", ref_no, True, None)

        def _is_unclaimed_member_placeholder(folder_name: str) -> bool:
            for base in (_eid_placeholder_base, _pp_placeholder_base):
                if folder_name == base:
                    return True
                if folder_name.startswith(base + "-"):
                    suffix = folder_name[len(base) + 1:]
                    # 6-hex is process_uploaded_document's collision suffix,
                    # never a real member index (those are plain small ints).
                    if len(suffix) == 6 and all(c in "0123456789abcdef" for c in suffix.lower()):
                        return True
            return False

        def _scan_dir_for_orphans(scan_dir, is_members_dir: bool):
            found = []
            if not scan_dir.exists():
                return found
            for item in scan_dir.iterdir():
                if not item.is_dir():
                    continue
                if not is_members_dir and item.name == "members":
                    continue
                if is_members_dir and not _is_unclaimed_member_placeholder(item.name):
                    continue
                out = item / "output.json"
                if not out.exists():
                    continue
                try:
                    with open(out, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

                doc_type = (data.get("document_type") or "").strip().lower()
                if doc_type not in _IDENTITY_TYPES:
                    continue
                if not data.get("is_valid"):
                    continue

                from app.services.bulk_upload_service import extract_person_name
                extracted_fields = data.get("extracted_fields") or {}
                name = extract_person_name(extracted_fields)

                # An identity doc whose folder name matches a member exactly
                # (e.g. it was already reconciled/moved once before) isn't an
                # orphan — skip it so it can't be "matched" a second time.
                if item.name.lower() in member_names_lower:
                    continue

                found.append({
                    "dir": item,
                    "doc_type": "passport" if doc_type in ("passport", "travel_document", "travel document", "intl_id") else "eid",
                    "name": name,
                    "already_in_members": is_members_dir,
                })
            return found

        orphans = _scan_dir_for_orphans(root, is_members_dir=False)
        orphans += _scan_dir_for_orphans(root / "members", is_members_dir=True)

        if not orphans:
            return matched

        from app.services.bulk_upload_service import name_matches_expected

        used_orphans = set()

        for member_name in list(remaining):
            best = None
            if _SKIP_NAME_MATCH:
                # TESTING MODE: skip the name check entirely, just take the
                # next unused orphan in encounter order.
                for i, orphan in enumerate(orphans):
                    if i in used_orphans:
                        continue
                    best = i
                    break
            else:
                for i, orphan in enumerate(orphans):
                    if i in used_orphans or not orphan["name"]:
                        continue
                    if name_matches_expected(member_name, orphan["name"]):
                        best = i
                        break
            if best is None:
                continue

            orphan = orphans[best]
            try:
                member_index = get_member_index(email, member_name)
                new_doc_id = build_document_id(orphan["doc_type"], ref_no, True, member_index)
                members_dir = get_user_documents_path_by_ref(ref_no) / "members"
                members_dir.mkdir(parents=True, exist_ok=True)
                target_dir = members_dir / new_doc_id

                if target_dir.exists():
                    # Slot already occupied (shouldn't normally happen for a
                    # brand-new member) — don't clobber, leave the orphan
                    # where it is and let the normal upload path handle it.
                    continue

                old_files = [p for p in orphan["dir"].iterdir() if p.is_file() and p.name != "output.json"]
                orphan["dir"].rename(target_dir)
                used_orphans.add(best)

                # Rename the document file + patch output.json to match the
                # new member-scoped id, same convention build_document_id
                # sets everywhere else (see reassign_member_document).
                if old_files:
                    old_file = target_dir / old_files[0].name
                    new_filename = f"{new_doc_id}{old_files[0].suffix}"
                    new_file = target_dir / new_filename
                    if old_file.exists() and old_file != new_file:
                        old_file.rename(new_file)
                    out_json = target_dir / "output.json"
                    if out_json.exists():
                        try:
                            with open(out_json, "r", encoding="utf-8") as f:
                                out_data = json.load(f)
                            out_data["filename"] = new_filename
                            out_data["document_id"] = new_doc_id
                            out_data["human_verified"] = True
                            with open(out_json, "w", encoding="utf-8") as f:
                                json.dump(out_data, f, indent=2, ensure_ascii=False)
                        except Exception as e:
                            logger.warning(f"[RECONCILE] output.json patch failed for {target_dir}: {e}")

                matched.append(member_name)
                remaining.remove(member_name)
                _bypass_note = " (name-match BYPASSED — testing mode)" if _SKIP_NAME_MATCH else ""
                logger.info(
                    f"[RECONCILE] {email}: matched an already-uploaded "
                    f"{orphan['doc_type'].upper()} to member '{member_name}'{_bypass_note} -> {target_dir}"
                )

                try:
                    from app.services.key_individual_service import update_ki_verification_by_name
                    update_ki_verification_by_name(email=email, member_name=member_name, document_id=new_doc_id)
                except Exception as e:
                    logger.warning(f"[RECONCILE] KI sync failed for '{member_name}': {e}")
            except Exception as e:
                logger.warning(f"[RECONCILE] move failed for member '{member_name}': {e}")

    except Exception as e:
        logger.warning(f"[RECONCILE] reconcile_unclaimed_identity_docs failed for {email}: {e}")

    return matched
