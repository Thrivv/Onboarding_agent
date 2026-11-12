"""
Ownership structure: declaring Single Owner vs Partnership, confirming UBOs,
and resolving a mismatch between the role a document states and the one the
user selected.
"""
from app.i18n import localized

import logging
import json
from fastapi import APIRouter, HTTPException
import traceback
from app.utils.language import normalize_language
from app.services.message_generator import MessageGenerator, ai_message_gen
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
from app.services.key_individual_service import (
    load_key_individuals, save_key_individual, update_ki_verification,
    update_ki_verification_by_name,
    save_moa_member_as_status, update_member_ubo_status, get_ki_summary,
    ki_json_path, is_account_owner,
)
from app.services.supabase_client import supabase, get_user_by_email
from app.repositories.user_repository import UserRepository
from app.schemas.key_individuals import MoaAsRequest, KiFormRequest, KiVerifyRequest, UboConfirmRequest, SoAsSelectionRequest, KiAiAddRequest, KiContactInfoRequest, KiLoopFinalizeRequest
from app.schemas.ownership import OwnershipTypeSaveRequest, MismatchRoleRequest
from app.domain.onboarding.stage_table import (
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
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

@router.post("/ownership-type/save")
async def save_ownership_type(req: OwnershipTypeSaveRequest):
    """
    Persist the user's Ownership Type (and, for Partnership/Multiple Owners,
    the shareholder-structure follow-up) — the manual fallback path used when
    auto-classification from the Commercial License couldn't confidently
    determine it. Clears the ownership_ambiguous.json breadcrumb so
    get_onboarding_status()'s ownership_selection_pending flag turns off.
    """
    try:
        valid_types = (OWNERSHIP_SINGLE, OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE)
        if req.ownership_type not in valid_types:
            raise ValidationError(f"ownership_type must be one of: {', '.join(valid_types)}")

        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        update_fields = {"ownership_type": req.ownership_type}
        if req.ownership_type != OWNERSHIP_SINGLE and req.partnership_details:
            update_fields["partnership_details"] = req.partnership_details

        UserRepository.update_by_email_as_service(req.email, update_fields)
        logger.info(f"[OWNERSHIP-TYPE] Saved for {req.email}: {req.ownership_type}")

        # Clear the ambiguous-detection breadcrumb now that we have an answer.
        try:
            _amb_path = user_docs_path(req.email) / "ownership_ambiguous.json"
            if _amb_path.exists():
                _amb_path.unlink()
        except Exception as _amb_del_err:
            logger.warning(f"[OWNERSHIP-TYPE] Could not clear ownership_ambiguous.json: {_amb_del_err}")

        if req.ownership_type == OWNERSHIP_SINGLE:
            ai_message = localized(None,
                en="Thanks — since you own this business under Sole Proprietorship, the next document I'll need is your MOA (Memorandum of Association).",
                es="Gracias. Como es el único propietario de la empresa, el siguiente documento que necesito es su Memorando de Asociación (MOA).",
                ar="شكراً — بما أنك تملك هذا النشاط بصفة ملكية فردية، فالمستند التالي الذي أحتاجه هو عقد التأسيس (MOA).")
        else:
            ai_message = localized(None,
                en="Thanks — since you share ownership under Joint Ownership, the next document I'll need is your Memorandum of Association (MOA), to identify all owners. After that I'll request an Emirates ID or Passport for each owner.",
                es="Gracias. Como comparte la propiedad, el siguiente documento que necesito es su Memorando de Asociación (MOA), para identificar a todos los propietarios. Después le pediré el Emirates ID o pasaporte de cada uno.",
                ar="شكراً — بما أنك تتشارك الملكية، فالمستند التالي الذي أحتاجه هو عقد التأسيس (MOA) لتحديد جميع الملاك. بعد ذلك سأطلب الهوية الإماراتية أو جواز السفر لكل مالك.")

        # Persist to chat history so this message survives fetchGroundTruth()'s
        # resync — without this it only lived in the one-shot API response and
        # was wiped out ~1s later when the frontend re-pulled history from disk.
        try:
            insert_conversation_log(
                user_email=req.email,
                role="agent",
                message=ai_message,
                channel="chat",
                metadata={
                    "message_type":   "ownership_type_saved",
                    "ownership_type": req.ownership_type,
                }
            )
        except Exception as _log_err:
            logger.warning(f"[OWNERSHIP-TYPE] Could not log ai_message to conversation history: {_log_err}")

        return {
            "success": True,
            "ownership_type": req.ownership_type,
            "partnership_details": update_fields.get("partnership_details"),
            "ai_message": ai_message,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"save_ownership_type: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/member/ubo-confirm")
async def member_ubo_confirm(req: UboConfirmRequest):
    """
    Record UBO Yes/No answer for a specific member during Stage 2.
    Pre-fill is handled on the frontend (share % >= 25 → suggest Yes).
    """
    try:
        update_member_ubo_status(req.email, req.member_name, req.is_ubo)

        role_label = (
            "UBO & Authorised Signatory" if req.is_ubo else "Member"
        )

        # Reconciliation inside save_member_progress() may already have
        # matched this member to an identity document uploaded earlier
        # (e.g. bulk-uploaded alongside Ejari/MOA, before the member list —
        # and this UBO question — even existed). Don't ask for an ID that's
        # already on file.
        _already_verified = False
        try:
            _mp = load_member_progress(req.email) or {}
            _already_verified = req.member_name in (_mp.get("verified_members", []) or [])
        except Exception as _uv_err:
            logger.warning(f"[UBO] Could not check verified_members for {req.member_name}: {_uv_err}")

        if _already_verified:
            ubo_str = "a UBO" if req.is_ubo else "not a UBO"
            msg = localized(None,
                en=f"{req.member_name} has been recorded as {ubo_str}. Their identity document is already on file, so there's nothing further needed for them.",
                es=f"{req.member_name} se ha registrado como {('UBO' if req.is_ubo else 'no UBO')}. Su documento de identidad ya consta, así que no se necesita nada más.",
                ar=f"تم تسجيل {req.member_name} بصفة {('مستفيداً نهائياً' if req.is_ubo else 'غير مستفيد نهائي')}. مستند هويته موجود مسبقاً، فلا حاجة لأي إجراء إضافي.")
        else:
            try:
                from app.services.message_generator import MessageGenerator
                msg = MessageGenerator.ubo_confirmed_prompt_id(
                    member_name=req.member_name,
                    is_ubo=req.is_ubo,
                    language=normalize_language(None),  # X-User-Language header
                )
            except Exception:
                ubo_str = "a UBO" if req.is_ubo else "not a UBO"
                msg = localized(None,
                    en=f"{req.member_name} has been recorded as {ubo_str}. Please upload their Emirates ID or Passport to complete identity verification.",
                    es=f"{req.member_name} se ha registrado como {('UBO' if req.is_ubo else 'no UBO')}. Cargue su Emirates ID o pasaporte para completar la verificación de identidad.",
                    ar=f"تم تسجيل {req.member_name} بصفة {('مستفيداً نهائياً' if req.is_ubo else 'غير مستفيد نهائي')}. يُرجى تحميل الهوية الإماراتية أو جواز السفر الخاص به لإكمال التحقق من الهوية.")

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={
                "message_type": "ubo_confirmed",
                "member_name": req.member_name,
                "is_ubo": req.is_ubo,
            }
        )

        return {"success": True, "message": msg, "member_name": req.member_name, "is_ubo": req.is_ubo}

    except Exception as e:
        logger.error(f"[UBO] Error: {e}")
        raise DomainError(context=str(e))


