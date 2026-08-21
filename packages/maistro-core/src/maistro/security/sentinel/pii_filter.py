"""Sentinel PII filter: scans text for leaked secrets and personal data.

Two families of detectors, and the module is only honestly named because both
exist:

- **Secrets** — API keys, tokens, JWTs, connection strings, private-key
  headers, passwords, IPs, emails.
- **Personal data** — payment card numbers (Luhn-validated), US Social
  Security numbers, and international-format phone numbers.

Known scope limits, stated so the next reader doesn't rediscover them as a
finding: national ID formats other than US SSN are not detected, and phone
numbers are matched in E.164 international form only (a bare local
"555-1234" is indistinguishable from ordinary numerics at acceptable
false-positive rates). Postal addresses, names, and dates of birth need
context-aware NER, not regex, and are out of scope here.

``PIIMatch.value`` is a masked preview, never the plaintext: the match list is
returned across API boundaries and routinely logged, and a redaction API that
hands back the secret it just redacted is itself a leak.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from maistro.security.normalize import normalize_for_redaction


@dataclass(frozen=True)
class PIIMatch:
    """One detected span. ``value`` is masked (prefix + length), never raw."""

    pii_type: str
    value: str
    start: int
    end: int


def _mask(raw: str) -> str:
    """First four characters plus length: enough to identify which credential
    leaked (key prefixes are public — AKIA, ghp_, sk-) without re-leaking it."""
    return f"{raw[:4]}…({len(raw)} chars)"


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _ssn_ok(candidate: str) -> bool:
    """Reject the SSN ranges never issued (000/666/9xx areas, 00 group,
    0000 serial) — they're the bulk of look-alike false positives."""
    area, group, serial = candidate.split("-")
    if area in ("000", "666") or area.startswith("9"):
        return False
    return group != "00" and serial != "0000"


# (type, pattern, validator). A validator narrows a shape-match to a real hit;
# None means the pattern alone is specific enough.
_PII_PATTERNS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), None),
    ("github_token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}"), None),
    ("github_token", re.compile(r"github_pat_[A-Za-z0-9_]{22,}"), None),
    ("gitlab_token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}"), None),
    ("api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}"), None),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9_-]{20,}"), None),
    (
        "api_key",
        re.compile(
            r"""(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)"""
            r"""[\s]*[=:]\s*["']?[A-Za-z0-9_/+=.-]{16,}["']?""",
            re.IGNORECASE,
        ),
        None,
    ),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), None),
    (
        "connection_string",
        re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
            r"[^\s\"'>{})]+",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        "ip_address",
        re.compile(
            r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?!255\.255\.255\.255\b)"
            r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        None,
    ),
    # `[A-Za-z]`, not `[A-Z|a-z]`: the pipe is not alternation inside a
    # character class, it is a literal `|`, so the old class matched TLDs
    # containing a pipe character.
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), None),
    (
        "password",
        re.compile(
            r"""(?:password|passwd|pwd)[\s]*[=:]\s*["']?[^\s"']{8,}["']?""",
            re.IGNORECASE,
        ),
        None,
    ),
    # Personal data. These sit after the secret detectors so an overlapping
    # span is claimed by the more specific credential type first.
    (
        "payment_card",
        re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),
        _luhn_ok,
    ),
    (
        "ssn",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        _ssn_ok,
    ),
    (
        "phone",
        # E.164 international form only: leading +, 8-15 digits with common
        # separators. Bare local numbers are left alone on purpose (FP rate).
        re.compile(r"\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]?\d{2,4}){2,4}"),
        lambda s: 8 <= sum(c.isdigit() for c in s) <= 15,
    ),
]


def normalize_for_scan(text: str) -> str:
    """Return the folded string that scanning and redaction share.

    ``scan_for_pii`` matches against this string and records offsets into it.
    ``redact`` MUST slice the same string, otherwise compatibility characters
    (ligatures like ``ﬁ``, fractions like ``½``, composed accents) expand to a
    different length and shift every subsequent offset, leaking part of the
    matched secret. Keeping a single canonical string for both phases is the
    invariant that closes that desync.

    The fold is NFKD plus invisible-character stripping (see
    ``maistro.security.normalize``): a secret with a zero-width space inserted
    every few characters would otherwise walk past every pattern and reach the
    caller intact.
    """
    return normalize_for_redaction(text)


def scan_for_pii(text: str) -> list[PIIMatch]:
    normalized = normalize_for_scan(text)
    matches: list[PIIMatch] = []
    seen_ranges: list[tuple[int, int]] = []

    for pii_type, pattern, validator in _PII_PATTERNS:
        for m in pattern.finditer(normalized):
            start, end = m.start(), m.end()
            if any(not (end <= s or start >= e) for s, e in seen_ranges):
                continue
            if validator is not None and not validator(m.group()):
                continue
            matches.append(
                PIIMatch(
                    pii_type=pii_type,
                    value=_mask(m.group()),
                    start=start,
                    end=end,
                )
            )
            seen_ranges.append((start, end))

    matches.sort(key=lambda x: x.start)
    return matches


def redact(text: str, matches: list[PIIMatch] | None = None) -> str:
    """Return ``text`` with every match replaced by a typed placeholder.

    Output is ALWAYS the normalized string, matches or none: the previous
    version returned the original on no-match and the normalized form on
    match, so the same function produced two encodings of the same input
    conditional on secret presence — an information side channel and a
    downstream-diffing hazard rolled into one.
    """
    if matches is None:
        matches = scan_for_pii(text)

    result = normalize_for_scan(text)
    for match in sorted(matches, key=lambda x: x.start, reverse=True):
        placeholder = f"[REDACTED:{match.pii_type}]"
        result = result[: match.start] + placeholder + result[match.end :]

    return result


def scan_and_redact(text: str) -> tuple[str, list[PIIMatch]]:
    matches = scan_for_pii(text)
    return redact(text, matches), matches
