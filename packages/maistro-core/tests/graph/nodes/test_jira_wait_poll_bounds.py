"""#1206: bounded Jira wait polling and truthful corrupt `first_seen` repair.

Two traps this pins shut:

- `poll_interval_seconds`/`timeout_seconds` had no bounds, so a zero interval
  turned the node into a hot external polling loop and a timeout smaller than
  the poll interval meant the deadline always passed before the first
  re-check. The schema now rejects all of that at validation time.
- A persisted `first_seen` that could not be parsed was silently replaced by
  `now` *and re-persisted as the same corrupt string*, resetting the elapsed
  clock on every evaluation forever. The repair is now explicit and one-shot:
  the pause carries one canonical anchor plus evidence of what it replaced,
  and later evaluations measure against that anchor instead of restarting.

Timing scenarios run against a fake `now_utc` so the boundary cases (elapsed
exactly equal to, and exactly one second short of, the timeout) are exact
rather than wall-clock races.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

import maistro.graph.nodes.jira_wait_for_subtasks as jira_module
from maistro.graph.nodes import NodeContext, get_node
from maistro.graph.nodes.base import RESUMED_PAUSE_KEY
from maistro.graph.nodes.jira_wait_for_subtasks import (
    MIN_POLL_INTERVAL_SECONDS,
    WaitForSubtasksIn,
)

_BASE_INPUTS: dict[str, Any] = {
    "base_url": "https://jira.example.com",
    "parent_key": "PROJ-100",
    "pat": "pat",
}
_NODE_ID = "n1"


class _Clock:
    """Deterministic replacement for the node's `now_utc` import."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _ctx(metadata: dict[str, Any] | None = None) -> NodeContext:
    return NodeContext(
        run_id="r1",
        dag_id="d1",
        node_id=_NODE_ID,
        user_id="u1",
        project_id="p1",
        metadata=metadata or {},
    )


