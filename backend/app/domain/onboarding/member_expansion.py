"""
Shared "are all shareholder-stage documents ready -> expand into a member
list -> transition to member_eids" check for Multiple Owners / Partnership
accounts.

Two shapes this covers:
    Type-1 (no corporate shareholder): identification stage, needs
        commercial + ejari + moa. Members come straight from the
        Commercial License's own partners list.
    Type-2 (has a corporate shareholder): corporate_shareholder_docs
        stage, needs CoI(s) + ejari + moa. Members come from expanding
        each corporate shareholder's own CoI-declared shareholders against
        the Commercial License's partner list (effective ownership,
        >25% = UBO).

Why this exists
----------------
This logic used to be duplicated per trigger point -- once for every
document type that could plausibly be the LAST one uploaded (MOA, Ejari --
and for Type-2, notably, NOT Certificate of Incorporation, which never got
its own copy). Six near-identical implementations existed before this file:
two Type-1 blocks and two Type-2 blocks in the single-file upload path,
plus one Type-1 and one Type-2 block in the bulk upload path. A user who
uploaded CoI last (a perfectly ordinary thing to do, since you only find
out you need a CoI after the Commercial License reveals a corporate
shareholder) hit a gap none of those six copies covered, and the flow
silently stalled until they manually typed "Okay" in chat -- a legacy
fallback path that re-runs this same check one more time.

One function now, called after every corporate-stage document upload
(ejari, moa, coi) from both the single-file and bulk paths, so upload
order genuinely does not matter -- whichever document happens to complete
the set triggers the same check, the same way.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.i18n import localized
from app.i18n.messages import doc_name
from app.utils.language import normalize_language

logger = logging.getLogger(__name__)


def check_and_expand_members(email: str, user: dict, language: str = "english") -> Optional[dict]:
    """
    If this account is Multiple Owners/Partnership and every document
    required for its CURRENT stage is now valid and on disk, expand the
    member list, save member_progress, transition the stage to
    member_eids, and return a dict describing what happened.

    Returns None when:
      - the account isn't Corporate + Multiple Owners/Partnership, or
      - the relevant document set isn't fully ready yet, or
      - expansion ran but produced no members (falls back to the "okay"
        chat-path handler as a safety net, same as before this change).

    Return shape (only when it actually fires):
        {
            "message":            str,          # chat ack, language-aware
            "members":            list[str],
            "ubo_names":          list[str],
            "expanded_members":   list[dict] | None,   # Type-2 only
            "stage_transition":   True,
            "new_stage":          "member_eids",
        }

    Safe to call from anywhere, any number of times, after any corporate
    document is verified -- it always re-derives readiness from disk state,
    never from what document just triggered the call. Every exception is
    caught and logged; a failure here must never break the upload response
    it's called from.
    """
    language = normalize_language(language)
    try:
        from app.domain.onboarding.stage_table import (
            ACCOUNT_CORPORATE, OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP,
            STAGE_IDENTIFICATION, STAGE_CORPORATE_SHAREHOLDER_DOCS, STAGE_MEMBER_EIDS,
        )
        from app.services.chatupload_helpers import (
            check_documents_status, user_docs_path, member_progress_path,
            load_member_progress,
        )
        from app.domain.onboarding.members import save_member_progress
        from app.domain.onboarding.stages import update_user_onboarding_status
        from app.domain.onboarding.documents import _find_commercial_output, extract_members_from_commercial
        from app.services.fatca_service import fatca_json_path
        from app.services.pep_service import pep_json_path
        from app.services.specialized_ocr.corporate_shareholder_detector import (
            detect_corporate_shareholders as _detect_corps,
            run_type2_analysis as _run_type2,
        )

        if user.get("account_type") != ACCOUNT_CORPORATE:
            return None
        if user.get("ownership_type") not in (OWNERSHIP_MULTIPLE, OWNERSHIP_PARTNERSHIP):
            return None

        stage = user.get("document_stage")
        doc_status = check_documents_status(email)

        # ── Type-1: identification stage, commercial + ejari + moa ──────────
        if stage == STAGE_IDENTIFICATION:
            _comm_path, _comm_data = _find_commercial_output(email)
            if not _comm_data:
                return None
            if not (doc_status.get("ejari") and doc_status.get("moa")):
                return None

            _partners = (
                _comm_data.get("extracted_fields", {}).get("partners", [])
                or _comm_data.get("partners", [])
            )
            if _partners:
                _corp_check = _detect_corps(_partners)
                if _corp_check.get("has_corporate_shareholders"):
                    # Actually Type-2 -- the commercial-upload classification
                    # step should already have moved the stage to
                    # corporate_shareholder_docs. If we're still seeing
                    # "identification" here, that transition hasn't landed
                    # yet; don't expand as Type-1.
                    logger.info(
                        f"[MEMBER-EXPANSION] {email}: corporate shareholder "
                        f"detected but stage still identification -- skipping"
                    )
                    return None

            _member_data = extract_members_from_commercial(email)
            _members = _member_data.get("all_names", [])
            _ubos_raw = _member_data.get("ubos", [])
            _ubo_names = [u.get("name") if isinstance(u, dict) else u for u in _ubos_raw]

            if not _members:
                logger.warning(f"[MEMBER-EXPANSION] {email}: Type-1 ready but no members extracted")
                return None

            save_member_progress(email, _members, 0, ubo_names=_ubo_names)
            update_user_onboarding_status(email, False, STAGE_MEMBER_EIDS)

            # save_member_progress() above may already have matched some of
            # these members to an identity document uploaded earlier (e.g.
            # bulk-uploaded alongside Ejari/MOA before this member list
            # existed to attribute it to). Don't ask for those again.
            _verified_now = set()
            try:
                _mp_after = load_member_progress(email) or {}
                _verified_now = set(_mp_after.get("verified_members", []) or [])
            except Exception as _vn_err:
                logger.warning(f"[MEMBER-EXPANSION] {email}: could not read back verified_members: {_vn_err}")

            _still_pending = [m for m in _members if m not in _verified_now]
            _member_list_str = "\n".join(
                f"  {i}. {m}{' (UBO)' if m in _ubo_names else ''}"
                for i, m in enumerate(_still_pending, 1)
            )
            if _still_pending:
                _already_note = (
                    f"\n\n({len(_verified_now)} already have a verified identity "
                    f"document on file and won't be asked again.)" if _verified_now else ""
                )
                _already_note_es = (
                    f"\n\n({len(_verified_now)} ya tienen un documento de identidad verificado "
                    f"y no se les volverá a solicitar.)" if _verified_now else ""
                )
                _already_note_ar = (
                    f"\n\n(لدى {len(_verified_now)} منهم مستند هوية موثّق مسبقاً ولن يُطلب منهم مرة أخرى.)"
                    if _verified_now else ""
                )
                message = (
                    localized(language,
                        en=("Business ownership analysis complete. Emirates ID or Passport "
                    "verification is required for the following members:\n\n"
                    f"{_member_list_str}{_already_note}\n\n"
                    "Please confirm the list of Authorised Signatories below."),
                        es=("Análisis de propiedad empresarial completado. Se requiere verificación "
                    "de Emirates ID o Pasaporte para los siguientes miembros:\n\n"
                    f"{_member_list_str}{_already_note_es}\n\n"
                    "Por favor confirme la lista de firmantes autorizados a continuación."),
                        ar=("اكتمل تحليل ملكية الشركة. يلزم التحقق من الهوية الإماراتية أو جواز "
                    "السفر للأعضاء التاليين:\n\n"
                    f"{_member_list_str}{_already_note_ar}\n\n"
                    "يُرجى تأكيد قائمة المخولين بالتوقيع أدناه."))
                )
            else:
                message = (
                    localized(language,
                        en=("Business ownership analysis complete, and every member already has a "
                    "verified identity document on file — nothing further needed there.\n\n"
                    "Please confirm the list of Authorised Signatories below."),
                        es=("Análisis de propiedad empresarial completado, y todos los miembros ya "
                    "tienen un documento de identidad verificado registrado — no se necesita "
                    "nada más ahí.\n\nPor favor confirme la lista de firmantes autorizados a continuación."),
                        ar=("اكتمل تحليل ملكية الشركة، وجميع الأعضاء لديهم بالفعل مستند هوية موثّق "
                    "مسجل — لا حاجة لأي إجراء إضافي هناك.\n\nيُرجى تأكيد قائمة المخولين "
                    "بالتوقيع أدناه."))
                )
            logger.info(f"[MEMBER-EXPANSION] {email}: Type-1 auto-triggered -> {len(_members)} members")
            return {
                "message": message,
                "members": _members,
                "ubo_names": _ubo_names,
                "expanded_members": None,
                "stage_transition": True,
                "new_stage": STAGE_MEMBER_EIDS,
            }

        # ── Type-2: corporate_shareholder_docs stage, CoI(s) + ejari + moa ──
        if stage == STAGE_CORPORATE_SHAREHOLDER_DOCS:
            _progress_file = member_progress_path(email)
            if not _progress_file.exists():
                return None
            try:
                with open(_progress_file, "r", encoding="utf-8") as f:
                    _progress = json.load(f)
            except Exception:
                return None
            _pending_coi = _progress.get("pending_coi", [])

            _coi_types = {"certificate_of_incorporation", "coi"}
            _base = user_docs_path(email)
            _coi_on_disk = 0
            if _pending_coi and _base.exists():
                for cf in _base.iterdir():
                    if not cf.is_dir():
                        continue
                    out = cf / "output.json"
                    if not out.exists():
                        continue
                    try:
                        with open(out, "r", encoding="utf-8") as f:
                            od = json.load(f)
                        if od.get("document_type", "").lower() in _coi_types and od.get("is_valid"):
                            _coi_on_disk += 1
                    except Exception:
                        pass

            _all_cois_ready = len(_pending_coi) == 0 or _coi_on_disk >= len(_pending_coi)
            if not (_all_cois_ready and doc_status.get("ejari") and doc_status.get("moa")):
                logger.info(
                    f"[MEMBER-EXPANSION] {email}: Type-2 not ready yet "
                    f"(cois_ready={_all_cois_ready}, ejari={doc_status.get('ejari')}, "
                    f"moa={doc_status.get('moa')})"
                )
                return None

            _coi_map = {}
            if _base.exists():
                for cf in _base.iterdir():
                    if not cf.is_dir():
                        continue
                    out = cf / "output.json"
                    if not out.exists():
                        continue
                    try:
                        with open(out, "r", encoding="utf-8") as f:
                            od = json.load(f)
                        if od.get("document_type", "").lower() in _coi_types:
                            ef = od.get("extracted_fields", od)
                            key = ef.get("company_name") or ef.get("entity_name") or ef.get("name") or cf.name
                            individuals = (
                                ef.get("directors_and_shareholders")
                                or ef.get("shareholders")
                                or ef.get("directors")
                                or []
                            )
                            _coi_map[key] = individuals
                    except Exception:
                        pass

            _comm_path, _comm_data = _find_commercial_output(email)
            _partners_list = []
            if _comm_data:
                try:
                    _partners_list = (
                        _comm_data.get("extracted_fields", {}).get("partners", [])
                        or _comm_data.get("partners", [])
                    )
                except Exception:
                    pass

            if not _partners_list:
                logger.warning(f"[MEMBER-EXPANSION] {email}: Type-2 ready but no commercial partners found")
                return None

            _result = _run_type2(_partners_list, coi_map=_coi_map if _coi_map else None)
            _expanded = _result.get("expanded_owners") or []
            _ubo_names = [o["name"] for o in _expanded if o.get("is_ubo")]
            _all_names = [o["name"] for o in _expanded]

            if not _all_names:
                logger.warning(f"[MEMBER-EXPANSION] {email}: Type-2 ready but no members from expansion")
                return None

            save_member_progress(
                email, members=_all_names, current_index=0,
                ubo_names=_ubo_names, expanded_members=_expanded, pending_coi=[],
            )
            update_user_onboarding_status(email, False, STAGE_MEMBER_EIDS)

            for stale_path, label in (
                (fatca_json_path(email), "fatca.json"),
                (pep_json_path(email), "pep.json"),
            ):
                if stale_path.exists():
                    stale_path.unlink(missing_ok=True)
                    logger.info(f"[MEMBER-EXPANSION] {email}: cleaned stale {label}")

            # save_member_progress() above may already have matched some of
            # these beneficial owners to an identity document uploaded
            # earlier (e.g. bulk-uploaded alongside Ejari/MOA/CoI before this
            # member list existed to attribute it to). Don't ask again.
            _verified_now = set()
            try:
                _mp_after = load_member_progress(email) or {}
                _verified_now = set(_mp_after.get("verified_members", []) or [])
            except Exception as _vn_err:
                logger.warning(f"[MEMBER-EXPANSION] {email}: could not read back verified_members: {_vn_err}")

            _still_pending = [o for o in _expanded if o.get("name") not in _verified_now]
            _member_list_str = "\n".join(
                f"  {i}. {o['name']} - {o.get('effective_percentage', o.get('effective_pct', '?'))}% "
                f"effective ownership{' (UBO)' if o.get('is_ubo') else ''}"
                for i, o in enumerate(_still_pending, 1)
            )
            if _still_pending:
                _already_note = (
                    f"\n\n({len(_verified_now)} already have a verified identity "
                    f"document on file and won't be asked again.)" if _verified_now else ""
                )
                _already_note_es = (
                    f"\n\n({len(_verified_now)} ya tienen un documento de identidad verificado "
                    f"y no se les volverá a solicitar.)" if _verified_now else ""
                )
                _already_note_ar = (
                    f"\n\n(لدى {len(_verified_now)} منهم مستند هوية موثّق مسبقاً ولن يُطلب منهم مرة أخرى.)"
                    if _verified_now else ""
                )
                message = (
                    localized(language,
                        en=("Ownership analysis is complete. Emirates ID or Passport "
                    "verification is required for the following beneficial owners:\n\n"
                    f"{_member_list_str}{_already_note}\n\n"
                    "Please confirm the list of Authorised Signatories below."),
                        es=("Análisis de propiedad corporativa completo. Se requiere verificación "
                    "de Emirates ID o Pasaporte para los siguientes beneficiarios:\n\n"
                    f"{_member_list_str}{_already_note_es}\n\n"
                    "Por favor confirme la lista de firmantes autorizados a continuación."),
                        ar=("اكتمل تحليل الملكية. يلزم التحقق من الهوية الإماراتية أو جواز السفر "
                    "للمستفيدين الفعليين التاليين:\n\n"
                    f"{_member_list_str}{_already_note_ar}\n\n"
                    "يُرجى تأكيد قائمة المخولين بالتوقيع أدناه."))
                )
            else:
                message = (
                    localized(language,
                        en=("Ownership analysis is complete, and every beneficial owner already has a "
                    "verified identity document on file — nothing further needed there.\n\n"
                    "Please confirm the list of Authorised Signatories below."),
                        es=("Análisis de propiedad corporativa completo, y todos los beneficiarios ya "
                    "tienen un documento de identidad verificado registrado — no se necesita "
                    "nada más ahí.\n\nPor favor confirme la lista de firmantes autorizados a continuación."),
                        ar=("اكتمل تحليل الملكية، وجميع المستفيدين الفعليين لديهم بالفعل مستند هوية "
                    "موثّق مسجل — لا حاجة لأي إجراء إضافي هناك.\n\nيُرجى تأكيد قائمة "
                    "المخولين بالتوقيع أدناه."))
                )
            logger.info(f"[MEMBER-EXPANSION] {email}: Type-2 auto-triggered -> {len(_all_names)} members")
            return {
                "message": message,
                "members": _all_names,
                "ubo_names": _ubo_names,
                "expanded_members": _expanded,
                "stage_transition": True,
                "new_stage": STAGE_MEMBER_EIDS,
            }

        return None
    except Exception as e:
        logger.warning(f"[MEMBER-EXPANSION] check_and_expand_members failed for {email}: {e}")
        return None
