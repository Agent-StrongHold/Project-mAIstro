"""Canonical capability-slot bootstrap.

Builds the `CapabilityRegistry` every mAIstro engine ships with: the canonical
slot definitions (SPEC-184) plus the dependency-free baselines that can live in
core. HTTP-backed providers (host-health monitor/action) are registered by the
*app* once it has the config to construct them — core only declares their slots.

This is the DI composition root for capabilities: `Container` holds the registry
returned here, so every consumer of maistro-core (Conductor, Stronghold, Canvas)
inherits the same slots and baselines.
"""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import EntryPoint

from maistro.capabilities.discovery import discover_into
from maistro.capabilities.providers.approval_inbox import InboxApproval
from maistro.capabilities.registry import CapabilityRegistry
from maistro.capabilities.types import FallbackPolicy, SlotSpec

# Canonical slots wired in Phase 1b. infra_* are SAFE_NOOP (no dependency-free
# baseline exists — the host-health provider is app-supplied); approval ships a
# built-in inbox baseline so HITL works with no external service.
_CANONICAL_SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec(name="infra_monitor", fallback_policy=FallbackPolicy.SAFE_NOOP),
    SlotSpec(name="infra_action", fallback_policy=FallbackPolicy.SAFE_NOOP),
    SlotSpec(
        name="approval",
        fallback_policy=FallbackPolicy.BASELINE,
        baseline_provider="inbox",
    ),
    # self_repair (SPEC-188): SAFE_NOOP. Core defines the slot; the app supplies
    # the provider, which needs the app-wired infra_monitor/infra_action.
    SlotSpec(name="self_repair", fallback_policy=FallbackPolicy.SAFE_NOOP),
    # harness_runner (SPEC-208): SAFE_NOOP. Adapters over foreign agent harnesses
    # (pi, openclaw, claude_code, codex) — an absent/unhealthy harness degrades to
    # a typed Unavailable, never breaks the host run.
    SlotSpec(name="harness_runner", fallback_policy=FallbackPolicy.SAFE_NOOP),
)


def default_capability_registry(
    *,
    entry_points: Iterable[EntryPoint] | None = None,
) -> CapabilityRegistry:
    """Build the canonical registry: define slots, register baselines, discover plugins.

    `entry_points` is injectable for tests; when omitted the live
    ``maistro.capabilities`` metadata group is swept. Discovery never raises on a
    single bad entry point.
    """
    registry = CapabilityRegistry()
    for spec in _CANONICAL_SLOTS:
        registry.define(spec)

    # Dependency-free baseline: the built-in approval inbox.
    registry.register(InboxApproval())

    discover_into(registry, entry_points=entry_points)
    return registry
