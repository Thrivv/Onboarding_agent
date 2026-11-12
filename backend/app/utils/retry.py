# backend/app/utils/retry.py
"""
Shared retry-with-exponential-backoff decorator for upstream API calls.

Replaces five near-identical copies that had drifted apart:

    app/services/ocr_service.py                        28 lines
    app/services/specialized_ocr/ejari_extractor.py    20 lines
    app/services/specialized_ocr/moa_extractor.py      20 lines
    app/services/specialized_ocr/trade_extractor.py    18 lines
    app/services/specialized_ocr/bvi_extractor.py      22 lines  (named _retry_with_backoff)

The control flow was identical in all five — retry on HTTP 503/429/502/504 with
delay = base_delay * 2**attempt, re-raise anything else. The only real
difference was the label in the log line ("API error", "Ejari API error",
"MOA API error", "CoI API error"), so that is now a parameter and each caller
keeps the wording it had.
"""

from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

# Upstream statuses worth retrying: rate limiting and transient gateway errors.
RETRYABLE_STATUS_CODES = ("503", "429", "502", "504")


def retry_with_backoff(max_retries: int = 3, base_delay: int = 5, label: str = "API"):
    """
    Retry a function on transient upstream errors, with exponential backoff.

    Args:
        max_retries: total attempts before giving up.
        base_delay:  seconds for the first retry; doubles each attempt.
        label:       prefix for the log line, e.g. "Ejari API".

    Only ``RuntimeError`` is inspected — that is what the extractors raise for a
    failed HTTP call. Any other exception propagates immediately, and so does a
    RuntimeError whose message contains none of RETRYABLE_STATUS_CODES.
    Returns None if every attempt is exhausted without raising, matching the
    behaviour of the copies this replaces.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except RuntimeError as e:
                    error_msg = str(e)
                    retryable = any(
                        code in error_msg for code in RETRYABLE_STATUS_CODES
                    )
                    if retryable and attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"{label} error (attempt {attempt + 1}/{max_retries}): "
                            f"{error_msg}"
                        )
                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        raise
            return None

        return wrapper

    return decorator
