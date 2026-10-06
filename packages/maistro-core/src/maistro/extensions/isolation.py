"""Sandbox isolation profiles for extension execution (#970, M9-G2).

The governed registry (M9-B) decides *whether* extension code may run; this
module decides *where and how*: a host-selected isolation profile, derived
from the extension's declared authority and its trust evidence, compiled onto
the :mod:`maistro.sandbox` substrate (ADR-093 / SPEC-190) so the declared
permissions are enforced at a real execution boundary — network namespaces,
mount namespaces, kernel rlimits — rather than represented in metadata.

The contract, in order:

1. :func:`select_isolation_profile` intersects what the extension was granted
   with what the host's :class:`ExtensionSandboxPolicy` permits. Undeclared
   authority stays denied even when the policy would allow it; policy
   ceilings are ceilings, never defaults a manifest can widen.
2. The trusted **in-process tier is a selection outcome, not a fallback**:
   it is chosen only when the operator's policy explicitly allows it for the
   publisher, the trust evidence is good, and the extension asked for no
   sandbox-enforced authority. A sandbox that fails to start raises
   :class:`ExtensionSandboxStartFailure` — nothing retries in process.
3. :class:`ExtensionSandboxRunner` executes through a
   :class:`~maistro.sandbox.SandboxSelector`, so the boundary is whichever
   real backend the host evidenced (bubblewrap today, a VM tier when wired)
   and startup fails closed when none qualifies. Resource kills and timeouts
   become :class:`ExtensionSandboxViolation` records carrying the extension
   id and version, kept in a bounded :class:`SandboxViolationLog` and logged
   — attributable, operationally visible.

Honesty notes. The boundary denies whole categories (undeclared egress, host
paths outside the profile's mounts, processes beyond the PID ceiling) by
construction; what it cannot do is attribute a workload's *own* failed
connection attempt inside a deny-by-default sandbox to "network violation" —
a nonzero exit is reported on the outcome, and only kernel-evidenced kills
(signals, timeouts) become violations. And per ADR-093 a bubblewrap-tier
boundary is a guardrail, not a containment guarantee for hostile code; the
tier ladder and mode floors in :mod:`maistro.sandbox.policy` govern how much
boundary an execution mode demands, and this module never selects below them.
And ``max_file_mb`` is a per-file ceiling (``RLIMIT_FSIZE``), not an aggregate
storage quota: a workspace quota needs backing this substrate does not provide.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import signal
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from maistro.extensions.authority import normalize_permission
from maistro.extensions.service import ExtensionCodeLoader, LoadedExtension
from maistro.extensions.trust import TrustReport
from maistro.extensions.types import ExtensionInstallRecord, ExtensionManifest
from maistro.sandbox.network import (
    DENY_ALL,
    EgressGrant,
    EgressMode,
    EgressNotEnforceableError,
)
from maistro.sandbox.policy import ExecutionMode, IsolationTier, WorkloadPolicy
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance, SandboxProtocol
from maistro.sandbox.selector import NoSuitableBackendError, SandboxSelector

logger = logging.getLogger("maistro.extensions.isolation")

#: The permission token that requests outbound network authority. Without it
#: the profile's egress grant is deny-all, whatever the host policy would
#: permit: undeclared capability fails closed (#970).
NETWORK_OUTBOUND_PERMISSION = "network.outbound"

#: The permission token that requests writable filesystem authority. Without
#: it the sandbox's only writable surface is its own ephemeral workspace.
FILESYSTEM_WRITE_PERMISSION = "filesystem.write"

#: The permission token that requests read access to host paths beyond the
#: sandbox's own workspace. Sandbox-scoped like every filesystem authority
#: (ADR-093): it forces the sandboxed tier and mounts exactly the policy's
#: declared paths, read-only.
FILESYSTEM_READ_PERMISSION = "filesystem.read"

#: Tiers a sandboxed extension profile may demand, strongest first. The fake
#: tier is deliberately absent: it provides no isolation and must never carry
#: extension code (ADR-093: there is no bare-subprocess tier).
REAL_ISOLATION_TIERS: tuple[IsolationTier, ...] = ("vm", "gvisor", "container", "bubblewrap")

#: Default boundary for sandboxed extension code: ADR-093's Tier 3, the
#: weakest boundary that exists at all. The execution-mode floor does the
#: raising — unattended execution demands Tier 2 (gVisor) on top of this,
#: and a host without it refuses rather than downgrades.
DEFAULT_MIN_TIER: IsolationTier = "bubblewrap"

T = TypeVar("T")


class ExtensionIsolationError(RuntimeError):
    """Base class for extension isolation failures."""


class ExtensionIsolationRefused(ExtensionIsolationError):
    """No isolation profile exists for this extension.

    Selection is a security decision: an extension whose trust evidence
    fails has no profile at all — not a weaker one.
    """


class ExtensionSandboxStartFailure(ExtensionIsolationError):
    """The sandbox could not be started, so nothing ran.

    Fail-closed by definition: there is no in-process fallback, no weaker
    tier, and no second attempt on a different boundary. The exception
    carries the extension identity so the operational log line is
    attributable without unpacking it.
    """

    def __init__(self, extension_id: str, version: str, reason: str) -> None:
        super().__init__(
            f"sandbox startup failed for {extension_id} {version}: {reason} "
            "(fail-closed; extension code did not run)"
        )
        self.extension_id = extension_id
        self.version = version
        self.reason = reason


class ExtensionSandboxExecutionFailure(ExtensionIsolationError):
    """The sandbox started but the backend failed before a result existed.

    Deliberately **not** a subclass of :class:`ExtensionSandboxStartFailure`:
    startup had already succeeded, so extension code may have run and had
    side effects inside the sandbox. The message never claims otherwise —
    a caller must not treat this failure as safe to retry merely because
    the type resembles a startup failure.
    """

    def __init__(self, extension_id: str, version: str, reason: str) -> None:
        super().__init__(
            f"sandbox execution failed for {extension_id} {version}: {reason} "
            "(mid-execution; extension code may already have run)"
        )
        self.extension_id = extension_id
        self.version = version
        self.reason = reason


class ExtensionRiskTier(StrEnum):
    """How much authority the extension's granted set asks for.

    Risk is derived from *what was granted*, never from who published it —
    publisher identity is the trust axis (:class:`TrustReport`), and the two
    are deliberately separate inputs to selection.
    """

    #: Reads mediated by the host only. Eligible for the trusted in-process
    #: tier when policy and trust allow.
    STANDARD = "standard"
    #: Declares network egress or sandbox-scoped filesystem authority — the
    #: grants a sandbox boundary exists to contain. Never eligible in process.
    ELEVATED = "elevated"


@dataclass(frozen=True)
class ExtensionSandboxPolicy:
    """The host's standing sandbox policy for extensions (#970).

    Every resource number here is a **ceiling**: a profile carries these
    values and per-execution overrides may tighten them, never widen them.
    """

    #: Minimum isolation tier demanded of the backend for sandboxed
    #: extensions. Defaults to the weakest real boundary; the execution
    #: mode's floor (ADR-093 decision 6) raises it for unattended execution.
    min_tier: IsolationTier = DEFAULT_MIN_TIER
    max_memory_mb: int = 512
    max_cpu_cores: float = 1.0
    #: PID ceiling — the fork-bomb bound, enforced as ``RLIMIT_NPROC``.
    max_processes: int = 64
    max_timeout_s: int = 120
    #: Per-file size ceiling inside the sandbox (``RLIMIT_FSIZE``): no single
    #: file the workload writes may exceed this. It is deliberately **not** an
    #: aggregate storage quota — unboundedly many just-under-limit files can
    #: still accumulate in the sandbox workspace, so a host that needs a hard
    #: disk-exhaustion bound adds a quota-backed filesystem or a usage monitor
    #: on top; this field must not be read as promising one (#970 review).
    max_file_mb: int = 64
    #: The network ceiling for sandboxed extensions. Extensions never get
    #: ``HOST`` egress: sharing the host namespace whole with third-party
    #: code is the exact configuration ADR-093 deprecates. Deny or a scoped
    #: allowlist only — and a backend that cannot filter destinations
    #: refuses the grant rather than approximating it.
    egress: EgressGrant = DENY_ALL
    #: Explicit trusted in-process tier. ``False`` — the default — means no
    #: extension ever runs in process, whatever it declares or whoever
    #: signed it. Flipping this on is an operator decision, narrowed by
    #: :attr:`in_process_publishers`, never a default and never a fallback.
    allow_in_process: bool = False
    #: Publishers whose trusted extensions may use the in-process tier.
    in_process_publishers: frozenset[str] = frozenset()
    #: Host paths a ``filesystem.write`` extension may mount writable. An
    #: extension that did not declare ``filesystem.write`` gets none of
    #: these; an extension that did gets exactly these and nothing more.
    writable_host_paths: tuple[str, ...] = ()
    #: Host paths a ``filesystem.read`` extension may mount read-only. Same
    #: intersection rule as the writable set: granted ``filesystem.read``
    #: gets exactly these paths, read-only; no grant, none at all.
    readable_host_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_tier not in REAL_ISOLATION_TIERS:
            raise ValueError(
                f"min_tier must be one of {REAL_ISOLATION_TIERS}, got {self.min_tier!r}; "
                "the fake tier provides no isolation and must never carry extension code"
            )
        if self.egress.mode is EgressMode.HOST:
            raise ValueError(
                "extensions never receive HOST egress: sharing the host network "
                "namespace whole with third-party code is the configuration "
                "ADR-093 deprecates. Grant a scoped allowlist, or deny."
            )
        if self.allow_in_process and not self.in_process_publishers:
            raise ValueError(
                "allow_in_process without in_process_publishers would make the "
                "trusted tier universal; name the publishers it covers"
            )


@dataclass(frozen=True)
class ExtensionIsolationProfile:
    """The enforced execution contract for one extension version.

    Frozen once selected: the runner compiles this into a
    :class:`~maistro.sandbox.SandboxConfig` and nothing — not the caller,
    not the workload — edits it afterwards.

    On an in-process profile the sandbox-shaped resource fields are zero and
    ``min_tier`` is ``None``: there is no sandbox contract to describe, and
    the zeros fail dead if the profile is ever routed at a sandbox by
    mistake. The containment *is* the recorded operator decision.
    """

    extension_id: str
    version: str
    publisher: str
    risk_tier: ExtensionRiskTier
    #: True only for the explicit trusted in-process tier. Decided at
    #: selection, from policy; never reachable as a fallback.
    in_process: bool
    #: Minimum tier the backend must evidence. ``None`` for in-process.
    min_tier: IsolationTier | None
    #: The execution mode the floors were computed under. ``None`` reads as
    #: autonomous — the stricter answer (ADR-093 decision 6).
    mode: ExecutionMode | None
    egress: EgressGrant
    memory_mb: int
    cpu_cores: float
    max_processes: int
    timeout_s: int
    max_file_mb: int
    #: Host paths mounted writable beyond the sandbox's own workspace.
    writable_paths: tuple[str, ...]
    #: Host paths mounted read-only beyond the backend's standard binds.
    readable_paths: tuple[str, ...]
    #: The selection inputs, recorded as evidence: which authorities were
    #: granted, what was denied as undeclared, and why the tier was chosen.
    selection_reason: str

    def workload_policy(self) -> WorkloadPolicy:
        """The substrate policy this profile compiles to.

        Extensions are third-party code, so sandboxed profiles are
        ``untrusted``: the execution-mode floor applies on top of the
        profile's own tier, and an unattended run demands the stronger
        boundary (ADR-093 decision 6) rather than the weaker one.
        """
        if self.in_process or self.min_tier is None:
            raise ExtensionIsolationError(
                f"{self.extension_id} {self.version} runs in process; "
                "it has no sandbox workload policy"
            )
        return WorkloadPolicy(
            min_tier=self.min_tier,
            network_allowed=self.egress.grants_network,
            max_memory_mb=self.memory_mb,
            max_timeout_s=self.timeout_s,
            reason=(
                f"extension {self.extension_id} {self.version} "
                f"risk={self.risk_tier.value}: {self.selection_reason}"
            ),
            mode=self.mode,
            untrusted=True,
            egress=self.egress,
        )


def risk_tier_for(granted: Sequence[str]) -> ExtensionRiskTier:
    """Derive the risk tier from the granted permission set.

    Every filesystem permission is sandbox-enforced authority — read and
    write alike (ADR-093 / the capabilities contract in
    ``docs/extensions/capabilities.md``) — so either excludes the trusted
    in-process tier: in process there is no boundary to scope those paths
    with, and a host read would be arbitrary rather than sandbox-scoped.
    """
    sandbox_enforced = {
        NETWORK_OUTBOUND_PERMISSION,
        FILESYSTEM_READ_PERMISSION,
        FILESYSTEM_WRITE_PERMISSION,
    }
    if sandbox_enforced & set(granted):
        return ExtensionRiskTier.ELEVATED
    return ExtensionRiskTier.STANDARD


def _in_process_profile(
    manifest: ExtensionManifest,
    *,
    risk: ExtensionRiskTier,
    mode: ExecutionMode | None,
) -> ExtensionIsolationProfile:
    """The explicit trusted tier: no sandbox contract, recorded decision."""
    return ExtensionIsolationProfile(
        extension_id=manifest.extension_id,
        version=manifest.version,
        publisher=manifest.publisher,
        risk_tier=risk,
        in_process=True,
        min_tier=None,
        mode=mode,
        egress=DENY_ALL,
        memory_mb=0,
        cpu_cores=0.0,
        max_processes=0,
        timeout_s=0,
        max_file_mb=0,
        writable_paths=(),
        readable_paths=(),
        selection_reason=(
            f"trusted in-process tier: explicit operator policy for publisher "
            f"{manifest.publisher!r}, risk={risk.value} (no sandbox-enforced "
            "authority granted), trust verified; not a fallback"
        ),
    )


def _sandboxed_profile(
    manifest: ExtensionManifest,
    *,
    granted_tokens: tuple[str, ...],
    policy: ExtensionSandboxPolicy,
    mode: ExecutionMode | None,
    network_granted: bool,
    fs_read_granted: bool,
    fs_write_granted: bool,
    risk: ExtensionRiskTier,
) -> ExtensionIsolationProfile:
    """The sandboxed tier: the policy's ceilings, narrowed by the grant."""
    egress = policy.egress if network_granted else DENY_ALL
    writable_paths = policy.writable_host_paths if fs_write_granted else ()
    readable_paths = policy.readable_host_paths if fs_read_granted else ()
    granted_view = ", ".join(granted_tokens) if granted_tokens else "none"
    return ExtensionIsolationProfile(
        extension_id=manifest.extension_id,
        version=manifest.version,
        publisher=manifest.publisher,
        risk_tier=risk,
        in_process=False,
        min_tier=policy.min_tier,
        mode=mode,
        egress=egress,
        memory_mb=policy.max_memory_mb,
        cpu_cores=policy.max_cpu_cores,
        max_processes=policy.max_processes,
        timeout_s=policy.max_timeout_s,
        max_file_mb=policy.max_file_mb,
        writable_paths=writable_paths,
        readable_paths=readable_paths,
        selection_reason=(
            f"sandboxed at {policy.min_tier}; risk={risk.value}; granted=[{granted_view}]; "
            f"egress={'policy allowlist' if network_granted else 'undeclared — denied'}; "
            f"writable_host_paths={len(writable_paths)} "
            f"({'filesystem.write granted' if fs_write_granted else 'undeclared — none'}); "
            f"readable_host_paths={len(readable_paths)} "
            f"({'filesystem.read granted' if fs_read_granted else 'undeclared — none'})"
        ),
    )