@router.get("/member/ubo-status/{user_email}")
async def member_ubo_status(user_email: str):
    """
    Return each member's current UBO status + share % for the frontend pre-fill.
    Reads from member_progress.json for members list and commercial output.json for share %.
    """
    try:
        mp = load_member_progress(user_email)
        if not mp:
            return {"members": []}

        members = mp.get("members", [])

        # Load commercial license to get share percentages
        share_map: dict = {}
        root = user_docs_path(user_email)
        for item in root.iterdir():
            if not item.is_dir():
                continue
            out = item / "output.json"
            if not out.exists():
                continue
            try:
                with open(out) as f:
                    data = json.load(f)
                if data.get("document_type", "").lower() == "commercial":
                    partners = data.get("partners", [])
                    for p in partners:
                        name = (p.get("name") or p.get("partner_name") or "").strip().upper()
                        share_str = str(p.get("share_percentage") or p.get("ownership_percentage") or "0")
                        try:
                            share = float(share_str.replace("%", "").strip())
                        except Exception:
                            share = 0.0
                        if name:
                            share_map[name] = share
                    break
            except Exception:
                pass

        # Load current KI records for UBO flags
        kis = load_key_individuals(user_email)
        ki_map = {k.get("display_name", "").upper(): k for k in kis}

        result = []
        for name in members:
            share = share_map.get(name.upper(), 0.0)
            ki = ki_map.get(name.upper(), {})
            suggested_ubo = share >= 25.0
            result.append({
                "name": name,
                "share_percentage": share,
                "suggested_ubo": suggested_ubo,
                "is_ubo": ki.get("is_ubo", suggested_ubo),   # confirmed or pre-filled
                "is_authorised_signatory": ki.get("is_authorised_signatory", False),
                "role": ki.get("role", "Member"),
                "ubo_confirmed": "is_ubo" in ki,
            })

        return {"members": result}

    except Exception as e:
        logger.error(f"[UBO] Status error: {e}")
        raise DomainError(context=str(e))


