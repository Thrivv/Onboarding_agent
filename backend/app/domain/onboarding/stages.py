"""
Onboarding stage resolution — where a user is in the flow and what comes next.

`get_onboarding_status` (378 lines) is the heart of the product: it decides,
from the documents on disk and the user record, which stage the user is in and
which document is requested next. It is currently an implicit state machine
expressed as nested conditionals. Stage C turns it into an explicit stage
table; B4 only gives it a module of its own.

Moved verbatim from `app/api/routes/chatupload.py` in Stage B4.
"""

from __future__ import annotations
from app.i18n import localized

import logging
import json
from datetime import datetime, timezone
import traceback
from app.services.document_messaging import (
    # generate_dynamic_valid_document_response is not called here — it is
    # re-exported from this module and imported by documentpage.py.
    generate_dynamic_valid_document_response,
    generate_dynamic_invalid_document_response,
    generate_welcome_message,
    generate_ai_reasoning_for_invalid_document,
    generate_unknown_document_reasoning,
    format_extraction_message,
    extract_document_text_for_reasoning,
)
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
from app.repositories.user_repository import UserRepository
from app.utils.behaviour_capture import capture
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
    resolve_stage,
)
from app.domain.onboarding.documents import _find_commercial_output, get_submitted_documents

logger = logging.getLogger(__name__)

