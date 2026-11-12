# backend/app/services/message_generator.py

"""
Professional Banking Message Generator
Pure LLM-based generation with NO fallback templates
All messages enforce professional banking standards

FIXED: Welcome messages now support emojis
FIXED: Welcome message uses the configured brand name (config.BRAND_NAME),
       no Upload Order section
FIXED: Last document message ends with 'Please type "okay" to continue.'
FIXED: MOA success message ends with 'Please type "okay" to continue.'
"""

from app.services.run_model import call_local_llm
from app.utils.language import normalize_language
import logging
from typing import Optional, Dict, List
import time
from app import config
from app.domain.onboarding.stage_table import (
    ACCOUNT_CORPORATE,
    OWNERSHIP_MULTIPLE,
    OWNERSHIP_PARTNERSHIP,
    OWNERSHIP_SINGLE,
)

logger = logging.getLogger(__name__)

# Import MessageMonitor if available
try:
    from app.services.message_monitor import MessageMonitor
except ImportError:
    class MessageMonitor:
        @staticmethod
        def log_generation(*args, **kwargs):
            pass

# ============================================================================
# CRITICAL: ONLY ONE HARDCODED MESSAGE IN ENTIRE SYSTEM
# ============================================================================
TECHNICAL_ERROR_MESSAGE = (
    "We are experiencing technical difficulties. Please try again in a moment "
    "or contact support if the issue persists."
)

# ============================================================================
# PROFESSIONAL BANKING CONTEXT - Prepended to ALL Prompts
# ============================================================================
PROFESSIONAL_BANKING_CONTEXT = f"""
CRITICAL SYSTEM IDENTITY:
You are an AI assistant for {config.BRAND_NAME}, a regulated financial institution in the UAE.

❌ ABSOLUTE PROHIBITIONS - NEVER INCLUDE:
1. GREETINGS AT START:
   - "Dear [Name]," or "Dear valued customer,"
   - "Hello [Name]," or "Hi [Name],"
   - "Greetings," or "Good morning/afternoon,"
   - Any personalized salutation format
   
2. SIGN-OFFS AT END:
   - "Kind regards," "Best regards," "Sincerely," "Regards,"
   - "Thank you," as a closing statement
   - "{config.BRAND_NAME}" as a signature
   - "The Team," "Support Team," "The {config.BRAND_NAME} Team"
   - Any formal letter-style closing

3. CASUAL/CELEBRATORY LANGUAGE:
   - No Emojis of any kind (🎉, ✅, ❌, 💪, 😊, 👋, 📋, etc.) 
   - Celebratory expressions ("Great!", "Awesome!", "Congrats!", "Yay!", "Perfect!")
   - Casual greetings ("Hey!", "Hi there!", "What's up!")
   - Informal expressions ("Oops!", "No worries!", "Hang tight!", "Let's go!")
   - Excessive exclamation marks (use sparingly, only for genuine urgency)

REQUIRED MESSAGE FORMAT:
- START IMMEDIATELY with the core message content
- END when the information is complete
- NO greeting line before content
- NO sign-off line after content
- Use "you" or "your" to address customer naturally within the message body
- Professional, direct, and action-oriented

MANDATORY COMMUNICATION STANDARDS:
1. Professional, formal business tone at all times
2. Clear, direct language - avoid casual expressions
3. Sound like a professional bank representative
4. Calm, measured, reassuring tone
5. Clear action items when applicable
6. Precise, unambiguous language
7. Regulatory compliance mindset
8. Respectful and courteous without being casual

STRUCTURE GUIDELINES:
- Lead with key information or status
- Provide clear next actions when applicable
- Use "we" for institutional voice, "you" for user actions
- Be concise but complete
- Use natural paragraphs, not bullet points unless specifically requested
- Never structure message like a formal letter

❌ WRONG FORMAT (FORMAL LETTER STYLE - NEVER DO THIS):
"Dear Varsha Balaji,

Your Emirates ID has been received and validated successfully. Document details are currently being processed.

Kind regards,
{config.BRAND_NAME}"

CORRECT FORMAT (DIRECT CONTENT ONLY):
"Your Emirates ID has been received and validated successfully. Document details are currently being processed. Next, please upload your Commercial License."

❌ WRONG FORMAT (WITH SIGN-OFF):
"We were unable to verify your document due to security concerns. Our system detected potential modifications. Please upload an original document.

Best regards,
The Team"

CORRECT FORMAT (NO SIGN-OFF):
"We were unable to verify your document due to security verification findings. Our forensic analysis detected unusual compression patterns and metadata inconsistencies. Please upload an original, unmodified document."

ACCEPTABLE LANGUAGE EXAMPLES:
✓ "Your document has been successfully verified."
✓ "The verification process is complete. Please proceed with the next step."
✓ "We have received your Emirates ID / Passport submission."
✓ "Your account setup requires the following documents: [list]."
✓ "The document could not be validated. Please ensure all information is clearly visible."
✓ "Your onboarding requires three documents: Emirates ID or Passport, Commercial License, and Ejari Contract. Please upload your Emirates ID or Passport to begin."

UNACCEPTABLE LANGUAGE EXAMPLES:
✗ "Dear [Name]," (NO formal greetings)
✗ "Kind regards," (NO sign-offs)
✗ "{config.BRAND_NAME}" (NO signature at end)
✗ "Great job! 🎉" (NO celebration/emojis - except welcome messages)
✗ "Awesome progress!" (NO casual enthusiasm)
✗ "Oops! Something went wrong." (NO informal expressions)
✗ "Let's get started!" (NO casual prompts)
✗ "Perfect! You're doing amazing!" (NO encouragement language)
✗ "Hey there! Welcome aboard!" (NO casual greetings)

MESSAGE STRUCTURE REMINDER:
- First sentence: Key information or status
- Middle sentences: Details, context, or technical information
- Last sentence: Next action or what to expect
- NO greeting before
- NO sign-off after

Now generate the requested message following ALL above requirements. Start directly with the message content:
"""


