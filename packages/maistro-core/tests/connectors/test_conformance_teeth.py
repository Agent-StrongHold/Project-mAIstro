"""The shared conformance suite must have teeth, not pass vacuously.

Each test here sabotages one contract axis — a store that never persists, a
store that leaks checkpoints across Workspaces, a connector whose queries are
nondeterministic or whose fetch returns the wrong identity — and asserts the
suite names the violation instead of passing. A conformance suite that cannot
fail is decoration; this module is its proof of enforcement.
"""

from __future__ import annotations

import pytest

from connectors.connector_fixtures import Page, ScriptedConnector
from maistro.connectors import (
    ConnectorCapability,
    ConnectorScopeError,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SecretRef,
    SourceItem,
    SyncCursor,
    SyncEngine,
    SyncPage,
    run_connector_conformance,
)

_WS = ("ws-primary",)


def _item(external_id: str, content: str = "content") -> SourceItem:
    return SourceItem(source_id="repo", external_id=external_id, content=content, version="v1")


def _working_connector(**overrides) -> ScriptedConnector:
    kwargs = {"connector_id": "builtin.working"}
    kwargs.update(overrides)
    return ScriptedConnector(
        {None: Page(items=(_item("doc-1"), _item("doc-2")), next_cursor=None)},
        **kwargs,
    )


async def test_empty_version_is_a_named_violation():
    violations = await run_connector_conformance(_working_connector(version=""), workspace_ids=_WS)
    assert any("version must be a non-empty token" in v for v in violations)


async def test_empty_capabilities_is_a_named_violation():
    violations = await run_connector_conformance(
        _working_connector(capabilities=frozenset[ConnectorCapability]()), workspace_ids=_WS
    )
    assert any("at least one of list/query/fetch" in v for v in violations)


async def test_duplicate_secret_names_are_a_named_violation():
    duplicated = (
        SecretRef(name="api_token", description="upstream token"),
        SecretRef(name="api_token", description="same name again"),
    )
    violations = await run_connector_conformance(
        _working_connector(secret_refs=duplicated), workspace_ids=_WS
    )
    assert any("must not repeat a name" in v for v in violations)


async def test_changing_listing_between_runs_is_a_named_violation():
    """A source whose replay of the finished cursor mutates items fails."""

    class ShiftingConnector(ScriptedConnector):
        def __init__(self, pages=None, **kwargs) -> None:
            super().__init__(pages, **kwargs)
            self._runs = 0

        async def list_items(self, ctx: object) -> SyncPage:
            self._runs += 1
            content = f"content-{self._runs}"  # different on every listing
            return SyncPage(
                items=(_item("doc-1", content=content),),
                next_cursor=None,
            )

    violations = await run_connector_conformance(
        ShiftingConnector({None: Page(items=(), next_cursor=None)}, connector_id="builtin.shift"),
        workspace_ids=_WS,
    )
    assert any("re-ingested or changed items" in v for v in violations)


class _BlackHoleCheckpoints(MemoryCheckpointStore):
    """Accepts saves, remembers nothing: the engine 'completed' without one."""

    async def save(self, cursor: SyncCursor) -> None:
        return None


async def test_checkpoint_never_persisted_is_a_named_violation():
    violations = await run_connector_conformance(
        _working_connector(), workspace_ids=_WS, checkpoints=_BlackHoleCheckpoints()
    )
    assert any("without persisting a checkpoint" in v for v in violations)


class _LeakyCheckpoints(MemoryCheckpointStore):
    """Hands one Workspace's checkpoint back for another: a scope leak."""

    async def load(self, workspace_id: str, connector_id: str, config_id: str):
        if workspace_id == "other":
            return await super().load("ws-primary", connector_id, config_id)
        return await super().load(workspace_id, connector_id, config_id)


async def test_cross_workspace_checkpoint_leak_is_a_named_violation():
    violations = await run_connector_conformance(
        _working_connector(), workspace_ids=_WS, checkpoints=_LeakyCheckpoints()
    )
    assert any("readable under another" in v for v in violations)


async def test_checkpoint_cursor_mismatch_is_a_named_violation():
    """A check-time load that disagrees with the run's own cursor is caught."""
    from maistro.connectors.conformance import _check_checkpoint_scope
    from maistro.connectors.scope import ConnectorInstance

    class FixedLoadStore:
        """Always reports a cursor the run never reached."""

        async def load(self, workspace_id: str, connector_id: str, config_id: str) -> SyncCursor:
            return SyncCursor(
                workspace_id=workspace_id,
                connector_id=connector_id,
                config_id=config_id,
                cursor="mismatched-cursor",
                updated_at="stale",
            )

        async def save(self, cursor: SyncCursor) -> None:
            return None

    source = _working_connector()
    engine = SyncEngine(MemoryIngestStore(), MemoryCheckpointStore())
    instance = ConnectorInstance(descriptor=source.descriptor, workspace_ids=frozenset(_WS))

    violations = await _check_checkpoint_scope(
        engine, source, instance, FixedLoadStore(), _WS[0], "default", None
    )

    assert any("does not match the reported resume cursor" in v for v in violations)