def _resolve_pending_actions(
    email: str,
    account_type: str,
    ownership: str,
    doc_status: dict,
    members_info,
) -> dict:
    """
    Compute the twelve "what is the user being asked for right now" flags.

    Extracted verbatim from `get_onboarding_status` in Stage B5a — 142 lines
    that were the single largest block in that function. The statements are
    unchanged; only their location is.

    The seam was verified with `backend/tests/extract_method.py`, which
    confirmed the block reads exactly the five arguments above, writes exactly
    the twelve keys returned below, and contains no `return`/`break`/`continue`
    that would change meaning once lifted out. Behaviour is additionally pinned
    by the 709-case corpus in `backend/tests/golden/`.

    Why these twelve travel together
    --------------------------------
    They are all recomputed from persisted disk state on EVERY call — page
    load, refresh, resume, upload response — rather than from one-shot trigger
    fields in a single API response. That design note is the reason the block
    exists at all: triggers are lost on refresh and never fire if a request
    times out. See the comments inline.

    The broad `except` is deliberate and preserved: a failure to read a
    breadcrumb file must not fail the whole status call, it must leave the
    flags at their defaults.
    """
    as_ki_selection_pending = False
    as_ki_pending_source = None     # "SO_OWNER" | "MOA_EXTRACTED" — tells the frontend which card shape to build
    as_ki_pending_members = []      # names (MOA) or [{name, share_percentage, role, nationality}] (SO owner)
    as_ki_pending_ubo_names = []    # names flagged as UBO (effective ownership > 25%) — MOA/Type-2 only
    as_ki_pending_ownership_map = {}  # {name: effective_percentage} — MOA/Type-2 only, for expanded
                                       # (corporate-shareholder-derived) members who aren't on the
                                       # Commercial License partners list and so have no other source
                                       # for a share % on the AS/KI card
    product_package_pending = False
    ki_loop_prompt_pending = False
    self_declaration_pending = False
    ki_role_assignment_pending = False
    ki_role_assignment_data = None   # {extracted_fields, document_id} for the pending KiRoleAssignCard
    ki_details_pending = False
    ki_details_pending_data = None   # {ki_name, role} for the pending KiDetailsCard
    mismatch_role_pending = False
    mismatch_role_data = None        # {extracted_name, extracted_business} for the deferred mismatch modal
    try:
        is_multi_owner = ownership in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP)
        existing_kis = load_key_individuals(email)

        if is_multi_owner:
            # MOA AS/Member role selection is pending once MOA is verified but no
            # MOA_EXTRACTED KI record has been saved — that record is only ever
            # created by POST /ki/moa-as-selection.
            if doc_status.get("moa", False):
                as_ki_selection_pending = not any(
                    k.get("source") == "MOA_EXTRACTED" for k in existing_kis
                )
                if as_ki_selection_pending:
                    as_ki_pending_source = "MOA_EXTRACTED"
                    try:
                        _mp = load_member_progress(email)
                        as_ki_pending_members = (_mp or {}).get("members", [])
                        # These two are already persisted by save_member_progress
                        # whenever the Type-1/Type-2 auto-trigger runs (both the
                        # chat-path "type Okay" handler and the file-upload
                        # auto-trigger in upload.py write them) — this was simply
                        # never read back out until now, which is why the AS/KI
                        # card's UBO badge and expanded-member share % only ever
                        # showed up when a request's own JSON response carried
                        # moa_as_trigger/ubo_names directly (single-file, same
                        # session). Any restore through this ground-truth path —
                        # a page reload, or the bulk-upload flow, which never
                        # returns those trigger fields at all — got is_ubo=false
                        # for everyone regardless of what was actually computed.
                        as_ki_pending_ubo_names = (_mp or {}).get("ubo_names", [])
                        as_ki_pending_ownership_map = {
                            _o.get("name"): (_o.get("effective_percentage") or _o.get("effective_pct"))
                            for _o in (_mp or {}).get("expanded_members", [])
                            if _o.get("name")
                        }
                    except Exception as _mp_err:
                        logger.warning(f"[get_onboarding_status] could not load member_progress for pending card: {_mp_err}")
        elif account_type == ACCOUNT_CORPORATE:
            # Owner AS/Member role selection is pending once Ejari is verified but
            # no SO_OWNER KI record has been saved — that record is only ever
            # created by POST /ki/so-as-selection.
            if doc_status.get("ejari", False):
                as_ki_selection_pending = not any(
                    k.get("source") == "SO_OWNER" for k in existing_kis
                )
                if as_ki_selection_pending:
                    as_ki_pending_source = "SO_OWNER"
                    try:
                        _, _comm_data = _find_commercial_output(email)
                        if _comm_data:
                            ef = _comm_data.get("extracted_fields", {})
                            owner_block = (
                                ef.get("owner") or
                                ef.get("english", {}).get("owner") or
                                {"name_english": ef.get("english", {}).get("owner_name", ""),
                                 "share_percentage": "100%", "role": "Owner"}
                            )
                            _owner_name = (
                                owner_block.get("name_english") or owner_block.get("name", "")
                            ).strip()
                            if _owner_name:
                                as_ki_pending_members = [{
                                    "name":             _owner_name,
                                    "share_percentage": owner_block.get("share_percentage", "100%"),
                                    "role":             owner_block.get("role", "Owner"),
                                    "nationality":      owner_block.get("nationality_english", ""),
                                }]
                    except Exception as _owner_err:
                        logger.warning(f"[get_onboarding_status] could not resolve SO owner for pending card: {_owner_err}")

        # Product Package is pending once the KI loop has been finalized
        # (ki_loop_done.json written) and no package has been saved yet.
        # Every ownership type must additionally clear FATCA + PEP first,
        # mirroring the gate already enforced in /ki/loop-finalize.
        loop_done_flag = user_docs_path(email) / "ki_loop_done.json"
        if loop_done_flag.exists() and not is_package_done(email):
            fatca_ready = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
            pep_ready = get_pep_status_disk_only(email) == "completed"
            product_package_pending = fatca_ready and pep_ready

        # ── KiLoopCard ("Add another AS/KI?") ─────────────────────────────────
        # Pending once every currently-known member's ID document is verified
        # but the loop hasn't been finalized yet (ki_loop_done.json missing).
        # Mirrors the exact gate already enforced inline during member-EID
        # upload processing (see the ki_loop_prompt block further down in this
        # file) — reuses members_info, which is already computed above for
        # stage in ("member_eids", "so_member_eids").
        if members_info and members_info.get("total", 0) > 0 and \
                members_info.get("verified", 0) >= members_info.get("total", 0):
            ki_loop_prompt_pending = not loop_done_flag.exists()

        # ── SelfDeclarationCard ────────────────────────────────────────────────
        # Pending once the package step is done (the last step before
        # self-declaration in both flows) but self_declaration.json hasn't
        # been written yet.
        if is_package_done(email):
            self_declaration_pending = not (user_docs_path(email) / "self_declaration.json").exists()

        # ── KiRoleAssignCard (assign AS/Member to a newly-added individual) ───
        # Pending if an EID/Passport was captured via the "Yes, add another"
        # loop (upload-conversational with is_ki_loop_add_eid=true writes this
        # breadcrumb — see chatupload.py's _is_ki_loop_add branch) but no role
        # has been assigned for it yet (/ki/add-ai deletes the breadcrumb on
        # success).
        _ki_role_breadcrumb = user_docs_path(email) / "pending_ki_role_assignment.json"
        if _ki_role_breadcrumb.exists():
            try:
                with open(_ki_role_breadcrumb, "r", encoding="utf-8") as _f:
                    ki_role_assignment_data = json.load(_f)
                ki_role_assignment_pending = True
            except Exception as _kb_err:
                logger.warning(f"[PENDING-ACTIONS] Could not read pending_ki_role_assignment.json: {_kb_err}")

        # ── KiDetailsCard (contact info for a newly-added individual) ─────────
        # Pending if a KI record exists with source=AI_ADDED (role already
        # assigned via /ki/add-ai) but no phone_number/contact_email has been
        # saved yet (/ki/contact-info is what fills those in).
        if not ki_role_assignment_pending:
            for _ki in existing_kis:
                if _ki.get("source") == "AI_ADDED" and not _ki.get("phone_number"):
                    ki_details_pending = True
                    ki_details_pending_data = {
                        "ki_name": _ki.get("display_name", ""),
                        "role": "AS" if _ki.get("is_authorised_signatory") else "MEMBER",
                    }
                    break

        # ── Mismatch role modal — DEFERRED to right before member verification ──
        # A Commercial License name/business mismatch is detected and written to
        # mismatch_pending.json at upload time (see /upload-conversational), but
        # is only surfaced here — same gate as the AS/KI role card
        # (Ejari verified for Single Owner, MOA verified for Multiple Owner) —
        # so the popup no longer interrupts the flow immediately after upload,
        # right before the ownership question. Resolved (cleared) once
        # /mismatch/assign-role saves a KI record and deletes the breadcrumb.
        _mismatch_breadcrumb_path = user_docs_path(email) / "mismatch_pending.json"
        if _mismatch_breadcrumb_path.exists() and (doc_status.get("ejari", False) or doc_status.get("moa", False)):
            try:
                with open(_mismatch_breadcrumb_path, "r", encoding="utf-8") as _mf:
                    mismatch_role_data = json.load(_mf)
                mismatch_role_pending = True
            except Exception as _mrd_err:
                logger.warning(f"[PENDING-ACTIONS] Could not read mismatch_pending.json: {_mrd_err}")
    except Exception as _pending_err:
        logger.warning(f"[get_onboarding_status] {email} could not compute pending-action flags: {_pending_err}")

    return {
        "as_ki_pending_members": as_ki_pending_members,
        "as_ki_pending_source": as_ki_pending_source,
        "as_ki_pending_ubo_names": as_ki_pending_ubo_names,
        "as_ki_pending_ownership_map": as_ki_pending_ownership_map,
        "as_ki_selection_pending": as_ki_selection_pending,
        "ki_details_pending": ki_details_pending,
        "ki_details_pending_data": ki_details_pending_data,
        "ki_loop_prompt_pending": ki_loop_prompt_pending,
        "ki_role_assignment_data": ki_role_assignment_data,
        "ki_role_assignment_pending": ki_role_assignment_pending,
        "mismatch_role_data": mismatch_role_data,
        "mismatch_role_pending": mismatch_role_pending,
        "product_package_pending": product_package_pending,
        "self_declaration_pending": self_declaration_pending,
    }


