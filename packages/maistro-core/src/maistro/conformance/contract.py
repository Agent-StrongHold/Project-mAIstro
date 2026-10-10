"""Types and versioning for the extension-family conformance suite (issue #965).

One extension family (provider, connector, tool) proves the same cross-cutting
platform semantics as supported built-ins by running the *same* check bodies
against its own implementation. This module is the contract half of that
framework: which checks exist, what a backend leg is, and what makes a
conformance *claim* valid.

A claim is deliberately narrow. It is valid only when every check in the
contract actually executed and passed against a subject whose declared contract
version is compatible with :data:`CONTRACT_VERSION`, and when the contract's
real-backend leg actually ran. A skipped check never supports a claim, and a
skipped required real-backend leg is fatal when the runner is asked to require
real backends — a report that says "skipped" is never allowed to say
"conforms". No check inspects source text: each one drives the subject's real
code through the canonical platform seams and asserts what the platform
actually did.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: The contract this suite enforces. Reports carry both values verbatim so a
#: conformance statement always names the exact contract and version it tested.
CONTRACT_ID = "maistro.extension-conformance"
CONTRACT_VERSION = "1.0.0"

#: Set to a truthy value in CI to make a skipped required real-backend leg a
#: hard failure instead of a documented skip. Mirrors the established
#: ``MAISTRO_REQUIRE_PG_LEGS`` convention.
ENV_REQUIRE_REAL_BACKENDS = "MAISTRO_REQUIRE_REAL_BACKEND_LEGS"

#: Importlib entry-point group a subject uses to opt in, so
#: ``maistro conformance`` discovers third-party implementations without a
#: hand-maintained list.
ENTRY_POINT_GROUP = "maistro.conformance"


class ConformanceFailure(RuntimeError):
    """A conformance run failed its fatal contract (failures or required skips)."""


class SubjectFamily(StrEnum):
    """The extension families the shared suite runs against."""

    PROVIDER = "provider"
    CONNECTOR = "connector"
    TOOL = "tool"


#: Every family the suite supports. ``run_registered_subjects`` reports the
#: families a registration set covers, so an install that claims extension
#: conformance can see which families its subjects actually exercise.
ALL_FAMILIES: tuple[SubjectFamily, ...] = (
    SubjectFamily.PROVIDER,
    SubjectFamily.CONNECTOR,
    SubjectFamily.TOOL,
)


class CheckStatus(StrEnum):
    """Outcome of one check body against one subject."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class CheckId(StrEnum):
    """The cross-cutting semantics every family must obey.

    Each id names a behavioral probe, not a text scan: the check drives the
    subject's real code and asserts platform-observable outcomes.
    """

    #: A plaintext secret handed to the extension is refused, or never
    #: survives into the extension's prepared configuration.
    SECRETS_PLAINTEXT_REFUSED = "secrets.plaintext-refused"
    #: Canonical secret-reference resolution: credentials flow only through
    #: the Binding-scoped credential authority, and the plaintext never
    #: reaches a persisted snapshot or a repr.
    SECRETS_CREDENTIAL_REF_RESOLUTION = "secrets.credential-ref-resolution"
    #: Undeclared egress is refused before any socket connects.
    EGRESS_UNDECLARED_BLOCKED = "egress.undeclared-blocked"
    #: A declared origin is reachable through the guarded seam.
    EGRESS_DECLARED_ALLOWED = "egress.declared-allowed"
    #: Tenant/workspace scope propagates onto the persisted effect record.
    SCOPE_PROPAGATION = "scope.propagation"
    #: Provider errors normalize to the canonical Invocation ledger states.
    ERROR_NORMALIZATION = "errors.normalization"
    #: Cancellation lands as UNKNOWN ambiguity evidence, never fake closure.
    CANCELLATION_NORMALIZATION = "errors.cancellation-normalization"
    #: A hung effect is deadline-cancellable (cooperative cancellation).
    DEADLINE_ENFORCEMENT = "errors.deadline-enforcement"
    #: Usage is reported once with provenance; missing usage is marked
    #: unreported rather than measured zero.
    USAGE_AND_PROVENANCE = "usage.provenance"
    #: Direct model/tool/network bypass attempts are refused before dispatch.
    BYPASS_REFUSED = "bypass.refused"


