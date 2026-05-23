"""
utils.py
========
Shared utilities used by both main.py and test_scenarios.py.
Single source of truth for retry logic and reply parsing.
"""

import time
from groq import RateLimitError, APIConnectionError


def call_with_retry(fn, retries=3):
    """
    Calls fn() with exponential backoff on transient Groq API errors.
    Always returns (result, None) on success, (None, error_str) on failure.
    Callers always pass a bare lambda — wrapping is done here.
    """
    for attempt in range(retries):
        try:
            return fn(), None
        except RateLimitError:
            if attempt == retries - 1:
                return None, "rate_limit"
            time.sleep(2 ** attempt)
        except APIConnectionError:
            if attempt == retries - 1:
                return None, "connection"
            time.sleep(2 ** attempt)
    return None, "unknown"


def parse_reply(raw: str) -> tuple:
    """
    Strips the internal ESCALATE: line from the model's raw reply.
    Returns (escalated: bool, reason: str, clean_reply: str).
    The customer-facing reply never contains the ESCALATE flag.
    """
    lines = raw.strip().splitlines()
    if lines and lines[0].upper().startswith("ESCALATE:"):
        reason      = lines[0].split(":", 1)[1].strip()
        clean_reply = "\n".join(lines[1:]).strip()
        return True, reason, clean_reply
    return False, "", raw.strip()