def _intersect_grants_with_declaration(
    manifest: ExtensionManifest, granted: Sequence[str]
) -> tuple[str, ...]:
    """Normalized grant tokens, narrowed to what the manifest declared.

    The third selection rule guards the grant source itself: a grant token
    the manifest never declared (a mismatched preview/record, a replayed
    install record against a newer manifest) is dropped with a warning, so a
    record can never widen authority past the declaration — undeclared means
    denied, whatever the record says.
    """
    declared = {normalize_permission(token) for token in manifest.permissions}
    tokens = tuple(normalize_permission(token) for token in granted)
    undeclared = sorted({token for token in tokens if token not in declared})
    if undeclared:
        logger.warning(
            "%s %s: dropping granted permissions the manifest never declared: %s",
            manifest.extension_id,
            manifest.version,
            ", ".join(undeclared),
        )
        tokens = tuple(token for token in tokens if token in declared)
    return tokens


def _in_process_eligible(
    manifest: ExtensionManifest, policy: ExtensionSandboxPolicy, risk: ExtensionRiskTier
) -> bool:
    """Whether the explicit trusted in-process tier applies to this version.

    Every condition is a named policy decision (publisher allowlist, the
    opt-in flag, standard risk only) — the tier is a choice made up front,
    never a fallback after sandbox failure.
    """
    return bool(
        policy.allow_in_process
        and manifest.publisher in policy.in_process_publishers
        and risk is ExtensionRiskTier.STANDARD
    )


