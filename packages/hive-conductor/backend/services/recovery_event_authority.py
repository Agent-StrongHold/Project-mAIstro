"""Select the existing recovery Event authority for a shipped Hive product.

This is an adapter *selection*, not a second Event store or delivery path.
The configured Container owns the canonical publisher and rebinding policy;
recovery callers must not hand the legacy EventBus to graph recovery directly.

Minimal test-only/standalone owners without a publisher retain their existing
legacy-only behavior. A publisher without a canonical Run store fails loudly.
"""

from __future__ import annotations

from typing import Any

from maistro.runs.recovery_events import CanonicalRecoveryEventSink, RecoveryEventSink


def recovery_events_for(owner: Any) -> RecoveryEventSink | None:
    """Bind recovery facts to the owner's current canonical Run and Event stores."""
    selector = getattr(owner, "_recovery_events", None)
    if callable(selector):
        # Configured Container: rebind if a crash-test replica swapped RunStore.
        return selector()

    publisher = getattr(owner, "canonical_event_publisher", None)
    if publisher is not None:
        # A thin product owner may expose canonical stores but not the
        # Container helper. Never substitute the legacy bus in this case.
        return CanonicalRecoveryEventSink(owner.run_store, publisher)

    saved_sink = getattr(owner, "recovery_event_sink", None)
    if saved_sink is not None:
        return saved_sink

    # Legacy standalone/test owners have no canonical Event infrastructure.
    return getattr(owner, "event_bus", None)


__all__ = ["recovery_events_for"]