class BackendKind(StrEnum):
    """Whether a backend leg exercised real infrastructure or a stand-in."""

    MOCK = "mock"
    REAL = "real"


@dataclass(frozen=True)
class BackendLeg:
    """One executed backend: what the checks actually ran against."""

    name: str
    kind: BackendKind
    detail: str = ""


#: The in-memory leg: canonical stores, credential pools and invocation
#: services stand in for their durable twins. Always executable.
MEMORY_BACKEND = BackendLeg(
    name="memory", kind=BackendKind.MOCK, detail="in-memory canonical stores"
)


@dataclass(frozen=True)
class SubjectDescriptor:
    """Who is under test and what contract version it declares."""

    name: str
    family: SubjectFamily
    declared_contract_version: str


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome, with execution evidence attached."""

    check_id: CheckId
    status: CheckStatus
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id.value,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def version_compatible(declared: str) -> bool:
    """Whether a subject's declared contract version can be claimed against.

    Same major version means the subject agreed to the same breaking-contract
    generation; anything else refuses to conform even if every check passes,
    because a claim names the contract it actually tested.
    """
    return bool(declared.strip()) and _major(declared) == _major(CONTRACT_VERSION)


@dataclass
class ConformanceReport:
    """The auditable result of running the shared suite against one subject.

    ``claim_valid`` is the narrow gate downstream consumers rely on: true only
    when the subject's declared version is compatible, every contract check
    executed and passed, and the real-backend leg was not skipped. A subject
    cannot buy a claim with a partial run.
    """

    descriptor: SubjectDescriptor
    backend: BackendLeg
    results: list[CheckResult] = field(default_factory=list)
    contract_id: str = CONTRACT_ID
    contract_version: str = CONTRACT_VERSION
    real_backend_executed: bool = False

    def result(self, check_id: CheckId) -> CheckResult | None:
        for entry in self.results:
            if entry.check_id is check_id:
                return entry
        return None

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(entry for entry in self.results if entry.status is CheckStatus.FAIL)

    @property
    def skipped(self) -> tuple[CheckResult, ...]:
        return tuple(entry for entry in self.results if entry.status is CheckStatus.SKIP)

    @property
    def declared_version_compatible(self) -> bool:
        return version_compatible(self.descriptor.declared_contract_version)

    @property
    def claim_valid(self) -> bool:
        """Whether this report supports a "conforms" statement at all.

        Every check must have run and passed — a FAIL fails it, and so does a
        SKIP: an unexecuted path is exactly the "never-run path" the issue
        forbids conformance claims from resting on.
        """
        return (
            self.declared_version_compatible
            and self.real_backend_executed
            and bool(self.results)
            and all(entry.status is CheckStatus.PASS for entry in self.results)
        )

    @property
    def conforms(self) -> bool:
        """Every executed check passed (skips allowed, claim not implied)."""
        return bool(self.results) and not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "declared_contract_version": self.descriptor.declared_contract_version,
            "subject": self.descriptor.name,
            "family": self.descriptor.family.value,
            "backend": {
                "name": self.backend.name,
                "kind": self.backend.kind.value,
                "detail": self.backend.detail,
            },
            "real_backend_executed": self.real_backend_executed,
            "claim_valid": self.claim_valid,
            "conforms": self.conforms,
            "results": [entry.as_dict() for entry in self.results],
        }


def require_real_backends_from_env(env: dict[str, str] | None = None) -> bool:
    """Read the fatal-real-backend-legs switch (default off, like PG legs)."""
    source = os.environ if env is None else env
    return source.get(ENV_REQUIRE_REAL_BACKENDS, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


__all__ = [
    "ALL_FAMILIES",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "ENTRY_POINT_GROUP",
    "ENV_REQUIRE_REAL_BACKENDS",
    "MEMORY_BACKEND",
    "BackendKind",
    "BackendLeg",
    "CheckId",
    "CheckResult",
    "CheckStatus",
    "ConformanceFailure",
    "ConformanceReport",
    "SubjectDescriptor",
    "SubjectFamily",
    "require_real_backends_from_env",
    "version_compatible",
]