def select_isolation_profile(
    manifest: ExtensionManifest,
    *,
    granted: Sequence[str],
    trust: TrustReport,
    policy: ExtensionSandboxPolicy,
    mode: ExecutionMode | None = None,
) -> ExtensionIsolationProfile:
    """Select the isolation profile for one extension version.

    ``granted`` is the host's approved authority set — the install record's
    ``granted_permissions`` once active, the manifest's declared set for a
    pre-grant preview. ``trust`` is the registry's trust evaluation; a
    failed one has no profile at all.

    The intersection rules that make undeclared access impossible:

    - network egress exists only if the grant declares
      :data:`NETWORK_OUTBOUND_PERMISSION` **and** the policy's ceiling
      allows it — the ceiling's scoped allowlist is what the sandbox gets;
    - writable host paths exist only if the grant declares
      :data:`FILESYSTEM_WRITE_PERMISSION`, and then exactly
      :attr:`ExtensionSandboxPolicy.writable_host_paths`;
    - read-only host paths exist only if the grant declares
      :data:`FILESYSTEM_READ_PERMISSION`, and then exactly
      :attr:`ExtensionSandboxPolicy.readable_host_paths`. Both filesystem
      permissions are sandbox-enforced authority: they select the sandboxed
      tier and are never eligible in process.

    A third rule guards the grant source itself: ``granted`` is intersected
    with the manifest's declared permissions before any of the checks above.
    A grant token the manifest never declared (a mismatched preview/record,
    a replayed install record against a newer manifest) is dropped with a
    warning, so a record can never widen authority past the declaration —
    undeclared means denied, whatever the record says.
    """
    tokens = _intersect_grants_with_declaration(manifest, granted)

    if not trust.trusted:
        raise ExtensionIsolationRefused(
            f"no isolation profile for {manifest.extension_id} {manifest.version}: "
            f"trust evaluation failed ({'; '.join(trust.failures) or 'unspecified'})"
        )

    risk = risk_tier_for(tokens)
    if _in_process_eligible(manifest, policy, risk):
        return _in_process_profile(manifest, risk=risk, mode=mode)

    return _sandboxed_profile(
        manifest,
        granted_tokens=tokens,
        policy=policy,
        mode=mode,
        network_granted=NETWORK_OUTBOUND_PERMISSION in tokens,
        fs_read_granted=FILESYSTEM_READ_PERMISSION in tokens,
        fs_write_granted=FILESYSTEM_WRITE_PERMISSION in tokens,
        risk=risk,
    )


