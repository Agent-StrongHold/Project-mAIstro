"""The policy object and the sweeper that rides on admission (#131).

The store's `purge_expired_runs` is proved across all three backends in
`test_retention_conformance`. This is the layer above: what deadline a Run gets,
and when a sweep actually happens. Both matter independently — a correct purge
that never runs is the defect `SqliteSessionStore.purge_expired` was written to
fix, and this is the same shape.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from maistro.observability.metrics import retention_backlog_remaining, retention_purged_total
from maistro.runs.retention import (
    DEFAULT_CHAT_RETENTION_SECONDS,
    UNBOUNDED_RETENTION,
    RetentionPolicy,
    RetentionScopeRequired,
    RunRetentionSweeper,
)
from maistro.runs.retention_scope import (
    GlobalRetentionScope,
    WorkspaceRetentionScope,
)
from maistro.runs.store import PurgeOutcome

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
SCOPE = WorkspaceRetentionScope(workspace_id="workspace-1")
OTHER = WorkspaceRetentionScope(workspace_id="workspace-2")
GLOBAL = GlobalRetentionScope(authorized_by="operator")


class SpyStore:
    """Just enough RunStore to watch the sweeper."""

    def __init__(
        self,
        *,
        purged: int = 0,
        fail_with: Exception | None = None,
        backlog: bool = False,
    ) -> None:
        self.calls: list[tuple[object, datetime | None, int]] = []
        self._purged = purged
        self._fail_with = fail_with
        self._backlog = backlog

    async def purge_expired_runs(
        self,
        scope: object,
        *,
        now: datetime | None = None,
        limit: int = 500,
    ) -> PurgeOutcome:
        self.calls.append((scope, now, limit))
        if self._fail_with is not None:
            raise self._fail_with
        return PurgeOutcome(  # type: ignore[arg-type]
            scope=SCOPE if scope is None else scope,
            runs=self._purged,
            backlog_remaining=self._backlog,
        )


class SlowStore(SpyStore):
    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__()
        self._gate = gate

    async def purge_expired_runs(
        self,
        scope: object,
        *,
        now: datetime | None = None,
        limit: int = 500,
    ) -> PurgeOutcome:
        self.calls.append((scope, now, limit))
        await self._gate.wait()
        return PurgeOutcome(scope=SCOPE if scope is None else scope)  # type: ignore[arg-type]


# ── the policy ────────────────────────────────────────────────────


def test_the_default_ttl_is_bounded() -> None:
    policy = RetentionPolicy()

    assert policy.bounded
    assert policy.ttl_seconds == DEFAULT_CHAT_RETENTION_SECONDS


def test_a_deadline_is_the_ttl_after_now() -> None:
    policy = RetentionPolicy(ttl_seconds=3600)

    assert policy.deadline(now=NOW) == NOW + timedelta(hours=1)


def test_no_ttl_means_no_deadline() -> None:
    """The opt-out. `None` reproduces exactly what every other entry point
    already does, which is why it is expressible at all."""
    assert UNBOUNDED_RETENTION.deadline(now=NOW) is None
    assert not UNBOUNDED_RETENTION.bounded


def test_a_deadline_defaults_to_the_real_clock() -> None:
    before = datetime.now(UTC)
    deadline = RetentionPolicy(ttl_seconds=60).deadline()
    assert deadline is not None
    assert before + timedelta(seconds=59) <= deadline <= datetime.now(UTC) + timedelta(seconds=61)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 0},
        {"ttl_seconds": -1},
        {"sweep_interval_seconds": -1.0},
        {"batch_limit": 0},
    ],
)
def test_a_nonsense_policy_is_refused(kwargs: dict[str, object]) -> None:
    """Each of these is a policy that silently does nothing — a zero TTL purges
    live-looking work, a zero batch sweeps nothing. Refused at construction
    rather than discovered in production."""
    with pytest.raises(ValueError):
        RetentionPolicy(**kwargs)  # type: ignore[arg-type]


# ── the sweeper ───────────────────────────────────────────────────


async def test_the_first_sweep_happens_immediately() -> None:
    store = SpyStore(purged=3)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(), scope=SCOPE)  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 3
    assert store.calls == [(SCOPE, NOW, RetentionPolicy().batch_limit)]


async def test_a_second_sweep_inside_the_interval_is_skipped() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=3600), scope=SCOPE)  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)
    await sweeper.maybe_sweep(now=NOW)

    assert len(store.calls) == 1


async def test_a_zero_interval_sweeps_every_time() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE)  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)
    await sweeper.maybe_sweep(now=NOW)

    assert len(store.calls) == 2


async def test_an_unbounded_policy_never_sweeps() -> None:
    """Opting out of the deadline has to opt out of the sweep too, or a
    deployment that wanted its Runs kept would still pay for the scan."""
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, UNBOUNDED_RETENTION, scope=SCOPE)  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert await sweeper.sweep_now(now=NOW) == 0
    assert store.calls == []


async def test_concurrent_admissions_produce_one_sweep() -> None:
    """A burst of chat turns must not become a burst of sweeps queued behind
    each other — that turns housekeeping into the bottleneck it was meant to
    prevent."""
    gate = asyncio.Event()
    store = SlowStore(gate)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE)  # type: ignore[arg-type]

    waiters = [asyncio.create_task(sweeper.maybe_sweep(now=NOW)) for _ in range(8)]
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(*waiters)

    assert len(store.calls) == 1


async def test_a_failing_sweep_does_not_fail_the_admission() -> None:
    """Retention is housekeeping. A database hiccup during a sweep must never
    be the reason a user's chat turn was refused."""
    store = SpyStore(fail_with=RuntimeError("connection reset"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy(), scope=SCOPE)  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert isinstance(sweeper.last_error, RuntimeError)


async def test_sweep_now_ignores_the_interval_and_propagates_errors() -> None:
    """The escape hatch for an operator or a test: unconditional, and honest
    about failing."""
    store = SpyStore(fail_with=RuntimeError("boom"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=3600), scope=SCOPE)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await sweeper.sweep_now(now=NOW)


async def test_a_recovered_sweep_clears_the_recorded_error() -> None:
    store = SpyStore(fail_with=RuntimeError("transient"))
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE)  # type: ignore[arg-type]
    await sweeper.maybe_sweep(now=NOW)
    assert sweeper.last_error is not None

    store._fail_with = None
    await sweeper.maybe_sweep(now=NOW)

    assert sweeper.last_error is None