class MessageGenerator:
    """
    Professional Banking Message Generator
    Pure LLM-based - NO fallback templates
    """
    
    # Configurable via MESSAGE_GEN_MAX_RETRIES in .env.docker — change +
    # restart the container to raise/lower without editing code. Lowered
    # default from 3 to 2: each retry is a full fresh LLM round trip (up to
    # DEFAULT_LLM_TIMEOUT_SECONDS x2 models), so this directly caps worst-case
    # latency for every AI-generated message (welcome message no longer uses
    # this path at all — see generate_welcome_message).
    MAX_RETRIES = config.MESSAGE_GEN_MAX_RETRIES
    MIN_RESPONSE_LENGTH = 30
    
    # ========================================================================
    # CORE: Retry Logic for ALL Message Generation
    # ========================================================================
    
    @staticmethod
    def _generate_with_retry(prompt: str, message_type: str) -> str:
        """
        Core retry logic with smart pattern detection.
        Includes post-generation brand-name correction to guarantee the
        single configured brand (config.BRAND_NAME).
        """
        import re as _re

        # ARCHITECTURE FIX (prompt-remediation Phase 2): PROFESSIONAL_BANKING_
        # CONTEXT used to be textually prepended into the USER turn on every
        # single call here (full_prompt = f"{PROFESSIONAL_BANKING_CONTEXT}\n\n
        # {prompt}"). Some callers (document_messaging.py) ALSO prepended it
        # themselves into the `prompt` they pass in, so those calls sent it
        # TWICE per request -- once from the caller, once from here. It now
        # goes through the model's actual system role exactly once, at a
        # lower temperature (0.3, down from the shared 0.7 default) that
        # suits these heavily format-locked, often verbatim-phrase-required
        # outputs better than a temperature tuned for open-ended chat.
        for attempt in range(1, MessageGenerator.MAX_RETRIES + 1):
            try:
                logger.info(f"[{message_type}] Attempt {attempt}/{MessageGenerator.MAX_RETRIES}")
                
                # Call LLM
                response = call_local_llm(prompt, system_prompt=PROFESSIONAL_BANKING_CONTEXT, temperature=0.3)
                
                if not response:
                    logger.warning(f"[{message_type}] Attempt {attempt}: Empty response")
                    if attempt < MessageGenerator.MAX_RETRIES:
                        time.sleep(1)
                        continue
                    else:
                        break
                
                response = response.strip()
                original_response = response

                # ============================================================
                # FIX #1 (brand safety): the model has, at various points in
                # this codebase's history, seen "Thrivv", "DigiOB", and
                # "MyBank" all used as the assistant's name in different
                # prompts, so any of them can leak into a completion as a
                # hallucinated brand name. Replace every wrong-brand variant
                # with the single configured identity (config.BRAND_NAME)
                # before further validation, rather than hardcoding one
                # literal target -- this stays correct whichever name a
                # deployment configures.
                # ============================================================
                _wrong_brand_names = {"Thrivv", "DigiOB", "MyBank"}
                _wrong_brand_names.discard(config.BRAND_NAME)
                if _wrong_brand_names:
                    _wrong_brand_pattern = _re.compile(
                        r'\b(?:' + '|'.join(_re.escape(n) for n in _wrong_brand_names)
                        + r')(?:\.ai|\.com|[- ]?[Bb]ank)?\b'
                    )
                    response = _wrong_brand_pattern.sub(config.BRAND_NAME, response)

                # CLEAN OUTPUT - Remove greetings/sign-offs
                response = MessageGenerator._validate_and_clean_output(response)
                
                if response != original_response:
                    logger.warning(f"[{message_type}] Cleaned greeting/sign-off or brand name from output")
                
                # Validate length AFTER cleaning
                if len(response) < MessageGenerator.MIN_RESPONSE_LENGTH:
                    logger.warning(f"[{message_type}] Attempt {attempt}: Response too short after cleaning ({len(response)} chars)")
                    if attempt < MessageGenerator.MAX_RETRIES:
                        time.sleep(1)
                        continue
                    else:
                        break
                
                # ============================================================
                # SMART FORBIDDEN PATTERN DETECTION
                # ============================================================
                violations = MessageGenerator._check_format_violations(response, message_type)
                
                if violations:
                    logger.warning(f"[{message_type}] Attempt {attempt}: Format violations detected")
                    for violation in violations:
                        logger.warning(f"[{message_type}] Violation: {violation}")
                    
                    if attempt < MessageGenerator.MAX_RETRIES:
                        time.sleep(1)
                        continue
                    else:
                        logger.critical(f"[{message_type}] Violations persist after all retries")
                        break
                
                # SUCCESS
                logger.info(f"[{message_type}] Successfully generated and validated ({len(response)} chars)")
                
                MessageMonitor.log_generation(
                    message_type=message_type.lower(),
                    success=True,
                    duration_ms=0,
                    fallback_used=False
                )
                
                return response
                
            except Exception as e:
                logger.error(f"[{message_type}] Attempt {attempt} failed: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                if attempt < MessageGenerator.MAX_RETRIES:
                    time.sleep(1)
                    continue
        
        # ALL retries exhausted
        logger.critical(f"[ALERT] Message generation failed after {MessageGenerator.MAX_RETRIES} attempts: {message_type}")
        
        MessageMonitor.log_generation(
            message_type=message_type.lower(),
            success=False,
            duration_ms=0,
            fallback_used=False
        )
        
        return TECHNICAL_ERROR_MESSAGE


    @staticmethod
    def _check_format_violations(text: str, message_type: str = "") -> list:
        """
        Check for specific format violations.
        SMART detection - only flags actual violations, not natural mentions.

        Allows emojis for WELCOME_MESSAGE type.
        """
        import re
        
        violations = []
        
        # 1. CHECK FOR GREETINGS AT START
        # Localized (Phase 5, multilingual rollout): the English-only check
        # below never caught Spanish/Arabic greetings, so Spanish output has
        # been shipping without this guardrail — extended alongside Arabic
        # support rather than left as an English-only safety net.
        if re.match(r'^\s*(Dear|Hello|Hi|Greetings|Estimad[oa]|Apreciad[oa]|Hola)', text, re.IGNORECASE):
            violations.append("Contains greeting at start")
        if re.match(r'^\s*(عزيزي|عزيزتي|مرحبا|السلام عليكم|أهلا)', text):
            violations.append("Contains greeting at start (Arabic)")
        
        # 2. CHECK FOR SIGN-OFFS AT END
        lines = text.split('\n')
        last_lines = '\n'.join(lines[-3:]) if len(lines) >= 3 else text
        
        sign_off_patterns = [
            r'Kind regards',
            r'Best regards', 
            r'Sincerely',
            r'Regards',
            r'Thank you\s*$',
            # Spanish / Arabic equivalents — see the greeting note above.
            r'Atentamente',
            r'Saludos cordiales',
            r'Cordialmente',
            r'Gracias\s*$',
            r'مع تحياتنا',
            r'تحياتنا',
            r'مع خالص التحية',
            r'شكرا\s*$',
        ]
        
        for pattern in sign_off_patterns:
            if re.search(pattern, last_lines, re.IGNORECASE):
                violations.append(f"Contains sign-off: '{pattern}'")
        
        # 3. CHECK FOR SIGNATURE AT END
        last_two_lines = '\n'.join(lines[-2:]) if len(lines) >= 2 else text
        
        _brand_escaped = re.escape(config.BRAND_NAME)
        if re.search(rf'\n\s*{_brand_escaped}\s+Bank\s*$', last_two_lines, re.IGNORECASE):
            violations.append(f"Contains '{config.BRAND_NAME}' as signature")
        
        if re.search(r'\n\s*(The\s+Team|Support\s+Team)\s*$', last_two_lines, re.IGNORECASE):
            violations.append("Contains team signature")
        
        # 4. CHECK FOR EMOJIS — skip for WELCOME_MESSAGE
        if message_type != "WELCOME_MESSAGE":
            emoji_pattern = re.compile("["
                u"\U0001F600-\U0001F64F"
                u"\U0001F300-\U0001F5FF"
                u"\U0001F680-\U0001F6FF"
                u"\U0001F1E0-\U0001F1FF"
                u"\U00002702-\U000027B0"
                u"\U000024C2-\U0001F251"
                "]+", flags=re.UNICODE)
            
            if emoji_pattern.search(text):
                violations.append("Contains emojis")
        
        # 5. CHECK FOR CASUAL LANGUAGE
        casual_patterns = [
            'Awesome!', 'Great job!', 'Yay!', 'Perfect!', 'Amazing!',
            'Congrats!', 'Woohoo!', 'No worries', 'Hang tight'
        ]
        
        for pattern in casual_patterns:
            if pattern.lower() in text.lower():
                violations.append(f"Contains casual language: '{pattern}'")
                break
        
        return violations

    @staticmethod
    def _validate_and_clean_output(text: str) -> str:
        """
        Validate and clean LLM output - Remove greetings and sign-offs.
        Safety net to catch violations that slipped through the prompt.
        """
        import re
        
        original_length = len(text)
        text = text.strip()
        
        # Remove greetings from start
        greeting_patterns = [
            r'^Dear\s+[^,\n]+,?\s*\n*',
            r'^Hello\s+[^,\n]+,?\s*\n*',
            r'^Hi\s+[^,\n]+,?\s*\n*',
            r'^Greetings,?\s*\n*',
            r'^Good\s+(morning|afternoon|evening)\s+[^,\n]*,?\s*\n*',
            # Spanish / Arabic equivalents (Phase 5, multilingual rollout).
            r'^Estimad[oa]\s+[^,\n]+,?\s*\n*',
            r'^Hola\s+[^,\n]*,?\s*\n*',
            r'^(عزيزي|عزيزتي)\s+[^,\n]+,?\s*\n*',
            r'^(مرحبا|السلام عليكم|أهلا)\s*[^,\n]*,?\s*\n*',
        ]
        
        for pattern in greeting_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove sign-offs from end
        _brand_escaped = re.escape(config.BRAND_NAME)
        sign_off_patterns = [
            r'\n+\s*Kind regards,?\s*$',
            r'\n+\s*Best regards,?\s*$',
            r'\n+\s*Sincerely,?\s*$',
            r'\n+\s*Regards,?\s*$',
            r'\n+\s*Thank you,?\s*$',
            r'\n+\s*Thanks,?\s*$',
            rf'\n+\s*{_brand_escaped}\s*$',
            r'\n+\s*The Team\s*$',
            r'\n+\s*Support Team\s*$',
            rf'\n+\s*The {_brand_escaped} Team\s*$',
            rf'\n+\s*Kind regards,?\s*\n+\s*{_brand_escaped}\s*$',
            rf'\n+\s*Best regards,?\s*\n+\s*{_brand_escaped}\s*$',
            # Spanish / Arabic equivalents (Phase 5, multilingual rollout).
            r'\n+\s*Atentamente,?\s*$',
            r'\n+\s*Saludos cordiales,?\s*$',
            r'\n+\s*Cordialmente,?\s*$',
            r'\n+\s*Gracias,?\s*$',
            r'\n+\s*مع تحياتنا\s*$',
            r'\n+\s*تحياتنا\s*$',
            r'\n+\s*مع خالص التحية\s*$',
            r'\n+\s*شكرا\s*$',
        ]
        
        for pattern in sign_off_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove excessive blank lines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = text.strip()
        
        if len(text) != original_length:
            cleaned_chars = original_length - len(text)
            logger.info(f"[CLEANING] Removed {cleaned_chars} chars (greetings/sign-offs)")
        
        return text
        
    # ========================================================================
    # LANGUAGE INSTRUCTION BUILDER
    # ========================================================================
    
    @staticmethod
    def _build_language_instruction(language: str) -> str:
        lang_display = {
            "english": "English",
            "spanish": "Spanish (Español)",
            "arabic": "Arabic (العربية)"
        }
        
        target_lang = lang_display.get(language.lower(), "English")
        
        example_responses = {
            "english": "Your document has been successfully verified. Please proceed with uploading the next required document.",
            "spanish": "Su documento ha sido verificado exitosamente. Por favor, proceda con la carga del siguiente documento requerido.",
            "arabic": "تم التحقق من مستندك بنجاح. يُرجى المتابعة لتحميل المستند المطلوب التالي."
        }
        
        example = example_responses.get(language.lower(), example_responses["english"])
        
        return f"""CRITICAL LANGUAGE REQUIREMENT:
You MUST respond ONLY in {target_lang}.
- Do NOT use any other language
- Do NOT mix languages
- Even if context mentions another language, respond ONLY in {target_lang}
- This requirement is ABSOLUTE

Example of CORRECT {target_lang} response:
"{example}"

Your response must be in {target_lang} ONLY.
"""
    
    # ========================================================================
    # 1. WELCOME MESSAGE
    # ========================================================================
    # FIX #1:
    #   - Removed "Upload Order" section and numbered emoji steps from prompt
    #   - Hardened "Welcome to MyBank!" instruction so LLM cannot substitute
    #     any other brand name (e.g. "Thrivv")
    #   - Brand-name regex replacement also runs in _generate_with_retry as an
    #     additional safety layer
    # ========================================================================

    @staticmethod
    def generate_welcome_message(user_data: dict, language: str = "english") -> str:
        """
        Build the welcome message for a new user.

        CHANGED: No longer calls the LLM. The old prompt (still visible in
        the comment block below for reference) locked down the exact greeting
        line, exact document bullets, and exact boilerplate lines — every
        piece of content was already deterministic Python before it was ever
        sent to the model. The LLM's only job was to re-assemble already-fixed
        strings into a fixed structure, which is exactly why the format-
        violation retry logic existed: the model routinely drifted from the
        rigid template it was being asked to reproduce verbatim.
        That meant every first-time user's very first message required a
        10-60+ second OpenRouter round trip (worse if a retry or a model
        fallback kicked in), for zero actual generative value. This function
        now builds the exact same output directly — instant, no network call,
        no chance of format drift. (This is the same text that used to live
        only in the except-block fallback in chatupload.py's start_conversation
        — that fallback still exists as a safety net but should now be dead
        code in normal operation.)

        Args:
            user_data: User information dictionary
            language: "english" or "spanish"

        Returns:
            str: Welcome message (instant, deterministic)
        """
        language = normalize_language(language)

        raw_name = user_data.get("name", "").strip()
        account_type = user_data.get("account_type", "")

        # All three renderings are built and returned as one LocalizedStr
        # (app/i18n), so a later language switch swaps the welcome from the
        # stored variants instead of an LLM translation.
        #
        # Ownership type (Single Owner vs Partnership/Multiple Owners) is no
        # longer asked upfront — it is inferred from the Commercial License
        # once uploaded — so the welcome can't branch on it.
        from app.i18n import localized
        name_en = raw_name or "there"
        name_es = raw_name or "estimado cliente"
        name_ar = raw_name or "عميلنا الكريم"

        if account_type == ACCOUNT_CORPORATE:
            return localized(
                language,
                en=(f"Good to have you here, {name_en}.\n\n"
                    "Let's get your account set up. I'll guide you through it end to end — first up, "
                    "I'll need your Commercial License to verify your business and pull the next steps for you."),
                es=(f"Un gusto tenerte aquí, {name_es}.\n\n"
                    "Vamos a configurar tu cuenta. Te guiaré de principio a fin — para empezar, necesitaré "
                    "tu Licencia Comercial para verificar tu negocio y definir los próximos pasos."),
                ar=(f"يسعدنا وجودك معنا، {name_ar}.\n\n"
                    "سنقوم الآن بإعداد حسابك. سأرافقك خطوة بخطوة حتى الانتهاء — وسنبدأ بالحصول على "
                    "رخصتك التجارية للتحقق من نشاطك التجاري وتحديد الخطوات التالية."),
            )
        return localized(
            language,
            en=f"Welcome {name_en}! 👋\n\nI'm here to help you with your {account_type} account onboarding. Let's get started!",
            es=f"¡Bienvenido {name_es}! 👋\n\nEstoy aquí para ayudarte con la incorporación de tu cuenta {account_type}. ¡Comencemos!",
            ar=f"مرحباً بك {name_ar}! 👋\n\nأنا هنا لمساعدتك في إكمال إجراءات فتح حساب {account_type} الخاص بك. لنبدأ!",
        )

    # ────────────────────────────────────────────────────────────────────────
    # Former LLM-based implementation, kept for reference only — not called.
    # If the templated version above ever needs to go back to being AI-
    # generated (e.g. to reintroduce more varied phrasing), the prompt below
    # is the starting point. See the docstring above for why this was retired.
    # ────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _generate_welcome_message_via_llm_DEPRECATED(user_data: dict, language: str = "english") -> str:
        language = normalize_language(language)

        raw_name = user_data.get("name", "").strip()
        # Build personalised greeting: use name if available, else plain "Welcome!"
        if raw_name:
            greeting_line = f"Welcome, {raw_name}!"
        else:
            greeting_line = "Welcome!"
        name = raw_name or "valued customer"

        account_type = user_data.get("account_type", "")
        ownership_type = user_data.get("ownership_type", "")

        if account_type == "Savings":
            doc_list = ["Emirates ID (EID) or Passport", "Ejari (Tenancy Contract)"]
            upload_order = "Please start by uploading your Emirates ID (EID) or Passport first."
        elif account_type == ACCOUNT_CORPORATE and ownership_type == OWNERSHIP_SINGLE:
            # New flow: Commercial → Ejari → EID/Passport (role card) → KI loop → FATCA
            doc_list = ["Commercial License", "Ejari (Tenancy Contract)", "Emirates ID (EID) or Passport"]
            upload_order = "Please start by uploading your Commercial License first."
        elif account_type == ACCOUNT_CORPORATE and ownership_type in [OWNERSHIP_PARTNERSHIP, OWNERSHIP_MULTIPLE]:
            doc_list = ["Commercial License", "Ejari (Address Proof)", "Memorandum of Association (MOA)", "Emirates ID or Passport for all partners"]
            upload_order = "Please start by uploading the Commercial License first."
        else:
            doc_list = ["required documents"]
            upload_order = "Please upload your documents to begin."

        doc_bullets = "\n".join([f"• {d}" for d in doc_list])
        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Generate a concise, friendly welcome message for a banking customer beginning
document verification at MyBank.

CRITICAL BRAND RULE: The bank is called "MyBank". NEVER use any other name such as
"Thrivv", "Thrivv.ai", or any variation. Use "MyBank" exclusively.

USER INFORMATION:
- Name: {name}
- Account Type: {account_type} {f'({ownership_type})' if ownership_type else ''}
- Required Documents:
{doc_bullets}

MESSAGE REQUIREMENTS:
1. MUST start with EXACTLY this personalised greeting (copy verbatim): "{greeting_line}"
2. Write exactly: "Please upload the following documents:"
3. List required documents using bullet points (•) under the heading
   "Required Documents:"
4. MUST include the exact line: " Accepted Formats: PDF, JPG, PNG"
5. Include: "You can upload documents here in the chat or via the Document Upload
   page from the menu."
6. Action-oriented closing with the first step: "{upload_order} "
7. Final line: "Need help? Just ask!"
8. Tone: Friendly, clear, professional but approachable

CRITICAL FORMATTING RULES:
- Use bullet points (•) for the Required Documents list ONLY
- DO NOT add a separate "Upload Order" section with numbered steps (1️⃣ 2️⃣ 3️⃣)
- The first word of the message MUST be "Welcome" — starting with "{greeting_line}"
- NEVER write "Welcome to MyBank!" as a generic greeting — use the personalised greeting above
- NEVER write "Welcome to Thrivv!" or any name other than "MyBank"
- DO NOT use formal letter greetings or sign-offs

CORRECT EXAMPLE (Corporate Single Owner, name = "Ahmed Al Rashid"):
"Welcome, Ahmed Al Rashid!

Please upload the following documents:

Required Documents:
• Commercial License
• Ejari (Tenancy Contract)
• Emirates ID (EID) or Passport

 Accepted Formats: PDF, JPG, PNG

You can upload documents here in the chat or via the Document Upload page from the menu.

Please start by uploading your Commercial License first.

Need help? Just ask!"

Generate the welcome message following this exact structure:"""

        return MessageGenerator._generate_with_retry(prompt, "WELCOME_MESSAGE")
    
    # ========================================================================
    # 2. REGISTRATION WELCOME (FOR SIGNUP ENDPOINT)
    # ========================================================================
    
    @staticmethod
    def registration_welcome(user_name: str, account_type: str) -> str:
        """
        Generate registration welcome message (used in /register/signup endpoint).
        """
        prompt = f"""TASK: Generate a brief registration confirmation message.

USER INFORMATION:
- Name: {user_name}

MESSAGE REQUIREMENTS:
1. Confirm registration is complete
2. Do NOT name or describe the account type/category anywhere in the message —
   refer only to "your account" or "your registration", never a category label
3. State that they should login to upload documents
4. Length: 2-3 sentences
5. Professional, welcoming tone

Generate the registration confirmation:"""

        return MessageGenerator._generate_with_retry(prompt, "REGISTRATION_WELCOME")
    
    # ========================================================================
    # 3. DOCUMENT SUCCESS MESSAGE
    # ========================================================================
    # FIX #2: Last-document prompt now requires the final sentence to be
    #            exactly: 'Please type "okay" to continue.'
    # FIX #3 & #4: MOA prompt now requires the final sentence to be
    #            exactly: 'Please type "okay" to continue.'
    # ========================================================================

    @staticmethod
    def generate_document_success_message(
        doc_type: str,
        user: dict,
        remaining_docs: List[str],
        member_name: Optional[str] = None,
        language: str = "english",
        pending_coi_names: Optional[List[str]] = None
    ) -> str:
        """
        Generate success message after document validation.

        FIXED #2: Last-document message ends with 'Please type Okay to continue.'
        FIXED #3 & #4: MOA success message ends with 'Please type Okay to continue.'

        Args:
            doc_type: Document type validated (eid, commercial, etc.)
            user: User data dictionary
            remaining_docs: List of remaining required documents
            member_name: Optional member name for partnership accounts
            language: "english" or "spanish"
            pending_coi_names: Optional list of corporate entity names pending CoI

        Returns:
            str: LLM-generated success message
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")
        member_context = f" for member {member_name}" if member_name else ""
        doc_type_norm = doc_type.lower().strip()

        language_instruction = MessageGenerator._build_language_instruction(language)

        # ====================================================================
        # SPECIAL CASE 1: MOA validated
        # FIX #3 & #4: Final sentence must be 'Please type Okay to continue.'
        # ====================================================================
        is_moa = doc_type_norm in ("moa", "memorandum", "memorandum of association")
        if is_moa and len(remaining_docs) == 0:
            prompt = f"""{language_instruction}

    TASK: Generate a professional acknowledgment after the Memorandum of Association (MOA)
    has been validated, informing the customer that the process is moving to the next stage
    of member verification.

    CONTEXT:
    - Customer: {name}
    - Document Validated: Memorandum of Association (MOA)
    - Status: Successfully validated and accepted
    - Next Step: Move to member verification stage — Emirates ID or Passport for all partners/owners
    will now be collected

    MESSAGE REQUIREMENTS:
    1. Confirm the MOA has been successfully validated and accepted
    2. Inform the customer that once they confirm/approve the submitted documents, the
    process will move to the member verification stage where Emirates ID or Passport for all
    partners will be required to proceed further
    3. DO NOT say "all required documents have been submitted" or imply the process is
    complete — there are still Emirates ID or Passport documents to collect
    4. The VERY LAST sentence MUST be copied verbatim:
    Please type Okay to continue.
    5. Length: 2-3 sentences, then the mandatory final line
    6. Tone: Professional, clear, progress-oriented

    EXACT REQUIRED OUTPUT FORMAT:
    Your Memorandum of Association has been successfully validated and accepted. Once you
    confirm the submitted documents, we will proceed to the member verification stage,
    where Emirates ID or Passport for all partners will be required. Please type Okay to continue.

    CRITICAL: The message MUST end with exactly — Please type Okay to continue.
    No surrounding quotes. No celebratory language. No emojis. Professional banking tone only.

    Generate the MOA success message:"""
            return MessageGenerator._generate_with_retry(prompt, "DOCUMENT_SUCCESS_MOA")

        # ====================================================================
        # SPECIAL CASE 2: Commercial doc with corporate shareholders detected
        # ====================================================================
        is_commercial = doc_type_norm in ("commercial", "trade_license", "commercial_license")
        if is_commercial and pending_coi_names:
            corp_list = ", ".join([f'"{n}"' for n in pending_coi_names])
            first_corp = f'"{pending_coi_names[0]}"'
            remaining_count = len(remaining_docs)
            progress_note = (
                f"{remaining_count} document(s) remain to complete the process."
                if remaining_count > 0
                else "Please proceed with uploading the Certificate of Incorporation."
            )
            prompt = f"""{language_instruction}

    TASK: Generate a professional acknowledgment after a Commercial License has been
    validated and corporate shareholders were identified, requesting the Certificate of
    Incorporation for the detected company.

    CONTEXT:
    - Customer: {name}
    - Document Validated: Commercial License
    - Status: Successfully validated and accepted
    - Corporate Entities Detected in Partners: {corp_list}
    - First CoI Required: {first_corp}
    - Remaining Documents After This: {remaining_count}

    MESSAGE REQUIREMENTS:
    1. Confirm the Commercial document has been successfully validated and accepted
    2. State that in the commercial document, a company was identified in the partners
    section: specifically name {first_corp}
    3. Explain that because {first_corp} is a registered corporate entity listed as a
    partner/shareholder, the Certificate of Incorporation (CoI) for that company must
    be submitted to verify its registration and identify the beneficial owners
    4. Ask the customer to upload the Certificate of Incorporation (CoI) for {first_corp}
    to proceed further
    5. State how many documents remain: {progress_note}
    6. Length: 3-4 sentences
    7. Tone: Professional, explanatory, compliance-focused

    CRITICAL: No surrounding quotes. No celebratory language. No emojis. Professional banking tone only.

    Generate the commercial + CoI request message:"""
            return MessageGenerator._generate_with_retry(prompt, "DOCUMENT_SUCCESS_COMMERCIAL_COI")

        # ====================================================================
        # SPECIAL CASE 3: Member EID / Passport upload (multiple-owner flow)
        # Never mention "X documents remain" — just say next member's doc is needed.
        # ====================================================================
        is_member_identity = (
            member_name and
            doc_type_norm in ("eid", "passport", "emirates_id", "emirates id", "identity")
        )
        if is_member_identity:
            if remaining_docs:
                # More members still to verify
                prompt = f"""{language_instruction}

    TASK: Generate a short professional acknowledgment after a member's identity document
    has been validated, asking for the next member's document.

    CONTEXT:
    - Member Verified: {member_name}
    - Document Type: {doc_type.upper()}
    - Status: Successfully validated and accepted
    - Next Step: Upload the next member's Emirates ID or Passport

    MESSAGE REQUIREMENTS:
    1. Confirm the document for {member_name} has been successfully validated and accepted
    2. Ask the customer to proceed with uploading the next required document: Emirates ID (EID)
    3. Do NOT mention how many documents remain or a count of pending items
    4. Do NOT say "Two documents remain" or any similar count phrase
    5. Length: 1-2 sentences only
    6. Tone: Warm but professional, concise

    EXACT REQUIRED FORMAT:
    {member_name}'s Emirates ID checks out — verified and accepted. When you're ready, go ahead and upload the next person's Emirates ID or Passport.

    CRITICAL: No document counts, no "X remain", no celebratory language. Warm, professional banking tone only.

    Generate the message:"""
            else:
                # Last member verified — direct the user to complete FATCA
                prompt = f"""{language_instruction}

    TASK: Generate a short professional acknowledgment after the last member's identity
    document has been validated, then direct the user to complete their FATCA Declaration.

    CONTEXT:
    - Member Verified: {member_name}
    - Document Type: {doc_type.upper()}
    - Status: Successfully validated and accepted
    - Next Step: All member identity documents have been submitted — FATCA Declaration required

    MESSAGE REQUIREMENTS:
    1. Confirm the document for {member_name} has been successfully validated and accepted
    2. Instruct the user to please complete their FATCA Declaration below
    3. Length: 1-2 sentences only
    4. Tone: Warm but professional, concise

    EXACT REQUIRED FORMAT:
    {member_name}'s {doc_type.upper()} is verified — that's everyone. Please complete your FATCA Declaration below to continue.

    CRITICAL: No celebratory language. No mention of "all documents". No extra sentences. Warm, professional banking tone only.

    Generate the message:"""
            return MessageGenerator._generate_with_retry(prompt, "DOCUMENT_SUCCESS_MEMBER_EID")

        # ====================================================================
        # STANDARD PATH
        # ====================================================================
        if remaining_docs:
            next_doc = remaining_docs[0]
            next_action = f"Next required document: {next_doc}"
            progress_status = f"{len(remaining_docs)} document(s) remaining"
        else:
            next_action = "All required documents have been submitted"
            progress_status = "Document submission complete"

        is_last_document = len(remaining_docs) == 0

        if is_last_document:
            # FIX #2: End with 'Please type Okay to continue.'
            prompt = f"""{language_instruction}

    TASK: Generate a professional acknowledgment for the FINAL document validation.

    CONTEXT:
    - Customer: {name}
    - Document Validated: {doc_type.upper()}{member_context}
    - Status: Successfully validated and accepted
    - Progress: ALL required documents have been submitted

    MESSAGE REQUIREMENTS:
    1. Confirm this document has been successfully verified
    2. State that ALL required documents have now been submitted
    3. DO NOT mention "next document" or "remaining documents"
    4. DO NOT say "final verification will proceed" or any variation of that phrase
    5. The VERY LAST sentence MUST be copied verbatim:
    Please type Okay to continue.
    6. Length: 2-3 sentences, then the mandatory final line
    7. Tone: Professional, conclusive - like completing a document checklist

    EXACT REQUIRED OUTPUT FORMAT:
    Your [DOCUMENT TYPE] has been successfully verified and accepted. All required
    documents have now been submitted. Please type Okay to continue.

    CRITICAL: The message MUST end with exactly — Please type Okay to continue.
    No surrounding quotes. No celebratory language. No emojis. Professional banking tone only.

    Generate the final acknowledgment message:"""

        else:
            prompt = f"""{language_instruction}

    TASK: Generate a professional acknowledgment for successful document validation.

    CONTEXT:
    - Customer: {name}
    - Document Validated: {doc_type.upper()}{member_context}
    - Status: Successfully validated and accepted
    - Progress: {progress_status}
    - Next Required: {next_action}

    MESSAGE REQUIREMENTS:
    1. Confirm document has been successfully verified
    2. State what document is needed next clearly
    3. Length: 2-3 sentences
    4. Tone: Professional, clear, efficient - like confirming a banking transaction
    5. Structure: Natural sentences, no lists

    CRITICAL: No surrounding quotes. No celebratory language. No emojis. Professional banking tone only.

    Generate the acknowledgment message:"""

        return MessageGenerator._generate_with_retry(prompt, "DOCUMENT_SUCCESS")

    @staticmethod
    def generate_stage_transition_message(
        user: dict,
        from_stage: str,
        to_stage: str,
        context_data: dict,
        language: str = "english"
    ) -> str:
        """Generate message for onboarding stage transition with UBO annotation"""
        language = normalize_language(language)

        name = user.get("name", "valued customer")
        members = context_data.get("members", [])
        current_member = context_data.get("current_member")
        ubo_names = context_data.get("ubo_names", [])

        member_list_text = "\n".join([
            f"  - {member} (UBO - Ultimate Beneficial Owner)"
            if member in ubo_names
            else f"  - {member}"
            for member in members
        ])

        ubo_summary = (
            f"UBOs (Ultimate Beneficial Owners): {', '.join(ubo_names)}"
            if ubo_names
            else "No UBOs identified"
        )

        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

    TASK: Generate a professional message for onboarding stage transition.

    CONTEXT:
    - Customer: {name}
    - Completed Stage: {from_stage}
    - New Stage: {to_stage}
    - Total Members Requiring Verification: {len(members)} partner(s)/manager(s)
    - {ubo_summary}
    - Members List (UBOs annotated):
    {member_list_text}
    - First Member to Process: {current_member}

    MESSAGE REQUIREMENTS:
    1. Acknowledge completion of the identification stage professionally
    2. Clearly explain that Emirates ID or Passport verification is now required for all listed partners/managers
    3. List ALL members using a numbered list - annotate UBO members with "(UBO)" next to their name
    5. Specify which member to start with (the first one)
    6. Length: 4-6 sentences plus the member list
    7. Tone: Professional, clear, instructional - like a bank processing officer

    CRITICAL: Professional banking tone, no celebratory language, no emojis.

    Generate the transition message:"""

        return MessageGenerator._generate_with_retry(prompt, "STAGE_TRANSITION")
    
    @staticmethod
    def generate_error_message(
        error_type: str,
        doc_type: str,
        user: dict,
        error_details: dict,
        language: str = "english"
    ) -> str:
        """Generate professional error message for document issues"""
        language = normalize_language(language)
        
        name = user.get("name", "valued customer")
        missing_fields = error_details.get("missing_fields", [])
        issues = error_details.get("issues", [])
        uploaded_type = error_details.get("uploaded_type", doc_type)
        
        if missing_fields:
            issue_description = f"Missing or unclear fields: {', '.join(missing_fields)}"
        elif issues:
            issue_description = f"Issues identified: {', '.join(issues)}"
        else:
            issue_description = "Document validation failed"
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional error message for document validation failure.

CONTEXT:
- Customer: {name}
- Document Type: {doc_type.upper()}
- Error Category: {error_type}
- Problem Details: {issue_description}
- Uploaded Document: {uploaded_type}

MESSAGE REQUIREMENTS:
1. State clearly what went wrong (use simple, non-technical terms)
2. Specify exactly what needs to be corrected
3. Provide actionable guidance
4. Length: 3-4 sentences
5. Tone: Professional, helpful, clear - like a bank compliance officer
6. Be direct but courteous - not accusatory

CRITICAL: Professional banking tone only. No casual expressions, no emojis.

Generate the error message:"""

        return MessageGenerator._generate_with_retry(prompt, "ERROR_MESSAGE")
    
    @staticmethod
    def generate_completion_message(user: dict, language: str = "english") -> str:
        """Generate completion message for successful onboarding"""
        language = normalize_language(language)
        
        name = user.get("name", "valued customer")
        account_type = user.get("account_type", "account")
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional completion message for successful account onboarding.

CONTEXT:
- Customer: {name}
- Account Type: {account_type}
- Status: All document verification complete
- Next Step: Customer will receive confirmation email
- Timeline: Account activation within 3-4 business days

MESSAGE REQUIREMENTS:
1. Confirm all documents have been verified successfully
2. State they will receive confirmation email shortly
3. Mention account activation timeline (3-4 business days)
4. Welcome them to {config.BRAND_NAME} professionally
5. Length: 4-5 sentences
6. Tone: Professional, positive, welcoming

CRITICAL: Professional banking tone. Positive but not overly celebratory. No emojis.

Generate the completion message:"""

        return MessageGenerator._generate_with_retry(prompt, "COMPLETION_MESSAGE")
    
    @staticmethod
    def cross_validation_failure(
        mismatches: list,
        user_name: str = None,
        language: str = "english"
    ) -> str:
        """Generate cross-validation failure message"""
        language = normalize_language(language)
        
        mismatch_list = "\n".join([f"  - {m}" for m in mismatches])
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional message about document information inconsistencies.

CONTEXT:
- Customer: {user_name or 'valued customer'}
- Issue: Cross-validation detected inconsistencies
- Inconsistencies:
{mismatch_list}

MESSAGE REQUIREMENTS:
1. State that information does not match across documents
2. List the specific inconsistencies
3. Explain this is a security requirement
4. Request review and re-upload
5. Length: 4-5 sentences
6. Tone: Professional, solution-oriented

CRITICAL: Professional banking tone. Helpful and solution-oriented. No emojis.

Generate the message:"""

        return MessageGenerator._generate_with_retry(prompt, "CROSS_VALIDATION_FAILURE")

    @staticmethod
    def cross_validation_success(
        user_name: str = None,
        language: str = "english"
    ) -> str:
        """Generate the cross-validation-passed / onboarding-complete message."""
        language = normalize_language(language)

        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Confirm that cross-validation passed — every document's details agree with each
other — and that onboarding is now complete.

CONTEXT:
- Customer: {user_name or 'valued customer'}
- Status: Cross-validation passed, all documents consistent, onboarding complete

MESSAGE REQUIREMENTS:
1. Confirm all submitted documents were checked against each other and are consistent
2. Confirm onboarding is now complete
3. Do NOT name or describe an account type/category anywhere in the message
4. Length: 2 sentences
5. Tone: Warm, professional, no emojis

Generate the message:"""

        return MessageGenerator._generate_with_retry(prompt, "CROSS_VALIDATION_SUCCESS")

    @staticmethod
    def progress_update(
        completed: int,
        total: int,
        current_member: str = None,
        language: str = "english"
    ) -> str:
        """Generate progress update for multi-member accounts"""
        language = normalize_language(language)
        
        percentage = int((completed / total) * 100) if total > 0 else 0
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional progress update message.

CONTEXT:
- Progress: {completed} of {total} member verifications complete ({percentage}%)
- Next Member: {current_member or 'next member'}

MESSAGE REQUIREMENTS:
1. State current progress clearly
2. Identify which member's documents are needed next
3. Length: 2-3 sentences
4. Tone: Professional, clear

CRITICAL: Professional banking tone. Factual progress update. No celebratory language, no emojis.

Generate the progress update:"""

        return MessageGenerator._generate_with_retry(prompt, "PROGRESS_UPDATE")
    
    @staticmethod
    def surepass_failure(
        error_message: str,
        user_name: str = None,
        language: str = "english"
    ) -> str:
        """Generate SurePass government verification failure message"""
        language = normalize_language(language)
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional message for government ID verification failure.

CONTEXT:
- Customer: {user_name or 'valued customer'}
- Issue: Government verification system could not confirm Emirates ID
- Error: {error_message}

MESSAGE REQUIREMENTS:
1. State the verification system could not confirm ID details
2. Explain this can occur due to discrepancies or technical issues
3. Request review and re-upload
4. Mention support is available
5. Length: 3-4 sentences
6. Tone: Professional, reassuring

CRITICAL: Professional banking tone. Reassuring but factual. No emojis.

Generate the message:"""

        return MessageGenerator._generate_with_retry(prompt, "SUREPASS_FAILURE")
    
    @staticmethod
    def friendly_error(
        error_type: str,
        context: str,
        doc_type: Optional[str] = None,
        language: str = "english"
    ) -> str:
        """Generate general error message"""
        language = normalize_language(language)
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional error message.

ERROR INFORMATION:
- Error Type: {error_type}
- Context: {context}
- Document Type: {doc_type or 'N/A'}

MESSAGE REQUIREMENTS:
1. Explain what went wrong in simple terms
2. Provide clear next steps
3. Length: 2-3 sentences
4. Tone: Professional, helpful

CRITICAL: Professional banking tone. No technical jargon. No emojis.

Generate the error message:"""

        return MessageGenerator._generate_with_retry(prompt, "FRIENDLY_ERROR")

    @staticmethod
    def verification_success(
        doc_type: str,
        next_doc: Optional[str] = None,
        is_last: bool = False,
        user_name: str = None,
        language: str = "english"
    ) -> str:
        """Generate verification success message"""
        language = normalize_language(language)

        # Map internal type names to human-readable display names
        _doc_display_names = {
            "identity": "Identity Document (Emirates ID or Passport)",
            "eid": "Emirates ID (EID)",
            "eid_or_passport": "Emirates ID or Passport",
            "commercial": "Commercial License",
            "ejari": "Ejari (Tenancy Contract)",
            "moa": "Memorandum of Association (MOA)",
            "certificate_of_incorporation": "Certificate of Incorporation (CoI)",
            "passport": "Passport",
        }
        if next_doc:
            next_doc = _doc_display_names.get(next_doc.lower().strip(), next_doc)

        # Check if next_doc is same as doc_type
        if next_doc and doc_type:
            if next_doc.lower().strip() == doc_type.lower().strip():
                logger.warning(f"next_doc '{next_doc}' same as doc_type '{doc_type}' - treating as final")
                is_last = True
                next_doc = None
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        if is_last:
            prompt = f"""{language_instruction}

TASK: Generate a professional message confirming final document verification.

CONTEXT:
- Last Document Verified: {doc_type.upper()}
- Status: All required documents verified

MESSAGE REQUIREMENTS:
1. Confirm this document is verified
2. State all document verification is complete
3. Length: 2-3 sentences
4. Tone: Professional, conclusive

CRITICAL: Professional banking tone. No celebratory language, no emojis.

Generate the message:"""
        else:
            prompt = f"""{language_instruction}

TASK: Generate a professional verification acknowledgment with next step.

CONTEXT:
- Document Verified: {doc_type.upper()}
- Next Document Needed: {next_doc or 'processing next step'}

MESSAGE REQUIREMENTS:
1. Confirm this document is verified
2. State what document is needed next
3. Length: 2 sentences
4. Tone: Professional, directive

CRITICAL: Professional banking tone. No celebratory language, no emojis.

Generate the message:"""

        return MessageGenerator._generate_with_retry(prompt, "VERIFICATION_SUCCESS")
    
    @staticmethod
    def generate_tampering_rejection_message(
        tampering_result,
        language: str = "english"
    ) -> str:
        """Generate REJECT message for tampered documents"""
        language = normalize_language(language)
        
        test_report_id = tampering_result.test_report_id
        overall_score = tampering_result.overall_tampering_score
        
        from app.services.document_messaging import _get_tampering_details_for_reasoning
        
        forensic_details = {}
        if test_report_id:
            try:
                forensic_details = _get_tampering_details_for_reasoning(test_report_id)
            except Exception as e:
                logger.warning(f"Could not fetch forensic details: {e}")
                forensic_details = {
                    "summary": "document did not pass security verification",
                    "failed_tests": [],
                    "technical_details": "Security verification checks failed"
                }
        
        summary = forensic_details.get("summary", "document failed security verification")
        failed_tests = forensic_details.get("failed_tests", [])
        confidence = forensic_details.get("confidence", "High")
        
        simplified_findings = []
        for test in failed_tests:
            if "jpeg" in test.lower() or "quantization" in test.lower():
                simplified_findings.append("compression irregularities")
            elif "ela" in test.lower() or "error level" in test.lower():
                simplified_findings.append("modification patterns")
            elif "metadata" in test.lower():
                simplified_findings.append("file property inconsistencies")
            elif "noise" in test.lower():
                simplified_findings.append("image quality inconsistencies")
            elif "copy" in test.lower() or "move" in test.lower():
                simplified_findings.append("duplicate region detection")
            else:
                simplified_findings.append("security verification issues")
        
        simplified_findings = list(set(simplified_findings))
        findings_text = ", ".join(simplified_findings[:3]) if simplified_findings else "security verification issues"
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional document rejection message due to security verification failure.

SECURITY VERIFICATION RESULTS:
- Overall Tampering Score: {overall_score:.1f}%
- Confidence Level: {confidence}
- Detection Summary: {summary}
- Key Findings: {findings_text}
- Number of Failed Tests: {len(failed_tests)}
- Reference ID: {test_report_id}

MESSAGE REQUIREMENTS:
1. State clearly the document failed security verification
2. Mention what was detected (simplified, non-technical)
3. Explain this is for security and regulatory compliance
4. Clear instruction to upload original document
5. End with: "Reference ID: {test_report_id}"

LENGTH: 4-5 sentences plus reference ID
TONE: Professional, security-focused, firm but respectful

CRITICAL: Professional banking tone. Simple explanations. No technical jargon. No celebratory language.

Generate the rejection message:"""

        return MessageGenerator._generate_with_retry(prompt, "TAMPERING_REJECTION")

    @staticmethod
    def generate_tampering_escalation_message(
        tampering_result,
        language: str = "english"
    ) -> str:
        """Generate ESCALATE message for documents requiring manual review"""
        language = normalize_language(language)
        
        test_report_id = tampering_result.test_report_id
        overall_score = tampering_result.overall_tampering_score
        
        from app.services.document_messaging import _get_tampering_details_for_reasoning
        
        forensic_details = {}
        if test_report_id:
            try:
                forensic_details = _get_tampering_details_for_reasoning(test_report_id)
            except Exception as e:
                logger.warning(f"Could not fetch forensic details: {e}")
                forensic_details = {
                    "summary": "document requires manual verification",
                    "failed_tests": [],
                    "technical_details": "Manual review required"
                }
        
        summary = forensic_details.get("summary", "document requires additional verification")
        escalated_tests = forensic_details.get("failed_tests", [])
        confidence = forensic_details.get("confidence", "Medium")
        
        simplified_findings = []
        for test in escalated_tests:
            if "jpeg" in test.lower() or "quantization" in test.lower():
                simplified_findings.append("compression patterns")
            elif "ela" in test.lower() or "error level" in test.lower():
                simplified_findings.append("image quality variations")
            elif "metadata" in test.lower():
                simplified_findings.append("file properties")
            elif "noise" in test.lower():
                simplified_findings.append("image characteristics")
            else:
                simplified_findings.append("verification checks")
        
        simplified_findings = list(set(simplified_findings))
        findings_text = ", ".join(simplified_findings[:2]) if simplified_findings else "certain verification checks"
        
        language_instruction = MessageGenerator._build_language_instruction(language)
        
        prompt = f"""{language_instruction}

TASK: Generate a professional message for document requiring manual security review.

SECURITY VERIFICATION RESULTS:
- Status: Manual Review Required
- Detection Summary: {summary}
- Key Findings: {findings_text}
- Number of Tests Requiring Review: {len(escalated_tests)}
- Reference ID: {test_report_id}

MESSAGE REQUIREMENTS:
1. State manual review is required
2. Explain why (simplified, non-alarming)
3. Reassure this is standard procedure
4. State timeline: 24-48 hours
5. End with: "Reference ID: {test_report_id}"

LENGTH: 4 sentences plus reference ID
TONE: Professional, reassuring, security-focused

CRITICAL: Professional banking tone. Reassuring but factual. No technical percentages. No celebratory language.

Generate the escalation message:"""

        return MessageGenerator._generate_with_retry(prompt, "TAMPERING_ESCALATION")


    # ========================================================================
    # TYPE-2: CORPORATE SHAREHOLDER DETECTED
    # ========================================================================

    @staticmethod
    def generate_corporate_shareholder_detected_message(
        corp_names: list,
        commercial_data: dict,
        user: dict,
        language: str = "english"
    ) -> str:
        """
        Generate alert message when corporate shareholders are detected on a
        Joint Ownership Commercial License.
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")
        corp_list_text = "\n".join([f"  - {c}" for c in corp_names])
        total_corps = len(corp_names)
        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Inform a bank customer that their Commercial License contains corporate shareholders
requiring additional documentation before the account opening can proceed.

CONTEXT:
- Customer: {name}
- Document: Commercial License (Joint Ownership)
- Corporate Entities Detected ({total_corps}):
{corp_list_text}

MESSAGE REQUIREMENTS:
1. Acknowledge that the Commercial License has been successfully received and reviewed
2. Explain that one or more shareholders are registered corporate entities (not natural persons)
3. State that UAE banking regulations require a Certificate of Incorporation for each corporate entity
4. Clarify this is a mandatory compliance step before proceeding
5. Do NOT ask the customer to upload anything yet - just inform them of the requirement
6. Length: 3-4 sentences
7. Tone: Professional, informative, compliance-oriented

CRITICAL: Professional banking tone, no celebratory language, no emojis.

Generate the corporate shareholder alert message:"""

        return MessageGenerator._generate_with_retry(prompt, "TYPE2_CORP_DETECTED")

    # ========================================================================
    # TYPE-2: CERTIFICATE OF INCORPORATION REQUEST
    # ========================================================================

    @staticmethod
    def generate_coi_request_message(
        corp_name: str,
        corp_index: int,
        total_corps: int,
        user: dict,
        language: str = "english"
    ) -> str:
        """
        Generate a message requesting the Certificate of Incorporation upload
        for a specific corporate shareholder.
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")
        progress_note = f"{corp_index} of {total_corps}" if total_corps > 1 else "1 of 1"
        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Request the upload of a Certificate of Incorporation for a corporate shareholder
as part of a Joint Ownership Commercial License verification process.

CONTEXT:
- Customer: {name}
- Corporate Entity Requiring CoI: {corp_name}
- Progress: Corporate entity {progress_note}
- Document Required: Certificate of Incorporation (CoI) - also known as a Company Registration Certificate
- Reason: The company name "{corp_name}" was identified as a shareholder in the Commercial License. Since this is a registered corporate entity (not a natural person), its Certificate of Incorporation must be verified to confirm ownership and identify the ultimate beneficial owners.

MESSAGE REQUIREMENTS:
1. Clearly state that the company name "{corp_name}" was found listed as a shareholder in the Commercial License
2. Explain WHY the Certificate of Incorporation is required: because "{corp_name}" is a corporate entity, its CoI must be submitted to verify its registration and identify the beneficial owners behind it
3. Specify the exact document needed: Certificate of Incorporation (CoI), also known as a Company Registration Certificate
4. If there are multiple corporate shareholders, note that this is entity {progress_note}
5. Ask the customer to upload the CoI for "{corp_name}" now
6. Length: 3-4 sentences
7. Tone: Professional, clear, explanatory — like a compliance officer explaining a regulatory requirement

CRITICAL: Professional banking tone, no celebratory language, no emojis.

Generate the CoI upload request message:"""

        return MessageGenerator._generate_with_retry(prompt, "TYPE2_COI_REQUEST")

    # ========================================================================
    # TYPE-2: CERTIFICATE OF INCORPORATION SUCCESS
    # ========================================================================

    @staticmethod
    def generate_coi_success_message(
        corp_name: str,
        coi_data: dict,
        remaining_corps: list,
        user: dict,
        language: str = "english"
    ) -> str:
        """
        Generate acknowledgment after a Certificate of Incorporation is
        successfully extracted and validated.
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")
        jurisdiction = coi_data.get("jurisdiction", "")
        company_type = coi_data.get("company_type", "")
        directors_count = len(coi_data.get("directors_and_shareholders", []))

        if remaining_corps:
            next_step = f"The next Certificate of Incorporation required is for: {remaining_corps[0]}"
        else:
            next_step = "All Certificates of Incorporation have now been collected. Ownership analysis will now proceed."

        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Acknowledge successful processing of a Certificate of Incorporation for a corporate
shareholder, and indicate the next step in the verification process.

CONTEXT:
- Customer: {name}
- Corporate Entity: {corp_name}
- Jurisdiction: {jurisdiction or "N/A"}
- Entity Type: {company_type or "N/A"}
- Directors/Shareholders Identified: {directors_count}
- Remaining CoIs Required: {len(remaining_corps)}
- Next Step: {next_step}

MESSAGE REQUIREMENTS:
1. Confirm the Certificate of Incorporation for {corp_name} has been received and processed
2. Briefly note the key details extracted (jurisdiction/entity type if available)
3. State the next step clearly (either request next CoI OR confirm all CoIs are collected)
4. Length: 2-3 sentences
5. Tone: Professional, efficient, progress-oriented

CRITICAL: Professional banking tone, no celebratory language, no emojis.

Generate the CoI success message:"""

        return MessageGenerator._generate_with_retry(prompt, "TYPE2_COI_SUCCESS")

    # ========================================================================
    # TYPE-2: OWNERSHIP EXPANSION SUMMARY
    # ========================================================================

    @staticmethod
    def generate_ownership_expansion_message(
        expanded_owners: list,
        ubo_names: list,
        user: dict,
        language: str = "english"
    ) -> str:
        """
        Generate a message presenting the expanded ownership structure and
        identified UBOs after all CoIs have been collected and analysed.
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")

        owner_lines = []
        for o in expanded_owners:
            pct = o.get("effective_pct", 0)
            source = o.get("source", "direct")
            ubo_tag = " [UBO]" if o.get("is_ubo") else ""
            owner_lines.append(f"  - {o.get('name', 'Unknown')}: {pct}% effective ownership (via {source}){ubo_tag}")
        owner_table = "\n".join(owner_lines)

        ubo_summary = (
            f"Identified UBOs: {', '.join(ubo_names)}"
            if ubo_names
            else "No UBOs identified (no individual holds more than 25% effective ownership)"
        )

        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Present a summary of the expanded ownership structure derived from the Commercial
License and Certificates of Incorporation, highlighting Ultimate Beneficial Owners (UBOs).

CONTEXT:
- Customer: {name}
- Total Beneficial Owners Identified: {len(expanded_owners)}
- Ownership Breakdown:
{owner_table}
- {ubo_summary}
- UBO Definition: An individual who ultimately owns or controls more than 25% of the company

MESSAGE REQUIREMENTS:
1. State that ownership analysis is complete
2. Explain that effective ownership has been calculated from the Commercial License and
   the Certificates of Incorporation (proportional expansion)
3. Name the UBOs and their effective ownership percentages (or state none if no UBOs)
4. Briefly define UBO for the customer in simple terms
5. Length: 3-5 sentences
6. Tone: Professional, analytical, compliance-focused

CRITICAL: Professional banking tone, no celebratory language, no emojis.

Generate the ownership expansion summary message:"""

        return MessageGenerator._generate_with_retry(prompt, "TYPE2_OWNERSHIP_EXPANSION")

    # ========================================================================
    # TYPE-2: STAGE TRANSITION TO MEMBER EIDs
    # ========================================================================

    @staticmethod
    def generate_type2_stage_transition_message(
        user: dict,
        expanded_owners: list,
        ubo_names: list,
        first_member: str,
        language: str = "english"
    ) -> str:
        """
        Generate the stage transition message from corporate_shareholder_docs
        to member_eids for a Type-2 (corporate shareholder expansion) flow.
        """
        language = normalize_language(language)

        name = user.get("name", "valued customer")

        member_lines = []
        for i, o in enumerate(expanded_owners, 1):
            ubo_tag = " (UBO - Ultimate Beneficial Owner)" if o.get("is_ubo") else ""
            pct = o.get("effective_percentage", o.get("effective_pct", 0))
            member_lines.append(f"  {i}. {o.get('name', 'Unknown')} - {pct}% effective ownership{ubo_tag}")
        member_list_text = "\n".join(member_lines)

        ubo_summary = (
            f"UBOs identified: {', '.join(ubo_names)}"
            if ubo_names
            else "No UBOs identified"
        )

        language_instruction = MessageGenerator._build_language_instruction(language)

        prompt = f"""{language_instruction}

TASK: Generate a professional stage transition message informing the customer that
ownership analysis is complete and Emirates ID or Passport verification is now required for all
identified beneficial owners.

CONTEXT:
- Customer: {name}
- Completed Stage: Corporate Shareholder Documentation
- New Stage: Emirates ID or Passport Verification for Beneficial Owners
- Total Individuals Requiring Emirates ID or Passport: {len(expanded_owners)}
- {ubo_summary}
- Beneficial Owners List:
{member_list_text}
- First Person to Verify: {first_member}

MESSAGE REQUIREMENTS:
1. Confirm that corporate ownership analysis is complete
2. Explain that Emirates ID or Passport verification is now required for all identified beneficial owners
3. List all individuals with their effective ownership percentages using a numbered list
4. Annotate UBO members with "(UBO)" next to their name
6. Specify which person's Emirates ID or Passport to upload first
7. Length: 5-7 sentences plus the numbered list
8. Tone: Professional, clear, instructional - like a bank compliance officer

CRITICAL: Professional banking tone, no celebratory language, no emojis.

Generate the stage transition message:"""

        return MessageGenerator._generate_with_retry(prompt, "TYPE2_STAGE_TRANSITION")

    # ========================================================================
    # v3 — FATCA MESSAGES
    # ========================================================================

    @staticmethod
    def fatca_question(language: str = "english") -> str:
        """Ask the user if they are subject to FATCA."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Generate a professional message asking if the customer is subject to FATCA.

MESSAGE REQUIREMENTS:
1. Ask clearly: "Are you subject to U.S. tax regulations as outlined by FATCA (Foreign Account Tax Compliance Act)?"
2. Briefly state that their answer will determine the next steps.
3. Length: 2 sentences maximum.
4. Tone: Professional, factual, regulatory.

Generate the FATCA question:"""
        return MessageGenerator._generate_with_retry(prompt, "FATCA_QUESTION")

    @staticmethod
    def fatca_not_applicable_confirmed(language: str = "english") -> str:
        """Confirm FATCA = Not Applicable and prompt next step."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm that FATCA has been recorded as Not Applicable and prompt next document.

MESSAGE REQUIREMENTS:
1. Confirm FATCA status is recorded as "Not Applicable".
2. Ask the customer to proceed with the next required document.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "FATCA_NOT_APPLICABLE")

    @staticmethod
    def fatca_submitted_confirmed(language: str = "english") -> str:
        """Confirm FATCA form has been saved and prompt next step."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm that FATCA details have been saved.

MESSAGE REQUIREMENTS:
1. Confirm FATCA details have been saved successfully.
2. Ask the customer to proceed with the remaining required documents.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "FATCA_SUBMITTED")

    @staticmethod
    def pep_not_applicable_confirmed(language: str = "english") -> str:
        """Confirm PEP = Not Applicable and prompt next step."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm that the PEP (Politically Exposed Person) declaration has been recorded as
