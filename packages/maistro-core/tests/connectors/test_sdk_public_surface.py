"""Public-SDK ingestion: provenance stamping, refresh, explicit deletion.

Acceptance criteria under test (issue #963):

- AC1: an out-of-tree connector ingests and refreshes content through the
  public SDK only (the connector here imports nothing but
  ``maistro.connectors``);
- AC2: every ingested item carries connector/source/version provenance;
- AC4: update and deletion are explicit — a changed version updates in place,
  an unchanged item is skipped rather than re-ingested, and only an item the
  source marks deleted becomes a tombstone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from connectors.connector_fixtures import ExternalStyleConnector, Page
from maistro.connectors import (
    ConnectorCapability,
    ConnectorCapabilityError,
    ConnectorInstance,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SourceItem,
    SyncAction,
    SyncEngine,
    content_hash,
)

WORKSPACE = "ws-acme"
CONFIG = "main"

_ALL_CAPABILITIES = frozenset(ConnectorCapability)


def _item(external_id: str, version: str, content: str, *, deleted: bool = False) -> SourceItem:
    return SourceItem(
        source_id="repo",
        external_id=external_id,
        content=content,
        version=version,
        updated_at="2026-10-01T00:00:00Z",
        deleted=deleted,
    )


def _engine() -> tuple[SyncEngine, MemoryIngestStore, MemoryCheckpointStore]:
    ingest = MemoryIngestStore()
    checkpoints = MemoryCheckpointStore()
    return SyncEngine(ingest, checkpoints), ingest, checkpoints


def _single_page_connector(
    items: list[SourceItem],
    *,
    capabilities: frozenset[ConnectorCapability] = _ALL_CAPABILITIES,
) -> ExternalStyleConnector:
    """One-page source: items then end-of-stream, with a configurable contract."""
    return ExternalStyleConnector(
        {None: Page(items=tuple(items), next_cursor=None)},
        capabilities=capabilities,
    )


@pytest.mark.contract("boundary")
async def test_out_of_tree_connector_ingests_through_public_sdk_only():
    """AC1: public SDK surface is the entire integration, end to end.

    The marked contract (ADR-100526-be49, boundary): ``maistro.connectors`` is the
    whole integration an out-of-tree connector writes against — this test's
    connector imports nothing else and drives a full ingest.
    """
    source = _single_page_connector(
        [
            _item("doc-1", "v1", "first document"),
            _item("doc-2", "v1", "second document"),
        ]
    )
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    report = await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    assert report.ingested == 2
    records = await ingest.records(WORKSPACE, "tests.scripted")
    assert {record.external_id for record in records} == {"doc-1", "doc-2"}


async def test_every_ingested_item_carries_full_provenance():
    """AC2: connector/source/version/workspace provenance on every record."""
    source = _single_page_connector([_item("doc-1", "v7", "payload")])
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    await engine.run(source, instance, workspace_id=WORKSPACE, config_id=CONFIG)

    (record,) = await ingest.records(WORKSPACE, "tests.scripted")
    assert record.connector_id == "tests.scripted"
    assert record.connector_version == "1.0.0"
    assert record.source_id == "repo"
    assert record.external_id == "doc-1"
    assert record.item_version == "v7"
    assert record.content_hash == content_hash("payload")
    assert record.workspace_id == WORKSPACE
    assert record.config_id == CONFIG
    # ingested_at is a real timestamp, not a placeholder
    datetime.fromisoformat(record.ingested_at)


async def test_unchanged_items_are_skipped_not_reingested():
    """AC4: a refresh whose items did not change dedupes to UNCHANGED."""
    source = _single_page_connector([_item("doc-1", "v1", "same content")])
    engine, _ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    first = await engine.run(source, instance, workspace_id=WORKSPACE)
    replay = await engine.run(source, instance, workspace_id=WORKSPACE)

    assert first.ingested == 1
    assert replay.outcomes
    assert all(outcome.action is SyncAction.UNCHANGED for outcome in replay.outcomes)
    assert replay.unchanged == 1


async def test_version_change_updates_in_place_not_as_duplicate():
    """AC4: a source-side edit is one UPDATED record, not a second row."""
    source = _single_page_connector([_item("doc-1", "v1", "before")])
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))
    await engine.run(source, instance, workspace_id=WORKSPACE)

    source.live[("repo", "doc-1")] = _item("doc-1", "v2", "after")
    report = await engine.run(source, instance, workspace_id=WORKSPACE)

    assert report.updated == 1
    records = await ingest.records(WORKSPACE, "tests.scripted")
    assert len(records) == 1, "an update must replace, not duplicate"
    assert records[0].content == "after"
    assert records[0].item_version == "v2"


async def test_content_drift_with_same_version_still_updates():
    """A same-version item with different content is UPDATED, not skipped."""
    source = _single_page_connector([_item("doc-1", "v1", "before")])
    engine, _ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))
    await engine.run(source, instance, workspace_id=WORKSPACE)

    source.live[("repo", "doc-1")] = _item("doc-1", "v1", "silently rewritten")
    report = await engine.run(source, instance, workspace_id=WORKSPACE)

    assert report.updated == 1


async def test_deletion_is_explicit_tombstone_and_stays_deleted():
    """AC4: only a source-declared tombstone deletes; silence changes nothing."""
    source = _single_page_connector(
        [
            _item("doc-1", "v1", "kept"),
            _item("doc-2", "v1", "doomed"),
        ]
    )
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))
    await engine.run(source, instance, workspace_id=WORKSPACE)

    # The source drops doc-2 from its listing entirely (silence) and separately
    # marks doc-1 deleted in the feed it still lists.
    del source.live[("repo", "doc-2")]
    source.live[("repo", "doc-1")] = _item("doc-1", "v2", "kept", deleted=True)
    report = await engine.run(source, instance, workspace_id=WORKSPACE)

    assert report.tombstoned == 1
    records = {
        record.external_id: record for record in await ingest.records(WORKSPACE, "tests.scripted")
    }
    assert records["doc-1"].deleted is True
    # doc-2 disappearing from the feed is NOT a deletion: its record stands.
    assert records["doc-2"].deleted is False

    # The tombstone itself is stable on replay, not re-ingested as new content.
    replay = await engine.run(source, instance, workspace_id=WORKSPACE)
    assert replay.tombstoned == 0
    assert replay.unchanged == 1


async def test_multi_page_sync_walks_the_cursor_to_the_end():
    """Incremental listing consumes every page and reports the resume cursor."""
    source = ExternalStyleConnector(
        {
            None: Page(
                items=(_item("doc-1", "v1", "one"), _item("doc-2", "v1", "two")),
                next_cursor="page-2",
            ),
            "page-2": Page(items=(_item("doc-3", "v1", "three"),), next_cursor=None),
        }
    )
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    report = await engine.run(source, instance, workspace_id=WORKSPACE)

    assert report.ingested == 3
    assert len(await ingest.records(WORKSPACE, "tests.scripted")) == 3


async def test_query_capability_syncs_through_query_items():
    """QUERY drives the connector's query_items, not the listing path."""
    source = ExternalStyleConnector(
        {None: Page(items=(_item("doc-1", "v1", "one"), _item("doc-2", "v1", "two")))}
    )
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    report = await engine.run(source, instance, workspace_id=WORKSPACE, query="doc-2")

    assert report.ingested == 1
    (record,) = await ingest.records(WORKSPACE, "tests.scripted")
    assert record.external_id == "doc-2"