def build_sandbox_config(
    profile: ExtensionIsolationProfile,
    *,
    env: dict[str, str] | None = None,
    memory_mb: int | None = None,
    cpu_cores: float | None = None,
    max_processes: int | None = None,
    timeout_s: int | None = None,
    max_file_mb: int | None = None,
) -> SandboxConfig:
    """Compile a profile into the substrate's sandbox config.

    Every numeric argument here is an override that may only *tighten* the
    profile; passing a larger value gets the profile ceiling instead. The
    egress grant is never overridable at all — it was frozen at selection.
    """
    if profile.in_process or profile.min_tier is None:
        raise ExtensionIsolationError(
            f"{profile.extension_id} {profile.version} runs in process; "
            "there is no sandbox to configure"
        )
    return SandboxConfig(
        memory_mb=profile.memory_mb if memory_mb is None else min(memory_mb, profile.memory_mb),
        cpu_cores=(profile.cpu_cores if cpu_cores is None else min(cpu_cores, profile.cpu_cores)),
        max_processes=(
            profile.max_processes
            if max_processes is None
            else min(max_processes, profile.max_processes)
        ),
        timeout_s=(profile.timeout_s if timeout_s is None else min(timeout_s, profile.timeout_s)),
        max_file_mb=(
            profile.max_file_mb if max_file_mb is None else min(max_file_mb, profile.max_file_mb)
        ),
        network=profile.egress.grants_network,
        writable_paths=list(profile.writable_paths),
        read_paths=list(profile.readable_paths),
        env=dict(env or {}),
        min_isolation=profile.min_tier,
        egress=profile.egress,
    )


