"""
The conversation itself: starting a session, exchanging chat messages, resuming
by reference number, and reading or clearing conversation history.
"""

import logging
import json
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import traceback
from app.i18n import localized
from app.i18n.messages import doc_name
from app.services.message_generator import MessageGenerator, ai_message_gen
from app.utils.language import normalize_language, detect_and_translate_input, translate_stored_messages_batch
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
from app.services.chat_session_service import (
    create_chat_session,
    validate_reference_number,
    get_active_reference_for_user,
)
from app.services.supabase_client import supabase, get_user_by_email
from app import config
from app.utils.pii_masker import mask_name
from app.repositories.conversation_repository import ConversationRepository
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
from app.services.specialized_ocr.corporate_shareholder_detector import (
    detect_corporate_shareholders as _detect_corps,
    run_type2_analysis as _run_type2,
)
from app.services.run_model import call_local_llm
from app.schemas.onboarding import ChatMessage, StartConversationRequest, ChatConversationalRequest, UploadConversationalResponse, OnboardingStatusResponse, ValidateRefRequest, CrossValidationRequest
from app.domain.onboarding.documents import _find_commercial_output, extract_members_from_commercial, get_submitted_documents
from app.domain.onboarding.members import save_member_progress
from app.domain.onboarding.stages import get_onboarding_status, update_user_onboarding_status
from app.domain.onboarding.verification import handle_verification_response
from app.domain.onboarding.confirmation import is_confirmation
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)
from app.domain.exceptions import (
    DomainError,
    NotFoundError,
    PermissionError_,
)

logger = logging.getLogger(__name__)

# Sub-router. The `/chatupload` prefix and tags are applied once in
# app/api/routes/onboarding/__init__.py, so every path below is unchanged.
router = APIRouter()

# ARCHITECTURE FIX (prompt-remediation Phase 5): chat_conversational()'s prompt
# below used to stuff the assistant's persona, the whole banking knowledge
# base, the account-requirements table, and the 9-item instruction list --
# every bit of it identical on every single call -- into the same long
# user-turn string as the actual per-request context (chat history, the
# user's live question), then called call_local_llm(prompt) with no
# system_prompt at all, so it fell back to run_model.py's generic default
# system prompt and the shared 0.7 temperature. This was flagged by name in
# the original scorecard's #8 (chat/conversational prompt design) as the
# clearest example of the "everything in one user-turn string" anti-pattern,
# and Phase 2 fixed every OTHER chat/message call site (handle_reply.py,
# message_generator.py, document_expiry_validator.py) but missed this one --
# it only got its brand-name literal fixed in Phase 1. _CHAT_SYSTEM_PROMPT
# below is the constant, request-independent part, now sent through the
# model's actual system role (and Bedrock-cached the same way the extraction
# prompts are, since bedrock_client.py caches any non-empty system text) --
# see chat_conversational() further down for the user-turn half.
_CHAT_SYSTEM_PROMPT = f"""You are a helpful banking assistant for {config.BRAND_NAME}, helping customers with account onboarding in the UAE.

BANKING KNOWLEDGE BASE:
- Shareholder: Person who owns shares in a company. Has equity stake, voting rights, receives dividends.
- Signatory: Person authorized to sign documents and conduct transactions on behalf of a company. May not own shares.
- UBO (Ultimate Beneficial Owner): Person who ultimately owns or controls a company, typically holding 25% or more of shares.
- Corporate Account: Business bank account registered under a company's legal name for business transactions.
- Trade License (Commercial License): Legal document issued by UAE authorities permitting business operations.
- Emirates ID (EID): Official government-issued identification card required for all UAE residents.
- Passport: Valid international passport accepted as an alternative identity document to Emirates ID.
- Ejari: Government-registered tenancy contract in Dubai (required for bank accounts).
- MOA (Memorandum of Association): Legal document defining company structure, ownership, and management.
- Non-Resident: Can open corporate bank accounts in UAE with proper documentation (trade license, Emirates ID or Passport for signatories).

ACCOUNT REQUIREMENTS:
- Corporate Single Owner: Emirates ID or Passport + Commercial License + Ejari
- Corporate Partnership: Commercial License + MOA + Emirates ID or Passport for each partner/manager/UBO

INSTRUCTIONS:
1. Answer the user's question clearly and helpfully
2. If asked about banking concepts (shareholder, signatory, UBO, license, etc.), explain using the knowledge base
3. If asked about account requirements, provide specific info for their account type
4. If asked about document status, reference their current status
5. If asked general questions, answer naturally and professionally
6. Keep responses concise (2-5 sentences unless complex topic requires more)
7. Be professional but friendly - like a helpful bank representative
8. DO NOT tell them to upload documents unless they specifically ask what's needed
9. If you don't know something specific to their case, acknowledge it honestly
"""

