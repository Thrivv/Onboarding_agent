# app/services/onboarding_chat_service.py
"""
Onboarding Chat Service
-----------------------
Handles the full AI chat loop for the onboarding assistant:

  1. Load conversation history from Supabase
  2. Load current_step and context_data from the users table + document store
  3. Fill the improved system prompt template
  4. Call the LLM via llm_client.call_text_llm()
  5. Persist the user message and AI response back to Supabase
  6. Return the AI response to the caller

Public API
----------
  generate_chat_response(email: str, user_message: str) -> str
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.services.supabase_client import supabase
from app.services.llm_client import call_text_llm
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.domain.onboarding.stage_table import (
    STAGE_CORPORATE_SHAREHOLDER_DOCS,
    STAGE_IDENTIFICATION,
    STAGE_MEMBER_EIDS,
    STAGE_SO_MEMBER_EIDS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Onboarding step definitions — used to give the LLM step-aware context
# ---------------------------------------------------------------------------

STEP_DESCRIPTIONS = {
    "welcome": (
        "The user just registered. Welcome them and explain that they need to upload "
        "their required documents to complete onboarding."
    ),
    "ownership_selection": (
        "Ownership structure is not yet known — this is no longer collected at signup. "
        "Ask the user whether they own the business by themselves (Sole Proprietorship) "
        "or share ownership with others (Joint Ownership), before requesting any "
        "documents. Once answered, call POST /chatupload/ownership-type/save with the "
        "user's choice."
    ),
    STAGE_IDENTIFICATION: (
        "The user needs to upload identity documents. Under Sole Proprietorship: "
        "Trade License + Emirates ID + Ejari. Under Joint Ownership: Trade License "
        "+ MOA + Emirates IDs of all owners."
    ),
    STAGE_CORPORATE_SHAREHOLDER_DOCS: (
        "The user is uploading shareholder documents (MOA, shareholder agreements)."
    ),
    STAGE_MEMBER_EIDS: (
        "Collecting Emirates IDs for all owners or key individuals."
    ),
    STAGE_SO_MEMBER_EIDS: (
        "Collecting Emirates ID for the business owner. "
        "Once EID is verified, the next step is the FATCA declaration."
    ),
    "fatca": (
        "User needs to complete the FATCA (Foreign Account Tax Compliance Act) declaration. "
        "Required for every account, under Sole Proprietorship or Joint Ownership alike."
    ),
    "pep": (
        "User needs to complete the PEP (Politically Exposed Person) declaration. "
        "Required for every account, under Sole Proprietorship or Joint Ownership alike."
    ),
    "self_declaration": (
        "User needs to review and sign the self-declaration form."
    ),
    "verification_complete": (
        "All documents submitted and verified. Onboarding is complete. "
        "Guide the user on what happens next (account activation, timeline)."
    ),
    "document_review": (
        "Documents are under review by the compliance team. "
        "Keep the user informed and answer any status questions."
    ),
}

# ---------------------------------------------------------------------------
# Improved system prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are DigiOB, an AI onboarding assistant for a regulated financial institution in the UAE.
Your sole purpose is to guide users through the document onboarding process — step by step, \
clearly and efficiently.

━━━ PERSONA & TONE ━━━
- Professional, concise, and reassuring.
- Never use greetings (no "Dear", "Hi", "Hello") or sign-offs (no "Regards", "Best").
- Never use emojis.
- Never say more than 3 sentences in a response unless showing a summary.
- Ask only ONE question per response — never two.

━━━ ABSOLUTE RULES ━━━
1. Resume from the current step — never restart or repeat completed steps.
2. If a user asks something off-topic (not about onboarding), briefly redirect them.
3. Never ask for data already present in context_data.
4. Validate inputs — if an answer is invalid, ask again with a correction hint.
5. Move forward only when the current step is fully complete.
6. Never say "Corporate account", "Single Owner", "Partnership", or "Multiple
   Owner(s)" to the user. Use "Sole Proprietorship" for one owner and "Joint
   Ownership" for more than one. Refer to the account itself as just "your
   account" — no category label.

━━━ ONBOARDING STEPS ━━━
The process follows these ordered steps. Ownership structure is no longer
asked at signup, so every account starts at ownership_selection immediately
after welcome, before either flow below begins:

  welcome → ownership_selection → (then one of the two flows below)

  Joint Ownership:
    identification → corporate_shareholder_docs → member_eids
    → fatca → pep → product_package → self_declaration → verification_complete

  Sole Proprietorship:
    identification → so_member_eids
    → fatca → pep → product_package → self_declaration → verification_complete

━━━ CURRENT CONTEXT ━━━
Current Step : {current_step}
Step Guidance: {step_description}

User Profile:
{context_data}

━━━ CONVERSATION SO FAR ━━━
{chat_history}

━━━ YOUR TASK ━━━
Continue the onboarding conversation from the current step.
- Do NOT repeat any question already answered in the conversation.
- Do NOT re-introduce yourself.
- Ask the single next required action or question.
- If the current step is complete, transition to the next step and state it clearly.
- If context_data shows the step is already done, move to the next incomplete step.
"""

# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context_data(user: dict) -> str:
    """
    Serialize the user record into a readable key-value block.
    Only includes fields relevant to the onboarding conversation.
    """
    fields = {
        "Name":           user.get("name") or f"{user.get('first_name','')} {user.get('last_name','')}".strip(),
        "Email":          user.get("email"),
        "Account Type":   user.get("account_type"),
        "Ownership Type": user.get("ownership_type"),
        "Business Name":  user.get("business_name"),
        "Onboarding Step":user.get("onboarding_step"),
        "Onboarding Done":user.get("onboarding_complete"),
        "FATCA Done":     user.get("fatca_submitted"),
        "PEP Done":       user.get("pep_submitted"),
        "Self-Decl Done": user.get("self_declaration_submitted"),
    }

    # Load document upload status from disk
    doc_status = _load_document_status(user.get("email", ""))
    for doc_type, uploaded in doc_status.items():
        fields[f"Doc: {doc_type.replace('_', ' ').title()}"] = "Uploaded ✓" if uploaded else "Not uploaded"

    lines = []
    for k, v in fields.items():
        if v is not None and v != "" and v is not False:
            lines.append(f"  {k}: {v}")

    return "\n".join(lines) if lines else "  No profile data yet."


def _load_document_status(email: str) -> dict:
    """
    Check which document types have been uploaded for this user
    by scanning their document folder for non-superseded JSON records.
    """
    status: dict = {}
    if not email:
        return status

    try:
        from app.services.document_helpers import get_user_documents_path
        user_path = get_user_documents_path(email)

        for json_file in user_path.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if data.get("superseded"):
                    continue
                doc_type = data.get("document_type")
                if doc_type and data.get("valid", data.get("is_valid", False)):
                    status[doc_type] = True
            except Exception:
                continue
    except Exception as exc:
        logger.warning(f"[CHAT-SVC] Could not load doc status for {email}: {exc}")

    return status


def _load_chat_history(email: str, limit: int = 12) -> str:
    """
    Load the most recent `limit` chat messages from Supabase and format them
    as a plain conversation transcript.
    Filters out email-style system messages.
    """
    try:
        resp = ConversationRepository.list_transcript(email)
        rows = resp.data or []
    except Exception as exc:
        logger.warning(f"[CHAT-SVC] Could not load history for {email}: {exc}")
        return "(no prior conversation)"

    # Filter out email-style messages injected by the system
    email_markers = {"dear user", "best regards", "thrivv onboarding team", "welcome to thrivv"}
    chat_rows = [
        r for r in rows
        if not any(m in r.get("message", "").lower() for m in email_markers)
    ]

    # Strip the [CHAT] prefix that old code prefixed
    cleaned = []
    for r in chat_rows[-limit:]:
        msg = r.get("message", "").strip()
        if msg.startswith("[CHAT] "):
            msg = msg[7:]
        role = "User" if r.get("role") == "user" else "Assistant"
        cleaned.append(f"{role}: {msg}")

    return "\n".join(cleaned) if cleaned else "(no prior conversation)"


def _persist_messages(email: str, user_message: str, ai_response: str) -> None:
    """Save user message and AI response to the conversations table."""
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "user_email": email,
            "role":       "user",
            "message":    user_message,
            "channel":    "chat",
            "timestamp":  now,
        },
        {
            "user_email": email,
            "role":       "assistant",
            "message":    ai_response,
            "channel":    "chat",
            "timestamp":  now,
        },
    ]
    try:
        ConversationRepository.insert_many(records)
    except Exception as exc:
        logger.warning(f"[CHAT-SVC] Could not persist messages for {email}: {exc}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_chat_response(email: str, user_message: str) -> str:
    """
    Build context from Supabase, fill the system prompt, call the LLM,
    persist both messages, and return the AI response string.
    """
    # 1. Load user record
    try:
        result = UserRepository.get_by_email_limit_one(email)
        user = result.data[0] if result.data else {}
    except Exception as exc:
        logger.error(f"[CHAT-SVC] Could not load user {email}: {exc}")
        user = {}

    if not user:
        return "I couldn't find your account. Please contact support."

    # 2. Build context pieces
    current_step   = user.get("onboarding_step") or "welcome"
    step_desc      = STEP_DESCRIPTIONS.get(current_step, "Continue the onboarding process.")
    context_data   = _build_context_data(user)
    chat_history   = _load_chat_history(email)

    # 3. Fill system prompt
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        current_step    = current_step,
        step_description= step_desc,
        context_data    = context_data,
        chat_history    = chat_history,
    )

    # 4. Call LLM — user message goes in as the human turn
    try:
        ai_response = call_text_llm(
            prompt        = user_message,
            system_prompt = system_prompt,
            max_tokens    = 512,
            temperature   = 0.3,   # low temp for consistent, structured guidance
        )
    except Exception as exc:
        logger.error(f"[CHAT-SVC] LLM call failed for {email}: {exc}")
        ai_response = (
            "I'm experiencing a technical issue. "
            "Please try again in a moment or contact support."
        )

    # 5. Persist both turns
    _persist_messages(email, user_message, ai_response)

    return ai_response


def get_chat_history_for_user(email: str, limit: int = 50) -> list[dict]:
    """
    Return formatted chat history for the frontend.
    Strips system email messages and the [CHAT] prefix.
    """
    try:
        resp = ConversationRepository.list_transcript(email, limit=limit)
        rows = resp.data or []
    except Exception as exc:
        logger.warning(f"[CHAT-SVC] History fetch failed for {email}: {exc}")
        return []

    email_markers = {"dear user", "best regards", "thrivv onboarding team", "welcome to thrivv"}
    results = []
    for r in rows:
        msg = r.get("message", "").strip()
        if any(m in msg.lower() for m in email_markers):
            continue
        if msg.startswith("[CHAT] "):
            msg = msg[7:]
        results.append({
            "role":      r.get("role"),
            "message":   msg,
            "timestamp": r.get("timestamp"),
        })

    return results
