"""Extension health-store conformance: in-memory twin vs SQLite twin (M9-I3).

The two stores must agree on every rule the health projections rely on, and
the SQLite twin must carry the durability contract: the reads that drive a
projection are identical after the process that wrote them is gone, so
quarantines, disables, and recorded failures survive restarts. Fail-closed
corruption handling is exercised too: durable evidence that cannot round-trip
raises instead of projecting as plausible-but-wrong state.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from maistro.extensions.health import (
    ExtensionErrorKind,
    ExtensionErrorRecord,
    ExtensionHealth,
    ExtensionHealthService,
    ExtensionObservation,
    ExtensionOperatorAction,
    ExtensionOperatorState,
    InMemoryExtensionHealthStore,
    ObservationOutcome,
    OperatorDecision,
)
from maistro.extensions.sqlite_health_store import SqliteExtensionHealthStore
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.types import ExtensionScope

ORG = "org-1"
WORKSPACE = "ws-1"
OTHER_SCOPE = ExtensionScope(org_id="org-2", workspace_id="ws-9")
SCOPE = ExtensionScope(org_id=ORG, workspace_id=WORKSPACE)
AT = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _observation(
    observation_id: str,
    *,
    outcome: ObservationOutcome = ObservationOutcome.SUCCESS,
    version: str = "1.4.0",
    extension_id: str = "acme.chart",
    error: ExtensionErrorRecord | None = None,
) -> ExtensionObservation:
    return ExtensionObservation(
        observation_id=observation_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        latency_ms=float(len(observation_id)),
        outcome=outcome,
        cost_units=0.25 if outcome is ObservationOutcome.SUCCESS else None,
        error=error,
    )


def _dependency_error(error_id: str = "err-1") -> ExtensionErrorRecord:
    return ExtensionErrorRecord(
        error_id=error_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id="acme.chart",
        version="1.4.0",
        kind=ExtensionErrorKind.DEPENDENCY,
        code="provider_unreachable",
        message="the provider refused the connection",
        dependency="acme.provider",
        dependency_version="2.0.0",
    )


def _decision(decision_id: str, action: ExtensionOperatorAction) -> OperatorDecision:
    states = {
        ExtensionOperatorAction.ENABLE: ExtensionOperatorState.ENABLED,
        ExtensionOperatorAction.DISABLE: ExtensionOperatorState.DISABLED,
        ExtensionOperatorAction.QUARANTINE: ExtensionOperatorState.QUARANTINED,
        ExtensionOperatorAction.RELEASE: ExtensionOperatorState.ENABLED,
    }
    return OperatorDecision(
        decision_id=decision_id,
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id="acme.chart",
        action=action,
        state=states[action],
        actor="operator",
        reason=f"decision {decision_id}",
    )


class TwinPair:
    """Both store twins over one in-memory SQLite database."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.memory = InMemoryExtensionHealthStore()
        self.sqlite = SqliteExtensionHealthStore(conn)


@pytest.fixture
async def pair() -> AsyncIterator[TwinPair]:
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        yield TwinPair(conn)


async def test_twins_agree_on_observations_reads_and_filters(pair: TwinPair) -> None:
    """Both twins return the same rows, oldest first, under the same
    extension/version/limit filters — with limit selecting the newest rows."""
    success = _observation("obs-1")
    failure = _observation(
        "obs-2", outcome=ObservationOutcome.FAILURE, error=_dependency_error("err-1")
    )
    other_extension = _observation("obs-3", extension_id="acme.other")
    for store in (pair.memory, pair.sqlite):
        for observation in (success, failure, other_extension):
            await store.append_observation(observation)

        assert await store.observations(SCOPE) == (success, failure, other_extension)
        assert await store.observations(SCOPE, extension_id="acme.chart") == (success, failure)
        assert await store.observations(SCOPE, extension_id="acme.chart", version="9.9.9") == ()
        # Limit selects the newest rows, still oldest-first within them.
        assert await store.observations(SCOPE, extension_id="acme.chart", limit=1) == (failure,)
        # A foreign scope reads nothing: evidence is scope-contained.
        assert await store.observations(OTHER_SCOPE) == ()