async def test_nondeterministic_query_is_a_named_violation():
    """The same probe twice must yield the same identity set."""

    class FlakyQueryConnector(ScriptedConnector):
        def __init__(self, pages=None, **kwargs) -> None:
            super().__init__(pages, **kwargs)
            self._flip = False

        async def query_items(self, ctx: object) -> SyncPage:
            self._flip = not self._flip
            items = (_item("doc-1"),) if self._flip else ()
            return SyncPage(items=items, next_cursor=None)

    violations = await run_connector_conformance(
        FlakyQueryConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.flaky",
        ),
        workspace_ids=_WS,
    )
    assert any("different identity sets" in v for v in violations)


async def test_all_deleted_listing_skips_fetch_with_a_named_violation():
    source = ScriptedConnector(
        {
            None: Page(
                items=(_item("doc-1"),),
                next_cursor=None,
            )
        },
        connector_id="builtin.tombs",
    )
    source.live[("repo", "doc-1")] = _item("doc-1")
    # Make the listing yield only a tombstone, so no fetchable record exists.
    source.live[("repo", "doc-1")] = SourceItem(
        source_id="repo", external_id="doc-1", content="x", version="v2", deleted=True
    )
    violations = await run_connector_conformance(source, workspace_ids=_WS)
    assert any("no ingestable records" in v for v in violations)


async def test_fetch_returning_wrong_identity_is_a_named_violation():
    class WrongIdentityConnector(ScriptedConnector):
        async def fetch_item(self, ctx: object, external_id: str) -> SourceItem:
            return _item("someone-else")

    violations = await run_connector_conformance(
        WrongIdentityConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.wrong",
        ),
        workspace_ids=_WS,
    )
    assert any("different identity than requested" in v for v in violations)


async def test_fetch_serving_unknown_identity_is_a_named_violation():
    class ObliviousFetchConnector(ScriptedConnector):
        async def fetch_item(self, ctx: object, external_id: str) -> SourceItem:
            return _item(external_id)  # fabricates content for anything

    violations = await run_connector_conformance(
        ObliviousFetchConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.oblivious",
        ),
        workspace_ids=_WS,
    )
    assert any("did not raise" in v and "ConnectorUnavailableError" in v for v in violations)


async def test_broken_secret_enforcement_is_a_named_violation(monkeypatch: pytest.MonkeyPatch):
    """If the SDK's declaration gate regressed, the suite must catch it."""
    from maistro.connectors import scope as scope_module
    from maistro.connectors.conformance import _SCOPE_PROBE_SECRET
    from maistro.connectors.secrets import StaticSecretAuthority

    def permissive(descriptor_refs: tuple[SecretRef, ...], name: str) -> SecretRef:
        return SecretRef(name=name, description="monkeypatched permissive")

    monkeypatch.setattr(scope_module, "require_declared_secret", permissive)
    authority = StaticSecretAuthority(
        {("ws-primary", _SCOPE_PROBE_SECRET): "provisioned probe value"}
    )
    violations = await run_connector_conformance(
        _working_connector(), workspace_ids=_WS, secrets=authority
    )
    assert any("never declared" in v for v in violations)


async def test_connector_raising_scope_error_is_reported_as_unexpected():
    """A scope refusal outside the scope check is a named, non-fatal violation."""

    class ScopeBombConnector(ScriptedConnector):
        async def list_items(self, ctx: object) -> SyncPage:
            raise ConnectorScopeError("connector tried to escape mid-listing")

    violations = await run_connector_conformance(
        ScopeBombConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.bomb",
        ),
        workspace_ids=_WS,
    )
    assert any("unexpected ConnectorScopeError" in v for v in violations)


async def test_arbitrary_connector_crash_is_reported_by_type():
    class ExplodingConnector(ScriptedConnector):
        async def list_items(self, ctx: object) -> SyncPage:
            raise RuntimeError("connector bug: off-by-one")

    violations = await run_connector_conformance(
        ExplodingConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.boom",
        ),
        workspace_ids=_WS,
    )
    assert any("check raised RuntimeError" in v for v in violations)
