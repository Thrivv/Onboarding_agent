"""
Key individuals — the owners, partners, directors and signatories extracted
from a company's MOA and trade licence.

Eight endpoints covering the KI loop: selecting the authorised signatory,
adding individuals manually or via AI extraction, collecting contact details,
OTP verification, and finalising the loop.
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from fastapi import APIRouter, HTTPException
import traceback
from app.services.message_generator import MessageGenerator, ai_message_gen
from app.utils.language import normalize_language
from app.i18n import render_message, members_summary, concat
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
from app.services.fatca_service import (
    save_fatca, load_fatca, get_fatca_status, get_fatca_status_disk_only, fatca_json_path
)
from app.services.pep_service import (
    save_pep, load_pep, get_pep_status, get_pep_status_disk_only,
    validate_pep_data, pep_json_path,
)
from app.services.key_individual_service import (
    load_key_individuals, save_key_individual, update_ki_verification,
    update_ki_verification_by_name,
    save_moa_member_as_status, update_member_ubo_status, get_ki_summary,
    ki_json_path, is_account_owner,
)
from app.services.product_package_service import (
    is_package_done, save_package_selection, get_package_selection,
    get_package_status, recommend_package_from_nob,
)
from app.services.supabase_client import supabase, get_user_by_email
from app.schemas.key_individuals import MoaAsRequest, KiFormRequest, KiVerifyRequest, UboConfirmRequest, SoAsSelectionRequest, KiAiAddRequest, KiContactInfoRequest, KiLoopFinalizeRequest
from app.domain.onboarding.documents import _find_commercial_output
from app.domain.onboarding.members import save_member_progress
from app.domain.onboarding.stages import update_user_onboarding_status
from app.domain.onboarding.stage_table import (
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
    STAGE_IDENTIFICATION,
    STAGE_SO_MEMBER_EIDS,
)
from app.domain.exceptions import (
    DomainError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Sub-router. The `/chatupload` prefix and tags are applied once in
# app/api/routes/onboarding/__init__.py, so every path below is unchanged.
router = APIRouter()

@router.post("/ki/moa-as-selection")
async def ki_moa_as_selection(req: MoaAsRequest):
    """Save Authorised Signatory checkbox status for MOA-extracted members (Part A).
    Also merges any manually-added KI members into member_progress.json so they
    get included in the Stage-2 identity verification queue."""
    try:
        logger.info(f"[PENDING-ACTIONS] MOA AS/KI selection submitted for {req.email}: {req.member_role_map or req.member_as_map}")

        # ── Resolve role map: prefer new member_role_map, fall back to legacy booleans ──
        _role_map = req.member_role_map or {}
        if not _role_map and req.member_as_map:
            # Legacy conversion: bool → role string
            _role_map = {k: ("AS" if v else "MEMBER") for k, v in req.member_as_map.items()}
        save_moa_member_as_status(req.email, _role_map)
        logger.info(f"[PENDING-ACTIONS] MOA AS/KI selection cleared for {req.email} — as_ki_selection_pending will read False on next status check")

        # ── Merge any AI_ADDED / manually-added KIs into member_progress so they
        # are included in the Stage-2 verification queue ─────────────────────
        try:
            progress_file = member_progress_path(req.email)
            if progress_file.exists():
                with open(progress_file, "r", encoding="utf-8") as _pf:
                    _progress = json.load(_pf)

                current_members = _progress.get("members", [])
                current_members_upper = [m.upper() for m in current_members]

                # Load all manually-added KIs (source != MOA_EXTRACTED)
                from app.services.key_individual_service import load_key_individuals
                all_kis = load_key_individuals(req.email)
                added = []
                for ki in all_kis:
                    name = ki.get("display_name", "").strip()
                    if not name:
                        continue
                    if ki.get("source") in ("MOA_EXTRACTED", "AI_ADDED"):
                        continue  # already tracked — AI_ADDED are pre-verified with doc moved
                    if name.upper() not in current_members_upper:
                        current_members.append(name)
                        current_members_upper.append(name.upper())
                        added.append(name)

                if added:
                    _progress["members"] = current_members
                    with open(progress_file, "w", encoding="utf-8") as _pf:
                        json.dump(_progress, _pf, indent=2, ensure_ascii=False)
                    logger.info(f"[KI] Merged {len(added)} manually-added KI(s) into member_progress: {added}")
        except Exception as _me:
            logger.warning(f"[KI] Could not merge KIs into member_progress: {_me}")

        # ── Reconciliation-aware confirmation message ───────────────────────
        # member_progress.json (built earlier by member_expansion.check_and_
        # expand_members, before this endpoint ever runs) may already have
        # verified_members populated — e.g. one or more EIDs were bulk-
        # uploaded alongside Ejari/MOA/CoI before this card even existed to
        # attribute them to anyone, and reconcile_unclaimed_identity_docs
        # matched them by name at that point. Without this check every
        # confirmation used to say the same generic "please proceed with
        # identity verification for each member" regardless of how many (if
        # any) were already done, and — critically — if EVERY member was
        # already verified, there was no upload event left to hang the
        # "Add More Individuals?" (KiLoopCard) trigger off of, so it simply
        # never appeared and the user was stuck on an instruction with
        # nothing left to act on. Mirrors ki_so_as_selection's pattern below.
        all_members = []
        still_pending = []
        all_verified = False
        try:
            _mp_after = load_member_progress(req.email) or {}
            all_members = _mp_after.get("members", []) or []
            _verified_now = set(_mp_after.get("verified_members", []) or [])
            still_pending = [m for m in all_members if m not in _verified_now]
            all_verified = bool(all_members) and not still_pending
        except Exception as _va_err:
            logger.warning(f"[KI] Could not read back verified_members: {_va_err}")

        # No longer asks "is there anyone else, outside this list, who should
        # be added as a Key Individual?" — that exact question is asked (with
        # Yes/No buttons) by the KiLoopCard once identities are verified, so
        # asking it here too was a redundant free-text dead end that users
        # skipped (and that the general chat LLM then had to interpret).
        # The message now states the real next step, in the user's language.
        _lang = normalize_language(req.language)
        _names_block = "\n".join(f"  {i+1}. {name}" for i, name in enumerate(still_pending))
        if all_verified:
            msg = render_message("as_saved.all_verified", _lang)
        elif still_pending and len(still_pending) < len(all_members):
            msg = render_message("as_saved.partially_verified", _lang,
                                 already=len(all_members) - len(still_pending), names=_names_block)
        elif still_pending:
            msg = render_message("as_saved.upload_ids", _lang,
                                 count=len(still_pending), names=_names_block)
        else:
            # member_progress unreadable — still give a clear next step.
            msg = render_message("as_saved.upload_ids", _lang, count=len(all_members),
                                 names="\n".join(f"  {i+1}. {n}" for i, n in enumerate(all_members)))

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type": "ki_moa_as_saved",
                "member_role_map": _role_map,
                "all_members_verified": all_verified,
                "still_pending_members": still_pending,
                # Persisted card state (rule 4): survives reload / language
                # switch / re-login instead of living only in browser memory.
                "as_selection_completed": True,
                "ki_loop_prompt": all_verified,
            }
        )

        return {
            "success": True,
            "message": msg,
            "all_members": all_members,
            "still_pending_members": still_pending,
            "all_members_verified": all_verified,
        }

    except Exception as e:
        logger.error(f"[KI] MOA AS selection error: {e}")
        raise DomainError(context=str(e))


@router.post("/ki/so-as-selection")
async def ki_so_as_selection(req: SoAsSelectionRequest):
    """Save AS flag for the Single Owner and any added KIs.
    Builds member_progress.json so the upload flow sequences:
       Owner EID → KI-1 EID → KI-2 EID → ... → Ejari → Self-Declaration
    Transitions document_stage → 'so_member_eids' when there are KIs,
    or stays in 'identification' when there are no KIs (owner EID + Ejari only).
    """
    try:
        logger.info(f"[PENDING-ACTIONS] SO Owner AS/KI selection submitted for {req.email}: owner_role={req.owner_role}")

        # ── 1. Read owner name from commercial license ──────────────────────
        _, comm_data = _find_commercial_output(req.email)
        owner_name = ""
        owner_nationality = ""
        if comm_data:
            ef = comm_data.get("extracted_fields", {})
            ob = ef.get("owner") or {}
            owner_name        = ob.get("name_english") or ef.get("english", {}).get("owner_name", "")
            owner_nationality = ob.get("nationality_english", "")

        # ── FIX A: Fallback to registered user name if commercial didn't yield one ──
        # If owner_name is empty the owner would be silently dropped from all_members,
        # causing the system to think only the KIs need EIDs (total_members = n KIs),
        # and Ejari would be requested after the FIRST KI's EID is verified rather
        # than after the owner + all KIs have been verified.
        if not owner_name:
            try:
                _owner_user = get_user_by_email(req.email)
                owner_name = (_owner_user or {}).get("name", "").strip()
                if owner_name:
                    logger.info(f"[SO-AS] owner_name fallback → registered user name: '{owner_name}'")
                else:
                    logger.warning(f"[SO-AS] owner_name still empty after fallback — owner may be skipped!")
            except Exception as _fn_err:
                logger.warning(f"[SO-AS] Could not fetch fallback owner name: {_fn_err}")

        # ── 2. Upsert the owner as a KI record ─────────────────────────────
        if owner_name:
            parts      = owner_name.strip().split()
            first_name = parts[0] if parts else owner_name
            last_name  = " ".join(parts[1:]) if len(parts) > 1 else ""
            existing = next(
                (k for k in load_key_individuals(req.email)
                 if k.get("display_name", "").upper() == owner_name.upper()
                 and k.get("source") == "SO_OWNER"),
                None
            )
            ki_data = existing or {
                "first_name":          first_name,
                "last_name":           last_name,
                "mobile_number":       "",
                "id_number":           "",
                "id_type":             "EID",
                "source":              "SO_OWNER",
                "verification_status": "pending",
                "nationality":         owner_nationality,
            }
            # ── Resolve is_as from new role string or legacy bool ────────────
            if req.owner_is_as is not None:
                _so_is_as = req.owner_is_as          # legacy boolean path
            else:
                _so_is_as = str(req.owner_role).strip().upper() == "AS"
            ki_data["is_authorised_signatory"] = _so_is_as
            ki_data["role"] = (
                "Authorised Signatory" if _so_is_as else "Member"
            )
            ki_data["display_name"]            = owner_name
            save_key_individual(req.email, ki_data)
            logger.info(f"[SO-AS] Owner KI saved — name={owner_name}, owner_role={req.owner_role}, is_as={_so_is_as}")
            logger.info(f"[PENDING-ACTIONS] SO Owner AS/KI selection cleared for {req.email} — as_ki_selection_pending will read False on next status check")

        # ── 3. Collect all manually-added KIs ──────────────────────────────
        # FIX C: also dedupe by name against the owner. A DOCUMENT_EXTRACTED-
        # sourced KI created by the mismatch-name flow (mismatch_assign_role)
        # can carry the SAME person as the owner under a different `source`
        # tag, which previously slipped past the source-only filter below and
        # forced a second, duplicate EID upload for one physical person.
        _owner_name_normalized = " ".join(owner_name.strip().upper().split()) if owner_name else ""
        added_ki_names = []
        try:
            all_kis = load_key_individuals(req.email)
            for ki in all_kis:
                name = ki.get("display_name", "").strip()
                if not name:
                    continue
                if ki.get("source") in ("SO_OWNER", "MOA_EXTRACTED", "AI_ADDED"):
                    continue  # handled separately — AI_ADDED are pre-verified via loop
                _name_normalized = " ".join(name.upper().split())
                if _owner_name_normalized and (
                    _name_normalized == _owner_name_normalized
                    or _name_normalized in _owner_name_normalized
                    or _owner_name_normalized in _name_normalized
                ):
                    logger.info(f"[SO-AS] Skipping KI '{name}' — matches owner '{owner_name}', not a separate member")
                    continue
                added_ki_names.append(name)
            if added_ki_names:
                logger.info(f"[SO-AS] Manually-added KIs in queue: {added_ki_names}")
        except Exception as _me:
            logger.warning(f"[SO-AS] Could not enumerate added KIs: {_me}")

        # ── 4. Build full member list: owner first, then added KIs ─────────
        # The owner's EID is always required. KIs also need their EIDs.
        # Ejari comes after ALL of them are verified.
        all_members = []
        if owner_name:
            all_members.append(owner_name)
        all_members.extend(added_ki_names)

        has_kis = len(added_ki_names) > 0

        # ── 5. Save member_progress.json (always — even owner-only) ────────
        # This lets the upload endpoint auto-route the document to the right
        # member folder and sequence them correctly: Owner EID → KI EIDs → Ejari.
        # NOTE: this intentionally includes the owner as member #1 even when no
        # extra KIs were added — that's what drives the KiLoopCard ("Would you
        # like to add any additional Authorised Signatory or Key Individual?")
        # after the owner's own EID is verified (see _is_so_member_eids-gated
        # block in the /upload-conversational verify path). Skipping this for
        # owner-only accounts (a prior attempt) silently disabled that prompt
        # for every Single Owner who hadn't pre-added a KI before confirming —
        # i.e. almost everyone, since KIs are normally added via that same loop
        # *after* the owner's EID, not before.
        try:
            save_member_progress(req.email, all_members, 0)
            # NOTE: no longer pre-creating {ref_no}/{member_name}/ folders here — that was
            # the legacy per-name layout. Actual uploads are routed to
            # {ref_no}/members/{PREFIX}-{ref_no}-{index}/ by build_document_id, so those
            # pre-created folders were always empty (see e.g. the stray empty
            # "VARSHA BALAJI BALAJI" folder left in older onboarding records).
            logger.info(f"[SO-AS] member_progress saved: {all_members}")
        except Exception as _mp_err:
            logger.warning(f"[SO-AS] Could not save member_progress: {_mp_err}")

        # ── 6. Transition stage → so_member_eids (Single Owner only) ──────────
        # For Single Owner: always move to so_member_eids so the upload endpoint
        # sequences Owner EID → KI EIDs → Ejari → Self-Declaration correctly,
        # AND so the KiLoopCard ("add another AS/KI?") fires after the owner's
        # own EID is verified.
        # For Multiple Owner / Partnership: DO NOT update the stage here.
        # Their stage must remain "identification" so that the verify handler
        # (chat-conversational) can detect has_commercial + has_moa and
        # transition correctly to "member_eids" after MOA is confirmed.
        # ── FIX B: Retry stage update up to 2 times; raise on total failure ─
        _stage_updated = False
        _stage_update_attempts = 0
        _new_stage = STAGE_IDENTIFICATION
        try:
            _so_as_user = get_user_by_email(req.email)
            _so_as_ownership = (_so_as_user or {}).get("ownership_type", OWNERSHIP_SINGLE)
            if _so_as_ownership not in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP):
                for _attempt in range(2):
                    try:
                        _stage_update_attempts += 1
                        update_user_onboarding_status(req.email, False, STAGE_SO_MEMBER_EIDS)
                        _stage_updated = True
                        _new_stage = STAGE_SO_MEMBER_EIDS
                        logger.info(f"[SO-AS] Stage updated → so_member_eids (attempt {_attempt+1}, members={all_members})")
                        break
                    except Exception as _su_retry:
                        logger.warning(f"[SO-AS] Stage update attempt {_attempt+1} failed: {_su_retry}")
                if not _stage_updated:
                    # Stage update failed on both attempts — log prominently so this is visible in logs
                    logger.error(f"[SO-AS] CRITICAL: Stage update to so_member_eids FAILED after {_stage_update_attempts} attempts for {req.email}. "
                          f"Member EID sequencing will NOT work correctly until stage is set to so_member_eids.")
            else:
                logger.info(f"[SO-AS] Multiple Owner account — stage NOT updated to so_member_eids (stays identification)")
                _stage_updated = True  # not needed for this path
        except Exception as _su_err:
            logger.warning(f"[SO-AS] Could not update stage: {_su_err}")

        # ── 7. Build confirmation message ───────────────────────────────────
        # Reconciliation inside save_member_progress() (step 5 above) may
        # already have matched one or more of these members to an identity
        # document uploaded earlier — e.g. bulk-uploaded alongside Ejari,
        # before this card even existed to attribute it to anyone. Check
        # verified_members before asking for an ID that's already on file.
        _verified_after_save = set()
        try:
            _mp_after = load_member_progress(req.email) or {}
            _verified_after_save = set(_mp_after.get("verified_members", []) or [])
        except Exception as _va_err:
            logger.warning(f"[SO-AS] Could not read back verified_members: {_va_err}")

        first_person = all_members[0] if all_members else "yourself"
        still_pending = [m for m in all_members if m not in _verified_after_save]

        if first_person in _verified_after_save:
            if still_pending:
                msg = render_message(
                    "so_as.owner_verified_pending", normalize_language(None), owner=first_person,
                    names="\n".join(f"  {i+1}. {name}" for i, name in enumerate(still_pending)))
            else:
                msg = render_message("so_as.owner_verified_done", normalize_language(None), owner=first_person)
        else:
            msg = render_message("so_as.owner_upload", normalize_language(None), owner=first_person)
            if len(all_members) > 1:
                remaining = all_members[1:]
                msg = concat(normalize_language(None), msg, render_message(
                    "so_as.then_also", normalize_language(None),
                    names="\n".join(f"  {i+1}. {name}" for i, name in enumerate(remaining))))

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type":  "ki_so_as_saved",
                "owner_name":    owner_name,
                "owner_role":    req.owner_role,
                "owner_is_as":   _so_is_as,
                "added_kis":     added_ki_names,
                "all_members":   all_members,
                "new_stage":     _new_stage,
            }
        )

        return {
            "success":        True,
            "message":        msg,
            "owner_name":     owner_name,
            "owner_role":     req.owner_role,
            "owner_is_as":    _so_is_as,
            "added_ki_names": added_ki_names,
            "all_members":    all_members,
            "new_stage":      _new_stage,
        }

    except Exception as e:
        logger.error(f"[SO-AS] SO AS selection error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/ki/add")
async def ki_add(req: KiFormRequest):
    """
    ⚠️  DEPRECATED — use POST /ki/add-ai for the new conversational loop flow.
    Kept for backwards compatibility only.  The 18-field Add Individual popup
    has been replaced by an EID-first conversational loop (AI_ADDED source).
    """
    try:
        ki_data = req.dict()
        ki_data["email"] = ki_data.pop("email_address", None)
        ki_data["source"] = "MANUALLY_ADDED"
        ki_data["verification_status"] = "pending"
        ki_data["is_ubo"] = False

        saved = save_key_individual(req.email, ki_data)

        try:
            from app.services.message_generator import MessageGenerator
            msg = MessageGenerator.ki_added_prompt_id_upload(
                name=saved.get("display_name", ""),
                id_type=req.id_type,
                language=normalize_language(None),  # X-User-Language header
            )
        except Exception:
            msg = render_message("ki.added_fallback", normalize_language(None),
                                 name=saved.get("display_name", ""), id_type=req.id_type)

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type": "ki_added",
                "ki_id": saved.get("id"),
                "ki_name": saved.get("display_name"),
            }
        )

        return {"success": True, "ki": saved, "message": msg}

    except Exception as e:
        logger.error(f"[KI] Add KI error: {e}")
        raise DomainError(context=str(e))


@router.post("/ki/add-ai")
async def ki_add_ai(req: KiAiAddRequest):
    """
    Add a Key Individual via the conversational loop (AI_ADDED source).
    The EID/Passport was already uploaded and OCR'd — extracted_data contains
    the fields.  The KI is saved as 'verified' immediately and the uploaded
    doc is moved to the correct member folder so disk-scan tracking works.
    """
    try:
        from app.services.key_individual_service import save_ai_added_ki
        import shutil

        saved        = save_ai_added_ki(req.email, req.extracted_data, req.role, req.document_id)
        display_name = saved.get("display_name", "")

        # ── Clear the ki_role_assignment_pending breadcrumb — role is now saved ──
        try:
            _ki_role_breadcrumb_path = user_docs_path(req.email) / "pending_ki_role_assignment.json"
            if _ki_role_breadcrumb_path.exists():
                _ki_role_breadcrumb_path.unlink()
        except Exception as _kb_del_err:
            logger.warning(f"[KI-AI] Could not clear pending_ki_role_assignment.json breadcrumb: {_kb_del_err}")

        # ── Move the uploaded doc from {ref_no}/{doc_id}/ → {ref_no}/members/{MEID-ref_no-N}/ ──
        # FIX: previously this *copied* (shutil.copy2) into a legacy {ref_no}/{display_name}/
        # folder. That was wrong on three counts: (1) disk-scan member verification only
        # ever looks under members/ (see upload_conversational's pending_members check and
        # document_helpers.py), so a doc left in {display_name}/ was invisible to it; (2) the
        # source root-level {doc_id}/ folder was never removed, so it stuck around as an
        # orphaned duplicate (e.g. a bare EID-{ref_no}/ folder sitting next to TL-/POS-); and
        # (3) output.json never got member_name/document_id updated to match the new
        # convention, so even a correctly-placed copy wouldn't match by name.
        # Now: rename (move, not copy) into members/, using the same build_document_id +
        # get_member_index convention every other member document follows, and patch
        # output.json so member_name/document_id/filename are consistent with the new path.
        if display_name and req.document_id:
            from app.services.document_helpers import (
                get_document_ref_no, build_document_id, get_member_index,
            )

            _src_dir = user_docs_path(req.email) / req.document_id
            if _src_dir.exists():
                _src_output_json = _src_dir / "output.json"
                _doc_type = "eid"
                if _src_output_json.exists():
                    try:
                        with open(_src_output_json, "r", encoding="utf-8") as _f:
                            _src_data = json.load(_f)
                        _doc_type = (_src_data.get("document_type") or "eid").lower().strip()
                    except Exception as _read_err:
                        logger.warning(f"[KI-AI] Could not read source output.json for doc_type: {_read_err}")

                _ref_no = get_document_ref_no(req.email)
                _member_idx = get_member_index(req.email, display_name)
                _proper_doc_id = build_document_id(_doc_type, _ref_no, is_member=True, member_index=_member_idx)

                _members_dir = user_docs_path(req.email) / "members"
                _members_dir.mkdir(parents=True, exist_ok=True)
                _dst_dir = _members_dir / _proper_doc_id

                if _dst_dir.exists():
                    shutil.rmtree(_dst_dir)

                # Move (not copy) — leaves no orphaned root-level folder behind.
                _src_dir.rename(_dst_dir)

                # Rename the non-JSON file inside to match the new document_id.
                for _item in list(_dst_dir.iterdir()):
                    if _item.suffix.lower() != ".json":
                        _new_file = _dst_dir / f"{_proper_doc_id}{_item.suffix}"
                        if _item != _new_file:
                            _item.rename(_new_file)

                # Patch output.json — member_name is required for disk-scan matching,
                # document_id/filename kept consistent with the new location.
                _dst_output_json = _dst_dir / "output.json"
                if _dst_output_json.exists():
                    try:
                        with open(_dst_output_json, "r", encoding="utf-8") as _f:
                            _oj = json.load(_f)
                        _old_ext = Path(_oj.get("filename", "")).suffix
                        _oj["document_id"] = _proper_doc_id
                        _oj["member_name"] = display_name
                        _oj["filename"] = f"{_proper_doc_id}{_old_ext}"
                        with open(_dst_output_json, "w", encoding="utf-8") as _f:
                            json.dump(_oj, _f, indent=2, ensure_ascii=False)
                    except Exception as _patch_err:
                        logger.warning(f"[KI-AI] Could not patch output.json member_name/document_id: {_patch_err}")

                logger.info(f"[KI-AI] Doc moved: {_src_dir} → {_dst_dir}")

        # ── Add member to member_progress.json so the loop tracking works ────
        try:
            _mp = load_member_progress(req.email)
            if _mp is not None:
                _members = _mp.get("members", [])
                if display_name and display_name not in _members:
                    _members.append(display_name)
                    # NOTE: no legacy {display_name}/ folder created here — the doc already
                    # lives under members/{PREFIX}-{ref_no}-{index}/ from the move above.
                    save_member_progress(
                        req.email, _members,
                        current_index=_mp.get("current_index", 0),
                        ubo_names=_mp.get("ubo_names", []),
                        expanded_members=_mp.get("expanded_members", []),
                        pending_coi=_mp.get("pending_coi", []),
                    )
                    logger.info(f"[KI-AI] {display_name} added to member_progress")
        except Exception as _mpe:
            logger.warning(f"[KI-AI] Could not update member_progress: {_mpe}")

        _role_label = render_message("role.as" if req.role.upper() == "AS" else "role.member", normalize_language(None))
        msg = render_message("ki.ai_added", normalize_language(None), name=display_name, role=_role_label)

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type":     "ki_ai_added",
                "ki_id":            saved.get("id"),
                "ki_name":          display_name,
                "role":             req.role,
                "show_loop_prompt": True,
            }
        )

        return {
            "success":          True,
            "ki":               saved,
            "display_name":     display_name,
            "message":          msg,
            "show_loop_prompt": True,
        }

    except Exception as e:
        logger.error(f"[KI-AI] Add AI KI error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/ki/contact-info")
async def ki_contact_info(req: KiContactInfoRequest):
    """
    Save contact details collected after EID/Passport verification for a KI.
    Persists system_role, contact_email, phone_number, share_percentage to:
      - key_individuals.json (disk)
      - Supabase key_individuals table
      - {document_id}/output.json  (contact_info block)
    Returns ownershipMap + kiContactMap so the frontend can update the
    registered-individuals report card without a page reload.
    """
    import re
    try:
        from app.services.key_individual_service import update_ki_contact_info

        # ── Basic server-side validation ────────────────────────────────────
        if req.system_role.strip() not in ("Self Admin", "Maker", "Approver"):
            raise ValidationError("system_role must be one of: Self Admin, Maker, Approver")

        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', req.contact_email.strip()):
            raise ValidationError("Invalid email format")

        if not req.phone_number.strip():
            raise ValidationError("phone_number is required")

        # ── Persist to key_individuals.json + Supabase + output.json ────────
        updated = update_ki_contact_info(
            email=req.email,
            ki_name=req.ki_name,
            system_role=req.system_role,
            contact_email=req.contact_email,
            phone_number=req.phone_number,
            share_percentage=req.share_percentage,
        )

        if not updated:
            logger.warning(f"[KI-CONTACT] No KI matched display_name='{req.ki_name}' for {req.email}")

        # ── Build ownership/contact maps for frontend state update ──────────
        # ownershipMap  → feeds allReportItems ownershipMap scan → share% in report
        # kiContactMap  → feeds RegisteredIndividualsReportBlock email/phone rows
        ki_name_upper = req.ki_name.strip().upper()
        ownership_map: dict = {}
        ki_contact_map: dict = {}

        if req.share_percentage is not None:
            share_str = (
                f"{int(req.share_percentage)}%"
                if req.share_percentage == int(req.share_percentage)
                else f"{req.share_percentage}%"
            )
            ownership_map[ki_name_upper] = share_str

        ki_contact_map[ki_name_upper] = {
            "contact_email": req.contact_email.strip(),
            "phone_number":  req.phone_number.strip(),
        }

        # ── Build confirmation message then hand back to the KI loop gate ──
        share_line = (render_message("ki.share_line", normalize_language(None), share=ownership_map[ki_name_upper])
                      if ownership_map and ki_name_upper in ownership_map else "")
        msg = render_message("ki.contact_saved", normalize_language(None), name=req.ki_name, share_line=share_line)

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type":     "ki_contact_info_saved",
                "ki_name":          req.ki_name,
                "system_role":      req.system_role,
                "share_percentage": req.share_percentage,
                "show_loop_prompt": True,
            }
        )

        logger.info(f"[KI-CONTACT] Saved — ki={req.ki_name}, role={req.system_role}, share={req.share_percentage}")

        return {
            "success":          True,
            "updated":          updated,
            "message":          msg,
            "show_loop_prompt": True,       # resume KI loop gate
            "ownershipMap":     ownership_map,   # { "NAME": "25%" }
            "kiContactMap":     ki_contact_map,  # { "NAME": { contact_email, phone_number } }
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[KI-CONTACT] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/ki/loop-finalize")
async def ki_loop_finalize(req: KiLoopFinalizeRequest):
    """
    Called when the user clicks 'No, Proceed' in the KiLoopCard.
    Writes ki_loop_done.json so the verify path can advance past the loop gate
    and proceed to FATCA → PEP → Self-Declaration.
    Returns the appropriate next trigger based on account type and current status.
    """
    try:
        from app.services.fatca_service import get_fatca_status_disk_only
        from app.services.pep_service   import get_pep_status_disk_only

        # ── Write loop-done flag ─────────────────────────────────────────────
        _flag = user_docs_path(req.email) / "ki_loop_done.json"
        _flag.parent.mkdir(parents=True, exist_ok=True)
        with open(_flag, "w", encoding="utf-8") as _f:
            json.dump({"done": True, "at": datetime.now(timezone.utc).isoformat()}, _f)
        logger.info(f"[KI-LOOP] ki_loop_done.json written for {req.email}")

        # ── Determine account type to route correctly ────────────────────────
        _user = get_user_by_email(req.email)
        _ownership = (_user or {}).get("ownership_type", OWNERSHIP_SINGLE)
        _is_multiple = _ownership in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)

        if not _is_multiple:
            # Single Owner: Ejari was collected upfront (step 2 of the flow).
            # After the KI loop, show a final members summary then go straight
            # to the FATCA → PEP → Self-Declaration chain.
            # Transition stage so_member_eids → identification so the
            # verify handler's FATCA chain fires correctly.
            try:
                update_user_onboarding_status(req.email, False, STAGE_IDENTIFICATION)
                logger.info(f"[KI-LOOP] Stage updated: so_member_eids → identification for {req.email}")
            except Exception as _ste:
                logger.warning(f"[KI-LOOP] Could not update stage: {_ste}")

            # ── Build final members list (Name | Role | Share | Verified) ─────
            _so_summary_lines = []
            try:
                _so_all_ki = load_key_individuals(req.email)
                # Also check member_progress.json verified_members list,
                # since MOA_EXTRACTED members are tracked there (not via
                # verification_status field which is only set for AI_ADDED KIs)
                try:
                    _so_mp = load_member_progress(req.email)
                    _so_verified_names = [
                        n.upper() for n in (_so_mp or {}).get("verified_members", [])
                    ]
                except Exception:
                    _so_verified_names = []
                for _idx, _ki in enumerate(_so_all_ki, 1):
                    _ki_name = _ki.get("display_name") or (
                        f"{_ki.get('first_name', '')} {_ki.get('last_name', '')}".strip()
                    )
                    _ki_is_as = (
                        _ki.get("is_authorised_signatory") or
                        str(_ki.get("role", "")).strip().upper() in ("AS", "AUTHORISED SIGNATORY")
                    )
                    _ki_is_ubo = _ki.get("is_ubo", False)
                    _ki_role_label = "Authorised Signatory" if _ki_is_as else "Member"
                    if _ki_is_ubo:
                        _ki_role_label += " (UBO)"
                    _ki_share  = _ki.get("share_percentage", "—")
                    _ki_is_verified = (
                        _ki.get("verification_status") == "verified" or
                        _ki_name.upper() in _so_verified_names
                    )
                    if _ki_name:
                        _so_summary_lines.append({
                            "name": _ki_name, "is_as": bool(_ki_is_as), "is_ubo": bool(_ki_is_ubo),
                            "share": _ki_share, "verified": bool(_ki_is_verified),
                        })
            except Exception as _kse:
                logger.warning(f"[KI-LOOP] Could not build SO KI summary: {_kse}")

            _so_summary_block = members_summary(_so_summary_lines, "summary.header_final", normalize_language(None))

            # ── FATCA → PEP → Product Package → Self-Declaration chain (Single Owner) ──
            # Re-enabled: Single Owner now goes through the same compliance chain
            # as Multiple Owner/Partnership instead of skipping straight to
            # Product Package.
            _so_fatca_done = get_fatca_status_disk_only(req.email) in ("completed", "not_applicable")
            _so_pep_done   = get_pep_status_disk_only(req.email) == "completed"

            if not _so_fatca_done:
                msg = render_message("ki_loop.so_fatca", normalize_language(None), summary=_so_summary_block)
                insert_conversation_log(
                    user_email=req.email, role="agent", message=msg, channel="chat",
                    # fatca_trigger must be persisted here (not just returned in the
                    # HTTP response) — transformLogToMessage() on the frontend only
                    # reconstructs msg.fatcaTrigger from metadata.fatca_trigger on any
                    # rebuild (language switch, reload, logout/login). Without this,
                    # the FATCA card silently disappears the moment the page rebuilds
                    # from history instead of from the just-received response. Same
                    # fix already applied to product_package_trigger/self_declaration_trigger
                    # below — this closes the gap for fatca_trigger/pep_trigger too.
                    metadata={"message_type": "ki_loop_finalized", "next_step": "fatca", "fatca_trigger": True}
                )
                return {
                    "success":                  True,
                    "message":                  msg,
                    "fatca_trigger":            True,
                    "pep_trigger":              False,
                    "product_package_trigger":  False,
                    "self_declaration_trigger": False,
                    "next_step":                "fatca",
                }

            if not _so_pep_done:
                msg = render_message("ki_loop.pep", normalize_language(None), summary=_so_summary_block)
                insert_conversation_log(
                    user_email=req.email, role="agent", message=msg, channel="chat",
                    # Same reload-survival fix as fatca_trigger above, for pep_trigger.
                    metadata={"message_type": "ki_loop_finalized", "next_step": "pep", "pep_trigger": True}
                )
                return {
                    "success":                  True,
                    "message":                  msg,
                    "fatca_trigger":            False,
                    "pep_trigger":              True,
                    "product_package_trigger":  False,
                    "self_declaration_trigger": False,
                    "next_step":                "pep",
                }

            if not is_package_done(req.email):
                msg = render_message("ki_loop.package", normalize_language(None), summary=_so_summary_block)
                insert_conversation_log(
                    user_email=req.email, role="agent", message=msg, channel="chat",
                    metadata={"message_type": "ki_loop_finalized", "next_step": "product_package", "product_package_trigger": True}
                )
                return {
                    "success":                  True,
                    "message":                  msg,
                    "fatca_trigger":            False,
                    "pep_trigger":              False,
                    "product_package_trigger":  True,
                    "self_declaration_trigger": False,
                    "next_step":                "product_package",
                }

            msg = render_message("ki_loop.so_selfdecl", normalize_language(None), summary=_so_summary_block)
            insert_conversation_log(
                user_email=req.email, role="agent", message=msg, channel="chat",
                metadata={"message_type": "ki_loop_finalized", "next_step": "self_declaration", "self_declaration_trigger": True}
            )
            return {
                "success":                  True,
                "message":                  msg,
                "fatca_trigger":            False,
                "pep_trigger":              False,
                "self_declaration_trigger": True,
                "next_step":                "self_declaration",
            }

        # Multiple Owner: Ejari already collected — check Product Package then FATCA/PEP chain
        _fatca_done = get_fatca_status_disk_only(req.email) in ("completed", "not_applicable")
        _pep_done   = get_pep_status_disk_only(req.email) == "completed"

        _mp   = load_member_progress(req.email)
        _total = len((_mp or {}).get("members", []))

        # ── Build consolidated member+role summary ───────────────────────────
        # Load all key individuals and format a numbered list for the message.
        # This gives the user a clear record of who was registered before
        # the FATCA/PEP/Self-Declaration compliance chain begins.
        _ki_summary_lines = []
        try:
            _all_ki = load_key_individuals(req.email)
            # Also check member_progress.json verified_members list,
            # since MOA_EXTRACTED members are tracked there (not via
            # verification_status field which is only set for AI_ADDED KIs)
            try:
                _mo_mp = load_member_progress(req.email)
                _mo_verified_names = [
                    n.upper() for n in (_mo_mp or {}).get("verified_members", [])
                ]
            except Exception:
                _mo_verified_names = []
            for _idx, _ki in enumerate(_all_ki, 1):
                _ki_name = _ki.get("display_name") or (
                    f"{_ki.get('first_name', '')} {_ki.get('last_name', '')}".strip()
                )
                _ki_is_as_mo = (
                    _ki.get("is_authorised_signatory") or
                    str(_ki.get("role", "")).strip().upper() in ("AS", "AUTHORISED SIGNATORY")
                )
                _ki_is_ubo_mo = _ki.get("is_ubo", False)
                _ki_role = "Authorised Signatory" if _ki_is_as_mo else "Member"
                if _ki_is_ubo_mo:
                    _ki_role += " (UBO)"
                _ki_share_mo  = _ki.get("share_percentage", "—")
                _ki_mo_is_verified = (
                    _ki.get("verification_status") == "verified" or
                    _ki_name.upper() in _mo_verified_names
                )
                if _ki_name:
                    _ki_summary_lines.append({
                        "name": _ki_name, "is_as": bool(_ki_is_as_mo), "is_ubo": bool(_ki_is_ubo_mo),
                        "share": _ki_share_mo, "verified": bool(_ki_mo_is_verified),
                    })
        except Exception as _kse:
            logger.warning(f"[KI-LOOP] Could not build KI summary: {_kse}")

        _ki_summary_block = members_summary(_ki_summary_lines, "summary.header_registered", normalize_language(None))

        # ── FATCA → PEP → Product Package → Self-Declaration chain (Multiple Owner) ──
        if not _fatca_done:
            msg = render_message("ki_loop.mo_fatca", normalize_language(None), total=_total, summary=_ki_summary_block)
            insert_conversation_log(
                user_email=req.email, role="agent", message=msg, channel="chat",
                # Same reload-survival fix as the Single Owner branch above —
                # transformLogToMessage() needs metadata.fatca_trigger to
                # reconstruct the card after a rebuild.
                metadata={"message_type": "ki_loop_finalized", "next_step": "fatca", "fatca_trigger": True}
            )
            return {
                "success":                   True,
                "message":                   msg,
                "fatca_trigger":             True,
                "pep_trigger":               False,
                "product_package_trigger":   False,
                "self_declaration_trigger":  False,
            }

        if not _pep_done:
            msg = render_message("ki_loop.pep", normalize_language(None), summary=_ki_summary_block)
            insert_conversation_log(
                user_email=req.email, role="agent", message=msg, channel="chat",
                # Same reload-survival fix as above, for pep_trigger.
                metadata={"message_type": "ki_loop_finalized", "next_step": "pep", "pep_trigger": True}
            )
            return {
                "success":                   True,
                "message":                   msg,
                "fatca_trigger":             False,
                "pep_trigger":               True,
                "product_package_trigger":   False,
                "self_declaration_trigger":  False,
            }

        # ── Product Package gate (Multiple Owner) — after FATCA & PEP ────────
        if not is_package_done(req.email):
            msg = render_message("ki_loop.package", normalize_language(None), summary=_ki_summary_block)
            insert_conversation_log(
                user_email=req.email, role="agent", message=msg, channel="chat",
                metadata={"message_type": "ki_loop_finalized", "next_step": "product_package", "product_package_trigger": True}
            )
            return {
                "success":                   True,
                "message":                   msg,
                "product_package_trigger":   True,
                "fatca_trigger":             False,
                "pep_trigger":               False,
                "self_declaration_trigger":  False,
                "next_step":                 "product_package",
            }

        msg = render_message("ki_loop.mo_selfdecl", normalize_language(None), total=_total, summary=_ki_summary_block)
        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type": "ki_loop_finalized",
                "next_step": "self_declaration",
                # Without this, transformLogToMessage() can't reconstruct
                # msg.selfDeclTrigger on reload (it only reads
                # metadata.self_declaration_trigger), so the SelfDeclarationCard
                # never reappears after logout/relogin for accounts that reach
                # Self-Declaration via the KI loop finalize path.
                "self_declaration_trigger": True,
            }
        )
        return {
            "success":                   True,
            "message":                   msg,
            "fatca_trigger":             False,
            "pep_trigger":               False,
            "self_declaration_trigger":  True,
        }

    except Exception as e:
        logger.error(f"[KI-LOOP] Loop finalize error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/ki/verify")
async def ki_verify(req: KiVerifyRequest):
    """
    Mark a Key Individual as verified after their ID document has been
    uploaded and OCR-confirmed.
    """
    try:
        updated = update_ki_verification(req.email, req.ki_id, req.document_id)

        if not updated:
            raise NotFoundError("Key Individual not found")

        try:
            from app.services.message_generator import MessageGenerator
            msg = MessageGenerator.ki_verified(language=normalize_language(None))
        except Exception:
            msg = render_message("ki.verified_fallback", normalize_language(None))

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={"message_type": "ki_verified", "ki_id": req.ki_id}
        )

        return {"success": True, "message": msg}

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[KI] Verify KI error: {e}")
        raise DomainError(context=str(e))


@router.get("/ki/list/{user_email}")
async def ki_list(user_email: str):
    """Return all Key Individuals for this user."""
    kis = load_key_individuals(user_email)
    return {"email": user_email, "key_individuals": kis, "count": len(kis)}
