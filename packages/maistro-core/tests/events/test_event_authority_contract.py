"""Discriminatory convergence tests for canonical Event authority (#61)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro.events.bus import Event
from maistro.events.convergence import (
    ParallelEventAuthority,
    event_authority_fields,
    require_metadata_only_projection,
)
from maistro.runtime.execution import RuntimeEventEnvelope
from maistro.runs.recovery_events import RecoveryDispositionEvent


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

    require_metadata_only_projection(Event, metadata_fields=frozenset({"event_id", "correlation_id"}))
    require_metadata_only_projection(
        RuntimeEventEnvelope,
        metadata_fields=frozenset({"sequence"}),
    )
