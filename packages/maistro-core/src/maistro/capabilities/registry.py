"""Capability registry: defines slots, registers providers (installed/inactive),
activates/enables them, and resolves the live provider with fallback. Thread-safe."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.security.trust import UNVETTED_TRUST_TIER, is_known_trust_tier, trust_rank

if TYPE_CHECKING:
    from maistro.capabilities.protocols import CapabilityProvider

logger = logging.getLogger("maistro.capabilities.registry")


@dataclass
class _SlotState:
    spec: SlotSpec
    providers: dict[str, CapabilityProvider] = field(default_factory=dict)
    # These facts belong to the host registry, not provider-reported metadata.
    provider_trust: dict[str, str] = field(default_factory=dict)
    provider_provenance: dict[str, str] = field(default_factory=dict)
    active: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ProviderReplacementDecision:
    """Authenticated, human-readable authority to replace a provider.

    Discovery has no way to construct this decision. The composition root or
    an admin workflow must supply both an actor and a reason explicitly.
    """

    approved_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise ValueError("approved_by must be a non-empty string")
        if not self.reason.strip():
            raise ValueError("reason must be a non-empty string")


class CapabilityRegistry:
    """Holds slot definitions + provider state. Thread-safe via reentrant lock."""

    def __init__(self) -> None:
        self._slots: dict[str, _SlotState] = {}
        self._lock = threading.RLock()

    def define(self, spec: SlotSpec) -> None:
        """Declare a slot. Re-declaring the same slot is a no-op.

        Rediscovery must not reset host state: an identical redefinition keeps
        the installed providers, their host-owned trust and provenance, the
        active choice and the enabled flag. A conflicting redefinition is
        refused rather than silently swapping the slot's policy underneath the
        providers already installed for it.
        """
        with self._lock:
            existing = self._slots.get(spec.name)
            if existing is not None:
                if existing.spec != spec:
                    raise ValueError(f"Slot '{spec.name}' is already defined differently")
                return
            self._slots[spec.name] = _SlotState(spec=spec)
        logger.debug("Defined slot: %s (%s)", spec.name, spec.fallback_policy)

    def _slot(self, slot: str) -> _SlotState:
        state = self._slots.get(slot)
        if state is None:
            raise KeyError(f"Unknown slot '{slot}'")
        return state

    def register(
        self,
        provider: CapabilityProvider,
        *,
        trust_tier: str | None = None,
        provenance: str = "",
    ) -> bool:
        """Register an installed provider without replacing host trust state.

        A duplicate rediscovery is a no-op. The effective tier is host-owned:
        a host-supplied tier is authority, a foreign provider never
        self-certifies (it lands on the unvetted floor), and a malformed
        declaration is not laundered into a usable tier -- it stays unknown,
        and an unknown tier is not admissible for selection, for the baseline
        path, or for boot validation. The built-in package keeps its explicit
        tiers for compatibility with the core baseline providers.
        """
        with self._lock:
            state = self._slot(provider.slot)
            if provider.name in state.providers:
                return False
            effective = self._effective_tier(provider, trust_tier)
            state.providers[provider.name] = provider
            state.provider_trust[provider.name] = effective
            state.provider_provenance[provider.name] = provenance or type(provider).__module__
        logger.debug(
            "Registered provider %s -> slot %s (inactive, tier=%s)",
            provider.name,
            provider.slot,
            effective,
        )
        return True

    @staticmethod
    def _effective_tier(provider: CapabilityProvider, host_tier: str | None) -> str:
        """The host-owned effective trust tier for an admitted provider.

        A provider's own tier is metadata: it can lower a provider's standing
        but never raise it. Only a host-supplied tier can promote one. A
        declaration the host does not recognize is kept verbatim so the
        refusal is visible instead of being laundered into a usable tier.
        """
        if host_tier is not None:
            if is_known_trust_tier(host_tier):
                return str(host_tier).strip().lower()
            return UNVETTED_TRUST_TIER
        if not type(provider).__module__.startswith("maistro."):
            return UNVETTED_TRUST_TIER
        declared = getattr(provider, "trust_tier", None)
        if is_known_trust_tier(declared):
            return str(declared).strip().lower()
        return declared if isinstance(declared, str) else ""

    def replace(
        self,
        provider: CapabilityProvider,
        *,
        decision: ProviderReplacementDecision,
    ) -> None:
        """Replace a provider only through an explicit governed decision."""
        with self._lock:
            state = self._slot(provider.slot)
            if provider.name not in state.providers:
                raise KeyError(f"Provider '{provider.name}' is not installed")
            state.providers[provider.name] = provider
        logger.info(
            "Replaced provider %s -> slot %s by %s: %s",
            provider.name,
            provider.slot,
            decision.approved_by,
            decision.reason,
        )

    def provider_trust(self, slot: str, name: str) -> tuple[str, str] | None:
        """Return host-owned trust and provenance for an installed provider."""
        with self._lock:
            state = self._slot(slot)
            if name not in state.providers:
                return None
            return state.provider_trust[name], state.provider_provenance[name]

    def activate(self, slot: str, provider_name: str) -> None:
        with self._lock:
            state = self._slot(slot)
            if provider_name not in state.providers:
                raise KeyError(f"Provider '{provider_name}' not installed for slot '{slot}'")
            state.active = provider_name
        logger.info("Activated %s for slot %s", provider_name, slot)

    def set_enabled(self, slot: str, enabled: bool) -> None:
        with self._lock:
            self._slot(slot).enabled = enabled

    def is_enabled(self, slot: str) -> bool:
        with self._lock:
            return self._slot(slot).enabled

    def slots(self) -> list[str]:
        """All defined slot names (for listing/introspection)."""
        with self._lock:
            return list(self._slots.keys())

    def installed(self, slot: str) -> list[str]:
        with self._lock:
            return list(self._slot(slot).providers.keys())

    def active_name(self, slot: str) -> str | None:
        with self._lock:
            return self._slot(slot).active

    def provider(self, slot: str, name: str) -> CapabilityProvider | None:
        """Return the installed provider instance by name, or None if not installed.

        The live instance (not just its name) — so callers can share a single
        stateful provider (e.g. the approval inbox) across the action that awaits
        it and the route that resolves it. Raises KeyError on an unknown slot.
        """
        with self._lock:
            return self._slot(slot).providers.get(name)

    async def resolve(self, slot: str) -> CapabilityProvider | None:
        """Resolve the provider to use, or None to apply the slot's fallback.

        disabled → fallback; else active (or first by trust tier); healthcheck;
        unhealthy → fallback. Fallback = baseline provider (if policy BASELINE)
        else None. A provider whose host-owned tier is not a known tier is not
        admissible: it is refused on the live path and on the baseline path
        alike, so malformed metadata is never handed back under another name.
        """
        with self._lock:
            state = self._slot(slot)
            spec = state.spec
            enabled = state.enabled
            chosen_name = state.active
            providers = dict(state.providers)
            trust = dict(state.provider_trust)

        if not enabled:
            return self._baseline_provider(spec, providers, trust)

        if chosen_name is None:
            candidates = sorted(
                providers.values(),
                key=lambda p: (
                    trust_rank(trust.get(p.name)),
                    p.name,
                ),
            )
            chosen = candidates[0] if candidates else None
        else:
            chosen = providers.get(chosen_name)

        if chosen is None or not is_known_trust_tier(trust.get(chosen.name)):
            return self._baseline_provider(spec, providers, trust)

        health = await chosen.healthcheck()
        if not health.healthy:
            logger.warning(
                "Provider %s unhealthy for slot %s: %s", chosen.name, slot, health.detail
            )
            fb = self._baseline_provider(spec, providers, trust)
            return fb if (fb is not None and fb.name != chosen.name) else None
        return chosen

    @staticmethod
    def _baseline_provider(
        spec: SlotSpec,
        providers: dict[str, CapabilityProvider],
        trust: dict[str, str],
    ) -> CapabilityProvider | None:
        """The declared baseline, when the policy allows it and it is admissible.

        The baseline is provider-named metadata too, so it clears the same
        host-owned tier check as the live path: an unknown-tier baseline is
        refused rather than returned as a usable fallback.
        """
        if spec.fallback_policy is not FallbackPolicy.BASELINE or not spec.baseline_provider:
            return None
        baseline = providers.get(spec.baseline_provider)
        if baseline is None or not is_known_trust_tier(trust.get(baseline.name)):
            return None
        return baseline

    def validate_boot(self) -> None:
        """Raise if any HARD_REQUIRED slot cannot be satisfied at boot.

        Checks presence (a provider is installed), that the slot is enabled,
        and that at least one installed provider carries a tier the host
        knows: an unknown-tier provider can never resolve, so a slot that
        only has those must fail at boot rather than later.
        NOTE: provider *health* is async and is enforced at resolve() time, not here.
        """
        with self._lock:
            for name, state in self._slots.items():
                if state.spec.fallback_policy is not FallbackPolicy.HARD_REQUIRED:
                    continue
                if not state.providers:
                    raise RuntimeError(f"hard_required slot '{name}' has no provider")
                if not state.enabled:
                    raise RuntimeError(f"hard_required slot '{name}' is disabled")
                if not any(is_known_trust_tier(tier) for tier in state.provider_trust.values()):
                    raise RuntimeError(
                        f"hard_required slot '{name}' has no provider with a known trust tier"
                    )