async def test_twins_agree_on_error_reads_kind_filter_and_provenance(pair: TwinPair) -> None:
    """Error reads keep full provenance and filter by taxonomy kind in both
    twins — a dependency failure stays queryable as a dependency failure."""
    dependency_error = _dependency_error("err-dep")
    extension_error = ExtensionErrorRecord(
        error_id="err-ext",
        at=AT,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id="acme.chart",
        version="1.4.0",
        kind=ExtensionErrorKind.EXTENSION,
        code="threw",
        message="the extension raised",
    )
    for store in (pair.memory, pair.sqlite):
        await store.append_error(dependency_error)
        await store.append_error(extension_error)

        assert await store.errors(SCOPE) == (dependency_error, extension_error)
        assert await store.errors(SCOPE, kind=ExtensionErrorKind.DEPENDENCY) == (dependency_error,)
        assert await store.errors(SCOPE, kind=ExtensionErrorKind.EXTENSION) == (extension_error,)
        assert await store.errors(SCOPE, extension_id="acme.never") == ()
        assert await store.errors(OTHER_SCOPE) == ()


async def test_failed_observation_files_its_error_in_both_twins(pair: TwinPair) -> None:
    """One append of a failed observation makes both the observation and its
    classified error queryable — the atomic pair both twins guarantee."""
    error = _dependency_error("err-pair")
    failed = _observation("obs-fail", outcome=ObservationOutcome.FAILURE, error=error)
    for store in (pair.memory, pair.sqlite):
        await store.append_observation(failed)
        assert await store.observations(SCOPE) == (failed,)
        assert await store.errors(SCOPE) == (error,)


async def test_twins_agree_on_decision_order_and_newest_wins(pair: TwinPair) -> None:
    """Decisions read back in (extension, append) order in both twins, and
    the newest one is the effective state."""
    quarantine = _decision("decision-1", ExtensionOperatorAction.QUARANTINE)
    release = _decision("decision-2", ExtensionOperatorAction.RELEASE)
    for store in (pair.memory, pair.sqlite):
        await store.append_decision(quarantine)
        await store.append_decision(release)

        assert await store.decisions(SCOPE) == (quarantine, release)
        assert await store.decisions(SCOPE, extension_id="acme.chart") == (quarantine, release)
        assert await store.decisions(SCOPE, extension_id="acme.never") == ()
        assert await store.decisions(OTHER_SCOPE) == ()


async def test_health_survives_restart_on_the_sqlite_twin(tmp_path: Path) -> None:
    """Acceptance: health status survives restart. The same operations are
    driven through one SQLite database across a close/reopen; every read the
    projection consumes is identical afterwards — a quarantined extension is
    still quarantined and its failures are still on the record."""
    path = str(tmp_path / "health.db")
    error = _dependency_error("err-restart")
    quarantine = _decision("decision-restart", ExtensionOperatorAction.QUARANTINE)
    observations = (
        _observation("obs-keep-1"),
        _observation("obs-keep-2", outcome=ObservationOutcome.FAILURE, error=error),
    )

    async with aiosqlite.connect(path) as conn:
        before = SqliteExtensionHealthStore(conn)
        await before.ensure_schema()
        for observation in observations:
            await before.append_observation(observation)
        await before.append_decision(quarantine)

    async with aiosqlite.connect(path) as conn:
        after = SqliteExtensionHealthStore(conn)
        await after.ensure_schema()
        assert await after.observations(SCOPE) == observations
        assert await after.errors(SCOPE) == (error,)
        assert await after.decisions(SCOPE) == (quarantine,)

        # The projection over the reopened store reaches the same verdict:
        # the telemetry survives attributable but reports no active install.
        install_store = InMemoryExtensionStore()
        service = ExtensionHealthService(install_store, after)
        digests = await service.usage_digests(SCOPE)
        assert len(digests) == 1
        assert digests[0].active is False
        assert digests[0].invocations == 2


