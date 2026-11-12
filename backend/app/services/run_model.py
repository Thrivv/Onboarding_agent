import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Default system prompt and temperature, used only when a caller doesn't
# supply its own. Before Phase 2 of the prompt-remediation plan, EVERY
# caller of call_local_llm() (message_generator.py's ~15 message types,
# handle_reply.py's reasoning/chat prompts, document_messaging.py's
# reasoning functions, document_expiry_validator.py) shared this one
# generic sentence and one fixed temperature=0.7, regardless of whether the
# task was a strict, format-locked banking message (which wants low
# variance) or a looser explanatory paragraph. call_local_llm() now accepts
# optional per-call overrides so each caller can supply a task-specific
# system prompt and temperature instead; these two stay only as the
# fallback for a caller that passes neither.
_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful banking assistant for a regulated financial institution in the UAE. "
    "Follow all instructions in the user's prompt exactly."
)
_DEFAULT_TEMPERATURE = 0.7


def call_local_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
) -> str:
    """
    Unified LLM gateway — delegates to call_text_llm (AWS Bedrock).

    system_prompt / temperature: optional per-call overrides (prompt-
    remediation Phase 2). Omit either to keep the previous shared default
    for callers that haven't been given a task-specific system prompt yet.
    Raises RuntimeError if the LLM call fails so callers can handle it properly.
    """
    from app.services.llm_client import call_text_llm

    return call_text_llm(
        prompt=prompt,
        system_prompt=system_prompt if system_prompt is not None else _DEFAULT_SYSTEM_PROMPT,
        temperature=temperature if temperature is not None else _DEFAULT_TEMPERATURE,
    )
