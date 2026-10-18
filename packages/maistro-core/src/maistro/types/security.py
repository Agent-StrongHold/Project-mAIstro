"""Security types: Warden verdicts, audit entries, trust tiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from maistro.security.redact import redact as _redact


class TrustTier(StrEnum):
    """Trust tiers for agents and skills."""

    SKULL = "skull"
    T4 = "t4"
    T3 = "t3"
    T2 = "t2"
    T1 = "t1"
    T0 = "t0"


class Provenance(StrEnum):
    """Origin of an agent or skill. Permanent — never changes after creation."""

    BUILTIN = "builtin"
    ADMIN = "admin"
    USER = "user"
    COMMUNITY = "community"


@dataclass(frozen=True)
class WardenVerdict:
    """Result of Warden threat detection scan."""

    clean: bool = True
    sanitized_content: str | None = None
    blocked: bool = False
    flags: tuple[str, ...] = ()
    confidence: float = 1.0
    reasoning_trace: str | None = None


@dataclass(frozen=True)
class Violation:
    """A single policy violation."""

    boundary: str
    rule: str
    severity: str = "error"
    detail: str = ""
    repair_action: str | None = None

    def __post_init__(self) -> None:
        # #1159: this Violation rides the persisted AuditEntry's violations
        # tuple. The shipped Pg/SQLite audit stores happen not to serialize
        # that tuple today, but the invariant may not rest on that omission:
        # detail is scrubbed AT CONSTRUCTION so any future store that persists
        # violations inherits redacted text. (The sentinel-side Violation in
        # `maistro.security._types` applies the identical rule.)
        object.__setattr__(self, "detail", _redact(self.detail))


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log entry — every boundary crossing is logged."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    boundary: str = ""
    user_id: str = ""
    org_id: str = ""
    team_id: str = ""
    agent_id: str = ""
    tool_name: str | None = None
    verdict: str = "allowed"
    violations: tuple[Violation, ...] = ()
    trace_id: str = ""
    request_id: str = ""
    detail: str = ""
    # Correlation and route metadata are identifiers only; boundary consumers
    # must never put scanned content in an audit entry. (#1139: the Turing
    # ingress composes these onto the canonical record.)
    route: str = ""
    action: str = ""
    policy_version: str = ""
    workspace_id: str = ""
    project_id: str = ""
    run_id: str = ""
    invocation_id: str = ""
    content_sha256: str = ""
    content_length: int = 0

    def __post_init__(self) -> None:
        """Reject malformed non-secret audit correlation evidence."""
        if self.policy_version and not self.policy_version.strip():
            raise ValueError("policy_version must not be whitespace")
        if self.content_sha256 and (
            len(self.content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        if self.content_length < 0:
            raise ValueError("content_length must not be negative")


@dataclass(frozen=True)
class GateResult:
    """Result of Gate input processing."""

    sanitized_text: str = ""
    improved_text: str | None = None
    clarifying_questions: tuple[Any, ...] = ()
    warden_verdict: WardenVerdict = field(default_factory=WardenVerdict)
    blocked: bool = False
    block_reason: str = ""
    strike_number: int = 0
    scrutiny_level: str = "normal"
    locked_until: str = ""
    account_disabled: bool = False


@dataclass(frozen=True)
class ClarifyingQuestion:
    """A question the Gate asks to improve the user's request."""

    question: str = ""
    options: tuple[str, ...] = ()
    allow_freetext: bool = True
