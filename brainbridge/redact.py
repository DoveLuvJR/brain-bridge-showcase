"""Secret-stripper.

Runs on whole files and whole transcript turns BEFORE they are cut into records (a
secret split across two records would escape every pattern), and again on each stored
title and body. Each hit becomes [REDACTED:<kind>]. Order matters: private-key blocks
first, then vendor-shaped tokens, then "NAME = value" assignments.

The same patterns drive find_secrets(), which the audits use. That is a known limit: a
secret shape no pattern knows passes both. The answer is to extend PATTERNS and bump
VERSION, which makes the next run re-strip everything stored.
"""
import re

VERSION = 1

_ASSIGN_NAME = (
    r"[A-Za-z0-9_]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?key|_key)[A-Za-z0-9_]*"
)
_ENV_NAME = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*?_?(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PASS|PWD|CREDENTIALS?|AUTH)(?:_[A-Z0-9]+)*"
_VALUE = r"[^\s\"'`,;<>()\[\]{}]"

PATTERNS = [
    ("private-key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S)),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}")),
    ("github", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("stripe", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("bearer", re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/\-]{20,}=*)")),
    ("url-password", re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:)([^\s@/]{3,})(@)", re.I)),
    # Upper-case env-var names (DB_PASSWORD=, VENDOR_KEY:) are secrets whatever the value looks like.
    ("env-assignment", re.compile(r"(\b" + _ENV_NAME + r"[\"']?\s*[:=]\s*[\"']?)(" + _VALUE + r"{6,})")),
    ("assignment", re.compile(r"(?i)(\b" + _ASSIGN_NAME + r"[\"']?\s*[:=]\s*[\"']?)(" + _VALUE + r"{8,})")),
]


def _is_secret_value(value: str) -> bool:
    # Real secrets are random: they carry a digit or are long. Prose words are spared.
    if value.startswith("["):
        return False
    return any(c.isdigit() for c in value) or len(value) >= 20


def _replacement(kind: str, m: re.Match) -> str:
    if kind == "assignment":
        if not _is_secret_value(m.group(2)):
            return m.group(0)
        return m.group(1) + "[REDACTED:assignment]"
    if kind == "env-assignment":
        if m.group(2).startswith(("[", "$", "%")):  # already redacted, or a ${VAR} reference
            return m.group(0)
        return m.group(1) + "[REDACTED:env-assignment]"
    if kind == "bearer":
        return m.group(1) + "[REDACTED:bearer]"
    if kind == "url-password":
        return m.group(1) + "[REDACTED:url-password]" + m.group(3)
    return f"[REDACTED:{kind}]"


def redact(text: str):
    """Return (clean_text, number_of_redactions)."""
    total = 0
    for kind, pattern in PATTERNS:
        def repl(m, kind=kind):
            nonlocal total
            out = _replacement(kind, m)
            if out != m.group(0):
                total += 1
            return out
        text = pattern.sub(repl, text)
    return text, total


def find_secrets(text: str) -> list:
    """Kinds of secret-shaped strings still present (used by every audit)."""
    found = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if _replacement(kind, m) != m.group(0) and "[REDACTED" not in m.group(0):
                found.append(kind)
    return found