Not Applicable and prompt the next step.

MESSAGE REQUIREMENTS:
1. Confirm PEP status is recorded as "Not Applicable".
2. Ask the customer to proceed with the next step.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "PEP_NOT_APPLICABLE")

    @staticmethod
    def pep_submitted_confirmed(language: str = "english") -> str:
        """Confirm PEP form has been saved and prompt next step."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm that the PEP (Politically Exposed Person) declaration has been saved.

MESSAGE REQUIREMENTS:
1. Confirm the PEP declaration has been saved successfully.
2. Ask the customer to proceed with the next step.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "PEP_SUBMITTED")

    # ========================================================================
    # v3 — KEY INDIVIDUAL MESSAGES
    # ========================================================================

    @staticmethod
    def ki_question(language: str = "english") -> str:
        """Ask if the user has Key Individuals / Authorised Signatories to declare."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Ask if the customer has any Key Individuals (Authorised Signatories) to declare.

MESSAGE REQUIREMENTS:
1. Ask: "Do you have any Key Individuals or Authorised Signatories to declare for this account?"
2. Brief clarification that these are individuals who will have signing authority.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the question:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_QUESTION")

    @staticmethod
    def ki_moa_as_prompt(member_names: list, language: str = "english") -> str:
        """Prompt for MOA member AS checkbox selection (Part A)."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        names_str = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(member_names))
        prompt = f"""{language_instruction}

