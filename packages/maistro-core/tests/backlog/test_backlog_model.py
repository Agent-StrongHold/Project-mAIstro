"""BacklogItem model invariants (#82).

The model is the boundary statement: closure evidence is inseparable from
terminal status, Goal linkage is reference-only, and timestamps are always
aware UTC regardless of what a store round-trip did to them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from maistro.backlog.model import (
    BacklogClaim,
    BacklogClosure,
    BacklogItem,
    BacklogItemStatus,
)


def _item(**overrides: object) -> BacklogItem:
    defaults: dict[str, object] = {
        "workspace_id": "ws1",
        "title": "Migrate backlog authority",
        "created_by": "human:blake",
    }
    defaults.update(overrides)
    return BacklogItem(**defaults)  # type: ignore[arg-type]


def test_terminal_status_without_closure_is_refused() -> None:
    with pytest.raises(ValidationError, match="closure evidence"):
        _item(status=BacklogItemStatus.DONE)


def test_non_terminal_status_with_closure_is_refused() -> None:
    closure = BacklogClosure(summary="done", evidence_refs=("run-1",))
    with pytest.raises(ValidationError, match="closure evidence"):
        _item(status=BacklogItemStatus.OPEN, closure=closure)


def test_closure_requires_evidence_refs_and_non_blank_summary() -> None:
    with pytest.raises(ValidationError):
        BacklogClosure(summary="  ", evidence_refs=("run-1",))
    with pytest.raises(ValidationError):
        BacklogClosure(summary="done", evidence_refs=())
    with pytest.raises(ValidationError):
        BacklogClosure(summary="done", evidence_refs=("  ",))


def test_tags_are_stripped_deduplicated_and_blank_dropped() -> None:
    item = _item(tags=("engine", " engine ", "", "conductor", "engine"))
    assert item.tags == ("engine", "conductor")


def test_goal_linkage_is_reference_only_and_revision_positive() -> None:
    item = _item(goal_id="goal-1", goal_revision=3)
    assert item.goal_id == "goal-1"
    assert item.goal_revision == 3
    with pytest.raises(ValidationError, match="goal_revision"):
        _item(goal_id="goal-1", goal_revision=0)


def test_self_parent_is_refused() -> None:
    with pytest.raises(ValidationError, match="own parent"):
        _item(item_id="self", parent_id="self")


def test_naive_timestamps_are_read_as_utc() -> None:
    item = _item(
        created_at=datetime(2026, 9, 26, 12, 0, 0),
        updated_at=datetime(2026, 9, 26, 12, 0, 0),
    )
    assert item.created_at.utcoffset() == timedelta(0)
    assert item.created_at.tzinfo is UTC


def test_claim_activity_needs_release_and_unexpired_lease() -> None:
    claimed_at = datetime(2026, 9, 26, tzinfo=UTC)
    claim = BacklogClaim(
        item_id="it1",
        claimed_by="agent:bot",
        claimed_at=claimed_at,
        lease_expires_at=claimed_at + timedelta(seconds=60),
    )
    assert claim.is_active(at=claimed_at + timedelta(seconds=59))
    assert not claim.is_active(at=claimed_at + timedelta(seconds=61))
    released = claim.model_copy(update={"released_at": claimed_at + timedelta(seconds=1)})
    assert not released.is_active(at=claimed_at + timedelta(seconds=2))


def test_item_status_terminality() -> None:
    assert BacklogItemStatus.DONE.is_terminal
    assert BacklogItemStatus.REJECTED.is_terminal
    assert not BacklogItemStatus.OPEN.is_terminal
    assert not BacklogItemStatus.BLOCKED.is_terminal