@pytest.fixture(name="clock")
def _clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock(datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(jira_module, "now_utc", clock)
    return clock


@pytest.fixture(name="open_subtasks")
def _open_subtasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every poll sees a subtask that is still open."""

    async def _statuses(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        return {"PROJ-101": "In Progress"}

    monkeypatch.setattr(jira_module, "_fetch_subtask_statuses", _statuses)


# --- polling configuration bounds (host-approved floor + relationship) ------


@pytest.mark.parametrize("interval", [0, -1, MIN_POLL_INTERVAL_SECONDS - 1])
def test_zero_negative_and_too_small_intervals_are_rejected(interval: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        WaitForSubtasksIn.model_validate({**_BASE_INPUTS, "poll_interval_seconds": interval})
    errors = excinfo.value.errors()
    assert any(e["loc"] == ("poll_interval_seconds",) for e in errors), errors


def test_interval_at_the_host_floor_is_accepted() -> None:
    inputs = WaitForSubtasksIn.model_validate(
        {**_BASE_INPUTS, "poll_interval_seconds": MIN_POLL_INTERVAL_SECONDS}
    )
    assert inputs.poll_interval_seconds == MIN_POLL_INTERVAL_SECONDS


async def test_timeout_below_poll_interval_fails_the_run_visibly() -> None:
    """The relationship is enforced at the node's execution entry — the one
    point every run reaches — so the attempt fails and names both fields,
    instead of a week-long wait ending in an unexplained timeout."""
    node = get_node("jira.wait_for_subtasks")()
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 30, "poll_interval_seconds": 60}, _ctx()
    )
    assert result.success is False
    assert result.status == "failed"
    assert result.error_code == "ValueError"
    assert result.error_message is not None
    assert "timeout_seconds (30)" in result.error_message
    assert "poll_interval_seconds (60)" in result.error_message


def test_timeout_equal_to_poll_interval_is_accepted() -> None:
    inputs = WaitForSubtasksIn.model_validate(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60}
    )
    assert inputs.timeout_seconds == inputs.poll_interval_seconds


@pytest.mark.parametrize("timeout", [0, -86_400])
def test_nonpositive_timeout_is_rejected(timeout: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        WaitForSubtasksIn.model_validate({**_BASE_INPUTS, "timeout_seconds": timeout})
    errors = excinfo.value.errors()
    assert any(e["loc"] == ("timeout_seconds",) for e in errors), errors


def test_default_configuration_is_valid() -> None:
    inputs = WaitForSubtasksIn.model_validate(dict(_BASE_INPUTS))
    assert inputs.poll_interval_seconds >= MIN_POLL_INTERVAL_SECONDS
    assert inputs.timeout_seconds >= inputs.poll_interval_seconds


# --- corrupt first_seen: explicit, one-shot repair ---------------------------


async def test_corrupt_first_seen_repairs_once_and_does_not_restart_again(
    clock: _Clock, open_subtasks: None
) -> None:
    """The corrupt value must not survive, and the repair must happen once:
    a later evaluation measures against the repaired anchor, so the corrupt
    string can never reset the elapsed clock again."""
    node = get_node("jira.wait_for_subtasks")()

    first = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": "not-an-iso-date"}}),
    )
    assert first.status == "paused"
    # One canonical anchor, parseable and tz-aware — not the corrupt string.
    assert first.metadata is not None
    anchor = first.metadata["first_seen"]
    parsed_anchor = datetime.fromisoformat(anchor)
    assert parsed_anchor == clock.now
    assert parsed_anchor.tzinfo is not None
    # Explicit evidence of the repair, naming what it replaced.
    repair = first.metadata["first_seen_repair"]
    assert repair["reason"] == "unparseable_first_seen"
    assert repair["replaced"] == "not-an-iso-date"
    assert repair["repaired_at"] == clock.now.isoformat()

    # Simulate the runtime carrying the repaired pause forward: the second
    # evaluation resumes past the timeout measured from the repair — proof
    # the clock restarted exactly once, at the repair, never again.
    clock.advance(61)
    second = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": anchor}}),
    )
    assert second.status == "completed"
    assert second.output is not None
    assert second.output.timed_out is True


async def test_corrupt_first_seen_via_legacy_sidecar_repairs_and_converges(
    clock: _Clock, open_subtasks: None
) -> None:
    """The fallback key a resumed run may read is converged onto the repaired
    anchor too, so no reader can pick the corrupt value back up."""
    node = get_node("jira.wait_for_subtasks")()
    ctx = _ctx({f"wait_first_seen:{_NODE_ID}": "garbage-T0"})
    first = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60}, ctx
    )
    assert first.status == "paused"
    assert first.metadata is not None
    assert first.metadata["first_seen"] == clock.now.isoformat()
    assert first.metadata["first_seen_repair"]["replaced"] == "garbage-T0"
    assert ctx.metadata[f"wait_first_seen:{_NODE_ID}"] == clock.now.isoformat()


async def test_naive_first_seen_is_treated_as_corrupt(clock: _Clock, open_subtasks: None) -> None:
    """Parseable but tz-naive evidence cannot anchor elapsed math against the
    tz-aware clock — it routes to the same explicit repair, not a crash.
    Passed as a `datetime` object (not a string) so the in-memory resume
    path — pause metadata need not round-trip through JSON in every
    container — is covered too."""
    node = get_node("jira.wait_for_subtasks")()
    naive = (clock.now - timedelta(seconds=1)).replace(tzinfo=None)
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": naive}}),
    )
    assert result.status == "paused"
    assert result.metadata is not None
    assert result.metadata["first_seen_repair"]["replaced"] == repr(naive)


async def test_non_string_first_seen_is_repaired_with_repr_evidence(
    clock: _Clock, open_subtasks: None
) -> None:
    node = get_node("jira.wait_for_subtasks")()
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": 17_293_492}}),
    )
    assert result.status == "paused"
    assert result.metadata is not None
    assert result.metadata["first_seen_repair"]["replaced"] == "17293492"


# --- timeout and restart behaviour ------------------------------------------


async def test_normal_timeout_fires_from_carried_first_seen(
    clock: _Clock, open_subtasks: None
) -> None:
    node = get_node("jira.wait_for_subtasks")()
    long_ago = (clock.now - timedelta(hours=1)).isoformat()
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": long_ago}}),
    )
    assert result.status == "completed"
    assert result.output is not None
    assert result.output.timed_out is True
    assert result.output.all_match is False


async def test_restart_preserves_the_anchor_across_pause_resume(
    clock: _Clock, open_subtasks: None
) -> None:
    """First reach records the anchor; a resume (a restart of the run) must
    carry the same anchor forward, not take a fresh `now`."""
    node = get_node("jira.wait_for_subtasks")()
    first = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60}, _ctx()
    )
    assert first.status == "paused"
    assert first.metadata is not None
    anchor = first.metadata["first_seen"]

    clock.advance(30)
    carried = dict(first.metadata)
    carried.pop("paused_reason")
    second = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: carried}),
    )
    assert second.status == "paused"
    assert second.metadata is not None
    assert second.metadata["first_seen"] == anchor, "restart restarted the clock"
    assert "first_seen_repair" not in second.metadata


async def test_boundary_exactly_at_the_timeout_times_out(
    clock: _Clock, open_subtasks: None
) -> None:
    node = get_node("jira.wait_for_subtasks")()
    anchor = clock.now.isoformat()
    clock.advance(60)
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": anchor}}),
    )
    assert result.output is not None
    assert result.output.timed_out is True


async def test_boundary_one_second_short_of_the_timeout_still_pauses(
    clock: _Clock, open_subtasks: None
) -> None:
    node = get_node("jira.wait_for_subtasks")()
    anchor = clock.now.isoformat()
    clock.advance(59)
    result = await node.run(
        {**_BASE_INPUTS, "timeout_seconds": 60, "poll_interval_seconds": 60},
        _ctx({RESUMED_PAUSE_KEY: {"first_seen": anchor}}),
    )
    assert result.status == "paused"
    assert result.metadata is not None
    assert result.metadata["first_seen"] == anchor
