"""Naive Workspace timestamps must normalize to UTC, not the host's zone (#1149).

`datetime.astimezone()` on a naive value asks the platform to guess which zone
it was written in -- the same stored row would then decode to a different
instant depending on which host reads it. `Workspace`/`WorkspaceMembership`
instead read a naive value as already being UTC, deterministically, so the
two tests below run the exact same construction under two different local
`TZ` settings and require an identical result.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from maistro.workspaces.model import Workspace, WorkspaceMembership

_NON_UTC_ZONES = ["America/New_York", "Pacific/Kiritimati"]


@pytest.fixture(params=_NON_UTC_ZONES)
def non_utc_local_timezone(request, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    try:
        yield request.param
    finally:
        time.tzset()


def test_a_naive_workspace_timestamp_reads_as_utc_not_the_local_zone(
    non_utc_local_timezone: str,
) -> None:
    naive = datetime(2024, 2, 3, 4, 5)

    workspace = Workspace(name="Imported", created_at=naive, updated_at=naive)

    assert workspace.created_at == datetime(2024, 2, 3, 4, 5, tzinfo=UTC)
    assert workspace.created_at.tzinfo is not None
    assert workspace.updated_at == datetime(2024, 2, 3, 4, 5, tzinfo=UTC)


def test_a_naive_membership_timestamp_reads_as_utc_not_the_local_zone(
    non_utc_local_timezone: str,
) -> None:
    naive = datetime(2024, 2, 3, 4, 5)

    membership = WorkspaceMembership(workspace_id="ws-1", user_id="alice", added_at=naive)

    assert membership.added_at == datetime(2024, 2, 3, 4, 5, tzinfo=UTC)
    assert membership.added_at.tzinfo is not None


def test_an_already_aware_timestamp_is_left_alone(non_utc_local_timezone: str) -> None:
    aware = datetime(2024, 2, 3, 4, 5, tzinfo=UTC)

    workspace = Workspace(name="Imported", created_at=aware)

    assert workspace.created_at == aware