class ViolationKind(StrEnum):
    """The boundary events a sandbox run can evidence."""

    #: The kernel killed the workload for a resource ceiling (memory, CPU
    #: budget, file size, processes) or the wall-clock timeout stopped it.
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    #: No qualifying backend, or the backend failed to start the sandbox.
    #: Nothing ran — recorded because a start failure is an operational
    #: event on exactly the extensions that require isolation.
    SANDBOX_START_FAILURE = "sandbox_start_failure"
    #: The sandbox ran but the backend failed mid-execution; no result.
    SANDBOX_FAILURE = "sandbox_failure"

    #: The sandbox ran and the workload finished, but the backend could not
    #: tear the sandbox down. Reported even though the workload itself may
    #: have succeeded: a live environment or undeleted workspace behind a
    #: "success" is a leak the caller must not mistake for clean (#970).
    SANDBOX_TEARDOWN_FAILURE = "sandbox_teardown_failure"


@dataclass(frozen=True)
class ExtensionSandboxViolation:
    """One boundary event, attributed to an extension identity/version."""

    extension_id: str
    version: str
    kind: ViolationKind
    detail: str
    at: datetime
    sandbox_id: str | None = None


class SandboxViolationLog:
    """Bounded, queryable record of sandbox boundary events.

    The operational half of "violations are attributable and visible":
    every violation is also logged at warning level with its extension
    identity; this log is what a dashboard or an operator query reads to
    answer "which extension/version is tripping its ceilings?".
    """

    def __init__(self, *, capacity: int = 1000) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._entries: deque[ExtensionSandboxViolation] = deque(maxlen=capacity)
        # Escalation state lives outside the bounded deque: eviction must not
        # change when the threshold fires or how often it does (the deque is
        # an operator query window, not the escalation counter).
        self._violation_counts: dict[tuple[str, str], int] = {}
        self._escalated: set[tuple[str, str]] = set()

    def record(self, violation: ExtensionSandboxViolation) -> None:
        logger.warning(
            "extension_sandbox_violation extension=%s version=%s kind=%s detail=%s sandbox=%s",
            violation.extension_id,
            violation.version,
            violation.kind.value,
            violation.detail,
            violation.sandbox_id or "-",
        )
        self._entries.append(violation)
        key = (violation.extension_id, violation.version)
        count = self._violation_counts[key] = self._violation_counts.get(key, 0) + 1
        if count >= _ESCALATION_THRESHOLD and key not in self._escalated:
            self._escalated.add(key)
            logger.warning(
                "extension_repeated_sandbox_violations extension=%s version=%s count=%d "
                "— candidate for disable/quarantine through canonical controls (M9-G4)",
                violation.extension_id,
                violation.version,
                count,
            )

    def violations_for(
        self, extension_id: str, version: str | None = None
    ) -> tuple[ExtensionSandboxViolation, ...]:
        """Violations for one extension, optionally narrowed to a version.

        The query an operator surface (or the M9-G4 quarantine trigger) uses
        to answer "which extension/version keeps tripping its boundaries?".
        Escalation itself does not read this method — the per-identity count
        is kept outside the bounded deque (:meth:`record`) so eviction from
        the operator query window can never change when the threshold fires —
        but the quarantine flow that the escalation warning names consumes
        this query, and its in-tree callers are the conformance suites
        (packages/maistro-core/tests/extensions/) until that flow lands.
        """
        return tuple(
            v
            for v in self._entries
            if v.extension_id == extension_id and (version is None or v.version == version)
        )

    def all(self) -> tuple[ExtensionSandboxViolation, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True)
