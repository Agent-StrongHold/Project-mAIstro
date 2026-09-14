"""Capability registry: defines slots, registers providers (installed/inactive),
activates/enables them, and resolves the live provider with fallback. Thread-safe."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.security.trust import is_known_trust_tier, trust_rank

if TYPE_CHECKING:
    from maistro.capabilities.protocols import CapabilityProvider

logger = logging.getLogger("maistro.capabilities.registry")


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


@dataclass
class _SlotState:
    spec: SlotSpec
    providers: dict[str, CapabilityProvider] = field(default_factory=dict)
    active: str | None = None
    enabled: bool = True


class CapabilityRegistry:
    """Holds slot definitions + provider state. Thread-safe via reentrant lock."""

    def __init__(self) -> None:
        self._slots: dict[str, _SlotState] = {}
        self._lock = threading.RLock()

    def define(self, spec: SlotSpec) -> None:
        with self._lock:
            existing = self._slots.get(spec.name)
            if existing is not None:
                if existing.spec != spec:
                    raise ValueError(f"Slot '{spec.name}' is already defined differently")
                # Re-discovery is idempotent. In particular, do not recreate
                # the state and silently reset approval or enabled status.
                return
            self._slots[spec.name] = _SlotState(spec=spec)
        logger.debug("Defined slot: %s (%s)", spec.name, spec.fallback_policy)

    def _slot(self, slot: str) -> _SlotState:
        state = self._slots.get(slot)
        if state is None:
            raise KeyError(f"Unknown slot '{slot}'")
        return state

    def register(self, provider: CapabilityProvider) -> bool:
        """Register an installed provider without replacing existing authority.

        Entry-point discovery can run repeatedly, so registration is an
        admission operation rather than an update operation. A provider with
        an existing logical identity is retained exactly as installed; use
        :meth:`replace` with a governed decision for an intentional change.
        Returns ``True`` only when a new provider was admitted.
        """
        with self._lock:
            state = self._slot(provider.slot)
            if provider.name in state.providers:
                logger.warning(
                    "Ignored rediscovery of installed provider %s -> slot %s",
                    provider.name,
                    provider.slot,
                )
                return False
            state.providers[provider.name] = provider
        logger.debug("Registered provider %s -> slot %s (inactive)", provider.name, provider.slot)
        return True

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
        unhealthy → fallback. Fallback = baseline provider (if policy BASELINE) else None.
        """
        with self._lock:
            state = self._slot(slot)
            spec = state.spec
            enabled = state.enabled
            chosen_name = state.active
            providers = dict(state.providers)

        def _baseline() -> CapabilityProvider | None:
            if spec.fallback_policy is FallbackPolicy.BASELINE and spec.baseline_provider:
                return providers.get(spec.baseline_provider)
            return None

        if not enabled:
            return _baseline()

        if chosen_name is None:
            # Provider metadata is untrusted input. Use a finite host-owned
            # ordering and a name tie-breaker; unknown/blank values sort last.
            candidates = sorted(
                providers.values(),
                key=lambda p: (trust_rank(getattr(p, "trust_tier", None)), p.name),
            )
            chosen = candidates[0] if candidates else None
        else:
            chosen = providers.get(chosen_name)

        if chosen is None or not is_known_trust_tier(getattr(chosen, "trust_tier", None)):
            # Unknown provider metadata is not merely low priority: it is not
            # admissible for an implicit or pinned live resolution.
            return _baseline()

        health = await chosen.healthcheck()
        if not health.healthy:
            logger.warning(
                "Provider %s unhealthy for slot %s: %s", chosen.name, slot, health.detail
            )
            fb = _baseline()
            return fb if (fb is not None and fb.name != chosen.name) else None
        return chosen

    def validate_boot(self) -> None:
        """Raise if any HARD_REQUIRED slot cannot be satisfied at boot.

        Checks presence (a provider is installed) and that the slot is enabled.
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
