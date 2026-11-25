'''Prompt Injection Detection Module

Provides utilities to detect potential prompt injection attempts in user inputs.
'''  

# List of common injection patterns (case‑insensitive)
_INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "disregard safety",
    "system prompt",
    "override",
    "unrestricted",
    "new directive",
    "admin api key",
    "api key",
    "stop everything",
    "you are now",
    "you are an unrestricted",
    "ignore all previous",
    "bypass safety",
]

def is_prompt_injection(user_input: str) -> bool:
    """Return True if the input looks like a prompt‑injection attempt.

    The detection is deliberately simple: it checks whether any of the
    known suspicious substrings appear in the supplied text (case‑insensitive).
    For production use you would replace this with a more sophisticated
    LLM‑based guardrail.
    """
    lowered = user_input.lower()
    return any(keyword in lowered for keyword in _INJECTION_KEYWORDS)