class ExtensionSandboxOutcome:
    """What one sandboxed execution produced, with its boundary evidence."""

    extension_id: str
    version: str
    sandbox_id: str
    backend: str
    tier: IsolationTier
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    egress_mode: EgressMode
    violations: tuple[ExtensionSandboxViolation, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.violations


#: Repeated violations at which the operational log escalates from a per-event
#: warning to a named "candidate for quarantine" line — the health evidence
#: M9-G4's disable/quarantine flow consumes.
_ESCALATION_THRESHOLD = 3

#: Kill signals the kernel sends when a boundary fires, mapped to what the
#: profile's ceilings say they mean. ``SIGKILL`` is ambiguous between the
#: memory ceiling and the PID ceiling (the kernel does not say which), so
#: the detail names both rather than guessing one.
_LIMIT_SIGNALS: dict[int, str] = {
    getattr(signal, name): meaning
    for name, meaning in (
        ("SIGKILL", "memory ceiling or PID ceiling (SIGKILL)"),
        ("SIGXCPU", "CPU budget exhausted (SIGXCPU)"),
        ("SIGXFSZ", "file-size ceiling hit (SIGXFSZ)"),
    )
    # Windows' ``signal`` module lacks these POSIX-only signals; a sandbox
    # execution tier is meaningless there, so absent names are simply omitted
    # and import stays safe for consumers that never run sandboxes.
    if hasattr(signal, name)
}


class ExtensionSandboxRunner:
    """Executes extension work under an isolation profile.

    The runner owns the fail-closed path. Selection or spawn failure raises
    :class:`ExtensionSandboxStartFailure` and records a
    :data:`ViolationKind.SANDBOX_START_FAILURE` violation; there is no
    weaker-tier retry and no in-process fallback. A backend that fails
    *after* the sandbox is up raises the separate
    :class:`ExtensionSandboxExecutionFailure` instead, whose contract does
    not assert that extension code never ran. The in-process tier is
    reachable only through :meth:`run_in_process` with a profile that was
    *selected* as in-process.
    """

    def __init__(
        self,
        selector: SandboxSelector,
        *,
        violations: SandboxViolationLog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._selector = selector
        self._violations = violations if violations is not None else SandboxViolationLog()
        self._clock = clock if clock is not None else _utc_now

    @property
    def violations(self) -> SandboxViolationLog:
        return self._violations

    async def exec(
        self,
        profile: ExtensionIsolationProfile,
        command: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        memory_mb: int | None = None,
        cpu_cores: float | None = None,
        max_processes: int | None = None,
        timeout_s: int | None = None,
        max_file_mb: int | None = None,
    ) -> ExtensionSandboxOutcome:
        """Run ``command`` inside a sandbox compiled from ``profile``."""
        if profile.in_process:
            raise ValueError(
                f"{profile.extension_id} {profile.version} is an in-process profile; "
                "it has no sandbox to execute commands in — use run_in_process"
            )
        config = build_sandbox_config(
            profile,
            env=env,
            memory_mb=memory_mb,
            cpu_cores=cpu_cores,
            max_processes=max_processes,
            timeout_s=timeout_s,
            max_file_mb=max_file_mb,
        )
        started = time.monotonic()
        try:
            selected_tier, backend = self._selector.select(profile.workload_policy())
        except NoSuitableBackendError as exc:
            raise self._start_failure(profile, f"no qualifying isolation backend: {exc}") from exc
        except EgressNotEnforceableError as exc:
            # A grant the backend cannot enforce is refused, never approximated
            # with the host namespace whole (#77) — for an extension that
            # refusal is the fail-closed startup path.
            raise self._start_failure(profile, str(exc)) from exc

        try:
            instance = await backend.spawn(config=config)
        except Exception as exc:
            raise self._start_failure(
                profile, f"backend {type(backend).__name__} failed to start: {exc}"
            ) from exc

        try:
            result = await backend.exec(instance, list(command), timeout_s=config.timeout_s)
        except Exception as exc:
            self._record(
                profile,
                ViolationKind.SANDBOX_FAILURE,
                f"backend {type(backend).__name__} failed mid-execution: {exc}",
                sandbox_id=instance.id,
            )
            raise ExtensionSandboxExecutionFailure(
                profile.extension_id,
                profile.version,
                f"backend {type(backend).__name__} failed mid-execution: {exc}",
            ) from exc
        finally:
            # Teardown must be cancellation-safe: CancelledError is a
            # BaseException, so an ``except Exception`` path skips cleanup and
            # leaves the sandbox child running. Shielded so a second cancel
            # delivered mid-teardown cannot abandon the destroy either: the
            # shielded inner coroutine keeps running out-of-band even though
            # this task's cancellation still surfaces through the suppress.
            with contextlib.suppress(asyncio.CancelledError):
                teardown_violation = await asyncio.shield(self._destroy(profile, backend, instance))

        violations = (
            *self._classify_limits(profile, config, instance, result),
            *((teardown_violation,) if teardown_violation else ()),
        )
        outcome = ExtensionSandboxOutcome(
            extension_id=profile.extension_id,
            version=profile.version,
            sandbox_id=instance.id,
            backend=instance.backend,
            # The selector's adjudicated tier — registration refuses a backend
            # labelled stronger than it is, so this is the tier that counts.
            tier=selected_tier,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
            duration_ms=int((time.monotonic() - started) * 1000),
            egress_mode=config.egress.mode,
            violations=violations,
        )
        logger.info(
            "extension_sandbox_executed extension=%s version=%s tier=%s backend=%s "
            "egress=%s exit=%s violations=%d",
            outcome.extension_id,
            outcome.version,
            outcome.tier,
            outcome.backend,
            outcome.egress_mode.value,
            outcome.exit_code,
            len(outcome.violations),
        )
        return outcome

    async def run_in_process(
        self, profile: ExtensionIsolationProfile, call: Callable[[], Awaitable[T] | T]
    ) -> T:
        """Run a host-loaded extension callable under the trusted tier.

        Refuses anything but a profile that was *selected* as in-process:
        the tier cannot be entered by asking twice, only by having been
        granted at selection time.
        """
        if not profile.in_process:
            raise ExtensionIsolationError(
                f"{profile.extension_id} {profile.version} is a sandboxed profile; "
                "in-process execution requires the explicit trusted tier, selected "
                "up front — it is never a fallback"
            )
        logger.info(
            "extension_in_process_start extension=%s version=%s publisher=%s",
            profile.extension_id,
            profile.version,
            profile.publisher,
        )
        try:
            result = call()
            if inspect.isawaitable(result):
                return await result
            return result
        finally:
            logger.info(
                "extension_in_process_done extension=%s version=%s",
                profile.extension_id,
                profile.version,
            )

    # -- internals ---------------------------------------------------------

    def _start_failure(
        self, profile: ExtensionIsolationProfile, reason: str
    ) -> ExtensionSandboxStartFailure:
        self._record(profile, ViolationKind.SANDBOX_START_FAILURE, reason, sandbox_id=None)
        return ExtensionSandboxStartFailure(profile.extension_id, profile.version, reason)

    def _record(
        self,
        profile: ExtensionIsolationProfile,
        kind: ViolationKind,
        detail: str,
        *,
        sandbox_id: str | None,
    ) -> ExtensionSandboxViolation:
        violation = ExtensionSandboxViolation(
            extension_id=profile.extension_id,
            version=profile.version,
            kind=kind,
            detail=detail,
            at=self._clock(),
            sandbox_id=sandbox_id,
        )
        self._violations.record(violation)
        return violation

    def _classify_limits(
        self,
        profile: ExtensionIsolationProfile,
        config: SandboxConfig,
        instance: object,
        result: ExecResult,
    ) -> tuple[ExtensionSandboxViolation, ...]:
        """Kernel-evidenced boundary events, recorded and attributed.

        Only evidence counts: a signal the kernel sent for a ceiling, or the
        wall-clock timeout. A workload's ordinary nonzero exit is its own
        business and is reported on the outcome, not recorded as a violation.

        The *effective* ``config`` is classified, not the profile: per-run
        overrides may have tightened the ceilings, and the evidence must name
        the values that actually killed the workload.
        """
        violations: list[ExtensionSandboxViolation] = []
        if result.timed_out:
            violations.append(
                self._limit_violation(profile, config, instance, "wall-clock timeout")
            )
        # Signal death arrives in either convention: negative (the subprocess
        # wait convention, when the harness sees the process itself die) or
        # wrapped as 128+signal (the shell convention, when a wrapper like
        # bwrap relays its child's death — #970 conformance expects the
        # wrapped form from the real backend). Normalize before matching.
        sig = -result.exit_code if result.exit_code < 0 else result.exit_code - 128
        if sig > 0:
            meaning = _LIMIT_SIGNALS.get(sig)
            if meaning is not None:
                violations.append(self._limit_violation(profile, config, instance, meaning))
        return tuple(violations)

    def _limit_violation(
        self,
        profile: ExtensionIsolationProfile,
        config: SandboxConfig,
        instance: object,
        meaning: str,
    ) -> ExtensionSandboxViolation:
        violation = ExtensionSandboxViolation(
            extension_id=profile.extension_id,
            version=profile.version,
            kind=ViolationKind.RESOURCE_LIMIT_EXCEEDED,
            detail=(
                f"{meaning}; effective ceilings: memory={config.memory_mb}MB, "
                f"cpu={config.cpu_cores} cores, file={config.max_file_mb}MB, "
                f"pids={config.max_processes}, timeout={config.timeout_s}s"
            ),
            at=self._clock(),
            sandbox_id=getattr(instance, "id", None),
        )
        self._violations.record(violation)
        return violation

    async def _destroy(
        self,
        profile: ExtensionIsolationProfile,
        backend: SandboxProtocol,
        instance: SandboxInstance,
    ) -> ExtensionSandboxViolation | None:
        """Tear the sandbox down; record and return a violation on failure.

        A teardown failure must not be silent in the outcome: the backend may
        still hold a live environment or an undeleted workspace, so the run is
        attributed a :attr:`ViolationKind.SANDBOX_TEARDOWN_FAILURE` violation,
        which also makes ``outcome.succeeded`` false (#970).
        """
        try:
            await backend.destroy(instance)
        except Exception as exc:
            logger.exception("extension_sandbox_destroy_failed sandbox=%s", instance.id)
            return self._record(
                profile,
                ViolationKind.SANDBOX_TEARDOWN_FAILURE,
                f"backend {type(backend).__name__} failed to destroy sandbox: {exc}",
                sandbox_id=instance.id,
            )
        return None


class InProcessExtensionLoader(ExtensionCodeLoader):
    """The trusted tier's :class:`ExtensionCodeLoader` adapter (#970).

    A deployment that has explicitly allowed the in-process tier for a
    publisher wires this — one instance per authorized extension version,
    built at activation time when the host has the selected profile in hand —
    as the loader the install service calls. Activation runs through the
    host-supplied ``activate`` callable *inside* the runner's in-process
    evidence path, so the tier that skips the sandbox does not skip the
    operational logging.

    Fail-closed by construction: a record that does not match the profile
    this loader was built for — id, version, and the manifest's publisher,
    which is the axis the trusted tier's authorization is keyed on
    (``policy.in_process_publishers``) — is refused, and a sandboxed profile
    is refused outright — in-process activation cannot be reached by asking
    a sandboxed loader, only by being wired for it. The binding is identity-
    level, not byte-level: that the payload is the artifact the record's
    manifest digest names is the governed install flow's contract upstream
    (M9-B), not this adapter's to re-verify.
    """

    def __init__(
        self,
        runner: ExtensionSandboxRunner,
        profile: ExtensionIsolationProfile,
        activate: Callable[[ExtensionInstallRecord, bytes], Awaitable[object] | object],
    ) -> None:
        if not profile.in_process:
            raise ExtensionIsolationError(
                f"InProcessExtensionLoader requires an in-process profile for "
                f"{profile.extension_id} {profile.version}; got a sandboxed one"
            )
        self._runner = runner
        self._profile = profile
        self._activate = activate

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        if (
            record.extension_id != self._profile.extension_id
            or record.version != self._profile.version
            or record.manifest.publisher != self._profile.publisher
        ):
            raise ExtensionIsolationError(
                f"InProcessExtensionLoader is wired for {self._profile.extension_id} "
                f"{self._profile.version} by publisher {self._profile.publisher!r}, "
                f"not {record.extension_id} {record.version} by "
                f"{record.manifest.publisher!r}"
            )
        result = await self._runner.run_in_process(
            self._profile, lambda: self._activate(record, payload)
        )
        activated = LoadedExtension(record.extension_id, record.version)
        activated.result = result  # type: ignore[attr-defined]
        return activated


def _utc_now() -> datetime:
    return datetime.now(UTC)
