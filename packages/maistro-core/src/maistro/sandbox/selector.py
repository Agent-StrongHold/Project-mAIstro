"""Sandbox selector — picks the strongest available backend that satisfies policy.

Fail-closed: if no backend meets the minimum tier, refuses with a clear error.
No silent downgrade.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.sandbox.policy import _TIER_ORDER, IsolationTier, WorkloadPolicy, tier_satisfies
from maistro.sandbox.protocol import SandboxConfig, SandboxProtocol

logger = logging.getLogger("maistro.sandbox.selector")


class NoSuitableBackendError(Exception):
    """Raised when no registered backend meets the workload's minimum isolation."""


class TierMismatchError(ValueError):
    """Raised when a backend is registered at a tier it does not declare."""


class SandboxSelector:
    """Registry of sandbox backends. Selects the best one for a given policy."""

    def __init__(self) -> None:
        self._backends: dict[IsolationTier, SandboxProtocol] = {}

    def register(self, tier: IsolationTier, backend: SandboxProtocol) -> None:
        """Register a backend at a tier it declares it can actually provide.

        The tier used to be whatever the caller passed, and nothing compared it
        to the backend. `register("vm", FakeSandboxBackend())` was therefore a
        legal way to make in-process `subprocess.run` satisfy `UNTRUSTED_CODE`,
        whose entire stated reason is that model-generated code must run behind
        a VM boundary. A fail-open of that shape defeats every check downstream
        of it, because everything downstream trusts the tier.

        So the backend declares its own tier and a mismatch is refused. A
        caller may still register a weaker backend than it hoped for; it cannot
        relabel one as stronger.
        """
        declared = getattr(backend, "tier", None)
        if declared is not None and declared != tier:
            raise TierMismatchError(
                f"{type(backend).__name__} declares tier {declared!r} but was registered as "
                f"{tier!r}; a backend cannot be relabelled into a stronger boundary"
            )
        self._backends[tier] = backend
        logger.info("sandbox_backend_registered tier=%s backend=%s", tier, type(backend).__name__)

    @property
    def available_tiers(self) -> list[IsolationTier]:
        """Registered tiers, strongest first."""
        return [t for t in _TIER_ORDER if t in self._backends]

    @property
    def strongest_tier(self) -> IsolationTier | None:
        tiers = self.available_tiers
        return tiers[0] if tiers else None

    def select(self, policy: WorkloadPolicy) -> tuple[IsolationTier, SandboxProtocol]:
        """Select the strongest available backend that satisfies the policy.

        Returns (tier, backend). Raises NoSuitableBackendError if nothing qualifies.
        """
        for tier in _TIER_ORDER:
            if tier not in self._backends:
                continue
            if tier_satisfies(tier, policy.min_tier):
                return tier, self._backends[tier]

        available = ", ".join(self.available_tiers) or "none"
        raise NoSuitableBackendError(
            f"Workload requires min_tier={policy.min_tier!r} ({policy.reason}). "
            f"Available: {available}. No backend qualifies — execution refused."
        )

    def build_config(self, policy: WorkloadPolicy, **overrides: Any) -> SandboxConfig:
        """Build a SandboxConfig from a policy.

        Overrides may only make the sandbox *tighter*. The policy fields are
        named ``max_memory_mb``, ``max_timeout_s`` and ``network_allowed`` —
        ceilings and a permission, not defaults — so an override is clamped
        against them rather than replacing them. Without the clamp,
        ``build_config(UNTRUSTED_CODE, network=True)`` would hand model-
        generated code an egress-capable sandbox, against a policy whose
        stated reason is that it must run behind a VM boundary.
        """
        memory_mb = min(int(overrides.get("memory_mb", policy.max_memory_mb)), policy.max_memory_mb)
        timeout_s = min(int(overrides.get("timeout_s", policy.max_timeout_s)), policy.max_timeout_s)
        network = bool(overrides.get("network", policy.network_allowed)) and policy.network_allowed
        return SandboxConfig(
            memory_mb=memory_mb,
            timeout_s=timeout_s,
            network=network,
            min_isolation=policy.min_tier,
        )