async def test_fetch_capability_refreshes_one_item_by_identity():
    """FETCH re-reads one identity and applies the same provenance stamping."""
    source = _single_page_connector([_item("doc-1", "v1", "before")])
    engine, ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))
    await engine.run(source, instance, workspace_id=WORKSPACE)

    source.live[("repo", "doc-1")] = _item("doc-1", "v2", "refreshed")
    outcome = await engine.fetch(source, instance, workspace_id=WORKSPACE, external_id="doc-1")

    assert outcome.action is SyncAction.UPDATED
    (record,) = await ingest.records(WORKSPACE, "tests.scripted")
    assert record.content == "refreshed"


async def test_clock_injection_sets_ingest_timestamps():
    """The engine's timestamps come from its clock, keeping tests deterministic."""
    frozen = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
    source = _single_page_connector([_item("doc-1", "v1", "content")])
    ingest = MemoryIngestStore()
    engine = SyncEngine(ingest, MemoryCheckpointStore(), clock=lambda: frozen)
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    await engine.run(source, instance, workspace_id=WORKSPACE)

    (record,) = await ingest.records(WORKSPACE, "tests.scripted")
    assert record.ingested_at == frozen.isoformat()


@pytest.mark.parametrize(
    ("capabilities", "use_query"),
    [
        pytest.param(frozenset({ConnectorCapability.LIST}), True, id="query-gated"),
        pytest.param(frozenset({ConnectorCapability.LIST}), False, id="fetch-gated"),
    ],
)
async def test_undeclared_capabilities_are_refused(
    capabilities: frozenset[ConnectorCapability], use_query: bool
):
    """The engine refuses to drive capabilities the descriptor does not declare."""
    source = _single_page_connector([_item("doc-1", "v1", "content")], capabilities=capabilities)
    engine, _ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    with pytest.raises(ConnectorCapabilityError, match="does not declare"):
        if use_query:
            await engine.run(source, instance, workspace_id=WORKSPACE, query="probe")
        else:
            await engine.fetch(source, instance, workspace_id=WORKSPACE, external_id="doc-1")


async def test_capability_gate_names_the_connector_and_capability():
    """The refusal says which connector lacked which capability."""
    source = _single_page_connector(
        [_item("doc-1", "v1", "content")],
        capabilities=frozenset({ConnectorCapability.LIST}),
    )
    engine, _ingest, _checkpoints = _engine()
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset({WORKSPACE}))

    with pytest.raises(ConnectorCapabilityError, match=r"tests\.scripted.*'fetch'"):
        await engine.fetch(source, instance, workspace_id=WORKSPACE, external_id="doc-1")