async def test_the_batch_limit_reaches_the_store() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(batch_limit=7), scope=SCOPE)  # type: ignore[arg-type]

    await sweeper.maybe_sweep(now=NOW)

    assert store.calls[0][2] == 7


# ── the scope is the deletion authority (#1175) ──────────────────


async def test_a_sweeper_with_no_scope_deletes_nothing() -> None:
    """An unnamed scope must mean *nothing was deleted*, never *everything
    eligible was deleted*. `maybe_sweep` records the refusal where admission
    can see it and moves on."""
    store = SpyStore(purged=5)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0))  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert store.calls == []
    assert isinstance(sweeper.last_error, RetentionScopeRequired)
    assert sweeper.last_outcome is None


async def test_a_sweeper_with_no_scope_refuses_an_explicit_sweep() -> None:
    """`sweep_now` is the operator's escape hatch, so the refusal is in their
    face rather than in a field."""
    store = SpyStore(purged=5)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0))  # type: ignore[arg-type]

    with pytest.raises(RetentionScopeRequired):
        await sweeper.sweep_now(now=NOW)
    assert store.calls == []


async def test_a_per_sweep_scope_overrides_the_construction_scope() -> None:
    store = SpyStore()
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE)  # type: ignore[arg-type]

    await sweeper.sweep_now(now=NOW, scope=OTHER)

    assert store.calls[0][0] is OTHER


async def test_a_global_scope_reaches_the_store_intact() -> None:
    """Store-wide deletion is an explicitly attributed act, not a missing
    predicate: the grant travels to the store and into the outcome."""
    store = SpyStore(purged=2)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=GLOBAL)  # type: ignore[arg-type]

    assert await sweeper.sweep_now(now=NOW) == 2
    assert store.calls[0][0] is GLOBAL
    assert sweeper.last_outcome is not None
    assert sweeper.last_outcome.mode == "global"
    assert sweeper.last_outcome.is_global


