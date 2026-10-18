"""Regression: hydration fingerprints must cover scope/visibility fields.

Re-hydrating a durable record whose content and weight are unchanged but
whose agent_id, scope, project, metadata (declared entities) or visibility
markers changed must not be counted as "unchanged" — the projection would
otherwise keep serving the previous snapshot's visibility from hot recall
while durable retrieval already has the corrected one (review thread,
working/indexed.py hydrate()).
"""

from __future__ import annotations

import pytest

from maistro.memory.working.indexed import WorkspaceWorkingMemoryProjection
from maistro.types.memory import EpisodicMemory, MemoryScope


def _record(**overrides) -> EpisodicMemory:
    base = EpisodicMemory(
        memory_id="m-1",
        content="Apollo runs the deploy pipeline",
        weight=0.7,
        agent_id="agent-a",
        scope=MemoryScope.AGENT,
    )
    return EpisodicMemory(**{**base.__dict__, **overrides})


@pytest.mark.asyncio
async def test_scope_field_change_is_not_counted_unchanged() -> None:
    projection = WorkspaceWorkingMemoryProjection(workspace_id="ws-1")
    await projection.hydrate([_record()])
    report = await projection.hydrate([_record(agent_id="agent-b")])
    assert report.unchanged == 0
    assert report.updated == 1
    snapshot = projection._records["m-1"]
    assert snapshot.agent_id == "agent-b"


@pytest.mark.asyncio
async def test_project_and_metadata_and_visibility_changes_rehydrate() -> None:
    projection = WorkspaceWorkingMemoryProjection(workspace_id="ws-1")
    await projection.hydrate([_record()])
    for changed in (
        _record(project_id="proj-2"),
        _record(scope=MemoryScope.ORGANIZATION),
        _record(context={"entities": ["Apollo"]}),  # declared entities are metadata
        _record(shared=True),
    ):
        report = await projection.hydrate([changed])
        assert report.unchanged == 0, changed
        assert projection._records["m-1"] == changed


@pytest.mark.asyncio
async def test_metadata_key_order_does_not_cause_churn() -> None:
    projection = WorkspaceWorkingMemoryProjection(workspace_id="ws-1")
    await projection.hydrate([_record(context={"a": 1, "b": 2})])
    report = await projection.hydrate([_record(context={"b": 2, "a": 1})])
    assert report.unchanged == 1


@pytest.mark.asyncio
async def test_genuinely_unchanged_record_still_unchanged() -> None:
    projection = WorkspaceWorkingMemoryProjection(workspace_id="ws-1")
    record = _record()
    await projection.hydrate([record])
    report = await projection.hydrate([record])
    assert report.unchanged == 1
    assert report.updated == 0