@router.post("/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """
    ✅ FULLY UPDATED: Language support + AI-generated welcome messages
    Initialize chat with account-specific welcome message in user's language
    """
    try:
        email = request.email
        language = request.language.lower().strip() if hasattr(request, 'language') else "english"
        
        # ✅ VALIDATE LANGUAGE
        language = normalize_language(language)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"[START CONV] Initializing chat")
        logger.info(f"[START CONV] Email: {email}")
        logger.info(f"[START CONV] Language: {language.upper()}")
        logger.info(f"{'='*80}\n")
        
        user = get_user_by_email(email)
        if not user:
            raise NotFoundError("User not found")
        
        # ✅ DEBUG BLOCK
        logger.info(f"\n{'='*80}")
        logger.info(f"[START CONV] DEBUG INFO")
        logger.info(f"[START CONV] Email: {email}")
        logger.info(f"[START CONV] Name: '{user.get('name')}'")
        logger.info(f"[START CONV] Account Type: '{user.get('account_type')}'")
        logger.info(f"[START CONV] Ownership Type: '{user.get('ownership_type')}'")
        logger.info(f"[START CONV] Has seen welcome: {user.get('has_seen_ai_welcome', False)}")
        logger.info(f"{'='*80}\n")
        
        has_seen_welcome = user.get("has_seen_ai_welcome", False)

        if has_seen_welcome:
            # RETURNING USER — check if onboarding is fully complete
            onboarding_complete = user.get("onboarding_complete", False)

            if onboarding_complete:
                # Post-onboarding returning user: prompt for reference number in chat
                existing_ref = get_active_reference_for_user(email)
                logger.info(f"Post-onboarding returning user — ref_prompt mode (ref={existing_ref})")
                return {
                    "success":        True,
                    "should_resume":  False,
                    "ref_prompt":     True,
                    "is_first_visit": False,
                    "language":       language,
                    "existing_ref":   existing_ref,  # None or "REF-2026-XXXXXX"
                }

            # Mid-onboarding returning user: resume normally
            logger.info(f"Mid-onboarding returning user — resuming conversation")
            return {
                "success":        True,
                "should_resume":  True,
                "ref_prompt":     False,
                "is_first_visit": False,
                "language":       language,
            }
        
        # ========================================================================
        # FIRST-TIME USER - Clean up old generic messages
        # ========================================================================
        logger.info(f"First-time AI Assistant user")
        
        try:
            result = ConversationRepository.list_agent_chat_messages(email, limit=5)
            
            if result.data:
                for msg in result.data:
                    content = msg.get("message", "")
                    metadata = msg.get("metadata")
                    
                    # Detect old generic messages
                    is_generic = (
                        "I'm your AI onboarding assistant" in content or
                        "You can upload documents like:" in content or
                        ("Emirates ID" in content and "Commercial License" in content)
                    )
                    
                    is_old_welcome = (
                        metadata and 
                        metadata.get("message_type") == "welcome" and
                        metadata.get("display_once") is None
                    )
                    
                    if is_generic or is_old_welcome:
                        ConversationRepository.delete_by_id(msg["id"])
                        logger.info(f"Deleted old message (ID: {msg['id']})")
        
        except Exception as e:
            logger.warning(f"Failed to cleanup old messages: {e}")
        
        # ========================================================================
        # ✅ GENERATE AI WELCOME MESSAGE IN SPECIFIED LANGUAGE
        # ========================================================================
        logger.info(f"Generating AI welcome message in {language.upper()}")
        
        try:
            welcome_message = ai_message_gen.generate_welcome_message(
                user, 
                language=language
            )
            logger.info(f"[SUCCESS] AI welcome message generated ({len(welcome_message)} chars)")
            logger.debug(f"Preview: {welcome_message[:150]}...")
            
        except Exception as e:
            logger.error(f"AI generation failed: {e}")
            
            # Emergency fallback in correct language
            user_name = user.get("name", "there")
            account_type = user.get("account_type", "account")
            ownership_type = user.get("ownership_type")
            
            # ✅ CHANGED: ownership_type is no longer asked upfront — the AI
            # infers it from the Commercial License once uploaded (see the
            # auto-classification block in upload_conversational()), so this
            # fallback can no longer branch on ownership_type either. Kept in
            # sync with MessageGenerator.generate_welcome_message().
            if account_type == ACCOUNT_CORPORATE:
                welcome_message = localized(language,
                    en=(f"Good to have you here, {user_name}.\n\n"
                        "Let's get your account set up. I'll guide you through it end to end — first up, "
                        "I'll need your Commercial License to verify your business and pull the next steps for you."),
                    es=(f"Un gusto tenerte aquí, {user_name}.\n\n"
                        "Vamos a configurar tu cuenta. Te guiaré de principio a fin — para empezar, necesitaré "
                        "tu Licencia Comercial para verificar tu negocio y definir los próximos pasos."),
                    ar=(f"سعداء بانضمامك، {user_name}.\n\n"
                        "لنبدأ بإعداد حسابك. سأرشدك خطوة بخطوة — أولاً، سأحتاج إلى رخصتك التجارية "
                        "للتحقق من نشاطك التجاري وتحديد الخطوات التالية."))
            else:
                welcome_message = localized(language,
                    en=f"Welcome {user_name}!\n\nI'm here to help you with your {account_type} account onboarding. Let's get started!",
                    es=f"¡Bienvenido {user_name}!\n\nEstoy aquí para ayudarte con la incorporación de tu cuenta {account_type}. ¡Comencemos!",
                    ar=f"مرحباً {user_name}!\n\nأنا هنا لمساعدتك في تسجيل حسابك. لنبدأ!")
        
        # ========================================================================
        # ✅ STORE WELCOME MESSAGE WITH LANGUAGE METADATA
        # ========================================================================
        welcome_metadata = {
            "message_type": "initial_welcome",
            "display_once": True,
            "is_dismissable": False,
            "language": language,
            "user_info": {
                "account_type": user.get("account_type"),
                "ownership_type": user.get("ownership_type"),
                "onboarding_step": user.get("onboarding_step", "registration_complete")
            }
        }
        
        try:
            insert_conversation_log(
                user_email=email,
                role="agent",
                message=welcome_message,
                channel="chat",
                metadata=welcome_metadata
            )
            logger.info(f"[SUCCESS] Welcome message stored with metadata")
        except Exception as log_error:
            logger.warning(f"Failed to log welcome message: {log_error}")
        
        # ========================================================================
        # ✅ SET FLAG - Mark user as having seen welcome
        # ========================================================================
        try:
            UserRepository.update_by_email(email, {
                "has_seen_ai_welcome": True
            })
            
            logger.info(f"[SUCCESS] User flag updated - welcome will show only once")
        except Exception as flag_error:
            logger.warning(f"Flag update error (non-critical): {flag_error}")
        
        # ========================================================================
        # ✅ GET ONBOARDING STATUS
        # ========================================================================
        status = get_onboarding_status(email, user)
        
        # ========================================================================
        # ✅ RETURN RESPONSE FOR FIRST-TIME USER
        # ========================================================================
        return {
            "success": True,
            "welcome_message": welcome_message,
            "should_resume": False,
            "is_first_visit": True,
            "language": language,
            "status": status
        }
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"Start conversation error: {e}")
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.get("/get-onboarding-status/{email}")
async def get_onboarding_status_endpoint(email: str):
    """Get current onboarding status"""
    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")
    
    status = get_onboarding_status(email, user)
    return status


@router.post("/chat-conversational")
async def chat_conversational(request: ChatConversationalRequest):
    """
    ✅ FULLY UPDATED: Direct LLM responses + Strict verification detection + Language support
    Handle chat messages - answer ANY question with LLM, only check verification for explicit confirmations
    """
    email = request.email

    # ============================================================================
    # GET LANGUAGE FROM REQUEST
    # ============================================================================
    language = request.language.lower().strip() if hasattr(request, 'language') else "english"

    language = normalize_language(language)

    # ============================================================================
    # AUTO-DETECT + TRANSLATE INCOMING MESSAGE
    # ============================================================================
    # The user may type in a different language than the chat's active
    # language (e.g. active language is Arabic but they type in English).
    # Detect what they typed and translate it into the active language
    # before anything downstream (verification-keyword matching, the LLM
    # prompt, conversation logging) sees it, so the selected language stays
    # authoritative regardless of what language the user actually types in.
    _detection = detect_and_translate_input(request.message, language)
    original_message = request.message
    if _detection["was_translated"]:
        request.message = _detection["translated_message"]

    logger.info(f"\n{'='*80}")
    logger.info(f"[CHAT] Processing message")
    logger.info(f"[CHAT] Email: {email}")
    logger.info(f"[CHAT] Language: {language.upper()}")
    if _detection["was_translated"]:
        logger.info(f"[CHAT] Detected input language: {_detection['detected_language']} -> translated to {language}")
        logger.info(f"[CHAT] Original message: {original_message[:100]}...")
    logger.info(f"[CHAT] Message: {request.message[:100]}...")
    logger.info(f"{'='*80}\n")

    user = get_user_by_email(email)
    if not user:
        raise NotFoundError("User not found")

    # ============================================================================
    # STEP 1: Check ONLY for explicit verification responses
    # ============================================================================
    # Keyword list moved to app/domain/onboarding/confirmation.py — it used to
    # exist here AND in verification.py with different contents, so a message
    # could pass this gate and then be rejected by the function it gated.

    user_message_lower = request.message.lower().strip()
    user_words = user_message_lower.split()

    # max_words=3 preserves the existing gate: a long sentence that happens to
    # contain "ok" is prose, not an approval.
    is_likely_verification = is_confirmation(request.message, max_words=3)

    logger.info(f"[CHAT] Verification check: {is_likely_verification} (words: {len(user_words)})")

    if is_likely_verification:
        logger.info(f"[CHAT] Detected verification response")

        verification = handle_verification_response(
            email,
            request.message,
            user,
            language=language
        )

        if verification["is_verification"]:
            response = verification["next_message"]

            # Log conversation
            try:
                insert_conversation_log(
                    user_email=email,
                    role="user",
                    message=request.message,
                    channel="chat",
                    metadata={"language": language, "message_type": "verification"}
                )
                insert_conversation_log(
                    user_email=email,
                    role="agent",
                    message=response,
                    channel="chat",
                    metadata={"language": language, "message_type": "verification_response"}
                )
            except Exception as e:
                logger.warning(f"Could not log conversation: {e}")

            # ====================================================================
            # CHECK FOR STAGE TRANSITION (identification → member_eids)
            # ====================================================================
            account_type = user.get("account_type")
            ownership = user.get("ownership_type")
            current_stage = user.get("document_stage", STAGE_IDENTIFICATION)

            # Initialise here so elif branches below never hit UnboundLocalError
            has_commercial = False
            has_moa = False

            if (account_type == ACCOUNT_CORPORATE and
                ownership in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
                current_stage in (STAGE_IDENTIFICATION, STAGE_SO_MEMBER_EIDS) and
                verification["verified"]):
                # Note: current_stage includes "so_member_eids" as a safety-net fallback.
                # Under normal operation Multiple Owner accounts stay in "identification"
                # until both Commercial + MOA are verified. The so_member_eids guard
                # handles the edge case where a prior run accidentally set that stage.

                logger.info(f"Checking if identification stage is complete...")

                uploaded_docs = get_submitted_documents(email)

                has_commercial = any(
                    doc.get("document_type", "").lower() == "commercial" and
                    doc.get("is_valid")
                    for doc in uploaded_docs
                )
                has_moa = any(
                    doc.get("document_type", "").lower() == "moa" and
                    doc.get("is_valid")
                    for doc in uploaded_docs
                )

                logger.info(f"Document check: Commercial={has_commercial}, MOA={has_moa}")

                if has_commercial and has_moa:
                    logger.info("Identification stage complete - running Type-2 corporate check")

                    # ==============================================================
                    # TYPE-2 CHECK: detect corporate shareholders in Commercial License
                    # ==============================================================
                    _comm_out_path, comm_data = _find_commercial_output(email)
                    corporate_detected = False
                    pending_coi_list = []

                    if _comm_out_path is not None:
                        try:
                            partners_list = (
                                comm_data.get("extracted_fields", {}).get("partners", [])
                                or comm_data.get("partners", [])
                            )
                            if partners_list:
                                corp_detection = _detect_corps(partners_list)
                                if corp_detection["has_corporate_shareholders"]:
                                    corporate_detected = True
                                    pending_coi_list = [
                                        c["name"] for c in corp_detection["corporate_shareholders"]
                                    ]
                                    logger.info(f"[TYPE-2] Corporate shareholders found: {pending_coi_list}")
                        except Exception as _e:
                            logger.warning(f"Type-2 detection skipped (non-fatal): {_e}")

                    if corporate_detected and pending_coi_list:
                        # ── TYPE-2 PATH ──────────────────────────────────────
                        logger.info("[TYPE-2] Transitioning → corporate_shareholder_docs")

                        save_member_progress(
                            email,
                            members=[],
                            current_index=0,
                            pending_coi=pending_coi_list,
                        )
                        update_user_onboarding_status(email, False, STAGE_CORPORATE_SHAREHOLDER_DOCS)
                        logger.info("[TYPE-2] DB updated: identification → corporate_shareholder_docs")

                        try:
                            comm_fields = comm_data.get("extracted_fields", {})
                            alert_message = ai_message_gen.generate_corporate_shareholder_detected_message(
                                corp_names=pending_coi_list,
                                commercial_data=comm_fields,
                                user=user,
                                language=language,
                            )
                        except Exception as _ae:
                            logger.warning(f"AI corp-detected message failed, using fallback: {_ae}")
                            corp_list_str = ", ".join(pending_coi_list)
                            alert_message = localized(None,
                                en=f"The Commercial License has been received and reviewed. It contains the following corporate shareholders: {corp_list_str}. UAE banking regulations require a Certificate of Incorporation for each corporate entity. Please upload the Certificate of Incorporation for: {pending_coi_list[0]}.",
                                es=f"Se ha recibido y revisado la Licencia Comercial. Incluye los siguientes accionistas corporativos: {corp_list_str}. La normativa bancaria de los EAU exige un Certificado de Constitución para cada entidad corporativa. Cargue el Certificado de Constitución de: {pending_coi_list[0]}.",
                                ar=f"تم استلام الرخصة التجارية ومراجعتها. وهي تتضمن المساهمين الاعتباريين التاليين: {corp_list_str}. تشترط الأنظمة المصرفية في الإمارات تقديم شهادة تأسيس لكل كيان اعتباري. يُرجى تحميل شهادة التأسيس لـ: {pending_coi_list[0]}.")

                        try:
                            send_corporate_shareholder_request_email(
                                to_email=email,
                                corp_name=pending_coi_list[0],
                                corp_index=1,
                                total_corps=len(pending_coi_list),
                            )
                        except Exception as _ee:
                            logger.warning(f"CoI request email failed (non-fatal): {_ee}")

                        try:
                            insert_conversation_log(
                                user_email=email,
                                role="agent",
                                message=alert_message,
                                channel="chat",
                                metadata={
                                    "message_type": "type2_corp_detected",
                                    "from_stage": STAGE_IDENTIFICATION,
                                    "to_stage": STAGE_CORPORATE_SHAREHOLDER_DOCS,
                                    "pending_coi": pending_coi_list,
                                    "language": language,
                                }
                            )
                        except Exception:
                            pass

                        return {
                            "response": alert_message,
                            "verification_accepted": True,
                            "is_complete": False,
                            "stage_transition": True,
                            "new_stage": STAGE_CORPORATE_SHAREHOLDER_DOCS,
                            "pending_coi": pending_coi_list,
                            "language": language,
                            "was_translated": _detection["was_translated"],
                            "detected_language": _detection["detected_language"],
                            "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                        }

                    # ── STANDARD PATH (no corporate shareholders) ─────────────
                    member_data = extract_members_from_commercial(email)
                    members = member_data.get("all_names", [])
                    ubos = member_data.get("ubos", [])
                    ubo_names = [
                        u.get("name") if isinstance(u, dict) else u
                        for u in ubos
                    ]

                    logger.info(f"Extracted members: {[mask_name(_n) for _n in members] if config.PII_LOG_MASKING_ENABLED else members}")
                    logger.info(f"UBOs identified: {[mask_name(_n) for _n in ubo_names] if config.PII_LOG_MASKING_ENABLED else ubo_names}")

                    if members and len(members) > 0:
                        save_member_progress(email, members, 0, ubo_names=ubo_names)
                        logger.info(f"Member progress saved ({len(members)} members, {len(ubo_names)} UBOs)")

                        update_user_onboarding_status(email, False, STAGE_MEMBER_EIDS)
                        logger.info("DB updated: identification → member_eids")

                        try:
                            transition_message = ai_message_gen.generate_stage_transition_message(
                                user=user,
                                from_stage=STAGE_IDENTIFICATION,
                                to_stage=STAGE_MEMBER_EIDS,
                                context_data={
                                    "members": members,
                                    "current_member": members[0] if members else None,
                                    "ubo_names": ubo_names,
                                },
                                language=language
                            )
                        except Exception as ai_error:
                            logger.warning(f"AI transition generation failed, using fallback: {ai_error}")
                            member_list = "\n".join([
                                f"  {i}. {m} (UBO)" if m in ubo_names else f"  {i}. {m}"
                                for i, m in enumerate(members, 1)
                            ])
                            transition_message = localized(language,
                                en=(f"The identification stage has been completed successfully.\n\n"
                                    f"Emirates ID or Passport verification is now required for:\n\n{member_list}\n\n"
                                    f"Please start with: {members[0]}"),
                                es=(f"La etapa de identificacion se ha completado.\n\n"
                                    f"Se requiere verificacion de Emirates ID o Pasaporte para:\n\n{member_list}\n\n"
                                    f"Comience con el Emirates ID o Pasaporte de: {members[0]}"),
                                ar=(f"اكتملت مرحلة التعريف بنجاح.\n\n"
                                    f"يلزم الآن التحقق من الهوية الإماراتية أو جواز السفر لكلٍّ من:\n\n{member_list}\n\n"
                                    f"يُرجى البدء بـ: {members[0]}"))

                        try:
                            insert_conversation_log(
                                user_email=email,
                                role="agent",
                                message=transition_message,
                                channel="chat",
                                metadata={
                                    "message_type": "stage_transition",
                                    "from_stage": STAGE_IDENTIFICATION,
                                    "to_stage": STAGE_MEMBER_EIDS,
                                    "members": members,
                                    "ubo_names": ubo_names,
                                    "language": language,
                                }
                            )
                        except Exception as e:
                            logger.warning(f"Failed to log transition message: {e}")

                        return {
                            "response": transition_message,
                            "verification_accepted": True,
                            "is_complete": False,
                            "stage_transition": True,
                            "new_stage": STAGE_MEMBER_EIDS,
                            "members": members,
                            "ubo_names": ubo_names,
                            "current_member": members[0] if members else None,
                            "language": language,
                            "was_translated": _detection["was_translated"],
                            "detected_language": _detection["detected_language"],
                            "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                            # ── v3: frontend MOA AS selection trigger ─────
                            "moa_as_trigger": True,
                            "moa_members": members,
                        }

            elif has_commercial and not has_moa:
                # ── EARLY TYPE-2 CHECK ─────────────────────────────────────
                # Commercial is uploaded but MOA is not yet received.
                # If corporate shareholders are detected, transition to
                # corporate_shareholder_docs immediately so the user can
                # upload CoIs (and MOA) in the correct stage.
                logger.info("Commercial present but no MOA yet — running early Type-2 check")

                _early_comm_path, _early_comm_data = _find_commercial_output(email)
                _early_corp_detected = False
                _early_pending_coi = []

                if _early_comm_path is not None:
                    try:
                        _early_partners = (
                            _early_comm_data.get("extracted_fields", {}).get("partners", [])
                            or _early_comm_data.get("partners", [])
                        )
                        if _early_partners:
                            _early_detection = _detect_corps(_early_partners)
                            if _early_detection["has_corporate_shareholders"]:
                                _early_corp_detected = True
                                _early_pending_coi = [
                                    c["name"]
                                    for c in _early_detection["corporate_shareholders"]
                                ]
                                logger.info(f"[TYPE-2 EARLY] Corporate shareholders: {_early_pending_coi}")
                    except Exception as _ee:
                        logger.warning(f"Early Type-2 detection skipped: {_ee}")

                if _early_corp_detected and _early_pending_coi:
                    save_member_progress(
                        email,
                        members=[],
                        current_index=0,
                        pending_coi=_early_pending_coi,
                    )
                    update_user_onboarding_status(email, False, STAGE_CORPORATE_SHAREHOLDER_DOCS)
                    logger.info("[TYPE-2 EARLY] DB updated: identification → corporate_shareholder_docs")

                    try:
                        _comm_fields = _early_comm_data.get("extracted_fields", {})
                        _early_alert = ai_message_gen.generate_corporate_shareholder_detected_message(
                            corp_names=_early_pending_coi,
                            commercial_data=_comm_fields,
                            user=user,
                            language=language,
                        )
                    except Exception as _em:
                        logger.warning(f"Early Type-2 message failed: {_em}")
                        _first_corp = _early_pending_coi[0]
                        _early_alert = (
                            f"We have identified that {_first_corp} is a corporate entity listed "
                            f"as a shareholder. Please upload the Certificate of Incorporation for "
                            f"{_first_corp} to proceed."
                        )

                    try:
                        insert_conversation_log(
                            user_email=email,
                            role="agent",
                            message=_early_alert,
                            channel="chat",
                            metadata={
                                "message_type": "type2_corp_detected_early",
                                "pending_coi": _early_pending_coi,
                                "language": language,
                            },
                        )
                    except Exception:
                        pass

                    return {
                        "response": _early_alert,
                        "verification_accepted": True,
                        "is_complete": False,
                        "stage_transition": True,
                        "new_stage": STAGE_CORPORATE_SHAREHOLDER_DOCS,
                        "pending_coi": _early_pending_coi,
                        "language": language,
                        "was_translated": _detection["was_translated"],
                        "detected_language": _detection["detected_language"],
                        "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                    }

            # Return normal verification response if no stage transition.
            # Skip the early return when we are in corporate_shareholder_docs
            # so execution falls through to the dedicated handler below.
            if current_stage != STAGE_CORPORATE_SHAREHOLDER_DOCS:
                # ✅ FIX: FATCA / PEP / Self-Declaration triggers must be returned in
                # the is_verification format so the frontend reads them correctly.
                # The frontend only looks for fatca_trigger / pep_trigger /
                # self_declaration_trigger inside the `rd.is_verification` branch.
                # Returning as `{ "response": ... }` silently drops these flags.
                _has_trigger = (
                    verification.get("fatca_trigger") or
                    verification.get("pep_trigger") or
                    verification.get("self_declaration_trigger")
                )
                if _has_trigger:
                    return {
                        "is_verification": True,
                        "verified": verification.get("verified", True),
                        "next_message": response,
                        "is_complete": verification.get("is_complete", False),
                        "fatca_trigger": verification.get("fatca_trigger", False),
                        "pep_trigger": verification.get("pep_trigger", False),
                        "self_declaration_trigger": verification.get("self_declaration_trigger", False),
                        "language": language,
                        "was_translated": _detection["was_translated"],
                        "detected_language": _detection["detected_language"],
                        "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                    }
                return {
                    "response": response,
                    "verification_accepted": verification["verified"],
                    "is_complete": verification.get("is_complete", False),
                    "language": language,
                    "was_translated": _detection["was_translated"],
                    "detected_language": _detection["detected_language"],
                    "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                }
            # else: fall through to the corporate_shareholder_docs handler

        # ================================================================
        # CORPORATE_SHAREHOLDER_DOCS → MEMBER_EIDS transition
        # Fires when user says "okay" while stage is corporate_shareholder_docs
        # ================================================================
        if (account_type == ACCOUNT_CORPORATE and
                ownership in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE] and
                current_stage == STAGE_CORPORATE_SHAREHOLDER_DOCS and
                verification["verified"]):

            logger.info("[TYPE-2] Stage: corporate_shareholder_docs - checking CoI collection progress")

            progress_file = member_progress_path(email)
            if not progress_file.exists():
                logger.warning("No member_progress.json in corporate_shareholder_docs stage")
            else:
                try:
                    with open(progress_file, "r", encoding="utf-8") as _pf:
                        _progress = json.load(_pf)
                    pending_coi = _progress.get("pending_coi", [])

                    if len(pending_coi) <= 1:
                        # Last (or only) CoI just uploaded.
                        # Before expanding ownership, verify the MOA is also uploaded.
                        _uploaded_all = get_submitted_documents(email)
                        _has_moa_now = any(
                            d.get("document_type", "").lower() in ("moa", "memorandum")
                            and d.get("is_valid")
                            for d in _uploaded_all
                        )

                        if not _has_moa_now:
                            # Pop this CoI from the pending list so it's not re-requested
                            _remaining_after_last = pending_coi[1:]
                            save_member_progress(
                                email,
                                members=_progress.get("members", []),
                                current_index=_progress.get("current_index", 0),
                                pending_coi=_remaining_after_last,
                            )
                            logger.info("[TYPE-2] All CoIs done but MOA still missing — requesting MOA")
                            _moa_msg = (
                                localized(language,
                                    en=("All Certificates of Incorporation have been received. "
                                "Please now upload the Memorandum of Association (MOA) to proceed."),
                                    es=("Se han recibido todos los Certificados de Incorporación. "
                                "Ahora, por favor suba el Memorando de Asociación (MOA)."),
                                    ar=("تم استلام جميع شهادات التأسيس. "
                                "يُرجى الآن تحميل عقد التأسيس (MOA) للمتابعة."))
                            )
                            try:
                                insert_conversation_log(
                                    user_email=email, role="agent",
                                    message=_moa_msg, channel="chat",
                                    metadata={"message_type": "type2_moa_request", "language": language}
                                )
                            except Exception:
                                pass
                            return {
                                "response": _moa_msg,
                                "verification_accepted": True,
                                "is_complete": False,
                                "stage_transition": False,
                                "awaiting_moa": True,
                                "language": language,
                                "was_translated": _detection["was_translated"],
                                "detected_language": _detection["detected_language"],
                                "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                            }

                        # All CoIs collected AND MOA present — run full Type-2 analysis
                        logger.info("[TYPE-2] All CoIs collected - running ownership expansion")

                        # Gather all CoI extracted_fields.
                        # Scan every subfolder for output.json files whose
                        # document_type is certificate_of_incorporation/coi.
                        coi_map = {}
                        _coi_base = user_docs_path(email)
                        _coi_types = {"certificate_of_incorporation", "coi"}
                        if _coi_base.exists():
                            for _cf in _coi_base.iterdir():
                                if not _cf.is_dir():
                                    continue
                                _out_f = _cf / "output.json"
                                if _out_f.exists():
                                    try:
                                        with open(_out_f, "r", encoding="utf-8") as _of:
                                            _od = json.load(_of)
                                        _dt = _od.get("document_type", "").lower()
                                        if _dt in _coi_types:
                                            # Use company_name from extracted_fields as key
                                            # (fallback to folder name)
                                            _ef = _od.get("extracted_fields", _od)
                                            _key = (
                                                _ef.get("company_name")
                                                or _ef.get("entity_name")
                                                or _ef.get("name")
                                                or _cf.name
                                            )
                                            # coi_map values MUST be a list of individual
                                            # dicts {name, share_percentage} as expected by
                                            # expand_ownership().  The CoI stores them under
                                            # "directors_and_shareholders" (BVI extractor) or
                                            # similar keys — never the whole _ef dict.
                                            _individuals = (
                                                _ef.get("directors_and_shareholders")
                                                or _ef.get("shareholders")
                                                or _ef.get("directors")
                                                or []
                                            )
                                            coi_map[_key] = _individuals
                                            logger.info(f"[TYPE-2] CoI loaded for: {_key} "
                                                  f"({len(_individuals)} individual(s))")
                                    except Exception:
                                        pass
                        logger.info(f"[TYPE-2] coi_map keys: {list(coi_map.keys())}")

                        # Read Commercial License partners list
                        _comm_path2, _comm_data2 = _find_commercial_output(email)
                        partners_list = []
                        if _comm_path2 is not None:
                            try:
                                partners_list = (
                                    _comm_data2.get("extracted_fields", {}).get("partners", [])
                                    or _comm_data2.get("partners", [])
                                )
                            except Exception:
                                pass

                        if partners_list:
                            type2_result = _run_type2(partners_list, coi_map=coi_map if coi_map else None)
                            # expanded_owners is explicitly None when pending_coi is non-empty
                            # (i.e. corporate detected but CoI not yet collected).
                            # Use empty list as safe fallback to prevent TypeError downstream.
                            expanded_owners = type2_result.get("expanded_owners") or []
                            pending_coi_corps = type2_result.get("pending_coi", [])
                            if pending_coi_corps:
                                logger.warning(f"[TYPE-2]  Still waiting for CoI for: {pending_coi_corps}")
                            ubo_names = [o["name"] for o in expanded_owners if o.get("is_ubo")]
                            all_member_names = [o["name"] for o in expanded_owners]
                        else:
                            expanded_owners = []
                            ubo_names = []
                            all_member_names = []
                            pending_coi_corps = []

                        # Save full progress
                        save_member_progress(
                            email,
                            members=all_member_names,
                            current_index=0,
                            ubo_names=ubo_names,
                            expanded_members=expanded_owners,
                            pending_coi=[],
                        )

                        # Update DB stage
                        update_user_onboarding_status(email, False, STAGE_MEMBER_EIDS)
                        logger.info(f"[TYPE-2] DB updated: corporate_shareholder_docs → member_eids")

                        # Send UBO identified email
                        try:
                            send_ubo_identified_email(
                                to_email=email,
                                expanded_owners=expanded_owners,
                                ubo_names=ubo_names,
                            )
                        except Exception as _ue:
                            logger.warning(f"UBO email failed (non-fatal): {_ue}")

                        # Generate AI stage transition message
                        first_member = all_member_names[0] if all_member_names else None
                        try:
                            transition_message = ai_message_gen.generate_type2_stage_transition_message(
                                user=user,
                                expanded_owners=expanded_owners,
                                ubo_names=ubo_names,
                                first_member=first_member,
                                language=language,
                            )
                        except Exception as _te:
                            logger.warning(f"AI type2 transition message failed, using fallback: {_te}")
                            member_list_fb = "\n".join([
                                f"  {_i}. {_o['name']} - {_o.get('effective_percentage', _o.get('effective_pct', 0))}%"
                                + (" (UBO)" if _o.get('is_ubo') else "")
                                for _i, _o in enumerate(expanded_owners, 1)
                            ])
                            transition_message = localized(None,
                                en=f"Corporate ownership analysis is complete. Emirates ID or Passport verification is now required for all beneficial owners:\n\n{member_list_fb}\n\nPlease begin by uploading the Emirates ID or Passport for: {first_member}",
                                es=f"El análisis de la propiedad corporativa está completo. Ahora se requiere verificar el Emirates ID o pasaporte de todos los beneficiarios finales:\n\n{member_list_fb}\n\nComience cargando el Emirates ID o pasaporte de: {first_member}",
                                ar=f"اكتمل تحليل الملكية الاعتبارية. يلزم الآن التحقق من الهوية الإماراتية أو جواز السفر لجميع المستفيدين الفعليين:\n\n{member_list_fb}\n\nيُرجى البدء بتحميل الهوية الإماراتية أو جواز السفر لـ: {first_member}")

                        # Log
                        try:
                            insert_conversation_log(
                                user_email=email,
                                role="agent",
                                message=transition_message,
                                channel="chat",
                                metadata={
                                    "message_type": "type2_stage_transition",
                                    "from_stage": STAGE_CORPORATE_SHAREHOLDER_DOCS,
                                    "to_stage": STAGE_MEMBER_EIDS,
                                    "ubo_names": ubo_names,
                                    "expanded_owners": expanded_owners,
                                    "language": language,
                                }
                            )
                        except Exception:
                            pass

                        # ── v4: FATCA fires from verify path (after member EIDs), NOT here ──
                        # Clean any stale FATCA/PEP from previous sessions
                        for _stale_path, _stale_label in [
                            (fatca_json_path(email), "fatca.json"),
                            (pep_json_path(email),   "pep.json"),
                        ]:
                            if _stale_path.exists():
                                _stale_path.unlink(missing_ok=True)
                                logger.info(f"[TYPE-2] Cleaned stale {_stale_label}")

                        return {
                            "response": transition_message,
                            "verification_accepted": True,
                            "is_complete": False,
                            "stage_transition": True,
                            "new_stage": STAGE_MEMBER_EIDS,
                            "members": all_member_names,
                            "ubo_names": ubo_names,
                            "current_member": first_member,
                            "language": language,
                            "was_translated": _detection["was_translated"],
                            "detected_language": _detection["detected_language"],
                            "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                            # ── v4: FATCA/PEP fires from verify path after all EIDs ──
                            "fatca_trigger": False,
                            "pep_trigger": False,
                            # ── v3: MOA AS card pre-populated from expanded members ──
                            "moa_as_trigger": True,
                            "moa_members": all_member_names,
                        }

                    else:
                        # More CoIs pending - request next one
                        remaining_coi = pending_coi[1:]  # remove the one just processed
                        save_member_progress(
                            email,
                            members=_progress.get("members", []),
                            current_index=_progress.get("current_index", 0),
                            pending_coi=remaining_coi,
                        )
                        next_corp = remaining_coi[0]
                        total_remaining = len(remaining_coi)

                        try:
                            coi_req_message = ai_message_gen.generate_coi_request_message(
                                corp_name=next_corp,
                                corp_index=len(pending_coi) - total_remaining + 1,
                                total_corps=_progress.get("total_corps", len(pending_coi)),
                                user=user,
                                language=language,
                            )
                        except Exception as _cr:
                            coi_req_message = localized(None,
                                en=f"The Certificate of Incorporation for the previous entity has been received. Please now upload the Certificate of Incorporation for: {next_corp}.",
                                es=f"Se ha recibido el Certificado de Constitución de la entidad anterior. Cargue ahora el Certificado de Constitución de: {next_corp}.",
                                ar=f"تم استلام شهادة التأسيس للكيان السابق. يُرجى الآن تحميل شهادة التأسيس لـ: {next_corp}.")

                        # Also trigger email notification for next CoI
                        try:
                            send_corporate_shareholder_request_email(
                                to_email=email,
                                corp_name=next_corp,
                                corp_index=len(pending_coi) - total_remaining + 1,
                                total_corps=len(pending_coi),
                            )
                        except Exception:
                            pass

                        try:
                            insert_conversation_log(
                                user_email=email,
                                role="agent",
                                message=coi_req_message,
                                channel="chat",
                                metadata={
                                    "message_type": "type2_coi_request",
                                    "next_corp": next_corp,
                                    "remaining_coi": remaining_coi,
                                    "language": language,
                                }
                            )
                        except Exception:
                            pass

                        return {
                            "response": coi_req_message,
                            "verification_accepted": True,
                            "is_complete": False,
                            "stage_transition": False,
                            "pending_coi": remaining_coi,
                            "language": language,
                            "was_translated": _detection["was_translated"],
                            "detected_language": _detection["detected_language"],
                            "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
                        }

                except Exception as _pe:
                    logger.error(f"corporate_shareholder_docs handler failed: {_pe}")
                    import traceback as _tb
                    logger.error(_tb.format_exc())

    # ============================================================================
    # STEP 2: For ANY other question, call LLM directly
    # ============================================================================
    logger.info(f"[CHAT] Regular question - calling LLM directly")

    account_type = user.get("account_type", "account")
    ownership_type = user.get("ownership_type", "")
    user_name = user.get("name", "User")

    status = get_onboarding_status(email, user, skip_welcome=True)
    pending_docs = status.get("pending_documents", [])
    next_doc = status.get("next_required_document")
    is_complete = status.get("is_complete", False)

    if is_complete:
        status_context = "All required documents have been submitted and are under review."
    elif pending_docs:
        status_context = f"Documents still needed: {', '.join(pending_docs)}"
    elif next_doc:
        next_type = next_doc.get("type", "document")
        member = next_doc.get("member_name")
        if member:
            status_context = f"Next document needed: Emirates ID or Passport for {member}"
        else:
            status_context = f"Next document needed: {next_type}"
    else:
        status_context = "Processing current documents"

    # Arabic-aware instruction reused from MessageGenerator (already imported
    # above) instead of a third hand-rolled English/Spanish-only conditional --
    # see docs/language-mirroring-verdict.html, Phase 0, item 3.
    language_instruction = MessageGenerator._build_language_instruction(language)

    chat_history_context = ""
    if request.chat_history and len(request.chat_history) > 0:
        recent_messages = request.chat_history[-5:]
        history_lines = []
        for msg in recent_messages:
            role = "User" if msg.role == "user" else "Assistant"
            history_lines.append(f"{role}: {msg.content[:100]}")
        chat_history_context = "\n".join(history_lines)

    # ============================================================================
    # BUILD PROMPT — request-specific half only; the persona, knowledge base,
    # account-requirements table, and instructions live in the cached
    # _CHAT_SYSTEM_PROMPT system message now (see its definition above the
    # router for why — prompt-remediation Phase 5).
    # ============================================================================
    prompt = f"""{language_instruction}

USER CONTEXT:
- Name: {user_name}
- Account Type: {account_type} {ownership_type if ownership_type else ""}
- Current Status: {status_context}

RECENT CONVERSATION:
{chat_history_context if chat_history_context else "No previous messages"}

USER'S QUESTION:
{request.message}

Generate your response:"""

    # ============================================================================
    # CALL LLM
    # ============================================================================
    try:
        logger.info(f"[LLM] Calling local LLM with task-specific system prompt...")
        answer = call_local_llm(prompt, system_prompt=_CHAT_SYSTEM_PROMPT, temperature=0.5)
        logger.info(f"[LLM] Response generated ({len(answer)} chars)")
        logger.info(f"[LLM] Preview: {answer[:150]}...")
    except Exception as e:
        logger.error(f"LLM error: {e}")
        import traceback
        logger.error(traceback.format_exc())

        try:
            # MessageGenerator is already imported at module level (top of
            # this file) -- this used to re-import it locally too, which in
            # Python makes the name local to the WHOLE chat_conversational()
            # function (not just this block), shadowing the module-level
            # import even for code earlier in the function. That broke the
            # Phase 0 STEP-2 fix above (`MessageGenerator._build_language_
            # instruction(language)`) with "cannot access local variable
            # 'MessageGenerator'" -- UnboundLocalError, since that line runs
            # before this local import statement does. Removed; nothing
            # else in this file relied on this import happening HERE.
            answer = MessageGenerator.friendly_error(
                error_type="Chat Error",
                context="LLM service temporarily unavailable",
                doc_type=None,
                language=language
            )
            logger.info(f"[SUCCESS] AI error response generated in {language.upper()}")
        except Exception as err:
            logger.warning(f"Error response generation failed: {err}")
            # BUGFIX: this last-resort fallback (both the LLM reply AND
            # MessageGenerator.friendly_error() failed) only had English and
            # Spanish variants — an Arabic-language chat that hit this path
            # silently showed English text instead. Same pattern as every
            # other language branch in this module; see normalize_language()
            # in app/utils/language.py for the source of truth on supported
            # values.
            answer = localized(language,
                en=("Sorry, I'm experiencing temporary technical difficulties. Please try again in a moment."),
                es=("Lo siento, estoy teniendo problemas técnicos temporales. Por favor, intenta nuevamente."),
                ar=("عذرًا، أواجه مشكلة تقنية مؤقتة. يرجى المحاولة مرة أخرى بعد قليل."))

    # ============================================================================
    # STEP 3: Log conversation
    # ============================================================================
    try:
        _user_log_metadata = {"language": language, "message_type": "general_question"}
        if _detection["was_translated"]:
            _user_log_metadata["detected_language"] = _detection["detected_language"]
            _user_log_metadata["original_message"] = original_message
        insert_conversation_log(
            user_email=email,
            role="user",
            message=request.message,
            channel="chat",
            metadata=_user_log_metadata
        )
        insert_conversation_log(
            user_email=email,
            role="agent",
            message=answer,
            channel="chat",
            metadata={"language": language, "message_type": "llm_response"}
        )
        logger.info(f"[SUCCESS] Conversation logged")
    except Exception as e:
        logger.warning(f"Could not log conversation: {e}")

    # ============================================================================
    # STEP 4: Return response
    # ============================================================================
    return {
        "response": answer,
        "verification_accepted": False,
        "is_complete": False,
        "language": language,
        "was_translated": _detection["was_translated"],
        "detected_language": _detection["detected_language"],
        "translated_message": _detection["translated_message"] if _detection["was_translated"] else None,
    }


@router.get("/conversation-logs/{email}")
async def get_conversation_logs(
    email: str,
    limit: int = 20,
    channel: str = "chat",
    exclude_welcome: bool = False,
    language: Optional[str] = None,
):
    """
    Get conversation history filtered by channel.

    `language`, when given, retroactively translates the returned messages
    into that language (Phase 2, docs/language-mirroring-verdict.html) —
    normalized the same way every other language input in this app is
    (normalize_language(), so LANGUAGE_TOGGLE_ENABLED is enforced here too:
    the toggle being off means this can't be used to pull non-English
    history either). Each row's translation is cached on first request in
    `metadata.translations.<language>`; a later request for the same
    conversation + language is then a plain DB read, not a new LLM call.
    Rows already stored in the requested language (`metadata.language ==
    language`) are returned as-is — no translation, no cache entry needed.
    Omit `language` (or leave it unset) for the original pre-Phase-2
    behaviour — logs come back exactly as stored.
    """
    try:
        # `"all"` is the sentinel this endpoint uses for "no channel filter";
        # the repository applies the channel link only when one is passed.
        # Newest-first, as before.
        response = ConversationRepository.list_for_channel(
            email,
            None if channel == "all" else channel,
            limit=limit,
            descending=True,
        )

        logs = response.data if response.data else []

        # ========================================================================
        # ✅ FILTER OUT INITIAL WELCOME MESSAGES IF REQUESTED
        # ========================================================================
        if exclude_welcome and logs:
            original_count = len(logs)

            logs = [
                log for log in logs
                if not (
                    log.get("metadata") and
                    log["metadata"].get("message_type") == "initial_welcome"
                )
            ]

            filtered_count = original_count - len(logs)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} initial welcome message(s)")

        # ========================================================================
        # PHASE 2: RETROACTIVE TRANSLATION ON ?language= (with per-row caching)
        # ========================================================================
        if language and logs:
            target_language = normalize_language(language)
            to_translate = []  # [{"id", "text", "source_language"}, ...]

            for log in logs:
                metadata = log.get("metadata") or {}
                # Keep the stored text next to whatever this request swaps into
                # `message`, so the frontend can run its (English-keyed)
                # parsing/section logic on a stable text regardless of the
                # display language (docs/multilingual-flow-approach.html, R1).
                log.setdefault("original_message", log.get("message"))
                source_language = metadata.get("language")

                # Deterministic catalog message (app/i18n): every language's
                # rendering was stored at write time — serve it directly, no
                # LLM call. Checked first so a toggle back to the original
                # language also returns the exact catalog text.
                stored_variant = (metadata.get("i18n") or {}).get(target_language)
                if stored_variant:
                    log["message"] = stored_variant
                    continue

                if source_language == target_language:
                    continue  # already in the requested language — leave as-is

                cached = (metadata.get("translations") or {}).get(target_language)
                if cached:
                    log["message"] = cached
                    continue

                if log.get("message"):
                    to_translate.append({
                        "id": log.get("id"),
                        "text": log["message"],
                        "source_language": source_language,
                    })

            if to_translate:
                translations = translate_stored_messages_batch(to_translate, target_language)
                logs_by_id = {log.get("id"): log for log in logs}

                for item in to_translate:
                    translated_text = translations.get(str(item["id"]))
                    if not translated_text:
                        continue  # fail open — this row keeps its original text

                    row = logs_by_id.get(item["id"])
                    if not row:
                        continue

                    row["message"] = translated_text

                    try:
                        updated_metadata = dict(row.get("metadata") or {})
                        cache = dict(updated_metadata.get("translations") or {})
                        cache[target_language] = translated_text
                        updated_metadata["translations"] = cache
                        ConversationRepository.update_metadata(item["id"], updated_metadata)
                        row["metadata"] = updated_metadata
                    except Exception as cache_err:
                        # This response still carries the translation even if
                        # caching it failed — worst case, the next request
                        # for this language re-translates this one row.
                        logger.warning(f"[LANGUAGE] Failed to cache translation for row {item['id']}: {cache_err}")

        return {
            "email": email,
            "channel": channel,
            "logs": logs,
            "count": len(logs)
        }
        
    except Exception as e:
        logger.error(f"get_conversation_logs error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Return empty result on error
        return {
            "email": email,
            "channel": channel,
            "logs": [],
            "count": 0
        }


@router.get("/resume-conversation/{user_email}")
async def resume_conversation(user_email: str):
    """
    Resume existing conversation by loading chat history with metadata
    """
    try:
        # Get user
        user = get_user_by_email(user_email)
        if not user:
            raise NotFoundError("User not found")
        
        logger.info(f"[RESUME] Loading conversation for: {user_email}")
        
        # Load conversation history
        result = ConversationRepository.list_chat_messages(user_email, limit=100)

        messages = []
        if result.data:
            logger.info(f"[RESUME] Found {len(result.data)} messages")
            
            for log in result.data:
                message = {
                    "role": "assistant" if log["role"] == "agent" else "user",
                    "message": log["message"],
                    "timestamp": log["timestamp"]
                }
                
                # ✅ Parse and include metadata
                if log.get("metadata"):
                    try:
                        metadata = log["metadata"] if isinstance(log["metadata"], dict) else json.loads(log["metadata"])
                        message["metadata"] = metadata
                        
                        # ✅ ADD: Log metadata type for debugging
                        if metadata.get("message_type"):
                            logger.info(f"[RESUME]   - Message type: {metadata['message_type']}")
                            
                    except Exception as e:
                        logger.warning(f"Failed to parse metadata: {e}")
                
                messages.append(message)
        else:
            logger.info(f"[RESUME] No messages found")
        
        logger.info(f"[SUCCESS] Loaded {len(messages)} messages for {user_email}")
        
        return {
            "success": True,
            "messages": messages,
            "user": user
        }
        
    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"resume_conversation error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError("Failed to load conversation")


@router.delete("/clear-welcome-message/{user_email}")
async def clear_welcome_message(user_email: str):
    """
    Delete old generic welcome messages from conversation history
    """
    try:
        # Get all messages for this user
        result = ConversationRepository.list_agent_chat_messages(user_email)

        if not result.data or len(result.data) == 0:
            return {
                "success": True,
                "message": "No messages found",
                "deleted_count": 0
            }
        
        # Find and delete generic welcome messages
        deleted_count = 0
        for msg in result.data[:3]:  # Only check first 3 messages
            content = msg.get("message", "")
            
            # Detect generic welcome messages
            is_generic_welcome = (
                "I'm your AI onboarding assistant" in content and
                "You can upload documents like:" in content and
                "• Emirates ID" in content and
                "• Commercial License" in content
            )
            
            if is_generic_welcome:
                # Delete this message
                ConversationRepository.delete_by_id(msg["id"])

                deleted_count += 1
                logger.info(f"[DELETE] Removed generic welcome message (ID: {msg['id']})")
        
        return {
            "success": True,
            "message": f"Cleared {deleted_count} old welcome message(s)",
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        logger.error(f"clear_welcome_message: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise DomainError(context=str(e))


@router.post("/validate-ref")
async def validate_ref(req: ValidateRefRequest):
    """
    Validate a reference number (REF-YYYY-XXXXXX) submitted from inside the
    AI Assistant chat, and return the full conversation history for hydration.

    Security: the reference_number must belong to the authenticated user's email.
    """
    result = validate_reference_number(req.reference_number)

    if not result.get("valid"):
        raise NotFoundError(result.get("reason", "Invalid reference number."))

    # Security check: ref must belong to this user
    if result.get("user_email", "").lower() != req.user_email.lower():
        raise PermissionError_("This reference number does not belong to your account.")

    email = result["user_email"]

    # Fetch full conversation history
    messages = []
    try:
        hist_res = ConversationRepository.list_chat_transcript(email, limit=100)
        messages = [
            {
                "role":      r.get("role"),
                "message":   r.get("message"),
                "timestamp": r.get("timestamp"),
                "metadata":  r.get("metadata") or {},
            }
            for r in (hist_res.data or [])
        ]
    except Exception as hist_err:
        logger.warning(f"[VALIDATE-REF] History fetch failed: {hist_err}")

    logger.info(f"[VALIDATE-REF] {req.reference_number} → {email} ({len(messages)} msgs)")

    return {
        "valid":            True,
        "reference_number": req.reference_number,
        "user_email":       email,
        "messages":         messages,
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "chatupload-conversational",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
