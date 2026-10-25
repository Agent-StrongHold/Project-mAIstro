"""Capability registry: defines slots, registers providers (installed/inactive),
activates/enables them, and resolves the live provider with fallback. Thread-safe."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from maistro.capabilities.types import FallbackPolicy, SlotSpec

if TYPE_CHECKING:
    from maistro.capabilities.protocols import CapabilityProvider

logger = logging.getLogger("maistro.capabilities.registry")


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
            self._slots[spec.name] = _SlotState(spec=spec)
        logger.debug("Defined slot: %s (%s)", spec.name, spec.fallback_policy)

    def _slot(self, slot: str) -> _SlotState:
        state = self._slots.get(slot)
        if state is None:
            raise KeyError(f"Unknown slot '{slot}'")
        return state

    def register(self, provider: CapabilityProvider) -> None:
        """Register a provider as INSTALLED but INACTIVE (never auto-activates)."""
        with self._lock:
            state = self._slot(provider.slot)
            state.providers[provider.name] = provider
        logger.debug("Registered provider %s -> slot %s (inactive)", provider.name, provider.slot)

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
            candidates = sorted(providers.values(), key=lambda p: p.trust_tier)
            chosen = candidates[0] if candidates else None
        else:
            chosen = providers.get(chosen_name)

        if chosen is None:
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