@router.post("/mismatch/assign-role")
async def mismatch_assign_role(req: MismatchRoleRequest):
    """
    Called when a commercial license name doesn't match the registered user.
    Adds the extracted person to the key_individuals list with the selected role
    and marks source as DOCUMENT_EXTRACTED so it appears in member list UI.
    """
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        is_as = req.assigned_role.lower() in ("authorized_signatory", "authorised_signatory")

        # Split extracted name into parts
        name_parts = req.extracted_name.strip().split()
        first_name = name_parts[0] if name_parts else req.extracted_name
        last_name  = name_parts[-1] if len(name_parts) > 1 else ""
        mid_name   = " ".join(name_parts[1:-1]) if len(name_parts) > 2 else None

        ki_data = {
            "user_email":              req.email,
            "first_name":              first_name,
            "middle_name":             mid_name,
            "last_name":               last_name,
            "display_name":            req.extracted_name,
            "mobile_number":           req.mobile_number or "N/A",
            "id_type":                 req.id_type or "EID",
            "id_number":               req.id_number or "PENDING",
            "is_authorised_signatory": is_as,
            "is_ubo":                  False,
            "source":                  "DOCUMENT_EXTRACTED",
            "role_assigned_from_mismatch": True,
            "extracted_name":          req.extracted_name,
            "extracted_business_name": req.extracted_business_name,
            "verification_status":     "pending",
        }

        # Save to key_individuals via service
        saved = save_key_individual(req.email, ki_data)
        logger.info(f"[MISMATCH] Added '{req.extracted_name}' as {req.assigned_role} for {req.email}")

        # Clear the deferred-modal breadcrumb now that a role has been assigned —
        # mismatch_role_pending will read False on the next status check.
        try:
            _mismatch_breadcrumb_path = user_docs_path(req.email) / "mismatch_pending.json"
            if _mismatch_breadcrumb_path.exists():
                _mismatch_breadcrumb_path.unlink()
        except Exception as _mb_del_err:
            logger.warning(f"[MISMATCH] Could not clear mismatch_pending.json: {_mb_del_err}")

        _mismatch_msg = localized(None,
            en=f"'{req.extracted_name}' has been added as {req.assigned_role.replace('_', ' ').title()} and included in the identity verification queue.",
            es=f"'{req.extracted_name}' se ha añadido como {('Firmante Autorizado' if 'sign' in req.assigned_role.lower() else 'Persona Clave')} y se ha incluido en la cola de verificación de identidad.",
            ar=f"تمت إضافة '{req.extracted_name}' بصفة {('مفوّض بالتوقيع' if 'sign' in req.assigned_role.lower() else 'فرد رئيسي')} وإدراجه في قائمة التحقق من الهوية.")

        # Persist to chat history so this confirmation survives a refresh —
        # same pattern/bug as save_ownership_type(): the KI record itself was
        # already saved synchronously above, but without this the confirmation
        # bubble was only ever a one-shot API response and got wiped out by
        # the next fetchGroundTruth() resync.
        try:
            insert_conversation_log(
                user_email=req.email,
                role="agent",
                message=_mismatch_msg,
                channel="chat",
                metadata={
                    "message_type":  "mismatch_role_assigned",
                    "extracted_name": req.extracted_name,
                    "assigned_role": req.assigned_role,
                }
            )
        except Exception as _log_err:
            logger.warning(f"[MISMATCH] Could not log confirmation to conversation history: {_log_err}")

        return {
            "success": True,
            "message": _mismatch_msg,
            "ki": saved,
            "role": req.assigned_role,
        }
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[MISMATCH] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))