TASK: Ask the customer to select which MOA members are Authorised Signatories.

CONTEXT:
- MOA Members found:
{names_str}

MESSAGE REQUIREMENTS:
1. State that the listed members were found in the MOA.
2. Ask the customer to indicate which members should be designated as Authorised Signatories.
3. Note that a member can hold both UBO and AS status — UBO will be confirmed in Stage 2.
4. Length: 3 sentences.
5. Tone: Professional, instructional.

Generate the prompt:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_MOA_AS_PROMPT")

    @staticmethod
    def ki_moa_as_saved(language: str = "english") -> str:
        """Confirm MOA AS selections saved and state the ID-upload next step (unused by the MOA route since the i18n catalog; kept for compatibility)."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm AS selections saved and state the next step.

MESSAGE REQUIREMENTS:
1. Confirm Authorised Signatory selections have been saved.
2. State that the next step is uploading the Emirates ID or Passport for each listed individual.
   Do NOT ask whether there are additional/external Key Individuals — that is asked later by a dedicated card.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_MOA_AS_SAVED")

    @staticmethod
    def ki_added_prompt_id_upload(name: str, id_type: str, language: str = "english") -> str:
        """Confirm KI saved and prompt for ID upload."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm Key Individual saved and request their ID document upload.

CONTEXT:
- Key Individual Name: {name}
- Required ID Type: {id_type}

