"""Canonical secret classification and credential-shape policy (#1159).

One module owns the two questions every redaction consumer asks, so approval
evidence, the Sentinel PII filter, and the log redactor cannot drift apart:

1. **Is this field name a credential name?** (:func:`is_secret_key_name`) —
   used by ``redact_approval_value`` before durable approval persistence, and
   by the generic secret-assignment shape below. Classification is
   *segment*-based: a name counts as sensitive when one of its
   separator/camel-case delimited segments names a credential family. A
   substring hit would corrupt ordinary names ("tokenizer", "secretary",
   "monkey") the same way it corrupts diagnostic JSON, so substrings never
   match. A trailing ``id``/``identifier``/``arn`` segment marks an
   *identifier*, not a secret: ``aws_access_key_id`` holding an ``AKIA...``
   access key ID stays readable, because an access key ID is not a reusable
   credential — the paired 40-character secret is.

2. **What does a credential look like in free text?** — the compiled shapes
   below are the single source shared by ``security/redact.py`` (log
   pipelines) and ``security/sentinel/pii_filter.py`` (post-call output):
   the Slack ``xox*`` token family, the AWS secret access key, and the
   generic secret assignment.

Invariant (#1159): security/approval/audit evidence may preserve the fact and
type of an action or violation without persisting reusable credentials,
private keys, or raw secret-bearing arguments. Every helper in this module is
conservative about *reusable* material and deliberately preserves identifiers
and ordinary prose — arbitrary high-entropy or user text is never destroyed
except through the documented shapes plus the separate, named entropy policy
in ``security/redact.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

__all__ = [
    "AWS_SECRET_ACCESS_KEY_PATTERN",
    "SECRET_ASSIGNMENT_PATTERN",
    "SECRET_FIELD_SEGMENTS",
    "SLACK_TOKEN_PATTERN",
    "is_secret_key_name",
    "iter_secret_assignment_value_spans",
    "looks_like_aws_secret_access_key",
]

# ─── Field-name classification ────────────────────────────────────────────────

#: Name segments that mark a value as credential material. ``key`` is the
#: segment that makes ``api_key``, ``access_key``, ``private_key``, ``ssh_key``,
#: ``signing_key``, and a bare ``key`` sensitive; compound no-separator forms
#: such as ``apikey`` are spelled out because nothing splits them.
SECRET_FIELD_SEGMENTS = frozenset(
    {
        "authorization",
        "credential",
        "credentials",
        "password",
        "passwd",
        "pwd",
        "apikey",
        "secret",
        "token",
        "key",
    }
)

#: Segments that soften the family into an identifier when they come last:
#: ``token_id``, ``key_arn``, ``aws_access_key_id`` name *identifiers*. An
#: identifier is not a reusable credential, so the value survives.
_IDENTIFIER_QUALIFIERS = frozenset({"id", "identifier", "arn"})

#: Families where the identifier escape applies. ``secret_id`` /
#: ``password_id`` stay sensitive (a Vault AppRole ``secret_id`` is a live
#: credential whatever its suffix says), because their segments are not in
#: this set.
_SOFT_SEGMENTS = frozenset({"key", "token"})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _segments(name: str) -> list[str]:
    """Split a field name into lower-case segments on separators and camel case.

    Trailing digits are stripped per segment (``key2`` names the same family
    as ``key``); a segment that is only digits disappears here.
    """
    parts: list[str] = []
    for part in _NON_ALNUM.split(_CAMEL_BOUNDARY.sub(" ", name)):
        part = part.rstrip("0123456789").lower()
        if part:
            parts.append(part)
    return parts


def is_secret_key_name(name: str) -> bool:
    """Return True when a field/argument *name* claims credential material.

    Segment-based, so ``private_key``, ``ssh_key``, ``signing_key``, a bare
    ``key``, and camelCase ``apiKey`` are sensitive while ``tokenizer``,
    ``secretary``, ``monkey``, and ``author`` are not. A trailing identifier
    qualifier (``id``/``identifier``/``arn``) preserves identifier-valued
    fields such as ``aws_access_key_id`` unless a strong family segment
    (``secret``, ``password``, ``credential``, ...) is present.
    """
    lowered = str(name).strip().lower()
    if lowered == "pat":  # GitHub personal access token spelled bare
        return True
    segments = _segments(lowered)
    if not segments:
        return False
    strong = [s for s in segments if s in SECRET_FIELD_SEGMENTS and s not in _SOFT_SEGMENTS]
    if strong:
        return True
    if not any(s in _SOFT_SEGMENTS for s in segments):
        return False
    return segments[-1] not in _IDENTIFIER_QUALIFIERS


# ─── Credential shapes shared by both redaction engines ──────────────────────

#: Slack token family: bot (``xoxb``), user (``xoxp``), app/workspace
#: (``xoxa``), refresh (``xoxr``), session (``xoxs``). The left boundary
#: keeps a longer word containing ``xox`` from matching; the tail is
#: deliberately greedy — everything hyphen-joined to the token is token.
SLACK_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])xox[abprs]-[A-Za-z0-9_-]{10,}")

#: AWS secret access key: exactly 40 characters of the base64-ish AWS charset,
#: delimited by characters outside that charset. :func:`looks_like_aws_secret_access_key`
#: is the validator that keeps this shape from swallowing identifiers: a git
#: commit SHA (40 single-case hex characters) and 20-character ``AKIA...``
#: access key IDs (identifiers, not secrets) do not satisfy it.
AWS_SECRET_ACCESS_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"
)

#: Generic secret assignment: a credential-named identifier followed by
#: ``=``/``:`` and a quoted or bare value. Only the *value* span is reported,
#: so a more specific detector that fired inside the value (an AKIA key, a
#: JWT) keeps its more precise label, and the audit trail keeps the field
#: name. The value floor is 8 characters — the same false-positive bar the
#: password detectors already use; shorter values are left alone.
#
#: The name's left boundary is load-bearing twice: inside a long unbroken
#: token run every offset would otherwise start a fresh (failing) name
#: attempt — a linear-time pass with a 65x constant that the AC-36 scaling
#: ratio caught — and it pins the name to the start of its own token.
#: The bare value's boundary guard is load-bearing once: a bare value that
#: is itself immediately followed by another assignment (``error:
#: db_password=X``, ``config: signing_key = "X"``) would be swallowed by an
#: outer match whose name is regex-valid but names no credential family, and
#: the real assignment would never be reached. The guard fails that outer
#: match so the innermost assignment is the one found. A single trailing
#: ``=`` (base64 padding) does not fire the guard — nothing follows it — and
#: quoted values never hit it. What the guard gives up: an *unquoted* value
#: containing a mid-value ``=`` (``key=abc=def12345``) no longer matches as
#: one assignment; quote such values, or rely on a more specific detector
#: for the credential inside.
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<name>[A-Za-z_][A-Za-z0-9_.-]{0,64})\s*[=:]\s*"
    r"(?:'(?P<sq>[^'\n]{8,4096})'|\"(?P<dq>[^\"\n]{8,4096})\""
    r"|(?P<bare>(?![A-Za-z0-9_.-]+\s*[=:]\s*[^\s])[^\s'\"]{8,4096}))"
)


def looks_like_aws_secret_access_key(candidate: str) -> bool:
    """Validate a 40-character charset run as a plausible AWS secret access key.

    Requires mixed case and at least one digit — which excludes every
    single-case 40-character hex run, i.e. git commit SHAs, the dominant
    look-alike in logs. Length is exactly 40: the paired ``AKIA...`` access
    key ID (20 characters) can never match, and identifiers stay identifiers.
    """
    return (
        len(candidate) == 40
        and any(c.isupper() for c in candidate)
        and any(c.islower() for c in candidate)
        and any(c.isdigit() for c in candidate)
    )


def iter_secret_assignment_value_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield ``(start, end)`` spans of values in secret-named assignments.

    The name is validated with :func:`is_secret_key_name`, so the shape fires
    on ``my_secret = '...'``, ``db_password: ...``, ``client_key=...`` and
    their spacing/case/quoting variants, but never on ``tokenizer = ...`` or
    ``https://...``. For quoted values the span covers the value *inside* the
    quotes — the quote characters stay in the output, the credential does
    not. Only the value is reported — the field name stays readable in the
    redacted output.
    """
    for match in SECRET_ASSIGNMENT_PATTERN.finditer(text):
        if not is_secret_key_name(match.group("name")):
            continue
        # Exactly one of the three value groups participated.
        value_group = next(g for g in ("sq", "dq", "bare") if match.group(g) is not None)
        yield match.start(value_group), match.end(value_group)
