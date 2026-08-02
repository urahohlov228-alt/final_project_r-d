"""Input/output guardrails.

Deterministic checks that run before any LLM call (input) and after the last
one (output). They complement — not replace — the prompt-level rules in
`agents/prompts.py`: prompts steer the model, these filters enforce hard
boundaries in code.
"""

import re
from dataclasses import dataclass

# Patterns that indicate prompt-injection / instruction-override attempts.
# Matched case-insensitively against the raw user input.
INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+instructions", "instruction override"),
    (r"disregard\s+(all\s+|the\s+)?(previous|prior|above)", "instruction override"),
    (r"forget\s+(all\s+|everything|your\s+instructions)", "instruction override"),
    (r"reveal\s+(your\s+)?(system\s+)?prompt", "prompt extraction"),
    (r"(show|print|repeat)\s+(me\s+)?(your\s+)?(system\s+prompt|instructions)", "prompt extraction"),
    (r"you\s+are\s+now\s+(?!an?\s+hr)", "role hijack"),
    (r"act\s+as\s+(?!an?\s+hr)", "role hijack"),
    (r"pretend\s+(to\s+be|you\s+are)", "role hijack"),
    (r"\bDAN\b|do\s+anything\s+now", "jailbreak"),
    (r"developer\s+mode", "jailbreak"),
    (r"<\s*/?\s*system\s*>", "fake system tag"),
    (r"\[\s*system\s*\]", "fake system tag"),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), label) for pattern, label in INJECTION_PATTERNS]

# Output redaction: secret-looking tokens must never reach the user,
# no matter how they ended up in the reply.
_SECRET_RE = re.compile(r"\b(?:sk|gsk|xoxb|ghp|glpat|AKIA)[-_][A-Za-z0-9_\-]{10,}\b")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

MAX_OUTPUT_CHARS = 6000


@dataclass
class GuardrailVerdict:
    allowed: bool
    reason: str = ""


def check_input(text: str, max_chars: int = 2000) -> GuardrailVerdict:
    """Validate raw user input before it reaches any model."""
    stripped = text.strip()
    if not stripped:
        return GuardrailVerdict(False, "empty message")
    if len(stripped) > max_chars:
        return GuardrailVerdict(False, f"message longer than {max_chars} characters")
    if _CONTROL_CHARS_RE.search(stripped):
        return GuardrailVerdict(False, "control characters in message")
    for pattern, label in _COMPILED:
        if pattern.search(stripped):
            return GuardrailVerdict(False, f"prompt injection pattern: {label}")
    return GuardrailVerdict(True)


def sanitize_output(text: str) -> str:
    """Final pass over the assistant reply before it leaves the API."""
    text = _SECRET_RE.sub("[redacted]", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "…"
    return text.strip()