async def test_the_outcome_names_the_authorized_workspace() -> None:
    store = SpyStore(purged=1)
    sweeper = RunRetentionSweeper(store, RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE)  # type: ignore[arg-type]

    await sweeper.sweep_now(now=NOW)

    assert sweeper.last_outcome is not None
    assert sweeper.last_outcome.mode == "workspace"
    assert sweeper.last_outcome.workspace_id == "workspace-1"


def _mode_total(mode: str) -> float:
    """The counter's current value for one mode label."""
    return sum(
        float(sample["value"])
        for sample in retention_purged_total.collect()
        if sample.get("labels", {}).get("mode") == mode
    )


async def test_purged_runs_are_counted_by_mode() -> None:
    """The health metric identifies the authorization mode, never a Workspace
    id — Workspaces are caller-created and metric labels are bounded (#818)."""
    before_workspace = _mode_total("workspace")
    before_global = _mode_total("global")
    scoped = RunRetentionSweeper(
        SpyStore(purged=3), RetentionPolicy(sweep_interval_seconds=0), scope=SCOPE
    )  # type: ignore[arg-type]
    widened = RunRetentionSweeper(
        SpyStore(purged=2), RetentionPolicy(sweep_interval_seconds=0), scope=GLOBAL
    )  # type: ignore[arg-type]

    await scoped.sweep_now(now=NOW)
    await widened.sweep_now(now=NOW)

    assert _mode_total("workspace") - before_workspace == 3
    assert _mode_total("global") - before_global == 2


async def test_a_failed_sweep_counts_nothing() -> None:
    """A metric that outlives its sweep describes a purge that did not
    happen — the one thing a retention metric must never do."""
    before = _mode_total("workspace")
    sweeper = RunRetentionSweeper(
        SpyStore(purged=4, fail_with=RuntimeError("down")),
        RetentionPolicy(sweep_interval_seconds=0),
        scope=SCOPE,
    )  # type: ignore[arg-type]

    assert await sweeper.maybe_sweep(now=NOW) == 0

    assert _mode_total("workspace") == before
    assert sweeper.last_outcome is None


def _backlog(mode: str) -> float:
    """The backlog gauge's current value for one mode label."""
    return sum(
        float(sample["value"])
        for sample in retention_backlog_remaining.collect()
        if sample.get("labels", {}).get("mode") == mode
    )


async def test_a_drained_scope_reports_no_backlog() -> None:
    """The backlog gauge is the difference between 'the batch ran out' and
    'the scope is empty' — the state a retention alert is actually about."""
    sweeper = RunRetentionSweeper(
        SpyStore(purged=2),
        RetentionPolicy(sweep_interval_seconds=0),
        scope=SCOPE,
    )  # type: ignore[arg-type]

    await sweeper.sweep_now(now=NOW)

    assert sweeper.last_outcome is not None
    assert sweeper.last_outcome.backlog_remaining is False
    assert _backlog("workspace") == 0.0


async def test_a_batch_limited_scope_reports_its_backlog() -> None:
    sweeper = RunRetentionSweeper(
        SpyStore(purged=1, backlog=True),
        RetentionPolicy(sweep_interval_seconds=0),
        scope=OTHER,
    )  # type: ignore[arg-type]

    await sweeper.sweep_now(now=NOW)

    assert sweeper.last_outcome is not None
    assert sweeper.last_outcome.backlog_remaining is True
    assert _backlog("workspace") == 1.0
    # The label is the mode, never the Workspace id (#818).
    assert _backlog("global") == 0.0


async def test_a_failed_sweep_withdraws_the_standing_backlog_report() -> None:
    """`last_outcome` goes to None when a sweep fails; the gauge that was set
    from it must not keep describing a purge that no longer stands."""
    good = RunRetentionSweeper(
        SpyStore(purged=1, backlog=True),
        RetentionPolicy(sweep_interval_seconds=0),
        scope=SCOPE,
    )  # type: ignore[arg-type]
    await good.sweep_now(now=NOW)
    assert _backlog("workspace") == 1.0

    failing = RunRetentionSweeper(
        SpyStore(purged=4, fail_with=RuntimeError("down")),
        RetentionPolicy(sweep_interval_seconds=0),
        scope=SCOPE,
    )  # type: ignore[arg-type]

    assert await failing.maybe_sweep(now=NOW) == 0

    assert _backlog("workspace") == 0.0
    assert failing.last_outcome is None
