"""
Compliance declarations: FATCA, PEP and the final self-declaration.

Nine endpoints. Deliberately the first slice of the `chatupload` split — these
handlers are thin wrappers over `fatca_service`, `pep_service` and the summary
builder, so they carry the least risk.

FATCA and PEP apply to every ownership structure today — both the sole-owner
and joint-ownership branches now run through the same compliance chain before
reaching the product package step.
"""

import logging
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import traceback
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
from app.services.chat_session_service import (
    create_chat_session,
    validate_reference_number,
    get_active_reference_for_user,
)
from app.services.cross_validator import CrossValidator
from app.services.supabase_client import supabase, get_user_by_email
from app.repositories.user_repository import UserRepository
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
from app.schemas.compliance import FatcaNoRequest, FatcaYesRequest, PepRequest, SelfDeclConfirmRequest
from app.domain.onboarding.stages import update_user_onboarding_status
from app.domain.onboarding.stage_table import ACCOUNT_CORPORATE
from app.domain.exceptions import (
    DomainError,
    NotFoundError,
)

logger = logging.getLogger(__name__)

# Sub-router. The `/chatupload` prefix and tags are applied once in
# app/api/routes/onboarding/__init__.py, so every path below is unchanged.
router = APIRouter()

@router.post("/fatca/not-applicable")
async def fatca_not_applicable(req: FatcaNoRequest):
    """User answered No to FATCA — record as Not Applicable."""
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        result = save_fatca(req.email, str(user["id"]), fatca_applicable=False)

        # Log to conversation
        try:
            from app.services.message_generator import MessageGenerator
            msg = MessageGenerator.fatca_not_applicable_confirmed(language="english")
        except Exception:
            msg = "Thanks — I've recorded FATCA as Not Applicable for you. Let's move on to the next step."

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={"message_type": "fatca_confirmed", "fatca_applicable": False}
        )

        logger.info(f"[FATCA] Not Applicable saved for: {req.email}")

        pep_already_done = get_pep_status_disk_only(req.email) == "completed"

        return {
            "success": True,
            "message": msg,
            "fatca_applicable": False,
            "pep_trigger": not pep_already_done,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[FATCA] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/fatca/submit")
async def fatca_submit(req: FatcaYesRequest):
    """User submitted the FATCA Yes form — validate required fields and save."""
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        required = ["entity_type", "country_of_tax_residence",
                    "entity_incorporated_in_usa", "entity_has_us_ownership",
                    "address_or_phone_in_usa", "payment_instruction_to_usa",
                    "income_from_us_sources", "irs_form_obtained"]
        form_dict = req.dict()
        missing = [f for f in required if not form_dict.get(f)]
        if missing:
            return {
                "success": False,
                "error": "missing_fields",
                "missing_fields": missing,
                "message": "Please complete all required fields before submitting."
            }

        result = save_fatca(req.email, str(user["id"]), fatca_applicable=True, form_data=form_dict)

        try:
            from app.services.message_generator import MessageGenerator
            msg = MessageGenerator.fatca_submitted_confirmed(language="english")
        except Exception:
            msg = "Your FATCA details are saved — thank you. Let's continue with what's left."

        insert_conversation_log(
            user_email=req.email, role="agent", message=msg, channel="chat",
            metadata={"message_type": "fatca_confirmed", "fatca_applicable": True}
        )

        logger.info(f"[FATCA] Form submitted for: {req.email}")

        pep_already_done = get_pep_status_disk_only(req.email) == "completed"

        return {
            "success": True,
            "message": msg,
            "fatca_applicable": True,
            "pep_trigger": not pep_already_done,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[FATCA] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.get("/fatca/status/{user_email}")
async def fatca_status(user_email: str):
    """Return the FATCA status for a user: not_started / not_applicable / completed."""
    status = get_fatca_status(user_email)
    data = load_fatca(user_email)
    return {"status": status, "data": data}


@router.post("/pep/submit")
async def pep_submit(req: PepRequest):
    """Save the PEP declaration for a user (domestic + foreign sections)."""
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        pep_data = {
            "domestic_pep": req.domestic_pep or {},
            "foreign_pep":  req.foreign_pep  or {},
        }

        validation = validate_pep_data(pep_data)
        if not validation["valid"]:
            return {
                "success": False,
                "message": validation["message"],
                "missing_fields": validation["missing_fields"],
            }

        result = save_pep(req.email, str(user["id"]), pep_data)
        logger.info(f"[PEP] Submitted for: {req.email}")

        try:
            msg = MessageGenerator.pep_submitted_confirmed(language="english")
        except Exception:
            msg = "Thanks — your PEP declaration is saved. Let's continue."

        from app.services.product_package_service import is_package_done
        if is_package_done(req.email):
            return {
                "success": True,
                "message": msg,
                "record": result.get("record"),
                "product_package_trigger": False,
                "self_declaration_trigger": True,
            }
        return {
            "success": True,
            "message": msg,
            "record": result.get("record"),
            "product_package_trigger": True,
            "self_declaration_trigger": False,
        }
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[PEP] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/pep/not-applicable")
async def pep_not_applicable(req: PepRequest):
    """User confirmed they are not a PEP (both domestic and foreign = No)."""
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        pep_data = {
            "domestic_pep": {"status": False},
            "foreign_pep":  {"status": False},
        }
        result = save_pep(req.email, str(user["id"]), pep_data)
        logger.info(f"[PEP] Not Applicable saved for: {req.email}")

        try:
            msg = MessageGenerator.pep_not_applicable_confirmed(language="english")
        except Exception:
            msg = "Got it — I've recorded PEP as Not Applicable for you. Let's continue."

        from app.services.product_package_service import is_package_done
        if is_package_done(req.email):
            return {
                "success": True,
                "message": msg,
                "pep_applicable": False,
                "product_package_trigger": False,
                "self_declaration_trigger": True,
            }
        return {
            "success": True,
            "message": msg,
            "pep_applicable": False,
            "product_package_trigger": True,
            "self_declaration_trigger": False,
        }
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[PEP] Error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.get("/pep/status/{user_email}")
async def pep_status(user_email: str):
    """Return the PEP status for a user: not_started / completed."""
    status = get_pep_status(user_email)
    data = load_pep(user_email)
    return {"status": status, "data": data}


@router.get("/self-declaration/summary/{user_email}")
async def self_declaration_summary(user_email: str):
    """
    Build the full Self-Declaration summary for display in the chat.
    Returns: uploaded docs, FATCA status, KI list, declaration text.
    """
    try:
        user = get_user_by_email(user_email)
        if not user:
            raise NotFoundError("User not found")

        # ── Uploaded documents ───────────────────────────────────────────────
        from app.services.chatupload_helpers import check_documents_status
        doc_status = check_documents_status(user_email)

        submitted_docs = []
        root = user_docs_path(user_email)
        mp = load_member_progress(user_email)
        member_names = (mp or {}).get("members", []) if mp else []

        for item in (root.iterdir() if root.exists() else []):
            if not item.is_dir() or item.name in member_names:
                continue
            out = item / "output.json"
            if not out.exists():
                continue
            try:
                with open(out) as f:
                    data = json.load(f)
                if not data.get("is_valid"):
                    continue
                doc_type = data.get("document_type", "")
                # Build key fields summary
                fields = data.get("extracted_fields") or data.get("english") or {}
                key_fields = {}
                for field in ["company_name_english", "license_number", "expiry_date",
                               "Name", "ID Number", "contract_number", "owner_name"]:
                    if fields.get(field):
                        key_fields[field] = fields[field]
                submitted_docs.append({
                    "document_type": doc_type,
                    "document_id": item.name,
                    "key_fields": key_fields,
                    "status": "verified" if data.get("human_verified") else "pending",
                })
            except Exception:
                pass

        # ── FATCA ────────────────────────────────────────────────────────────
        fatca_data = load_fatca(user_email)
        fatca_summary = {
            "status": get_fatca_status(user_email),
            "data": fatca_data,
        }

        # ── Key Individuals ──────────────────────────────────────────────────
        ki_summary = get_ki_summary(user_email)

        # ── Declaration text ─────────────────────────────────────────────────
        declaration_text = (
            "I confirm that all information and documents submitted during this onboarding "
            "process are accurate, complete, and truthful to the best of my knowledge. "
            "I understand that providing false information may result in rejection of my application."
        )

        return {
            "email": user_email,
            "uploaded_documents": submitted_docs,
            "fatca": fatca_summary,
            "key_individuals": ki_summary,
            "declaration_text": declaration_text,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[SELF-DECL] Summary error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/self-declaration/confirm")
async def self_declaration_confirm(req: SelfDeclConfirmRequest):
    """
    User clicked [Submit & Confirm Declaration] on the Self-Declaration card.
    1. Records confirmation timestamp to DB + disk.
    2. Runs cross-validation.
    3. If passed → runs SurePass, marks onboarding complete, sends completion email.
    Returns: success, message, confirmed_at, crossValidation { passed, mismatches, message }.
    """
    try:
        user = get_user_by_email(req.email)
        if not user:
            raise NotFoundError("User not found")

        user_data = dict(user) if not isinstance(user, dict) else user
        user_name = user_data.get("name", "") or user_data.get("first_name", "User")
        user_language = (req.language or "english").lower()
        now = datetime.now(timezone.utc).isoformat()

        # ── 1. Persist confirmation timestamp ─────────────────────────────────
        try:
            UserRepository.update_by_email_as_service(req.email, {
                "document_confirmation_sent": True,
                "confirmation_timestamp": now,
            })
            logger.info(f"[SELF-DECL] Confirmation recorded for: {req.email}")
        except Exception as e:
            logger.warning(f"[SELF-DECL] DB update failed: {e}")

        try:
            decl_path = user_docs_path(req.email) / "self_declaration.json"
            with open(decl_path, "w", encoding="utf-8") as f:
                json.dump({"confirmed_at": now, "email": req.email}, f, indent=2)
        except Exception:
            pass

        try:
            from app.services.message_generator import MessageGenerator
            confirm_msg = MessageGenerator.self_declaration_confirmed(language=user_language)
        except Exception:
            confirm_msg = "Thanks for confirming your self-declaration. I'm now cross-checking everything you've submitted."

        insert_conversation_log(
            user_email=req.email, role="agent", message=confirm_msg, channel="chat",
            metadata={"message_type": "self_declaration_confirmed", "confirmed_at": now}
        )

        # ── 2. Cross-validation ───────────────────────────────────────────────
        cv_result = {"passed": False, "mismatches": [], "message": ""}
        try:
            cross_validator = CrossValidator()
            validation_result = cross_validator.validate_documents(req.email, user_data)
            passed = validation_result.get("passed", False)
            mismatches = validation_result.get("mismatches", [])
            logger.info(f"[SELF-DECL] Cross-validation: {'PASSED' if passed else 'FAILED'} ({len(mismatches)} mismatch(es))")

            if passed:
                try:
                    cv_msg = MessageGenerator.cross_validation_success(
                        user_name=user_data.get("first_name", ""),
                        language=user_language
                    )
                except Exception:
                    cv_msg = "Everything checks out — all your documents are consistent, and your onboarding is complete."

                # ── 3. SurePass + completion ──────────────────────────────────
                # Pass the cross-validation result we already computed above
                # (validation_result, passed=True) so validate_eid_before_confirmation
                # doesn't re-run the exact same cross-validation a second time.
                try:
                    surepass_valid, surepass_message = validate_eid_before_confirmation(
                        req.email, precomputed_cross_validation_result=validation_result
                    )
                except Exception as _spe:
                    logger.warning(f"[SELF-DECL] SurePass call failed (non-fatal): {_spe}")
                    surepass_valid = True
                    surepass_message = ""

                if surepass_valid:
                    logger.info(f"[SELF-DECL] SurePass passed — marking onboarding complete")
                    update_user_onboarding_status(req.email, True, "onboarding_complete")

                    # ── GrowX: single consolidated trigger point for ALL 3 APIs.
                    # By now cross-validation + SurePass have both passed, so
                    # real EID, Trade License, and package data are guaranteed
                    # to already exist — fire API 1+2 (user create + set
                    # password) then API 3 (SME company create), in sequence,
                    # non-blocking. Each call has its own try/except so a
                    # failure in one doesn't stop the other from attempting.
                    # ── DISABLED (temporary) — GrowX API calling turned off for now.
                    # Uncomment this block to re-enable the GrowX auto-trigger
                    # (API 1+2 user create/set-password, then API 3 SME create).
                    # logger.debug(f"[GROWX] conditions met (cross-validation + SurePass passed) — scheduling auto-trigger for {req.email}")
                    # try:
                    #     from app.api.routes.growx_integration import trigger_api1_api2, trigger_api3
                    #
                    #     async def _fire_growx_all(_gx_email: str):
                    #         _gx_userid = None
                    #         _api1_ok = False
                    #         _api3_ok = False
                    #         try:
                    #             try:
                    #                 _api12_result = await trigger_api1_api2(_gx_email)
                    #                 if isinstance(_api12_result, dict):
                    #                     _gx_userid = _api12_result.get("growx_user_id")
                    #                     _api1_ok = bool(_api12_result.get("success"))
                    #             except Exception as _e1:
                    #                 logger.error(f"[GROWX] trigger_api1_api2 failed (self-declaration) for {_gx_email}: {_e1}", exc_info=True)
                    #             # crtdBy: pass the real userId API 1 just returned, if any.
                    #             # If API 1 failed/returned nothing, still fire API 3 with
                    #             # crtdBy=None (falls back to any previously-saved
                    #             # growx_user_id inside trigger_api3, or None) — let GrowX
                    #             # decide what to do with it rather than skip the call.
                    #             try:
                    #                 _api3_result = await trigger_api3(_gx_email, crtd_by=_gx_userid)
                    #                 _api3_ok = bool(_api3_result.get("success")) if isinstance(_api3_result, dict) else False
                    #             except Exception as _e3:
                    #                 logger.error(f"[GROWX] trigger_api3 failed (self-declaration) for {_gx_email}: {_e3}", exc_info=True)
                    #         except Exception as _e_all:
                    #             # Catches anything outside the two guarded calls above
                    #             # (e.g. an import failure) so it's never silently dropped.
                    #             logger.error(f"[GROWX] unexpected error in auto-trigger for {_gx_email}: {_e_all}", exc_info=True)
                    #         finally:
                    #             logger.info(
                    #                 f"[GROWX] auto-trigger finished for {_gx_email}: "
                    #                 f"api1/2={'OK' if _api1_ok else 'FAILED'} api3={'OK' if _api3_ok else 'FAILED'}"
                    #             )
                    #
                    #     _spawn_background_task(_fire_growx_all(req.email))
                    # except Exception as _gx_e:
                    #     logger.error(f"[GROWX] could not schedule GrowX sync (self-declaration) for {req.email}: {_gx_e}", exc_info=True)

                    try:
                        send_validation_passed_email(req.email, user_name)
                    except Exception as _ee:
                        logger.warning(f"[SELF-DECL] Validation email failed: {_ee}")

                    try:
                        from app.services.handle_reply import send_completion_email
                        send_completion_email(req.email, user_data.get("account_type", ACCOUNT_CORPORATE))
                        logger.info(f"[SELF-DECL] Completion email sent to {req.email}")
                    except Exception as _ce:
                        logger.warning(f"[SELF-DECL] Completion email failed: {_ce}")

                    cv_result = {
                        "passed": True,
                        "mismatches": [],
                        "message": cv_msg,
                        "onboarding_complete": True,
                    }
                else:
                    logger.error(f"[SELF-DECL] SurePass failed: {surepass_message}")
                    logger.info(f"[GROWX] ⏭ SurePass failed for {req.email} — GrowX auto-trigger NOT scheduled")
                    cv_result = {
                        "passed": False,
                        "mismatches": [surepass_message],
                        "message": (
                            f"⚠️ Government verification failed: {surepass_message}\n\n"
                            "Please review and re-upload your Emirates ID."
                        ),
                        "onboarding_complete": False,
                    }
            else:
                logger.info(f"[GROWX] ⏭ Cross-validation failed for {req.email} — GrowX auto-trigger NOT scheduled")
                mismatch_summary = "\n".join(f"  • {m}" for m in mismatches[:5])
                try:
                    cv_msg = MessageGenerator.cross_validation_failure(
                        mismatches=mismatches,
                        user_name=user_data.get("first_name", ""),
                        language=user_language
                    )
                except Exception:
                    cv_msg = (
                        f"⚠️ Cross-validation found inconsistencies:\n\n{mismatch_summary}\n\n"
                        "Please review and re-upload the affected documents."
                    )
                try:
                    send_validation_failed_email(
                        to_email=req.email,
                        user_name=user_name,
                        mismatches=mismatches,
                        attempt_count=validation_result.get("attempt_count", 1)
                    )
                except Exception:
                    pass
                cv_result = {
                    "passed": False,
                    "mismatches": mismatches,
                    "message": cv_msg,
                    "onboarding_complete": False,
                }
        except Exception as cv_error:
            logger.warning(f"[SELF-DECL] Cross-validation error (non-fatal): {cv_error}")
            cv_result = {
                "passed": False,
                "mismatches": [],
                "message": f"Cross-validation could not be completed: {cv_error}",
                "onboarding_complete": False,
            }

        insert_conversation_log(
            user_email=req.email, role="agent", message=cv_result["message"], channel="chat",
            metadata={
                "message_type": "cross_validation_result",
                "passed": cv_result["passed"],
                # Without this, the frontend's transformLogToMessage() can never
                # reconstruct message.onboardingComplete on reload (it only reads
                # metadata.onboarding_complete), so completionIdx stays -1 and the
                # Declaration tab renders blank after any logout/relogin.
                "onboarding_complete": cv_result["onboarding_complete"],
            }
        )

        # ── Create chat session & generate reference number ──────────────────
        reference_number = None
        try:
            user_id = user_data.get("id") or user_data.get("user_id") or ""
            session_result = create_chat_session(
                user_id=str(user_id),
                user_email=req.email,
            )
            reference_number = session_result.get("reference_number")
            logger.info(f"[SELF-DECL] Chat session created: {reference_number}")
        except Exception as ref_err:
            logger.info(f"[SELF-DECL] Chat session creation failed (non-fatal): {ref_err}")

        return {
            "success":          True,
            "message":          confirm_msg,
            "confirmed_at":     now,
            "crossValidation":  cv_result,
            "reference_number": reference_number,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[SELF-DECL] Confirm error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.get("/self-declaration/status/{user_email}")
async def self_declaration_status(user_email: str):
    """Check if self-declaration has been confirmed."""
    decl_path = user_docs_path(user_email) / "self_declaration.json"
    if decl_path.exists():
        try:
            with open(decl_path) as f:
                data = json.load(f)
            return {"confirmed": True, "confirmed_at": data.get("confirmed_at")}
        except Exception:
            pass
    return {"confirmed": False, "confirmed_at": None}