async def test_corrupted_durable_evidence_fails_closed(tmp_path: Path) -> None:
    """A forged or corrupted payload row cannot project as plausible state:
    reads re-validate every enumerated field and refuse on unknown values."""
    path = str(tmp_path / "health.db")
    async with aiosqlite.connect(path) as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        forged = json.dumps(
            {
                "observation_id": "obs-forged",
                "at": AT.isoformat(),
                "org_id": ORG,
                "workspace_id": WORKSPACE,
                "extension_id": "acme.chart",
                "version": "1.4.0",
                "latency_ms": 1.0,
                "outcome": "flawless",  # not an ObservationOutcome
                "cost_units": None,
                "error": None,
            }
        )
        await conn.execute(
            "INSERT INTO extension_health_events "
            "(event_seq, org_id, workspace_id, extension_id, version, "
            " event_kind, error_kind, occurred_at, payload) "
            "VALUES (1, ?, ?, ?, ?, 'observation', NULL, ?, ?)",
            (ORG, WORKSPACE, "acme.chart", "1.4.0", AT.isoformat(), forged),
        )
        await conn.commit()

        with pytest.raises(ValueError, match="flawless"):
            await store.observations(SCOPE)


async def test_naive_evidence_timestamps_are_refused_at_the_write() -> None:
    """Durable evidence must round-trip its instant; a timezone-naive
    timestamp would read back as a different moment, so neither twin accepts
    it."""
    naive = datetime(2026, 10, 1, 12, 0, 0)
    observation = ExtensionObservation(
        observation_id="obs-naive",
        at=naive,
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id="acme.chart",
        version="1.4.0",
        latency_ms=1.0,
        outcome=ObservationOutcome.SUCCESS,
    )
    async with aiosqlite.connect(":memory:") as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        with pytest.raises(ValueError, match="timezone-aware"):
            await store.append_observation(observation)


async def test_twin_round_trip_preserves_every_field(tmp_path: Path) -> None:
    """Observations and decisions round-trip equal through the SQLite
    payload column — identity, latency, cost absence, error provenance, and
    decision actor/reason all survive."""
    path = str(tmp_path / "health.db")
    error = _dependency_error("err-rt")
    success = _observation("obs-rt")
    success_with_cost = _observation("obs-rt-cost")
    failed = _observation("obs-rt-fail", outcome=ObservationOutcome.FAILURE, error=error)
    decision = _decision("decision-rt", ExtensionOperatorAction.DISABLE)

    async with aiosqlite.connect(path) as conn:
        store = SqliteExtensionHealthStore(conn)
        await store.ensure_schema()
        for observation in (success, success_with_cost, failed):
            await store.append_observation(observation)
        await store.append_decision(decision)

    async with aiosqlite.connect(path) as conn:
        store = SqliteExtensionHealthStore(conn)
        assert await store.observations(SCOPE) == (success, success_with_cost, failed)
        assert await store.errors(SCOPE) == (error,)
        assert await store.decisions(SCOPE) == (decision,)


async def test_evaluated_health_over_reopened_twin_matches_in_memory(
    pair: TwinPair,
) -> None:
    """The conformance point the restart criterion rests on: the same
    evidence sequence produces the same health verdict through either twin,
    so a restart cannot change an operator's answer."""
    from maistro.extensions.health import evaluate_health

    observations = (
        _observation("obs-a"),
        _observation("obs-b", outcome=ObservationOutcome.FAILURE, error=_dependency_error("err-b")),
    )
    verdicts = []
    for store in (pair.memory, pair.sqlite):
        for observation in observations:
            await store.append_observation(observation)
        verdicts.append(evaluate_health(await store.observations(SCOPE)))
    assert verdicts == [ExtensionHealth.DEGRADED, ExtensionHealth.DEGRADED]
