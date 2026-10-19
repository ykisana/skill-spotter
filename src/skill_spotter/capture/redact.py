"""Remove secrets from text before anything is stored (SPEC section 9.2).

Redaction is deliberately greedy: a false positive only costs a little matching
signal, a false negative stores a credential on disk.
"""

from __future__ import annotations

import re

REDACTED = "<redacted>"

_PATTERNS = [
    # Private key blocks (multi-line)
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        re.S,
    ),
    # Provider tokens with recognisable prefixes
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic
    re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}"),  # GitLab
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),
    # JWTs
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
]

# "Authorization: Bearer xyz", "Bearer xyz"
_BEARER = re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=\-]{12,}")
# scheme://user:password@host -> keep user, hide password
_URL_PASSWORD = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^:/\s@]+:)[^@\s/]+@")
# API_KEY=..., export GITHUB_TOKEN="...", password: hunter22, --password=...
_SECRET_ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_\-]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIALS?|AUTH)"
    r"[A-Z0-9_\-]*)(\s*[=:]\s*|\s+)([\"']?)([^\s\"']{4,})\3"
)
# Any long UPPER_CASE=value env line (e.g. DATABASE_URL=..., STRIPE_LIVE=...)
_LONG_ENV = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=([\"']?)([^\s\"']{24,})\2")


def redact(text: str) -> str:
    """Return ``text`` with anything that looks like a credential replaced."""
    if not text:
        return text
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _URL_PASSWORD.sub(lambda m: f"{m.group(1)}{REDACTED}@", text)
    text = _SECRET_ASSIGN.sub(_assign_sub, text)
    text = _LONG_ENV.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return text


def _assign_sub(m: re.Match) -> str:
    name, sep, quote, value = m.group(1), m.group(2), m.group(3), m.group(4)
    if value == REDACTED or value.startswith("$"):  # already redacted, or a $VAR reference
        return m.group(0)
    if sep.strip() == "" and not name.isupper():
        return m.group(0)  # "the token value" in prose; only redact NAME value for env-style names
    return f"{name}{sep}{quote}{REDACTED}{quote}"
