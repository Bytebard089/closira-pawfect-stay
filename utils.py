"""
utils.py
========
Shared utilities used by both main.py and test_scenarios.py.
Single source of truth for retry logic and reply parsing.
"""

import time
from typing import Callable, Optional, Tuple

try:
    import fcntl
except ImportError:  # Windows or environments without fcntl
    fcntl = None

from groq import RateLimitError, APIConnectionError


def call_with_retry(fn: Callable[[], object], retries: int = 3) -> Tuple[object, Optional[str]]:
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


def parse_reply(raw: str) -> Tuple[bool, str, str]:
    """
    Strips the internal ESCALATE: line from the model's raw reply.
    Returns (escalated: bool, reason: str, clean_reply: str).
    The customer-facing reply never contains the ESCALATE flag.
    """
    lines = raw.strip().splitlines()
    first_non_empty = ""
    first_index = 0
    for idx, line in enumerate(lines):
        if line.strip():
            first_non_empty = line.strip()
            first_index = idx
            break

    if first_non_empty.upper().startswith("ESCALATE:"):
        reason = first_non_empty.split(":", 1)[1].strip()
        clean_reply = "\n".join(lines[first_index + 1:]).strip()
        return True, reason, clean_reply

    return False, "", raw.strip()


def lock_file(file_obj) -> None:
    if fcntl:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)


def unlock_file(file_obj) -> None:
    if fcntl:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


FORCED_ESCALATION_MESSAGE = (
    "Thanks for asking — I don't have that information in the SOP, so I don't want to guess. "
    "I'm flagging this for a team member who can help."
)


def forced_escalation_reason(user_input: str) -> str:
    """
    Returns a reason string when the user asks a known out-of-scope topic
    that should always escalate, or an empty string if no match.
    """
    text = user_input.lower()

    if "training" in text and "adult" in text:
        return "Customer asked about adult dog training, which is not in the SOP."

    if "hydrotherapy" in text or "swimming" in text:
        return "Customer asked about hydrotherapy or swimming sessions, which are not in the SOP."

    if ("anxiety" in text and "assessment" in text) or ("behavioral" in text and "assessment" in text) or ("behavioural" in text and "assessment" in text):
        return "Customer asked about a behavioral assessment, which is not in the SOP."

    return ""