MESSAGE REQUIREMENTS:
1. Confirm {name} has been added as a Key Individual.
2. Request upload of their {id_type} for identity verification.
3. Length: 2 sentences.
4. Tone: Professional, clear, directive.

Generate the prompt:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_ADDED_ID_PROMPT")

    @staticmethod
    def ki_verified(language: str = "english") -> str:
        """Confirm KI identity verified and ask for next action."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm Key Individual identity verification complete and ask about next steps.

MESSAGE REQUIREMENTS:
1. Confirm identity verification is complete for this individual.
2. Ask if there are additional Key Individuals to add, or if the customer is ready to proceed.
3. Length: 2 sentences.
4. Tone: Professional, clear.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_VERIFIED")

    @staticmethod
    def ki_no_declared(language: str = "english") -> str:
        """Acknowledge no KIs declared and proceed to Self-Declaration."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Acknowledge no Key Individuals declared and proceed to Self-Declaration.

MESSAGE REQUIREMENTS:
1. Acknowledge that no Key Individuals have been declared.
2. State that the process will now proceed to the Self-Declaration step.
3. Length: 2 sentences.
4. Tone: Professional, clear. NO warning or negative framing.

Generate the message:"""
        return MessageGenerator._generate_with_retry(prompt, "KI_NO_DECLARED")

    # ========================================================================
    # v3 — UBO CONFIRMATION MESSAGES
    # ========================================================================

    @staticmethod
    def ubo_question(member_name: str, suggested_ubo: bool, share_pct: float, language: str = "english") -> str:
        """Per-member UBO Yes/No question with pre-fill suggestion."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        suggestion = (
            f"Based on their {share_pct:.1f}% ownership stake, they are suggested as a UBO."
            if suggested_ubo
            else f"Based on their {share_pct:.1f}% ownership stake, they are not automatically classified as a UBO."
        )
        prompt = f"""{language_instruction}

TASK: Ask if a specific member is a UBO (Ultimate Beneficial Owner).

CONTEXT:
- Member Name: {member_name}
- Ownership: {share_pct:.1f}%
- Suggestion: {suggestion}

MESSAGE REQUIREMENTS:
1. Ask: "Is {member_name} a UBO (Ultimate Beneficial Owner) for this account?"
2. State the ownership context and pre-fill suggestion in one sentence.
3. Length: 2-3 sentences.
4. Tone: Professional, factual, compliance-oriented.

Generate the UBO question:"""
        return MessageGenerator._generate_with_retry(prompt, "UBO_QUESTION")

    @staticmethod
    def ubo_confirmed_prompt_id(member_name: str, is_ubo: bool, language: str = "english") -> str:
        """Confirm UBO status and prompt ID upload for this member."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        ubo_str = "a UBO (Ultimate Beneficial Owner)" if is_ubo else "not a UBO"
        prompt = f"""{language_instruction}

