"""Discriminatory convergence tests for canonical Event authority (#61)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro.events.bus import Event, EventBus
from maistro.events.convergence import (
    ParallelEventAuthority,
    event_authority_fields,
    require_metadata_only_projection,
)
from maistro.runs.recovery_events import RECOVERY_EVENT_TYPE, RecoveryDispositionEvent
from maistro.runtime.execution import RuntimeEventEnvelope


@dataclass(frozen=True)
class _PlantedPackageEventOwner:
    """The defect shape #61 must expose rather than silently normalize."""

    event_id: str
    sequence: int
    correlation_id: str
    payload: dict[str, object]


def test_planted_package_event_authority_is_rejected() -> None:
    with pytest.raises(ParallelEventAuthority) as exc:
        require_metadata_only_projection(_PlantedPackageEventOwner)

    assert str(exc.value) == (
        "package event projection owns canonical fields: correlation_id, event_id, sequence"
    )


def test_recovery_domain_fact_owns_no_universal_event_fields() -> None:
    assert event_authority_fields(RecoveryDispositionEvent) == frozenset()
    require_metadata_only_projection(RecoveryDispositionEvent)


def test_legacy_bus_and_runtime_sequence_are_exposed_as_compatibility_metadata() -> None:
    """Known duplicate shapes stay visible while their useful metadata remains."""
    assert event_authority_fields(Event) == frozenset({"event_id", "correlation_id"})
    assert event_authority_fields(RuntimeEventEnvelope) == frozenset({"sequence"})

    require_metadata_only_projection(
        Event, metadata_fields=frozenset({"event_id", "correlation_id"})
    )
    require_metadata_only_projection(
        RuntimeEventEnvelope,
        metadata_fields=frozenset({"sequence"}),
    )


async def test_legacy_bus_is_an_adapter_for_recovery_domain_facts() -> None:
    fact = RecoveryDispositionEvent(
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        attempt_status="failed",
        node_run_status="waiting",
        cancellation_cause="recovered",
        disposition="parked",
        error="worker exited",
        source="recovery-test",
    )
    bus = EventBus()

    await bus.emit(fact)

    [projected] = bus.get_history()
    assert projected.event_type == RECOVERY_EVENT_TYPE
    assert projected.correlation_id == "run-1"
    assert projected.payload["attempt_id"] == "attempt-1"
    assert projected.payload["disposition"] == "parked"
