"""Sentinel PII filter: scans text for leaked secrets and personal data.

Two families of detectors, and the module is only honestly named because both
exist:

- **Secrets** — API keys, tokens, JWTs, connection strings, private-key
  headers, passwords, IPs, emails.
- **Personal data** — payment card numbers (Luhn-validated), US Social
  Security numbers, and international-format phone numbers.

Detection uses multiple views of one canonical redaction string. NFKD and
invisible-character stripping produce the canonical output. A same-length
homoglyph-folded view catches visually confusable ASCII-shaped secrets without
rewriting ordinary non-Latin prose. Percent-encoded and Base64/Base64URL
candidate tokens are decoded only for detection; when decoded content matches a
real PII detector, the original encoded token span is redacted.

Known scope limits: national ID formats other than US SSN are not detected, and
phone numbers are matched in E.164 international form only (a bare local
"555-1234" is indistinguishable from ordinary numerics at acceptable
false-positive rates). Postal addresses, names, and dates of birth need
context-aware NER, not regex, and are out of scope here.

``PIIMatch.value`` is a masked preview, never the plaintext: the match list is
returned across API boundaries and routinely logged, and a redaction API that
hands back the secret it just redacted is itself a leak.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import unquote, unquote_plus

from maistro.security.normalize import fold_homoglyphs, normalize_for_redaction


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
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        None,
    ),
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
    ("payment_card", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), _luhn_ok),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), _ssn_ok),
    (
        "phone",
        # E.164 international form only: leading +, 8-15 digits with common
        # separators. Bare local numbers are left alone on purpose (FP rate).
        re.compile(r"\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]?\d{2,4}){2,4}"),
        lambda s: 8 <= sum(c.isdigit() for c in s) <= 15,
    ),
]

# Candidate encodings are deliberately broad, but never become findings merely
# for looking encoded. They are redacted only when decoded plaintext satisfies
# one of the real PII validators above — which is what lets the candidate
# classes be generous without generating false positives.
#
# The percent class spans URI structure (`:`, `/`, `@`, `?`, `#`) as well as the
# unreserved set. `urllib.parse.quote` leaves `/` literal by default, so a
# class that stopped at it split `postgres%3A//u%3Ap%40localhost/db` into
# fragments, none of which could satisfy the connection-string detector — and
# the whole credential passed through. `=` and `&` stay excluded so
# ``value=someone%40example.com`` still redacts the value and not the key.
_PERCENT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9._~%+:/@?#\-])[A-Za-z0-9._~%+:/@?#\-]*%[0-9A-Fa-f]{2}"
    r"[A-Za-z0-9._~%+:/@?#\-]*(?![A-Za-z0-9._~%+:/@?#\-])"
)

#: Minimum Base64 candidate length, in characters before padding.
#:
#: Not arbitrary: it is set by the shortest PII this module detects. A US SSN is
#: eleven characters, which Base64-encodes to fifteen before padding — so a
#: sixteen-character floor excluded every encoded SSN, and `219-09-9999` went
#: through untouched. Twelve characters decodes to nine bytes, which leaves
#: headroom under that. Lowering it costs only decode attempts on more
#: candidates; it cannot produce a false positive, because a decoded candidate
#: still has to satisfy a real detector and its validator.
_MIN_BASE64_CHARS = 12

_BASE64_TOKEN = re.compile(
    rf"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{{{_MIN_BASE64_CHARS},}}={{0,2}}(?![A-Za-z0-9+/_=\-])"
)


def normalize_for_scan(text: str) -> str:
    """Return the canonical string used for match offsets and redaction.

    NFKD plus invisible stripping defeats compatibility/zero-width evasions.
    Detection may additionally inspect derived views, but all reported spans
    always point into this canonical string so redaction never has to rewrite
    unrelated letters or reconstruct offsets after decoding.
    """
    return normalize_for_redaction(text)


def _plain_hits(text: str) -> Iterator[tuple[str, int, int]]:
    """Yield validated PII hits in one already-normalized detection view."""
    for pii_type, pattern, validator in _PII_PATTERNS:
        for match in pattern.finditer(text):
            if validator is not None and not validator(match.group()):
                continue
            yield pii_type, match.start(), match.end()


def _decoded_pii_type(text: str) -> str | None:
    """Return the first real PII family found after decoding an encoded token."""
    canonical = normalize_for_scan(text)
    for view in (canonical, fold_homoglyphs(canonical)):
        for pii_type, _, _ in _plain_hits(view):
            return pii_type
    return None


def _absorbable(
    seen_ranges: list[tuple[int, int]], start: int, end: int, may_absorb: bool
) -> set[tuple[int, int]] | None:
    """Spans `(start, end)` may replace, or None if it must be dropped.

    An empty set means no conflict. A populated set means the new span strictly
    contains those existing ones and should take their place.

    ``may_absorb`` is for encoded candidates, whose span is the whole encoded
    token and so can legitimately contain hits the plain view already found.
    Discarding such a candidate wholesale left the *rest* of its plaintext
    unredacted: scanning `AKIAIOSFODNN7EXAMPLE%2B1%20415%20555%202671` once
    redacted only the key, and scanning that output again then redacted the
    phone — a leak and a breach of the idempotence contract in the same bug.

    Partial overlap is refused either way. Two spans that cross without
    containment have no correct merge: widening to their union would redact
    text neither detector claimed, and picking one silently drops the other.
    """
    overlapping = {
        (existing_start, existing_end)
        for existing_start, existing_end in seen_ranges
        if not (end <= existing_start or start >= existing_end)
    }
    if not overlapping:
        return set()
    if not may_absorb:
        return None
    contains_all = all(
        start <= existing_start and end >= existing_end
        for existing_start, existing_end in overlapping
    )
    return overlapping if contains_all else None


def _append_match(
    matches: list[PIIMatch],
    seen_ranges: list[tuple[int, int]],
    *,
    pii_type: str,
    canonical: str,
    start: int,
    end: int,
    may_absorb: bool = False,
) -> None:
    """Record a hit, unless an earlier one already claims that span."""
    absorbed = _absorbable(seen_ranges, start, end, may_absorb)
    if absorbed is None:
        return
    if absorbed:
        matches[:] = [match for match in matches if (match.start, match.end) not in absorbed]
        seen_ranges[:] = [span for span in seen_ranges if span not in absorbed]

    matches.append(
        PIIMatch(
            pii_type=pii_type,
            value=_mask(canonical[start:end]),
            start=start,
            end=end,
        )
    )
    seen_ranges.append((start, end))


def _scan_percent_encoded(
    canonical: str,
    matches: list[PIIMatch],
    seen_ranges: list[tuple[int, int]],
) -> None:
    for candidate in _PERCENT_TOKEN.finditer(canonical):
        raw = candidate.group()
        # Both decodings, because `+` is ambiguous and the encoder does not say
        # which it meant. In `application/x-www-form-urlencoded` a `+` is a
        # space; elsewhere it is a literal `+`. `quote_plus("+1 415 555 2671")`
        # produces `%2B1+415+555+2671`, which plain `unquote` turns into
        # `+1+415+555+2671` — separators the phone detector does not accept, so
        # the number survived. Trying both costs one extra decode and removes
        # the guess.
        decodings = []
        for decoder in (unquote, unquote_plus):
            try:
                decoded = decoder(raw, encoding="utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
            if decoded != raw and decoded not in decodings:
                decodings.append(decoded)
        if not decodings:
            continue
        pii_type = next(
            (found for found in map(_decoded_pii_type, decodings) if found is not None), None
        )
        if pii_type is not None:
            _append_match(
                matches,
                seen_ranges,
                pii_type=pii_type,
                canonical=canonical,
                start=candidate.start(),
                end=candidate.end(),
                may_absorb=True,
            )


def _decode_base64_token(raw: str) -> str | None:
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw + padding, altchars=b"-_", validate=True)
        return decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _scan_base64_encoded(
    canonical: str,
    matches: list[PIIMatch],
    seen_ranges: list[tuple[int, int]],
) -> None:
    for candidate in _BASE64_TOKEN.finditer(canonical):
        decoded = _decode_base64_token(candidate.group())
        if decoded is None:
            continue
        pii_type = _decoded_pii_type(decoded)
        if pii_type is not None:
            _append_match(
                matches,
                seen_ranges,
                pii_type=pii_type,
                canonical=canonical,
                start=candidate.start(),
                end=candidate.end(),
                may_absorb=True,
            )


def scan_for_pii(text: str) -> list[PIIMatch]:
    canonical = normalize_for_scan(text)
    matches: list[PIIMatch] = []
    seen_ranges: list[tuple[int, int]] = []

    # Direct canonical view first, then a same-length confusable view. The
    # latter is detection-only: offsets still index the original canonical text.
    for pii_type, start, end in _plain_hits(canonical):
        _append_match(
            matches,
            seen_ranges,
            pii_type=pii_type,
            canonical=canonical,
            start=start,
            end=end,
        )

    # `fold_homoglyphs` is a `str.translate` over single-character targets, so
    # the folded view is index-for-index with `canonical`. That is what lets a
    # hit found here be redacted from `canonical` without recomputing offsets;
    # `test_pii_evasion_normalization.py` holds the map to it.
    folded = fold_homoglyphs(canonical)
    if folded != canonical:
        for pii_type, start, end in _plain_hits(folded):
            _append_match(
                matches,
                seen_ranges,
                pii_type=pii_type,
                canonical=canonical,
                start=start,
                end=end,
            )

    _scan_percent_encoded(canonical, matches, seen_ranges)
    _scan_base64_encoded(canonical, matches, seen_ranges)

    matches.sort(key=lambda item: item.start)
    return matches


def redact(text: str, matches: list[PIIMatch] | None = None) -> str:
    """Return canonical ``text`` with every match replaced by a typed placeholder.

    Output is always the NFKD/invisible-stripped canonical string. Homoglyph and
    encoded detection are views only, so legitimate non-Latin prose is never
    globally rewritten and an encoded finding replaces only its original token.
    """
    if matches is None:
        matches = scan_for_pii(text)

    result = normalize_for_scan(text)
    for match in sorted(matches, key=lambda item: item.start, reverse=True):
        placeholder = f"[REDACTED:{match.pii_type}]"
        result = result[: match.start] + placeholder + result[match.end :]

    return result


def scan_and_redact(text: str) -> tuple[str, list[PIIMatch]]:
    matches = scan_for_pii(text)
    return redact(text, matches), matches