TASK: Confirm UBO status for a member and request their ID document.

CONTEXT:
- Member Name: {member_name}
- UBO Status: Recorded as {ubo_str}

MESSAGE REQUIREMENTS:
1. Confirm {member_name} has been recorded as {ubo_str}.
2. Request upload of their Emirates ID or Passport to complete identity verification.
3. Length: 2 sentences.
4. Tone: Professional, directive.

Generate the confirmation and prompt:"""
        return MessageGenerator._generate_with_retry(prompt, "UBO_CONFIRMED_ID_PROMPT")

    # ========================================================================
    # v3 — SELF-DECLARATION MESSAGES
    # ========================================================================

    @staticmethod
    def self_declaration_prompt(language: str = "english") -> str:
        """Introduce the Self-Declaration summary and prompt user to review."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Introduce the Self-Declaration summary to the customer.

MESSAGE REQUIREMENTS:
1. Inform the customer that a complete summary of their onboarding submission is presented below.
2. Ask them to review all information carefully and click [I Confirm and Accept] to proceed.
3. Length: 2 sentences.
4. Tone: Professional, formal, regulatory.

Generate the introduction:"""
        return MessageGenerator._generate_with_retry(prompt, "SELF_DECL_PROMPT")

    @staticmethod
    def self_declaration_confirmed(language: str = "english") -> str:
        """Confirm self-declaration accepted and cross-validation starting."""
        language_instruction = MessageGenerator._build_language_instruction(language)
        prompt = f"""{language_instruction}

TASK: Confirm self-declaration accepted and inform cross-validation is starting.

MESSAGE REQUIREMENTS:
1. Confirm the self-declaration has been recorded with a timestamp.
2. State that cross-validation of all submitted documents is now in progress.
3. Length: 2 sentences.
4. Tone: Professional, formal, reassuring.

Generate the confirmation:"""
        return MessageGenerator._generate_with_retry(prompt, "SELF_DECL_CONFIRMED")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

ai_message_gen = MessageGenerator()