import logging

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful banking assistant for a regulated financial institution in the UAE. "
    "Follow all instructions in the user's prompt exactly."
)


def call_local_llm(prompt: str) -> str:
    """
    Unified LLM gateway — delegates to call_text_llm (OpenRouter).
    Language / tone instructions are already embedded in the prompt by the caller.
    Raises RuntimeError if the LLM call fails so callers can handle it properly.
    """
    from app.services.llm_client import call_text_llm

    return call_text_llm(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        temperature=0.7,
    )
