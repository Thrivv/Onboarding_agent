"""
`handle_verification_response` — what happens when a user confirms in chat.

Moved verbatim out of verification.py in B5. 1,181 lines, 29 returns at up to
five levels of nesting, still in one function.

READ THIS BEFORE CHANGING ANYTHING HERE

This function is under review for deletion, not improvement. The chat
confirmation path it serves looks vestigial: the email channel never calls it,
its one live caller is conversation.py, and upload.py performs the same stage
transitions itself. domain/onboarding/hvr_audit.py instruments all five
mutation sites and tags each write REDUNDANT or EFFECTIVE.

    Nothing EFFECTIVE over a representative period  => delete this module.
    One EFFECTIVE                                   => it is load bearing.

Decomposing the body before that question is answered risks spending real
effort on code that is about to be removed — and doing it unprotected, since
the 709-case golden corpus covers get_onboarding_status, not this.

Framework-free: no FastAPI import.
"""

from __future__ import annotations
from app.i18n import render_message, members_summary, concat

import logging
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import traceback
from app.i18n import localized
from app.i18n.messages import doc_name as i18n_doc_name
from app.services.message_generator import MessageGenerator, ai_message_gen
from app.utils.language import normalize_language
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
from app.services.cross_validator import CrossValidator
from app.services.supabase_client import supabase, get_user_by_email
from app.services.ocr_service import process_document
from app.services.email_sender import (
    send_email,
    send_tampering_rejection_email,
    send_manual_review_email_tampering,
    send_validation_failed_email,
    send_validation_passed_email,
    send_document_verification_email,
    # send_onboarding_completion_email is not called here — it is re-exported
    # from this module and imported by documentpage.py.
    send_onboarding_completion_email,
    send_corporate_shareholder_request_email,   # TYPE-2
    send_ubo_identified_email,                  # TYPE-2
)
from app.services.eid_validation import validate_eid_before_confirmation
from app.utils.behaviour_capture import capture
from app.domain.onboarding.stages import get_onboarding_status, update_user_onboarding_status
from app.domain.onboarding.confirmation import is_confirmation
from app.domain.onboarding.hvr_audit import audit_mutation, _ki_status_before  # noqa: F401
from app.domain.onboarding.verification.latest_document import (
    _find_latest_unverified_document,
)
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_SINGLE,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)


logger = logging.getLogger(__name__)