@capture("get_onboarding_status")
def get_onboarding_status(email: str, user_data: dict, skip_welcome: bool = False) -> dict:
    """
    Get comprehensive onboarding status with next required document
    skip_welcome: If True, don't generate welcome message (prevents duplicate completion messages)
    """
    account_type = user_data.get("account_type")
    ownership = user_data.get("ownership_type")
    document_stage = user_data.get("document_stage", STAGE_IDENTIFICATION)

    # ── OWNERSHIP TYPE — now auto-detected, not asked upfront ───────────────
    # Ownership Type (Single Owner vs Partnership/Multiple Owners) used to be
    # a mandatory question the AI asked before any document could be
    # uploaded. It's now inferred automatically from the Commercial License's
    # extracted partner list as soon as that document is verified (see the
    # auto-classification block in upload_conversational()), so this function
    # no longer short-circuits on an unset ownership — Corporate accounts
    # with ownership still unset simply fall into the "not yet classified"
    # branch below, which requires only the Commercial License.
    #
    # The one case that still needs to ask the user directly is when the
    # Commercial License couldn't be read confidently enough to classify
    # (e.g. no partner/owner data extracted) — that's signalled by an
    # `ownership_ambiguous.json` breadcrumb file written by the
    # auto-classification block, checked further down where
    # `ownership_selection_pending` is computed.

    doc_status = check_documents_status(email)
    submitted_docs = get_submitted_documents(email)

    logger.debug(f"[get_onboarding_status] {email} doc_status={doc_status}")
    logger.debug(
        f"[get_onboarding_status] {email} submitted_docs="
        f"{[(d.get('document_type'), d.get('is_valid')) for d in submitted_docs]}"
    )

    # CRITICAL FIX: Initialize members_info to None at the start
    members_info = None

    # Determine required documents based on account type
    # Note: "identity" in required_all is satisfied by either EID or Passport
    # Stage C1: this was 27 lines of nested account_type/ownership/stage
    # conditionals. It is now a declarative lookup in stage_table.py, where the
    # whole flow can be read at once instead of traced. Behaviour is unchanged
    # and pinned by the 709-case corpus in tests/synthesize_golden.py.
    required_all, stage = resolve_stage(account_type, ownership, document_stage)

    # CRITICAL FIX: Cross-check doc_status with submitted_docs
    # Sometimes check_documents_status() misses recently uploaded documents
    # So we verify against the actual submitted_documents list
    for doc in submitted_docs:
        doc_type = doc.get("document_type", "").lower()
        is_valid = doc.get("is_valid", False)

        # If this is a required document and it's valid, mark it in doc_status
        if doc_type in required_all and is_valid:
            if not doc_status.get(doc_type, False):
                doc_status[doc_type] = True
        # Passport satisfies the EID/identity requirement
        if doc_type == "passport" and is_valid:
            if not doc_status.get("eid", False):
                doc_status["eid"] = True
                doc_status["passport"] = True
        # EID satisfies identity requirement
        if doc_type == "eid" and is_valid:
            doc_status["identity"] = True
        # Recalculate identity virtual status after each doc check
        doc_status["identity"] = bool(doc_status.get("eid") or doc_status.get("passport"))

    logger.debug(f"[get_onboarding_status] {email} required={required_all} doc_status_after_fix={doc_status}")

    # Check what's missing
    pending = []
    for req in required_all:
        if req == "identity":
            # Identity is satisfied by EID OR Passport
            if not (doc_status.get("eid") or doc_status.get("passport") or doc_status.get("identity")):
                pending.append("identity")
        elif not doc_status.get(req, False):
            pending.append(req)

    logger.debug(f"[get_onboarding_status] {email} pending_documents={pending}")

    # Determine next required document
    next_required = None
    if stage == STAGE_IDENTIFICATION and pending:
        next_doc_type = pending[0]
        # Map identity to display-friendly type
        display_type = "identity" if next_doc_type == "identity" else next_doc_type
        next_required = {
            "type": display_type,
            "requires_member_name": False,
            "member_name": None
        }
    elif stage in (STAGE_MEMBER_EIDS, STAGE_SO_MEMBER_EIDS):
        # Build members_info from member_progress for both Multiple Owner and Single Owner
        mp = load_member_progress(email)
        if mp:
            all_members = mp.get("members", [])
            current_idx = mp.get("current_index", 0)

            # Verified check — trust member_progress.json's own "verified_members"
            # list, the same source every other verification path in this file
            # reads/writes (see the SO-EID and MEMBER-EID handlers below, and the
            # verify-response guards). A prior version of this block re-derived
            # verification by scanning user_docs_path/<member_name>/*/output.json,
            # but EID/Passport uploads are actually saved under
            # user_docs_path/members/MEID-<uuid>-<n>/output.json — a different
            # location — so that scan always found 0 files and silently reported
            # 0 verified members even once everyone was actually done, which kept
            # ki_loop_prompt_pending (and everything gated behind it) stuck False.
            _mp_verified_raw = mp.get("verified_members", [])
            verified_members = [m for m in all_members if m in _mp_verified_raw]

            members_info = {
                "total": len(all_members),
                "verified": len(verified_members),
                "current_member": all_members[current_idx] if current_idx < len(all_members) else None,
                "all_members": all_members,
                "verified_members": verified_members,
                "pending_members": [m for m in all_members if m not in verified_members]
            }

            pending_members = members_info["pending_members"]
            if pending_members:
                next_required = {
                    "type": "eid_or_passport",
                    "requires_member_name": True,
                    "member_name": pending_members[0]
                }

    # Check if complete
    is_complete = False
    if stage == STAGE_IDENTIFICATION and not pending:
        if account_type == ACCOUNT_CORPORATE and ownership in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            is_complete = False
        else:
            is_complete = True
    elif stage in (STAGE_MEMBER_EIDS, STAGE_SO_MEMBER_EIDS):
        if members_info:
            is_complete = members_info["verified"] >= members_info["total"] and members_info["total"] > 0
            # For Single Owner in so_member_eids: never mark complete here —
            # completing means Ejari still pending; that is handled by the
            # stage transition in handle_verification_response.
            if stage == STAGE_SO_MEMBER_EIDS:
                is_complete = False

    logger.debug(f"[get_onboarding_status] {email} is_complete={is_complete} next_required={next_required}")

    # Generate AI message ONLY if not skipping
    if skip_welcome:
        ai_message = ""
    else:
        ai_message = generate_welcome_message(
            email, user_data, doc_status, stage, pending,
            next_required, is_complete, members_info  # Now always initialized
        )

    # ── Ownership selection fallback ────────────────────────────────────────
    # Only true when the Commercial License auto-classification block
    # couldn't confidently read partner/owner data from it and wrote this
    # breadcrumb file, asking the user directly instead. Cleared by
    # POST /ownership-type/save once the user answers.
    ownership_selection_pending = (user_docs_path(email) / "ownership_ambiguous.json").exists()
    if ownership_selection_pending and not skip_welcome:
        ai_message = localized(None,
            en="I couldn't clearly read the ownership details on your Commercial License. Quick question so I can set things up right: do you own this business by yourself, as a Sole Proprietorship, or do you share ownership with others, under Joint Ownership?",
            es="No pude leer con claridad los datos de propiedad de su Licencia Comercial. Una pregunta rápida para configurarlo bien: ¿es el único propietario de la empresa (propiedad única) o comparte la propiedad con otras personas (propiedad conjunta)?",
            ar="لم أتمكن من قراءة تفاصيل الملكية في رخصتك التجارية بوضوح. سؤال سريع لإعداد الحساب بشكل صحيح: هل تملك هذا النشاط بمفردك بصفة ملكية فردية، أم تتشارك الملكية مع آخرين بصفة ملكية مشتركة؟")

    # ============================================================================
    # GROUND-TRUTH PENDING-ACTION FLAGS
    # ============================================================================
    # as_ki_selection_pending / product_package_pending are recomputed from
    # persisted disk state EVERY time this function runs (page load, refresh,
    # resume-conversation, any upload response) instead of relying on a one-shot
    # trigger field (so_as_trigger / moa_as_trigger / product_package_trigger)
    # that only ever lives inside a single API response. Those triggers are lost
    # on page refresh and never fire at all if the upload request times out —
    # these flags fix both cases by asking "has the required record actually
    # been saved yet?" rather than "did that one request succeed?".
    # Pending-action flags — extracted to _resolve_pending_actions() in B5a.
    # Unpacked into the same local names the return dict below expects, so
    # nothing downstream of here changed.
    _pending_actions = _resolve_pending_actions(
        email, account_type, ownership, doc_status, members_info
    )
    as_ki_pending_members = _pending_actions["as_ki_pending_members"]
    as_ki_pending_source = _pending_actions["as_ki_pending_source"]
    as_ki_pending_ubo_names = _pending_actions["as_ki_pending_ubo_names"]
    as_ki_pending_ownership_map = _pending_actions["as_ki_pending_ownership_map"]
    as_ki_selection_pending = _pending_actions["as_ki_selection_pending"]
    ki_details_pending = _pending_actions["ki_details_pending"]
    ki_details_pending_data = _pending_actions["ki_details_pending_data"]
    ki_loop_prompt_pending = _pending_actions["ki_loop_prompt_pending"]
    ki_role_assignment_data = _pending_actions["ki_role_assignment_data"]
    ki_role_assignment_pending = _pending_actions["ki_role_assignment_pending"]
    mismatch_role_data = _pending_actions["mismatch_role_data"]
    mismatch_role_pending = _pending_actions["mismatch_role_pending"]
    product_package_pending = _pending_actions["product_package_pending"]
    self_declaration_pending = _pending_actions["self_declaration_pending"]

    logger.debug(
        f"[get_onboarding_status] {email} pending-actions: "
        f"as_ki_selection={as_ki_selection_pending}(source={as_ki_pending_source}) "
        f"product_package={product_package_pending} ki_loop_prompt={ki_loop_prompt_pending} "
        f"self_declaration={self_declaration_pending} ki_role_assignment={ki_role_assignment_pending} "
        f"ki_details={ki_details_pending}"
    )

    # ============================================================================
    # Stage 10 — LangGraph shadow-mode comparison (additive, read-only)
    # ============================================================================
    # Off unless LANGGRAPH_ENABLED=true (see config.py). When on, this recomputes
    # the same two decisions this function just made — `stage` (via
    # stage_table.resolve_stage(), called above) and the pending-action flags
    # (via _resolve_pending_actions(), also called above) — through the graph
    # package's `routing.route_by_ownership()` / `pending.all_pending()` instead,
    # and logs any disagreement. It NEVER changes `ai_message`, the returned
    # dict, or anything else a caller can observe — this block exists purely to
    # keep proving, on real production traffic instead of only the synthetic
    # 14,688-case corpus `tests/langgraph_parity_check.py` already covers, that
    # the graph package's routing/pending logic has not drifted from this
    # function's own — before Stage 11 lets anything actually act on the graph's
    # answer instead of this function's.
    #
    # Every exception here is caught and logged, never raised — a bug in the
    # shadow path (or a graph-package import failure) must never be able to
    # break the real onboarding-status response this function returns.
    try:
        from app.config import LANGGRAPH_ENABLED

        if LANGGRAPH_ENABLED:
            from app.domain.onboarding.graph.adapters import state_from_user
            from app.domain.onboarding.graph.routing import route_by_ownership
            from app.domain.onboarding.graph.pending import all_pending

            _shadow_state = state_from_user(email, user_data, channel="chat")
            _shadow_routed_node = route_by_ownership(_shadow_state)
            _shadow_pending_types = {p["type"] for p in all_pending(email, _shadow_state)}

            _legacy_pending_flags = {
                "ownership_choice": ownership_selection_pending,
                "as_ki_selection": as_ki_selection_pending,
                "ki_loop_prompt": ki_loop_prompt_pending,
                "ki_role_assignment": ki_role_assignment_pending,
                "ki_details": ki_details_pending,
                "mismatch_role": mismatch_role_pending,
                "product_package": product_package_pending,
                "self_declaration": self_declaration_pending,
            }
            _mismatches = [
                f"pending[{_type}]: legacy={_legacy_val}, graph={_type in _shadow_pending_types}"
                for _type, _legacy_val in _legacy_pending_flags.items()
                if bool(_legacy_val) != (_type in _shadow_pending_types)
            ]
            if _shadow_state.get("stage") != stage:
                _mismatches.append(f"stage: legacy={stage!r}, graph={_shadow_state.get('stage')!r}")

            if _mismatches:
                logger.warning(
                    f"[graph.shadow] {email} DRIFT vs legacy get_onboarding_status(): "
                    f"{'; '.join(_mismatches)} (routed_node={_shadow_routed_node!r})"
                )
            else:
                logger.debug(f"[graph.shadow] {email} matches legacy — routed_node={_shadow_routed_node!r}")
    except Exception as _shadow_exc:
        logger.warning(f"[graph.shadow] {email} shadow comparison failed (non-fatal): {_shadow_exc}")

    return {
        "stage": stage,
        "required_documents": required_all,
        "submitted_documents": submitted_docs,
        "pending_documents": pending,
        "next_required_document": next_required,
        "members_info": members_info,  # Can be None for non-partnership accounts
        "ai_message": ai_message,
        "is_complete": is_complete,
        # ── Ground-truth pending-action flags (see notes above) ───────────────
        "ownership_selection_pending": ownership_selection_pending,
        "as_ki_selection_pending": as_ki_selection_pending,
        "as_ki_pending_source": as_ki_pending_source,
        "as_ki_pending_members": as_ki_pending_members,
        "as_ki_pending_ubo_names": as_ki_pending_ubo_names,
        "as_ki_pending_ownership_map": as_ki_pending_ownership_map,
        "product_package_pending": product_package_pending,
        "ki_loop_prompt_pending": ki_loop_prompt_pending,
        "self_declaration_pending": self_declaration_pending,
        "ki_role_assignment_pending": ki_role_assignment_pending,
        "ki_role_assignment_data": ki_role_assignment_data,
        "ki_details_pending": ki_details_pending,
        "ki_details_pending_data": ki_details_pending_data,
        "mismatch_role_pending": mismatch_role_pending,
        "mismatch_role_data": mismatch_role_data,
    }


def update_user_onboarding_status(email: str, is_complete: bool, stage: str):
    """Update user's onboarding status in database"""
    try:
        if is_complete:
            update_data = {
                "onboarding_step": "verification_complete",
                "document_stage": "onboarding_complete",
                "document_confirmation_sent": True,
                "confirmation_timestamp": datetime.now(timezone.utc).isoformat()
            }
            logger.info(f"Updating user status to COMPLETE")
        else:
            update_data = {
                "onboarding_step": "documents_pending",
                "document_stage": stage
            }
            logger.info(f"Updating user status to stage: {stage}")
        
        UserRepository.update_by_email(email, update_data)
        logger.info(f"[SUCCESS] Database updated for {email}")
        
    except Exception as e:
        logger.error(f"Failed to update user status: {e}")
        import traceback
        logger.error(traceback.format_exc())
