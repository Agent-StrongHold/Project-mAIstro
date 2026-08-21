"""Security subsystem type definitions.

Ported from Stronghold types/security.py and types/auth.py.
org_id stripped for single-tenant maistro-engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class IdentityKind(StrEnum):
    USER = "user"
    SYSTEM = "system"
    SERVICE_ACCOUNT = "service_account"
    INTERACTIVE_AGENT = "interactive_agent"


@dataclass
class AuthContext:
    user_id: str = ""
    username: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    team_id: str = ""
    kind: IdentityKind = IdentityKind.USER
    auth_method: str = ""
    on_behalf_of: str = ""

    def can_use_tool(self, tool_name: str, permission_table: PermissionTable) -> bool:
        allowed_roles = permission_table.get(tool_name)
        if allowed_roles is None:
            return True
        return bool(self.roles & allowed_roles)


SYSTEM_AUTH = AuthContext(
    user_id="system",
    username="system",
    roles=frozenset({"admin", "user"}),
    kind=IdentityKind.SYSTEM,
    auth_method="system",
)

PermissionTable = dict[str, frozenset[str]]


@dataclass
class WardenVerdict:
    """Outcome of a Warden scan.

    ``blocked`` is a severity tier, not a duplicate of ``not clean``: it is
    True whenever any reject-pattern flag hits (detector sets it; heuristic/
    semantic/LLM layers never do -- those return ``blocked=False`` even
    though they are also non-clean). ``blocked=True`` therefore implies
    ``clean=False``, never the reverse. Consumers choose the threshold their
    boundary warrants: the Gate refuses user input on ANY non-clean verdict
    (strictest boundary), while dag-shape evaluation now also hard-blocks a
    proposed DAG on ANY non-clean verdict (a single-pattern injection is not
    "fine" for a DAG that will run unattended). Both behaviors are asserted
    by tests -- do not repurpose the field without updating both consumers.
    """

    clean: bool = True
    blocked: bool = False
    flags: tuple[str, ...] = ()
    confidence: float = 0.0
    reasoning_trace: str | None = None


@dataclass
class Violation:
    boundary: str
    rule: str
    severity: str
    detail: str = ""
    repair_action: str | None = None


@dataclass
class SentinelVerdict:
    allowed: bool = True
    repaired: bool = False
    repaired_data: dict[str, Any] | None = None
    violations: tuple[Violation, ...] = ()


@dataclass
class AuditEntry:
    boundary: str
    user_id: str
    team_id: str = ""
    tool_name: str = ""
    verdict: str = ""
    violations: tuple[Violation, ...] = ()
    detail: str = ""
    agent_id: str = ""


@dataclass
class ClarifyingQuestion:
    question: str
    options: tuple[str, ...] = ()
    allow_freetext: bool = True


@dataclass
class GateResult:
    sanitized_text: str = ""
    warden_verdict: WardenVerdict | None = None
    blocked: bool = False
    block_reason: str = ""
    strike_number: int = 0
    scrutiny_level: str = "normal"
    locked_until: str = ""
    account_disabled: bool = False
    clarifying_questions: tuple[ClarifyingQuestion, ...] = ()


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    burst_limit: int = 10
    enabled: bool = True


@runtime_checkable
class AuditLog(Protocol):
    async def log(self, entry: AuditEntry) -> None: ...


@runtime_checkable
class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> dict[str, Any]: ...
