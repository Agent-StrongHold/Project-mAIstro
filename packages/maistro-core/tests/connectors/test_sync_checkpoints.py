"""Checkpoint semantics: restart safety and Workspace/config scoping.

Acceptance criterion under test (issue #963, AC3): sync checkpoints are
restart-safe and scoped to the correct Workspace/config.

Restart safety is structural, not incidental: the engine commits page items
*before* saving the cursor, so a crash between the two replays the same cursor
and version+hash dedup absorbs the replay. The fault-injection test below
crashes the checkpoint store at exactly that seam and proves the re-run is
idempotent.
"""

from __future__ import annotations

import pytest

from connectors.connector_fixtures import Page, ScriptedConnector
from maistro.connectors import (
    ConnectorInstance,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SourceItem,
    SyncAction,
    SyncCursor,
    SyncEngine,
)

WORKSPACE = "ws-restart"
OTHER_WORKSPACE = "ws-other"
CONFIG = "cfg-main"
OTHER_CONFIG = "cfg-side"


def _item(external_id: str, version: str = "v1", content: str = "content") -> SourceItem:
    return SourceItem(source_id="repo", external_id=external_id, content=content, version=version)


def _two_page_connector() -> ScriptedConnector:
    return ScriptedConnector(
        {
            None: Page(items=(_item("a"), _item("b")), next_cursor="cursor-2"),
            "cursor-2": Page(items=(_item("c"),), next_cursor=None),
        }
    )


class CrashingCheckpointStore:
    """Wrapper that raises on save, simulating a crash at the commit seam."""

    def __init__(self, inner: MemoryCheckpointStore) -> None:
        self.inner = inner
        self.fail_next_save = 0
        self.saves = 0

    async def load(self, workspace_id: str, connector_id: str, config_id: str) -> SyncCursor | None:
        return await self.inner.load(workspace_id, connector_id, config_id)

    async def save(self, cursor: SyncCursor) -> None:
        if self.fail_next_save > 0:
            self.fail_next_save -= 1
            raise RuntimeError("simulated crash between item commit and checkpoint")
        self.saves += 1
        await self.inner.save(cursor)


def _instance(source: ScriptedConnector) -> ConnectorInstance:
    return ConnectorInstance(
        descriptor=source.descriptor,
        workspace_ids=frozenset({WORKSPACE, OTHER_WORKSPACE}),
    )


@pytest.mark.contract("behavioral")
async def test_crash_before_checkpoint_replays_without_loss_or_duplicate():
    """The load-bearing restart test: crash at the commit seam, then recover.

    The marked contract (ADR-100526-be49, behavioral): checkpoints commit after items,
    so a crash between the two replays the last committed cursor and dedup
    makes the recovery idempotent — at-least-once, no duplicates, no loss.
    """
    source = _two_page_connector()
    inner = MemoryCheckpointStore()
    checkpoints = CrashingCheckpointStore(inner)
    ingest = MemoryIngestStore()
    engine = SyncEngine(ingest, checkpoints)
    instance = _instance(source)

    # First run crashes after committing both pages' items, before any
    # checkpoint survived.
    checkpoints.fail_next_save = 1
    with pytest.raises(RuntimeError, match="simulated crash"):
        await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    # Nothing durable about the cursor survived: the stream replays from None.
    assert await inner.load(WORKSPACE, "tests.scripted", CONFIG) is None

    # Recovery run: the same pages come back; dedup absorbs the replay.
    report = await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    assert report.ingested == 1  # only item "c" is genuinely new
    unchanged = {o.record.external_id for o in report.outcomes if o.action is SyncAction.UNCHANGED}
    assert unchanged == {"a", "b"}
    records = await ingest.records(WORKSPACE, "tests.scripted")
    assert len(records) == 3, "replay must not duplicate or lose items"


async def test_checkpoint_survives_and_resumes_from_the_right_cursor():
    """A completed sync saves its watermark; the next sync resumes from it."""

    class CursorSpyConnector(ScriptedConnector):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.resumed_from: list[str | None] = []

        async def list_items(self, ctx):
            self.resumed_from.append(ctx.cursor)
            return await super().list_items(ctx)

    source = CursorSpyConnector(
        pages={
            None: Page(items=(_item("a"),), next_cursor="watermark-1"),
            "watermark-1": Page(items=(), next_cursor=None),
        }
    )
    ingest = MemoryIngestStore()
    checkpoints = MemoryCheckpointStore()
    engine = SyncEngine(ingest, checkpoints)
    instance = _instance(source)

    first = await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)
    assert first.cursor == "watermark-1"
    source.resumed_from.clear()
    await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    assert source.resumed_from == ["watermark-1"], (
        "the second sync must resume from the saved watermark, not from scratch"
    )


async def test_checkpoints_are_scoped_per_workspace_and_config():
    """One stream's cursor is never handed to another Workspace or config."""
    source = _two_page_connector()
    ingest = MemoryIngestStore()
    checkpoints = MemoryCheckpointStore()
    engine = SyncEngine(ingest, checkpoints)
    instance = _instance(source)

    await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    saved = await checkpoints.load(WORKSPACE, "tests.scripted", CONFIG)
    assert saved is not None
    assert saved.connector_id == "tests.scripted"
    assert saved.config_id == CONFIG
    # The same connector + config under another Workspace has no checkpoint,
    # and neither does another config under the same Workspace.
    assert await checkpoints.load(OTHER_WORKSPACE, "tests.scripted", CONFIG) is None
    assert await checkpoints.load(WORKSPACE, "tests.scripted", OTHER_CONFIG) is None


async def test_same_connector_syncs_two_workspaces_without_cross_talk():
    """Two Workspaces sharing one connector ingest and checkpoint independently."""
    source = _two_page_connector()
    ingest = MemoryIngestStore()
    checkpoints = MemoryCheckpointStore()
    engine = SyncEngine(ingest, checkpoints)
    instance = _instance(source)

    first = await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)
    second = await engine.run(source, instance, workspace_id=OTHER_WORKSPACE, config_id=CONFIG)

    # Both workspaces ingest the full stream fresh; neither sees the other's
    # records, and neither skips items because the other already ingested them.
    assert first.ingested == 3
    assert second.ingested == 3
    mine = await ingest.records(WORKSPACE, "tests.scripted")
    theirs = await ingest.records(OTHER_WORKSPACE, "tests.scripted")
    assert {r.external_id for r in mine} == {"a", "b", "c"}
    assert {r.external_id for r in theirs} == {"a", "b", "c"}
    assert all(r.workspace_id == WORKSPACE for r in mine)
    assert all(r.workspace_id == OTHER_WORKSPACE for r in theirs)