@capture("handle_verification_response")
def handle_verification_response(
    email: str,
    user_message: str,
    user_data: dict,
    language: str = "english"
) -> dict:
    """
    FULLY UPDATED: Language-aware verification with proper completion messages
    Handle user verification with cross-validation + SurePass API validation
    Generates dynamic LLM messages in user's language
    """

    # ============================================================================
    # STEP 1: USE PASSED LANGUAGE (DON'T AUTO-DETECT)
    # ============================================================================
    user_language = normalize_language(language)

    logger.info(f"[VERIFY] Using selected language: {user_language.upper()}")
    logger.info(f"[VERIFY] User message: '{user_message}'")

    from app.services.message_generator import MessageGenerator

    # ============================================================================
    # STEP 2: KEYWORD CHECK - English + Spanish
    # ============================================================================
    # Whole-word match with negation handling — see app/domain/onboarding/
    # confirmation.py. The previous substring scan treated "not correct" as a
    # confirmation, and this function writes: update_user_onboarding_status at
    # four sites below, update_ki_verification_by_name at one.
    user_lower = user_message.lower().strip()
    is_verification = is_confirmation(user_message)

    if not is_verification:
        return {
            "is_verification": False,
            "verified": False,
            "next_message": None,
            "is_complete": False
        }

    logger.debug(f"Verification detected from user: '{user_message}'")

    # ============================================================================
    # STEP 2b: GUARD — if all members verified but self-declaration pending,
    # always return the self-declaration trigger (don't fall through to regular
    # doc verification which would skip it entirely).
    # ============================================================================
    try:
        _mp_guard = load_member_progress(email)
        _decl_guard = user_docs_path(email) / "self_declaration.json"
        if _mp_guard:
            _g_members = _mp_guard.get("members", [])
            _g_verified = _mp_guard.get("verified_members", [])
            _g_all_verified = len(_g_members) > 0 and len(_g_verified) >= len(_g_members)
            _g_decl_done = _decl_guard.exists()
            # Single Owner: Ejari is now collected UPFRONT (step 2 of the flow,
            # right after commercial license).  By the time we reach so_member_eids
            # and the KI loop, Ejari is already verified on disk.
            # We only block FATCA if Ejari is genuinely missing/unverified.
            _g_so_needs_ejari = False
            if user_data.get("ownership_type") == OWNERSHIP_SINGLE:
                if user_data.get("document_stage") == STAGE_SO_MEMBER_EIDS:
                    # Ejari was collected before role assignment in the new flow.
                    # Check whether it is actually verified on disk; only block
                    # if it's genuinely absent (edge-case / legacy sessions).
                    _guard_ki_done = (user_docs_path(email) / "ki_loop_done.json").exists()
                    if _guard_ki_done:
                        # KI loop is done — check if Ejari is already verified
                        _ejari_already_verified = False
                        try:
                            _root_so = user_docs_path(email)
                            for _so_item in _root_so.iterdir():
                                if not _so_item.is_dir():
                                    continue
                                _so_out = _so_item / "output.json"
                                if not _so_out.exists():
                                    continue
                                with open(_so_out, "r", encoding="utf-8") as _so_f:
                                    _so_data = json.load(_so_f)
                                if (_so_data.get("document_type", "").lower() in ("ejari", "tenancy")
                                        and _so_data.get("human_verified", False)):
                                    _ejari_already_verified = True
                                    break
                        except Exception:
                            pass
                        if not _ejari_already_verified:
                            # Ejari truly missing (legacy / edge-case) — block FATCA
                            _g_so_needs_ejari = True
                            logger.warning(f"[VERIFY] KI loop done but Ejari not yet verified — holding FATCA")
                        else:
                            logger.info(f"[VERIFY] KI loop done + Ejari already verified — proceeding to FATCA")
                    # else: ki_loop_done.json absent → KI loop gate below fires first
                elif user_data.get("document_stage") == STAGE_IDENTIFICATION:
                    # Check if Ejari exists AND is human_verified
                    _ejari_verified = False
                    try:
                        _root_guard = user_docs_path(email)
                        _mp_names = _mp_guard.get("members", []) if _mp_guard else []
                        for _gitem in _root_guard.iterdir():
                            if not _gitem.is_dir() or _gitem.name in _mp_names or _gitem.name == "members":
                                continue
                            _gout = _gitem / "output.json"
                            if not _gout.exists():
                                continue
                            with open(_gout, "r", encoding="utf-8") as _gf:
                                _gdata = json.load(_gf)
                            _gdt = _gdata.get("document_type", "").lower()
                            if _gdt in ("ejari", "tenancy") and _gdata.get("human_verified", False):
                                _ejari_verified = True
                                break
                    except Exception as _egex:
                        logger.warning(f"[VERIFY] Ejari human_verified check failed: {_egex}")
                    if not _ejari_verified:
                        _g_so_needs_ejari = True   # Ejari not yet confirmed by user
                        logger.info(f"[VERIFY] ⏭ Guard: Single Owner identification stage — Ejari not yet human_verified, skipping FATCA chain")

            if _g_all_verified and not _g_decl_done and not _g_so_needs_ejari:
                logger.info(f"[VERIFY]  Guard: all {len(_g_members)} members verified — checking KI loop gate then FATCA/PEP/SelfDecl chain")
                _total = len(_g_members)

                # ── KI Loop gate ──────────────────────────────────────────────
                # Before triggering FATCA, ensure the conversational "add another
                # AS/KI?" loop has been finalized by the user clicking "No, Proceed"
                # in the KiLoopCard.  The frontend calls /ki/loop-finalize which
                # writes ki_loop_done.json.  Until that file exists, hold here
                # and return ki_loop_prompt so the frontend shows the card.
                _ki_loop_done_path = user_docs_path(email) / "ki_loop_done.json"
                if not _ki_loop_done_path.exists():
                    _loop_msg = localized(user_language,
                        en=("All identity documents have been verified.\n\n"
                            "Would you like to add any additional Authorised Signatory "
                            "or Key Individual to this account?"),
                        es=("Todos los documentos de identidad han sido verificados.\n\n"
                            "¿Desea añadir algún Firmante Autorizado o Persona Clave adicional a esta cuenta?"),
                        ar=("تم التحقق من جميع مستندات الهوية.\n\n"
                            "هل ترغب في إضافة مفوّض بالتوقيع أو فرد رئيسي آخر إلى هذا الحساب؟"))
                    logger.info(f"[VERIFY] KI loop gate: ki_loop_done.json not found — returning ki_loop_prompt")
                    return {
                        "is_verification":           True,
                        "verified":                  True,
                        "next_message":              _loop_msg,
                        "is_complete":               False,
                        "ki_loop_prompt":            True,
                        "fatca_trigger":             False,
                        "pep_trigger":               False,
                        "self_declaration_trigger":  False,
                    }
                # ── End KI Loop gate ──────────────────────────────────────────

                # ── v4: FATCA → PEP → Product Package → Self-Declaration chain ──
                # Re-enabled: Single Owner now runs the same FATCA/PEP gating as
                # Multiple Owner/Partnership.
                _g_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                _g_pep_done   = get_pep_status_disk_only(email) == "completed"

                if not _g_fatca_done:
                    _guard_msg = localized(None,
                        en=f"All {_total} member identity documents have been successfully verified. Please complete your **FATCA Declaration** below before proceeding.",
                        es=f"Los {_total} documentos de identidad de los miembros se han verificado correctamente. Complete su **Declaración FATCA** a continuación antes de continuar.",
                        ar=f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_total}). يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه قبل المتابعة.")
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _guard_msg,
                        "is_complete": False,
                        "fatca_trigger": True,
                        "pep_trigger": False,
                        "self_declaration_trigger": False,
                    }

                if not _g_pep_done:
                    _guard_msg = render_message("ki_loop.pep", None, summary="")
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _guard_msg,
                        "is_complete": False,
                        "fatca_trigger": False,
                        "pep_trigger": True,
                        "self_declaration_trigger": False,
                    }

                # ── Product Package gate ──────────────────────────────────────
                # Reached once FATCA + PEP are both done, for every ownership type.
                if not is_package_done(email):
                    _pkg_msg = render_message("ki_loop.package", None, summary="")
                    logger.info(f"[VERIFY] Product Package gate: product_package.json not found — returning product_package_trigger")
                    return {
                        "is_verification":           True,
                        "verified":                  True,
                        "next_message":              _pkg_msg,
                        "is_complete":               False,
                        "product_package_trigger":   True,
                        "fatca_trigger":             False,
                        "pep_trigger":               False,
                        "self_declaration_trigger":  False,
                    }
                # ── End Product Package gate ───────────────────────────────────

                _guard_msg = localized(user_language,
                    en=(f"All {_total} member identity documents have been "
                        f"successfully verified.\n\n"
                        f"The final step before account activation is the "
                        f"**Self-Declaration**. Please review and confirm the declaration "
                        f"below to complete your onboarding process."),
                    es=(f"Los {_total} documentos de identidad de los miembros han sido "
                        f"verificados exitosamente.\n\n"
                        f"El paso final antes de la activación de la cuenta es la "
                        f"**Auto-Declaración**. Por favor, revise y confirme la declaración "
                        f"a continuación para completar su proceso de incorporación."),
                    ar=(f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_total}).\n\n"
                        f"الخطوة الأخيرة قبل تفعيل الحساب هي **الإقرار الذاتي**. "
                        f"يُرجى مراجعة الإقرار أدناه وتأكيده لاستكمال إجراءات التسجيل."))
                return {
                    "is_verification": True,
                    "verified": True,
                    "next_message": _guard_msg,
                    "is_complete": False,
                    "fatca_trigger": False,
                    "pep_trigger": False,
                    "self_declaration_trigger": True,
                }
    except Exception as _ge:
        logger.warning(f"[VERIFY] Self-decl guard check failed (non-fatal): {_ge}")

    # ============================================================================
    # STEP 3: Find the most recently uploaded unverified document
    # FIX: Load member names first so we can EXCLUDE their folders from the
    #         main-user scan (previously only skipped a literal "members" folder).
    # ============================================================================
    # Newest unconfirmed document — extracted to
    # _find_latest_unverified_document() in B5b. Unpacked into the same
    # local names the code below already used.
    _latest = _find_latest_unverified_document(email, user_data)
    analysis = _latest["analysis"]
    latest_doc = _latest["latest_doc"]
    latest_doc_type = _latest["latest_doc_type"]
    latest_member_name = _latest["latest_member_name"]
    latest_extracted_data = _latest["latest_extracted_data"]

    if not latest_doc:
        # ── Recovery: if all members are verified but self-declaration not yet done ──
        try:
            _mp = load_member_progress(email)
            _decl_path = user_docs_path(email) / "self_declaration.json"
            if _mp:
                _members = _mp.get("members", [])
                _verified = _mp.get("verified_members", [])
                _all_verified = len(_members) > 0 and len(_verified) >= len(_members)
                _self_decl_done = _decl_path.exists()
                # Single Owner: don't short-circuit to self-decl while still in
                # so_member_eids — Ejari must be collected first
                _so_ejari_pending = (
                    user_data.get("ownership_type") == OWNERSHIP_SINGLE and
                    user_data.get("document_stage") == STAGE_SO_MEMBER_EIDS
                )
                if _all_verified and not _self_decl_done and not _so_ejari_pending:
                    logger.info(f"[VERIFY] Recovery: all {len(_members)} members verified — checking FATCA/PEP/Package/SelfDecl chain")
                    _total = len(_members)
                    # ── v4: FATCA → PEP → Product Package → Self-Declaration chain ──
                    # Re-enabled: Single Owner now runs the same FATCA/PEP gating as
                    # Multiple Owner/Partnership.
                    _r_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                    _r_pep_done   = get_pep_status_disk_only(email) == "completed"

                    if not _r_fatca_done:
                        _msg = (
                            localized(user_language,
                                en=(f"All {_total} member identity documents have been successfully verified. "
                            f"Please complete your **FATCA Declaration** below before proceeding."),
                                es=(f"Los {_total} documentos de identidad de los miembros han sido verificados exitosamente. "
                            f"Por favor complete su **Declaración FATCA** a continuación."),
                                ar=(f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_total}). "
                            f"يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه قبل المتابعة."))
                        )
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": _msg, "is_complete": False,
                            "fatca_trigger": True, "pep_trigger": False, "self_declaration_trigger": False,
                        }

                    if not _r_pep_done:
                        _msg = (
                            localized(user_language,
                                en=("FATCA declaration saved.\n\nPlease complete your **PEP Declaration** below."),
                                es=("Declaración FATCA guardada.\n\nPor favor complete su **Declaración PEP** a continuación."),
                                ar=("تم حفظ إقرار فاتكا.\n\nيُرجى استكمال **إقرار الأشخاص المعرّضين سياسياً (PEP)** أدناه."))
                        )
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": _msg, "is_complete": False,
                            "fatca_trigger": False, "pep_trigger": True, "self_declaration_trigger": False,
                        }

                    if not is_package_done(email):
                        _msg = (
                            localized(user_language,
                                en=("FATCA and PEP declarations are complete.\n\nPlease select your **Product Package** below."),
                                es=("Declaraciones FATCA y PEP completadas.\n\nPor favor seleccione su **Paquete de Producto** a continuación."),
                                ar=("اكتمل إقرارا فاتكا والأشخاص المعرّضين سياسياً.\n\nيُرجى اختيار **باقة المنتجات** أدناه."))
                        )
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": _msg, "is_complete": False,
                            "product_package_trigger": True, "fatca_trigger": False,
                            "pep_trigger": False, "self_declaration_trigger": False,
                        }

                    _msg = (
                        localized(user_language,
                            en=(f"All {_total} member identity documents have been successfully verified.\n\n"
                        f"The final step before account activation is the **Self-Declaration**. "
                        f"Please review and confirm the declaration below."),
                            es=(f"Los {_total} documentos de identidad de los miembros han sido "
                        f"verificados exitosamente.\n\nEl paso final es la **Auto-Declaración**."),
                            ar=(f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({_total}).\n\n"
                        f"الخطوة الأخيرة قبل تفعيل الحساب هي **الإقرار الذاتي**. "
                        f"يُرجى مراجعة الإقرار أدناه وتأكيده."))
                    )
                    return {
                        "is_verification": True, "verified": True,
                        "next_message": _msg, "is_complete": False,
                        "fatca_trigger": False, "pep_trigger": False, "self_declaration_trigger": True,
                    }
        except Exception as _re:
            logger.warning(f"[VERIFY] Recovery check failed: {_re}")

        no_doc_message = localized(user_language,
            en=("I couldn't find a document to verify. Please upload a document first."),
            es=("No pude encontrar un documento para verificar. Por favor, sube un documento primero."),
            ar=("لم أجد مستنداً للتحقق منه. يُرجى تحميل مستند أولاً."))

        return {
            "is_verification": True,
            "verified": False,
            "next_message": no_doc_message,
            "is_complete": False
        }

    # ============================================================================
    # STEP 4: Mark document as verified
    # ============================================================================
    try:
        with open(latest_doc, "r", encoding="utf-8") as f:
            analysis = json.load(f)

        analysis["human_verified"] = True
        analysis["verified_at"] = datetime.now(timezone.utc).isoformat()

        with open(latest_doc, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)

        doc_type = latest_doc_type or "document"
        user_name = user_data.get("name", "User")

        logger.debug(f"Document marked as verified:")
        logger.info(f"  - Type: {doc_type}")
        logger.info(f"  - Member: {latest_member_name or 'N/A (main user)'}")
        logger.info(f"  - Language: {user_language.upper()}")

        # ====================================================================
        # MEMBER IDENTITY VERIFICATION FLOW (EID or Passport)
        # ====================================================================
        IDENTITY_DOC_TYPES = {"eid", "passport", "emirates id", "emirates_id"}
        if latest_member_name and doc_type.lower() in IDENTITY_DOC_TYPES:
            id_label = "Passport" if doc_type.lower() == "passport" else "EID"
            logger.info(f"Member {id_label} verified for: {latest_member_name}")

            # ── FIX Issue 2: Multiple Owner (member_eids stage) uses disk-based
            # detection in upload-conversational, NOT current_index.
            # If we also increment current_index here on "okay", the counter
            # double-advances and re-asks for the same / next member incorrectly.
            # Solution: when stage == "member_eids" (Multiple Owner Type 1 & 2),
            # mark the document human_verified (already done above) but do NOT
            # write back to member_progress.json here — let upload-conversational's
            # disk-scan be the sole source of truth for advancement.
            # Single Owner (so_member_eids) keeps the original increment logic.
            _current_doc_stage = user_data.get("document_stage", "")
            _is_multiple_owner_eids = _current_doc_stage == STAGE_MEMBER_EIDS

            progress_file = member_progress_path(email)
            if progress_file.exists():
                with open(progress_file, "r", encoding="utf-8") as f:
                    progress = json.load(f)

                members = progress.get("members", [])
                current_index = progress.get("current_index", 0)
                verified_members = progress.get("verified_members", [])

                if latest_member_name not in verified_members:
                    verified_members.append(latest_member_name)
                    progress["verified_members"] = verified_members

                    if not _is_multiple_owner_eids:
                        # Single Owner (so_member_eids): safe to increment index —
                        # upload-conversational uses current_index in this path.
                        progress["current_index"] = current_index + 1

                    with open(progress_file, "w", encoding="utf-8") as f:
                        json.dump(progress, f, indent=2, ensure_ascii=False)

                    # ── Sync verification_status in key_individuals.json ──────
                    # MOA_EXTRACTED members are tracked only in member_progress.json
                    # by default; this keeps key_individuals.json in sync so the
                    # final registered-individuals summary shows "Verified" for
                    # all members regardless of how they were added.
                    try:
                        # Derive document_id from the verified doc path:
                        # structure is .../email[/member_name]/doc_id/analysis.json
                        _eid_doc_id = latest_doc.parent.name if latest_doc else ""
                        audit_mutation("ki_verification", email=email,
                                       before=_ki_status_before(email, latest_member_name),
                                       after="verified", site="ki-verify")
                        update_ki_verification_by_name(
                            email=email,
                            member_name=latest_member_name,
                            document_id=_eid_doc_id,
                        )
                    except Exception as _kv_err:
                        logger.warning(f"[VERIFY] update_ki_verification_by_name failed for '{latest_member_name}': {_kv_err}")

                verified_count = len(verified_members)
                total_members = len(members)

                if verified_count < total_members:
                    if _is_multiple_owner_eids:
                        # Multiple Owner: derive next member from verified list
                        # (disk-scan authoritative; current_index not reliable here)
                        next_member = next(
                            (m for m in members if m not in verified_members), None
                        )
                    else:
                        next_member = (
                            members[progress["current_index"]]
                            if progress["current_index"] < len(members)
                            else None
                        )

                    if next_member:
                        try:
                            next_message = MessageGenerator.progress_update(
                                completed=verified_count,
                                total=total_members,
                                current_member=next_member,
                                language=user_language
                            )
                        except Exception as e:
                            logger.warning(f"Progress message generation failed: {e}")
                            next_message = localized(user_language,
                                en=(f"{latest_member_name}'s identity document ({id_label}) verified!\n\n"
                                    f"Progress: {verified_count}/{total_members}\n\n"
                                    f"Next: {next_member}"),
                                es=(f"¡Documento de identidad de {latest_member_name} verificado!\n\n"
                                    f"Progreso: {verified_count}/{total_members}\n\n"
                                    f"Siguiente: {next_member}"),
                                ar=(f"تم التحقق من مستند هوية {latest_member_name}!\n\n"
                                    f"التقدّم: {verified_count}/{total_members}\n\n"
                                    f"التالي: {next_member}"))

                        return {
                            "is_verification": True,
                            "verified": True,
                            "next_message": next_message,
                            "is_complete": False
                        }

                else:
                    # ── ALL MEMBERS VERIFIED ────────────────────────────────
                    logger.info(f"\n{'='*80}")
                    logger.info(f"ALL {total_members} MEMBER IDENTITY DOCUMENTS VERIFIED!")
                    logger.info(f"{'='*80}\n")

                    _so_ownership = user_data.get("ownership_type", "")

                    # ── Single Owner: KI loop gate first, then Ejari ───────────
                    if _so_ownership == OWNERSHIP_SINGLE:
                        logger.info(f" Single Owner — all member EIDs done → checking KI loop gate")

                        # ── KI Loop gate (verification path) ─────────────────
                        # Before requesting Ejari, ensure the user has finished
                        # the "add another AS/KI?" conversational loop.
                        # If ki_loop_done.json is absent the frontend must show
                        # KiLoopCard first; /ki/loop-finalize will then write the
                        # file and instruct the user to upload Ejari.
                        _vfy_ki_loop_done = user_docs_path(email) / "ki_loop_done.json"
                        if not _vfy_ki_loop_done.exists():
                            _vfy_loop_msg = localized(user_language,
                                en=(f"All {total_members} identity document(s) have been "
                                    f"successfully verified.\n\n"
                                    f"Would you like to add any additional Authorised Signatory "
                                    f"or Key Individual to this account?"),
                                es=(f"Los {total_members} documento(s) de identidad han sido verificados correctamente.\n\n"
                                    f"¿Desea añadir algún Firmante Autorizado o Persona Clave adicional a esta cuenta?"),
                                ar=(f"تم التحقق بنجاح من جميع مستندات الهوية ({total_members}).\n\n"
                                    f"هل ترغب في إضافة مفوّض بالتوقيع أو فرد رئيسي آخر إلى هذا الحساب؟"))
                            logger.info(f"[VERIFY] KI loop gate (SO verify path): ki_loop_done.json not found — returning ki_loop_prompt")
                            try:
                                insert_conversation_log(
                                    user_email=email,
                                    role="agent",
                                    message=_vfy_loop_msg,
                                    channel="chat",
                                    metadata={
                                        "message_type": "so_ki_loop_prompt",
                                        "total_members": total_members,
                                        "ki_loop_prompt": True,
                                    }
                                )
                            except Exception:
                                pass
                            return {
                                "is_verification":          True,
                                "verified":                 True,
                                "next_message":             _vfy_loop_msg,
                                "is_complete":              False,
                                "ki_loop_prompt":           True,
                                "fatca_trigger":            False,
                                "pep_trigger":              False,
                                "self_declaration_trigger": False,
                            }

                        # ── ki_loop_done.json exists — Ejari already collected upfront ──
                        # New flow: Ejari was uploaded at step 2 (before role assignment).
                        # Build final members summary then proceed to FATCA chain.
                        _vfy_summary_lines = []
                        try:
                            _vfy_ki_all = load_key_individuals(email)
                            # Also check member_progress.json verified_members list,
                            # since MOA_EXTRACTED members are tracked there (not via
                            # verification_status field which is only set for AI_ADDED KIs)
                            try:
                                _vfy_mp = load_member_progress(email)
                                _vfy_verified_names = [
                                    n.upper() for n in (_vfy_mp or {}).get("verified_members", [])
                                ]
                            except Exception:
                                _vfy_verified_names = []
                            for _vi, _vki in enumerate(_vfy_ki_all, 1):
                                _vname = _vki.get("display_name") or (
                                    f"{_vki.get('first_name','')} {_vki.get('last_name','')}".strip()
                                )
                                _vis_as = (
                                    _vki.get("is_authorised_signatory") or
                                    str(_vki.get("role", "")).strip().upper() in ("AS", "AUTHORISED SIGNATORY")
                                )
                                _vrole = "Authorised Signatory" if _vis_as else "Member"
                                _vshare = _vki.get("share_percentage", "—")
                                _vki_is_verified = (
                                    _vki.get("verification_status") == "verified" or
                                    _vname.upper() in _vfy_verified_names
                                )
                                if _vname:
                                    _vfy_summary_lines.append({
                                        "name": _vname, "is_as": bool(_vis_as), "is_ubo": False,
                                        "share": _vshare, "verified": bool(_vki_is_verified),
                                    })
                        except Exception as _vex:
                            logger.warning(f"[VERIFY] Could not build SO summary: {_vex}")

                        _vfy_summary_block = members_summary(_vfy_summary_lines, "summary.header_final", None)

                        # Re-enabled: Single Owner now runs the same FATCA → PEP →
                        # Product Package chain as Multiple Owner instead of
                        # skipping straight to Product Package.
                        _so_verify_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                        _so_verify_pep_done   = get_pep_status_disk_only(email) == "completed"

                        if not _so_verify_fatca_done:
                            next_message = render_message("ki_loop.so_fatca", None, summary=_vfy_summary_block)
                            try:
                                insert_conversation_log(
                                    user_email=email, role="agent", message=next_message, channel="chat",
                                    metadata={"message_type": "so_ki_loop_done_fatca", "total_members": total_members}
                                )
                            except Exception:
                                pass
                            return {
                                "is_verification":          True,
                                "verified":                 True,
                                "next_message":             next_message,
                                "is_complete":              False,
                                "fatca_trigger":            True,
                                "pep_trigger":              False,
                                "self_declaration_trigger": False,
                            }

                        if not _so_verify_pep_done:
                            next_message = render_message("ki_loop.pep", None, summary=_vfy_summary_block)
                            try:
                                insert_conversation_log(
                                    user_email=email, role="agent", message=next_message, channel="chat",
                                    metadata={"message_type": "so_ki_loop_done_pep", "total_members": total_members}
                                )
                            except Exception:
                                pass
                            return {
                                "is_verification":          True,
                                "verified":                 True,
                                "next_message":             next_message,
                                "is_complete":              False,
                                "fatca_trigger":            False,
                                "pep_trigger":              True,
                                "self_declaration_trigger": False,
                            }

                        if not is_package_done(email):
                            next_message = render_message("ki_loop.package", None, summary=_vfy_summary_block)
                            try:
                                insert_conversation_log(
                                    user_email=email, role="agent", message=next_message, channel="chat",
                                    metadata={"message_type": "so_ki_loop_done_product_package", "total_members": total_members}
                                )
                            except Exception:
                                pass
                            return {
                                "is_verification":          True,
                                "verified":                 True,
                                "next_message":             next_message,
                                "is_complete":              False,
                                "product_package_trigger":  True,
                                "fatca_trigger":            False,
                                "pep_trigger":              False,
                                "self_declaration_trigger": False,
                            }

                        next_message = concat(None,
                            localized(None, en="All documents complete.", es="Todos los documentos están completos.", ar="اكتملت جميع المستندات."),
                            _vfy_summary_block,
                            localized(None, en="\n\nPlease complete your **Self-Declaration** below.",
                                      es="\n\nComplete su **Autodeclaración** a continuación.",
                                      ar="\n\nيُرجى استكمال **الإقرار الذاتي** أدناه."))
                        try:
                            insert_conversation_log(
                                user_email=email, role="agent", message=next_message, channel="chat",
                                metadata={"message_type": "so_ki_loop_done_self_decl"}
                            )
                        except Exception:
                            pass
                        return {
                            "is_verification":          True,
                            "verified":                 True,
                            "next_message":             next_message,
                            "is_complete":              False,
                            "fatca_trigger":            False,
                            "pep_trigger":              False,
                            "self_declaration_trigger": True,
                        }

                    # ── Multiple Owners / Partnership: FATCA → PEP → Product Package → Self-Declaration ──
                    logger.info(f" All member EIDs verified — checking FATCA/PEP/Package/SelfDecl chain for {email}")

                    _mo_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                    _mo_pep_done   = get_pep_status_disk_only(email) == "completed"

                    if not _mo_fatca_done:
                        next_message = (
                            localized(user_language,
                                en=(f"All {total_members} member identity documents have been successfully verified. "
                            f"Please complete your **FATCA Declaration** below before proceeding."),
                                es=(f"Los {total_members} documentos de identidad de los miembros han sido verificados exitosamente. "
                            f"Por favor complete su **Declaración FATCA** a continuación."),
                                ar=(f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({total_members}). "
                            f"يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه قبل المتابعة."))
                        )
                        try:
                            insert_conversation_log(
                                user_email=email, role="agent", message=next_message, channel="chat",
                                metadata={"message_type": "mo_all_members_verified_fatca_prompt", "total_members": total_members}
                            )
                        except Exception:
                            pass
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": next_message, "is_complete": False,
                            "fatca_trigger": True, "pep_trigger": False, "self_declaration_trigger": False,
                        }

                    if not _mo_pep_done:
                        next_message = (
                            localized(user_language,
                                en=("FATCA declaration saved.\n\nPlease complete your **PEP (Politically Exposed Person) Declaration** below."),
                                es=("Declaración FATCA guardada.\n\nPor favor complete su **Declaración PEP** a continuación."),
                                ar=("تم حفظ إقرار فاتكا.\n\nيُرجى استكمال **إقرار الأشخاص المعرّضين سياسياً (PEP)** أدناه."))
                        )
                        try:
                            insert_conversation_log(
                                user_email=email, role="agent", message=next_message, channel="chat",
                                metadata={"message_type": "mo_all_members_verified_pep_prompt", "total_members": total_members}
                            )
                        except Exception:
                            pass
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": next_message, "is_complete": False,
                            "fatca_trigger": False, "pep_trigger": True, "self_declaration_trigger": False,
                        }

                    # FATCA + PEP done → Product Package gate
                    if not is_package_done(email):
                        next_message = (
                            localized(user_language,
                                en=("FATCA and PEP declarations are complete.\n\nPlease select your **Product Package** below to proceed."),
                                es=("Declaraciones FATCA y PEP completadas.\n\nPor favor seleccione su **Paquete de Producto** a continuación."),
                                ar=("اكتمل إقرارا فاتكا والأشخاص المعرّضين سياسياً.\n\nيُرجى اختيار **باقة المنتجات** أدناه للمتابعة."))
                        )
                        try:
                            insert_conversation_log(
                                user_email=email, role="agent", message=next_message, channel="chat",
                                metadata={"message_type": "mo_all_members_verified_package_prompt", "total_members": total_members}
                            )
                        except Exception:
                            pass
                        return {
                            "is_verification": True, "verified": True,
                            "next_message": next_message, "is_complete": False,
                            "product_package_trigger": True, "fatca_trigger": False,
                            "pep_trigger": False, "self_declaration_trigger": False,
                        }

                    # FATCA + PEP + Package done → Self-Declaration
                    logger.info(f" FATCA + PEP + Package done — triggering Self-Declaration for {email}")
                    next_message = (
                        localized(user_language,
                            en=(f"All {total_members} member identity documents have been successfully verified.\n\n"
                        f"The final step before account activation is the **Self-Declaration**. "
                        f"Please review and confirm the declaration below to complete your onboarding process."),
                            es=(f"Todos los {total_members} documentos de identidad de miembros han sido verificados exitosamente.\n\n"
                        f"El último paso antes de la activación de la cuenta es la **Auto-Declaración**. "
                        f"Por favor, revise y confirme la declaración a continuación."),
                            ar=(f"تم التحقق بنجاح من جميع مستندات هوية الأعضاء ({total_members}).\n\n"
                        f"الخطوة الأخيرة قبل تفعيل الحساب هي **الإقرار الذاتي**. "
                        f"يُرجى مراجعة الإقرار أدناه وتأكيده لاستكمال إجراءات التسجيل."))
                    )
                    try:
                        insert_conversation_log(
                            user_email=email, role="agent", message=next_message, channel="chat",
                            metadata={"message_type": "mo_all_members_verified_self_decl_prompt", "total_members": total_members}
                        )
                    except Exception:
                        pass
                    return {
                        "is_verification": True, "verified": True,
                        "next_message": next_message, "is_complete": False,
                        "fatca_trigger": False, "pep_trigger": False, "self_declaration_trigger": True,
                    }

        # ====================================================================
        # REGULAR DOCUMENT VERIFICATION (NON-MEMBER)
        # ====================================================================
        # Re-fetch fresh user data from DB so that any stage transitions that
        # happened earlier in this request (e.g. so_member_eids → identification
        # after all member EIDs are verified) are reflected when we check
        # is_complete below.  Using the stale user_data dict would keep
        # document_stage = "so_member_eids" and prevent self-declaration from
        # ever triggering for Single Owner accounts.
        try:
            _fresh_user = get_user_by_email(email)
            _status_user_data = dict(_fresh_user) if _fresh_user else user_data
        except Exception as _fud_err:
            logger.warning(f"Could not re-fetch user for status check: {_fud_err}")
            _status_user_data = user_data

        status = get_onboarding_status(email, _status_user_data, skip_welcome=True)
        is_complete = status.get("is_complete", False)

        if is_complete:
            account_type = user_data.get("account_type", "")
            ownership = user_data.get("ownership_type", "")

            # ── v4: FATCA → PEP → PRODUCT PACKAGE → SELF-DECLARATION GATE (Corporate Single Owner) ──
            # Re-enabled: Single Owner flow now runs FATCA and PEP like Multiple
            # Owner before Product Package → Self-Declaration.
            if account_type == ACCOUNT_CORPORATE and ownership == OWNERSHIP_SINGLE:
                _so_decl_path  = user_docs_path(email) / "self_declaration.json"
                _so_final_fatca_done = get_fatca_status_disk_only(email) in ("completed", "not_applicable")
                _so_final_pep_done   = get_pep_status_disk_only(email) == "completed"

                if not _so_final_fatca_done:
                    logger.info(f"[VERIFY]  Single Owner — FATCA pending, triggering FATCA declaration")
                    _so_fatca_msg = render_message("ki_loop.so_fatca", None, summary="")
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _so_fatca_msg,
                        "is_complete": False,
                        "product_package_trigger": False,
                        "fatca_trigger": True,
                        "pep_trigger": False,
                        "self_declaration_trigger": False,
                    }

                if not _so_final_pep_done:
                    logger.info(f"[VERIFY]  Single Owner — PEP pending, triggering PEP declaration")
                    _so_pep_msg = render_message("ki_loop.pep", None, summary="")
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _so_pep_msg,
                        "is_complete": False,
                        "product_package_trigger": False,
                        "fatca_trigger": False,
                        "pep_trigger": True,
                        "self_declaration_trigger": False,
                    }

                if not is_package_done(email):
                    logger.info(f"[VERIFY]  Single Owner — Product Package pending, triggering package selection")
                    _so_pkg_msg = render_message("ki_loop.package", None, summary="")
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _so_pkg_msg,
                        "is_complete": False,
                        "product_package_trigger": True,
                        "fatca_trigger": False,
                        "pep_trigger": False,
                        "self_declaration_trigger": False,
                    }

                if not _so_decl_path.exists():
                    logger.info(f"[VERIFY]  Single Owner self-declaration pending — returning trigger")
                    _so_decl_msg = localized(user_language,
                        en=(f"All your documents have been successfully verified.\n\n"
                            f"The final step before account activation is the "
                            f"**Self-Declaration**. Please review and confirm the declaration "
                            f"below to complete your onboarding process."),
                        es=(f"Todos sus documentos han sido verificados exitosamente.\n\n"
                            f"El paso final antes de la activación de la cuenta es la "
                            f"**Auto-Declaración**. Por favor, revise y confirme la declaración "
                            f"a continuación para completar su proceso de incorporación."),
                        ar=("تم التحقق من جميع مستنداتك بنجاح.\n\n"
                            "الخطوة الأخيرة قبل تفعيل الحساب هي **الإقرار الذاتي**. "
                            "يُرجى مراجعة الإقرار أدناه وتأكيده لاستكمال إجراءات التسجيل."))
                    return {
                        "is_verification": True,
                        "verified": True,
                        "next_message": _so_decl_msg,
                        "is_complete": False,
                        "fatca_trigger": False,
                        "pep_trigger": False,
                        "self_declaration_trigger": True,
                    }
                logger.info(f"[VERIFY] Single Owner self-declaration already confirmed — proceeding to cross-validation")

            if account_type == ACCOUNT_CORPORATE and ownership == OWNERSHIP_SINGLE:
                try:
                    cross_validator = CrossValidator()
                    validation_result = cross_validator.validate_documents(email, user_data)

                    if validation_result.get("passed", False):
                        logger.info(f"[SUCCESS] Cross-validation passed!")

                        logger.info(f"\n{'='*80}")
                        logger.info(f"[SUREPASS] Running government verification...")
                        logger.info(f"{'='*80}")

                        surepass_valid, surepass_message = validate_eid_before_confirmation(email)

                        if not surepass_valid:
                            logger.error(f"ERROR: SurePass validation failed")

                            try:
                                next_message = MessageGenerator.surepass_failure(
                                    error_message=surepass_message,
                                    user_name=user_name,
                                    language=user_language
                                )
                            except Exception as e:
                                logger.warning(f"SurePass message generation failed: {e}")
                                next_message = localized(user_language,
                                    en=(f"⚠️ Verification Issue\n\n{surepass_message}\n\nPlease review and re-upload your Emirates ID."),
                                    es=(f"⚠️ Problema de Verificación\n\n{surepass_message}\n\nPor favor, revisa y vuelve a subir tu Emirates ID."),
                                    ar=(f"⚠️ مشكلة في التحقق\n\n{surepass_message}\n\nيُرجى المراجعة وإعادة تحميل الهوية الإماراتية."))

                            return {
                                "is_verification": True,
                                "verified": False,
                                "next_message": next_message,
                                "is_complete": False
                            }

                        else:
                            logger.info(f"SUCCESS: SurePass validation passed!")

                            send_validation_passed_email(email, user_name)
                            logger.info("Validation success email sent")

                            final_status = get_onboarding_status(email, user_data, skip_welcome=True)
                            is_truly_complete = final_status.get("is_complete", False)

                            logger.debug(f"Final verification check (Regular):")
                            logger.info(f"  - Is truly complete: {is_truly_complete}")
                            logger.info(f"  - Remaining docs: {final_status.get('pending_documents', [])}")

                            try:
                                if is_truly_complete:
                                    next_message = localized(user_language,
                                        en=(f"Your {doc_type.upper()} has been successfully verified.\n\n"
                                            f"All your documents have been verified and your onboarding document "
                                            f"verification step is complete.\n\n"
                                            f"Your account will be activated within 3-4 business days."),
                                        es=(f"Su {doc_type.upper()} ha sido verificado exitosamente.\n\n"
                                            f"Todos sus documentos han sido verificados y su paso de verificación "
                                            f"de incorporación está completo.\n\n"
                                            f"Su cuenta será activada dentro de 3-4 días hábiles."),
                                        ar=(f"تم التحقق من {doc_type.upper()} بنجاح.\n\n"
                                            f"تم التحقق من جميع مستنداتك واكتملت خطوة التحقق من مستندات التسجيل.\n\n"
                                            f"سيتم تفعيل حسابك خلال 3-4 أيام عمل."))
                                else:
                                    next_message = MessageGenerator.verification_success(
                                        doc_type=doc_type,
                                        next_doc=None,
                                        is_last=True,
                                        user_name=user_name,
                                        language=user_language
                                    )
                            except Exception as e:
                                logger.warning(f"Completion message generation failed: {e}")
                                next_message = localized(user_language,
                                    en=(f"{doc_type.upper()} verified!\n\n"
                                        f"All your documents have been verified and your onboarding document "
                                        f"verification step is complete.\n\n"
                                        f"Your account will be activated within 3-4 business days."),
                                    es=(f"¡{doc_type.upper()} verificado!\n\n"
                                        f"Todos sus documentos han sido verificados y su paso de verificación "
                                        f"de incorporación está completo.\n\n"
                                        f"Su cuenta será activada en 3-4 días hábiles."),
                                    ar=(f"تم التحقق من {doc_type.upper()}!\n\n"
                                        f"تم التحقق من جميع مستنداتك واكتملت خطوة التحقق من مستندات التسجيل.\n\n"
                                        f"سيتم تفعيل حسابك خلال 3-4 أيام عمل."))

                            audit_mutation("document_stage", email=email,
                                           before=user_data.get("document_stage"),
                                           after="onboarding_complete", site="complete-A")
                            update_user_onboarding_status(email, True, "onboarding_complete")

                            try:
                                from app.services.handle_reply import send_completion_email
                                send_completion_email(email, account_type)
                            except Exception as email_error:
                                logger.error(f"Failed to send completion email: {email_error}")

                            return {
                                "is_verification": True,
                                "verified": True,
                                "next_message": next_message,
                                "is_complete": True
                            }

                    else:
                        # ❌ CROSS-VALIDATION FAILED
                        logger.error(f"[ERROR] Cross-validation failed")

                        try:
                            next_message = MessageGenerator.cross_validation_failure(
                                mismatches=validation_result["mismatches"],
                                user_name=user_name,
                                language=user_language
                            )
                        except Exception as e:
                            logger.warning(f"Cross-validation message failed: {e}")
                            mismatch_details = "\n".join([f"  • {m}" for m in validation_result["mismatches"]])
                            next_message = localized(user_language,
                                en=(f"⚠️ Cross-Validation Failed\n\n"
                                    f"Inconsistencies detected:\n\n{mismatch_details}\n\n"
                                    f"Please review and re-upload."),
                                es=(f"⚠️ Validación Cruzada Falló\n\n"
                                    f"Inconsistencias detectadas:\n\n{mismatch_details}\n\n"
                                    f"Por favor, revisa y vuelve a subir."),
                                ar=(f"⚠️ فشل التحقق المتقاطع\n\n"
                                    f"تم رصد عدم تطابق:\n\n{mismatch_details}\n\n"
                                    f"يُرجى المراجعة وإعادة التحميل."))

                        send_validation_failed_email(
                            to_email=email,
                            user_name=user_name,
                            mismatches=validation_result["mismatches"],
                            attempt_count=validation_result.get("attempt_count", 1)
                        )

                        return {
                            "is_verification": True,
                            "verified": False,
                            "next_message": next_message,
                            "is_complete": False
                        }

                except Exception as validation_error:
                    logger.error(f"Cross-validation error: {validation_error}")

                    try:
                        next_message = MessageGenerator.friendly_error(
                            error_type="Verification Error",
                            context=str(validation_error),
                            doc_type=doc_type,
                            language=user_language
                        )
                    except Exception as e:
                        logger.warning(f"Error message generation failed: {e}")
                        next_message = localized(user_language,
                            en=(f"❌ An error occurred during verification: {str(validation_error)}\n\nPlease contact support."),
                            es=(f"❌ Ocurrió un error durante la verificación: {str(validation_error)}\n\nPor favor, contacta a soporte."),
                            ar=(f"❌ حدث خطأ أثناء التحقق: {str(validation_error)}\n\nيُرجى التواصل مع الدعم."))

                    return {
                        "is_verification": True,
                        "verified": False,
                        "next_message": next_message,
                        "is_complete": False
                    }

            else:
                # Multiple Owner Corporate (or other account types):
                # All required documents are submitted → mark onboarding complete
                logger.info("Multiple Owner account: all documents submitted, completing onboarding")
                try:
                    next_message = localized(user_language,
                        en=(f"Your {doc_type.upper() if doc_type else 'document'} has been successfully verified.\n\n"
                            f"All your documents have been verified and your onboarding document "
                            f"verification step is complete.\n\n"
                            f"Your account will be activated within 3-4 business days."),
                        es=(f"Su {doc_type.upper() if doc_type else 'documento'} ha sido verificado exitosamente.\n\n"
                            f"Todos sus documentos han sido verificados y su proceso de verificación "
                            f"de incorporación está completo.\n\n"
                            f"Su cuenta será activada dentro de 3-4 días hábiles."),
                        ar=(f"تم التحقق من {doc_type.upper() if doc_type else 'المستند'} بنجاح.\n\n"
                            f"تم التحقق من جميع مستنداتك واكتملت خطوة التحقق من مستندات التسجيل.\n\n"
                            f"سيتم تفعيل حسابك خلال 3-4 أيام عمل."))
                except Exception:
                    next_message = localized(None,
                        en="All documents verified. Your account will be activated within 3-4 business days.",
                        es="Todos los documentos verificados. Su cuenta se activará en un plazo de 3 a 4 días hábiles.",
                        ar="تم التحقق من جميع المستندات. سيتم تفعيل حسابك خلال 3-4 أيام عمل.")

                audit_mutation("document_stage", email=email,
                               before=user_data.get("document_stage"),
                               after="onboarding_complete", site="complete-B")
                update_user_onboarding_status(email, True, "onboarding_complete")

                try:
                    from app.services.handle_reply import send_completion_email
                    _acct_type = user_data.get("account_type", ACCOUNT_CORPORATE)
                    send_completion_email(email, _acct_type)
                except Exception as _ce:
                    logger.error(f"Failed to send completion email: {_ce}")

                return {
                    "is_verification": True,
                    "verified": True,
                    "next_message": next_message,
                    "is_complete": True
                }

        elif status["next_required_document"]:
            # More documents needed
            next_doc = status["next_required_document"]

            # ── FIX C: Safety-net guard — prevent premature Ejari for Single Owner ──
            # If the status says next_required = ejari but member_progress still has
            # members whose identity docs are NOT yet on disk (i.e. member EIDs weren't
            # sequenced because the stage didn't transition to so_member_eids), redirect
            # to the next pending member instead of asking for Ejari.
            # This heals the flow even when ki_so_as_selection's stage update failed.
            if (next_doc.get("type") == "ejari" and
                    user_data.get("account_type") == ACCOUNT_CORPORATE and
                    user_data.get("ownership_type") == OWNERSHIP_SINGLE):
                try:
                    _c_mp = load_member_progress(email)
                    if _c_mp:
                        _c_members = _c_mp.get("members", [])
                        _C_IDTYPES = {"eid", "passport", "emirates id", "emirates_id"}
                        _c_verified_disk = []
                        for _cm in _c_members:
                            _cmdir = user_docs_path(email) / _cm
                            if not _cmdir.exists():
                                continue
                            for _ci in _cmdir.iterdir():
                                if not _ci.is_dir():
                                    continue
                                _co = _ci / "output.json"
                                if not _co.exists():
                                    continue
                                try:
                                    with open(_co, "r", encoding="utf-8") as _cof:
                                        _cd = json.load(_cof)
                                    if (_cd.get("is_valid") and
                                            _cd.get("document_type", "").lower() in _C_IDTYPES):
                                        _c_verified_disk.append(_cm)
                                        break
                                except Exception:
                                    pass

                        _c_pending = [m for m in _c_members if m not in _c_verified_disk]
                        if _c_pending:
                            logger.warning(f"[FIX-C]  Ejari requested but {len(_c_pending)} member(s) still need IDs: {_c_pending}")
                            logger.info(f"[FIX-C]  Redirecting to next pending member: {_c_pending[0]}")

                            # Self-heal: restore so_member_eids stage
                            try:
                                audit_mutation("document_stage", email=email,
                                               before=user_data.get("document_stage"),
                                               after=STAGE_SO_MEMBER_EIDS, site="FIX-C-selfheal")
                                update_user_onboarding_status(email, False, STAGE_SO_MEMBER_EIDS)
                                logger.info(f"[FIX-C] Stage self-healed → so_member_eids for {email}")
                            except Exception as _chfix:
                                logger.warning(f"[FIX-C] Could not self-heal stage: {_chfix}")

                            _c_next_member = _c_pending[0]
                            next_message = localized(user_language,
                                en=(f"Identity document verified successfully.\n\n"
                                    f"Please proceed by uploading the Emirates ID or Passport for: "
                                    f"**{_c_next_member}**."),
                                es=(f"Documento de identidad verificado exitosamente.\n\n"
                                    f"Por favor, proceda a subir el Emirates ID o Pasaporte para: "
                                    f"**{_c_next_member}**."),
                                ar=(f"تم التحقق من مستند الهوية بنجاح.\n\n"
                                    f"يُرجى المتابعة بتحميل الهوية الإماراتية أو جواز السفر لـ: "
                                    f"**{_c_next_member}**."))

                            try:
                                insert_conversation_log(
                                    user_email=email, role="agent", message=next_message, channel="chat",
                                    metadata={
                                        "message_type": "so_member_eid_redirect",
                                        "next_member": _c_next_member,
                                        "pending_members": _c_pending,
                                        "language": user_language,
                                    }
                                )
                            except Exception:
                                pass

                            return {
                                "is_verification": True,
                                "verified": True,
                                "next_message": next_message,
                                "is_complete": False,
                            }
                except Exception as _c_err:
                    logger.warning(f"[FIX-C] Guard check failed (non-fatal): {_c_err}")
            # ── End Fix C ──────────────────────────────────────────────────────

            try:
                next_message = MessageGenerator.verification_success(
                    doc_type=doc_type,
                    next_doc=next_doc.get("type", "document"),
                    is_last=False,
                    user_name=user_name,
                    language=user_language
                )
            except Exception as e:
                logger.warning(f"Verification message generation failed: {e}")
                doc_name = next_doc.get("type", "document").upper()
                if next_doc.get("requires_member_name"):
                    member = next_doc.get("member_name")
                    next_message = localized(user_language,
                        en=(f"{doc_type.upper()} verified!\n\nNext, I need the Emirates ID or Passport for {member}."),
                        es=(f"¡{doc_type.upper()} verificado!\n\nSiguiente, necesito el Emirates ID o Pasaporte para {member}."),
                        ar=(f"تم التحقق من {doc_type.upper()}!\n\nالخطوة التالية: أحتاج إلى الهوية الإماراتية أو جواز السفر لـ {member}."))
                else:
                    next_message = localized(user_language,
                        en=(f"{doc_type.upper()} verified!\n\nNext, please upload your {doc_name}."),
                        es=(f"¡{doc_type.upper()} verificado!\n\nSiguiente, por favor sube tu {doc_name}."),
                        ar=(f"تم التحقق من {doc_type.upper()}!\n\nالخطوة التالية: يُرجى تحميل {i18n_doc_name(doc_name, 'arabic')}."))

            is_actually_complete = status.get("is_complete", False)
            audit_mutation("document_stage", email=email,
                           before=user_data.get("document_stage"),
                           after=status["stage"], site="next-stage")
            update_user_onboarding_status(email, is_actually_complete, status["stage"])

        else:
            try:
                next_message = MessageGenerator.verification_success(
                    doc_type=doc_type,
                    next_doc=None,
                    is_last=False,
                    user_name=user_name,
                    language=user_language
                )
            except Exception as e:
                logger.warning(f"Verification message generation failed: {e}")
                next_message = localized(user_language,
                    en=(f"{doc_type.upper()} verified! Processing..."),
                    es=(f"¡{doc_type.upper()} verificado! Procesando..."),
                    ar=(f"تم التحقق من {doc_type.upper()}! جارٍ المعالجة..."))

        return {
            "is_verification": True,
            "verified": True,
            "next_message": next_message,
            "is_complete": status.get("is_complete", False)
        }

    except Exception as e:
        logger.error(f"handle_verification_response: {e}")
        import traceback
        logger.error(traceback.format_exc())

        try:
            from app.services.message_generator import MessageGenerator
            error_message = MessageGenerator.friendly_error(
                error_type="Verification Error",
                context=str(e),
                doc_type="document",
                language=user_language
            )
        except Exception as err:
            logger.warning(f"Error message generation failed: {err}")
            error_message = localized(user_language,
                en=(f"Sorry, I encountered an error during verification: {str(e)}\n\nPlease try again."),
                es=(f"Lo siento, encontré un error durante la verificación: {str(e)}\n\nPor favor, intenta nuevamente."),
                ar=(f"عذراً، حدث خطأ أثناء التحقق: {str(e)}\n\nيُرجى المحاولة مرة أخرى."))

        return {
            "is_verification": True,
            "verified": False,
            "next_message": error_message,
            "is_complete": False
        }
