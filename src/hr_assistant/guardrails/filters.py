"""Input/output guardrails.

Deterministic checks that run before any LLM call (input) and after the last
one (output). They complement — not replace — the prompt-level rules in
`agents/prompts.py`: prompts steer the model, these filters enforce hard
boundaries in code.
"""

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

# Patterns that indicate prompt-injection / instruction-override attempts.
# Matched case-insensitively against a normalized copy of the input.
INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+instructions", "instruction override"),
    (r"disregard\s+(all\s+|the\s+)?(previous|prior|above)", "instruction override"),
    (r"forget\s+(all\s+|everything|your\s+instructions)", "instruction override"),
    (r"reveal\s+(your\s+)?(system\s+)?prompt", "prompt extraction"),
    (
        r"(show|print|repeat)\s+(me\s+)?(your\s+)?(system\s+prompt|instructions)",
        "prompt extraction",
    ),
    (r"you\s+are\s+now\s+(?!an?\s+hr)", "role hijack"),
    (r"act\s+as\s+(?!an?\s+hr)", "role hijack"),
    (r"pretend\s+(to\s+be|you\s+are)", "role hijack"),
    (r"\bDAN\b|do\s+anything\s+now", "jailbreak"),
    (r"developer\s+mode", "jailbreak"),
    (r"<\s*/?\s*system\s*>", "fake system tag"),
    (r"\[\s*system\s*\]", "fake system tag"),
]

_WHITESPACE_TOKEN_RE = re.compile(r"\\s[+*]?|\\b")


def _compact_pattern(pattern: str) -> str:
    """Derive a whitespace-agnostic variant that still matches when an attacker
    strips or splits words (e.g. 'i g n o r e p r e v i o u s')."""
    return _WHITESPACE_TOKEN_RE.sub("", pattern)


_COMPILED = [(re.compile(pattern, re.IGNORECASE), label) for pattern, label in INJECTION_PATTERNS]
_COMPILED_COMPACT = [
    (re.compile(_compact_pattern(pattern), re.IGNORECASE), label)
    for pattern, label in INJECTION_PATTERNS
]

# Invisible / bidi / formatting characters attackers use to defeat regex:
# zero-width space/joiner/non-joiner, LRM/RLM, bidi overrides/isolates,
# word joiner, invisible math operators, BOM, soft hyphen.
_INVISIBLE_RE = re.compile(
    "[​-‏‪-‮⁠-⁯﻿­]"
)
# Base64 blob that's long enough to plausibly hide a directive.
_B64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def _normalize_for_match(text: str) -> str:
    """Fold unicode look-alikes, drop invisibles, collapse whitespace.
    Used only for pattern matching — the original text is still what reaches
    the model, so legitimate formatting is preserved."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    text = text.casefold()
    return re.sub(r"\s+", " ", text)


def _compact(text: str) -> str:
    """Strip every non-alphanumeric so 'i-g-n-o-r-e' collapses to 'ignore'."""
    return re.sub(r"[\W_]+", "", text)


def _decode_base64_blobs(text: str) -> str:
    """Return the concatenation of successfully-decoded base64 runs, so we can
    re-scan the plaintext for injection patterns hidden behind an encoding."""
    decoded: list[str] = []
    for match in _B64_RE.finditer(text):
        try:
            raw = base64.b64decode(match.group(0), validate=True)
        except (binascii.Error, ValueError):
            continue
        try:
            decoded.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return " ".join(decoded)


def _match_injection(text: str) -> str | None:
    """Return the label of the first injection pattern that fires, or None."""
    normalized = _normalize_for_match(text)
    for pattern, label in _COMPILED:
        if pattern.search(normalized):
            return label
    compact = _compact(normalized)
    for pattern, label in _COMPILED_COMPACT:
        if pattern.search(compact):
            return label
    return None

# Output redaction: secret-looking tokens must never reach the user,
# no matter how they ended up in the reply.
_SECRET_PATTERNS: list[re.Pattern] = [
    # provider-prefixed API keys (OpenAI, Groq, Slack, GitHub, GitLab, AWS access key id)
    re.compile(r"\b(?:sk|gsk|xoxb|xoxp|ghp|gho|ghu|ghs|ghr|glpat|AKIA|ASIA)[-_][A-Za-z0-9_\-]{10,}\b"),
    # generic bearer tokens in Authorization-style prose
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    # PEM private key blocks (RSA, EC, OPENSSH, generic)
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    # GCP service-account JSON "private_key" field
    re.compile(r'"private_key"\s*:\s*"[^"]+"'),
]
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
    label = _match_injection(stripped)
    if label:
        return GuardrailVerdict(False, f"prompt injection pattern: {label}")
    decoded = _decode_base64_blobs(stripped)
    if decoded:
        label = _match_injection(decoded)
        if label:
            return GuardrailVerdict(False, f"prompt injection pattern: {label} (base64)")
    return GuardrailVerdict(True)


def sanitize_output(text: str) -> str:
    """Final pass over the assistant reply before it leaves the API."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "…"
    return text.strip()
