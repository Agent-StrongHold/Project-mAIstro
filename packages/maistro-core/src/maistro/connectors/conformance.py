"""Shared conformance for connector implementations (M9-E2, issue #963).

One suite, run unchanged against built-in and out-of-tree connectors: if a
connector passes, the host knows it terminates, refreshes without
duplicating, keeps its checkpoints scoped, honors its capability and secret
declarations, and normalizes unknown-identity fetches. What the suite cannot
simulate against a live connector — source-side deletion, upstream outages —
stays covered by the engine's own tests with scripted sources.

The suite performs real sync runs against the connector it is given; point it
at a connector instance whose upstream is safe to touch. Empty violation
tuple means conformant.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from maistro.connectors.scope import ConnectorInstance, ConnectorSession
from maistro.connectors.secrets import SecretAuthority
from maistro.connectors.sync import (
    DEFAULT_CONFIG_ID,
    MemoryCheckpointStore,
    MemoryIngestStore,
    SyncEngine,
)
from maistro.connectors.types import (
    ConnectorCapability,
    ConnectorError,
    ConnectorScopeError,
    ConnectorUnavailableError,
    SyncReport,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

    from maistro.connectors.base import ConnectorSource
    from maistro.connectors.sync import CheckpointStore, IngestStore

#: The Workspace id the scope probe syncs against; an instance that declares
#: it is a harness misconfiguration, reported as a violation.
_SCOPE_PROBE_WORKSPACE = "__conformance_undeclared_workspace__"

#: The secret name the secret-scope probe resolves; declared names are
#: provisioned by installers, never by this probe.
_SCOPE_PROBE_SECRET = "__conformance_undeclared_secret__"

_FETCH_PROBE_EXTERNAL_ID = "__conformance_missing_external_id__"

_QUERY_PROBE = "conformance-probe"


def _identities(report: SyncReport) -> set[tuple[str, str]]:
    """The (source, external) identity set a sync run touched."""
    return {(o.record.source_id, o.record.external_id) for o in report.outcomes}


def _check_descriptor(source: ConnectorSource) -> tuple[str, ...]:
    """Well-formedness the engine silently relies on."""
    descriptor = source.descriptor
    problems: list[str] = []
    if not descriptor.connector_id or "." not in descriptor.connector_id:
        problems.append("connector_id must be namespaced as 'vendor.connector'")
    if not descriptor.version:
        problems.append("version must be a non-empty token (stamped into provenance)")
    if not descriptor.capabilities:
        problems.append("capabilities must declare at least one of list/query/fetch")
    names = [ref.name for ref in descriptor.secret_refs]
    if len(names) != len(set(names)):
        problems.append("secret_refs must not repeat a name")
    for ref in descriptor.secret_refs:
        if not ref.description:
            problems.append(f"secret ref {ref.name!r} needs a description")
    return tuple(problems)


async def _check_refresh(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """First sync ingests; an immediate replay of the same cursor changes nothing."""
    first = await engine.run(
        source, instance, workspace_id=workspace_id, config_id=config_id, config=config
    )
    if not first.outcomes:
        return ("first sync produced no outcomes; list_items yielded nothing",)
    identities = {(o.record.source_id, o.record.external_id) for o in first.outcomes}
    if len(identities) != len(first.outcomes):
        return (
            "one listing yielded the same source identity twice; the duplicate "
            "would silently overwrite the earlier item",
        )
    problems: list[str] = [
        f"record for {outcome.record.external_id!r} is missing {field}"
        for outcome in first.outcomes
        for field, value in (
            ("connector provenance", outcome.record.connector_id),
            ("connector version", outcome.record.connector_version),
            ("item version", outcome.record.item_version),
            ("ingest timestamp", outcome.record.ingested_at),
            ("workspace scope", outcome.record.workspace_id),
        )
        if not value
    ]
    replay = await engine.run(
        source, instance, workspace_id=workspace_id, config_id=config_id, config=config
    )
    if replay.ingested or replay.updated or replay.tombstoned:
        problems.append(
            "replaying the finished cursor re-ingested or changed items instead of "
            "skipping unchanged ones",
        )
    return tuple(problems)


async def _check_checkpoint_scope(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    checkpoints: CheckpointStore,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """The saved checkpoint must address exactly this Workspace/config stream."""
    report = await engine.run(
        source, instance, workspace_id=workspace_id, config_id=config_id, config=config
    )
    connector_id = instance.descriptor.connector_id
    saved = await checkpoints.load(workspace_id, connector_id, config_id)
    if saved is None:
        return ("engine completed a sync without persisting a checkpoint",)
    if saved.cursor != report.cursor:
        return ("persisted checkpoint cursor does not match the reported resume cursor",)
    other = await checkpoints.load("other", connector_id, config_id)
    if other is not None:
        return ("a checkpoint saved for one Workspace is readable under another",)
    return ()


async def _check_scope(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """Syncing an undeclared Workspace must refuse before the connector runs."""
    try:
        await engine.run(
            source,
            instance,
            workspace_id=_SCOPE_PROBE_WORKSPACE,
            config_id=config_id,
            config=config,
        )
    except ConnectorScopeError:
        return ()
    return ("engine synced a Workspace the instance never declared",)


async def _check_query(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """QUERY connectors must answer identical probes deterministically.

    Emptiness is allowed — an upstream may legitimately hold no matches for a
    probe — but the same probe twice must yield the same identity set.
    """
    first = await engine.run(
        source,
        instance,
        workspace_id=workspace_id,
        config_id=config_id,
        config=config,
        query=_QUERY_PROBE,
    )
    second = await engine.run(
        source,
        instance,
        workspace_id=workspace_id,
        config_id=config_id,
        config=config,
        query=_QUERY_PROBE,
    )
    if _identities(first) != _identities(second):
        return (f"querying {_QUERY_PROBE!r} twice returned different identity sets",)
    return ()


async def _check_fetch(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    ingest: IngestStore,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """FETCH must refresh a known identity and normalize an unknown one."""
    connector_id = instance.descriptor.connector_id
    records = await ingest.records(workspace_id, connector_id)
    known = [record for record in records if not record.deleted]
    if not known:
        return ("no ingestable records from the listing; fetch check skipped",)
    outcome = await engine.fetch(
        source,
        instance,
        workspace_id=workspace_id,
        config_id=config_id,
        external_id=known[0].external_id,
        config=config,
    )
    if outcome.record.external_id != known[0].external_id:
        return ("fetch returned a record for a different identity than requested",)
    try:
        await engine.fetch(
            source,
            instance,
            workspace_id=workspace_id,
            config_id=config_id,
            external_id=_FETCH_PROBE_EXTERNAL_ID,
            config=config,
        )
    except ConnectorUnavailableError:
        return ()
    return (
        f"fetch of unknown identity {_FETCH_PROBE_EXTERNAL_ID!r} did not raise "
        "ConnectorUnavailableError",
    )


async def _check_secrets(
    instance: ConnectorInstance,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[str, ...]:
    """Undeclared secret names must refuse; declared names may be unprovisioned."""
    session = ConnectorSession.create(
        instance, workspace_id=workspace_id, config_id=config_id, config=config or {}
    )
    for ref in instance.descriptor.secret_refs:
        try:
            await session.resolve_secret(ref.name)
        except LookupError:
            continue  # declared but unprovisioned: an operator concern, not a leak
    try:
        await session.resolve_secret(_SCOPE_PROBE_SECRET)
    except ConnectorScopeError:
        return ()
    return ("session resolved a secret the descriptor never declared",)


async def run_connector_conformance(
    source: ConnectorSource,
    *,
    workspace_ids: Sequence[str] = ("default",),
    config_id: str = DEFAULT_CONFIG_ID,
    config: Mapping[str, str] | None = None,
    secrets: SecretAuthority | None = None,
    ingest: IngestStore | None = None,
    checkpoints: CheckpointStore | None = None,
) -> tuple[str, ...]:
    """Run every check; return the violation strings (empty means conformant).

    The instance under test is bound to ``workspace_ids`` as its declared
    allowlist, with ``secrets`` (when given) as its authority. ``ingest`` and
    ``checkpoints`` default to the in-memory reference stores; tests inject
    sabotaged stores here to prove the checkpoint-scope checks have teeth.
    """
    if _SCOPE_PROBE_WORKSPACE in workspace_ids:
        return (f"harness misconfigured: {_SCOPE_PROBE_WORKSPACE!r} must not be declared",)
    problems: list[str] = []
    problems.extend(_check_descriptor(source))
    instance = ConnectorInstance(
        descriptor=source.descriptor,
        workspace_ids=frozenset(workspace_ids),
        secrets=secrets,
    )
    ingest_store: IngestStore = ingest if ingest is not None else MemoryIngestStore()
    checkpoint_store: CheckpointStore = (
        checkpoints if checkpoints is not None else MemoryCheckpointStore()
    )
    engine = SyncEngine(ingest_store, checkpoint_store)
    workspace_id = next(iter(workspace_ids))
    checks = _build_checks(
        engine,
        source,
        instance,
        ingest_store,
        checkpoint_store,
        workspace_id,
        config_id,
        config,
    )
    problems.extend(await _run_checks(checks))
    return tuple(problems)


def _build_checks(
    engine: SyncEngine,
    source: ConnectorSource,
    instance: ConnectorInstance,
    ingest: IngestStore,
    checkpoints: CheckpointStore,
    workspace_id: str,
    config_id: str,
    config: Mapping[str, str] | None,
) -> tuple[Callable[[], Awaitable[tuple[str, ...]]], ...]:
    """Assemble the per-connector checks; capability-gated ones self-skip."""

    async def refresh_check() -> tuple[str, ...]:
        return await _check_refresh(engine, source, instance, workspace_id, config_id, config)

    async def checkpoint_check() -> tuple[str, ...]:
        return await _check_checkpoint_scope(
            engine, source, instance, checkpoints, workspace_id, config_id, config
        )

    async def scope_check() -> tuple[str, ...]:
        return await _check_scope(engine, source, instance, config_id, config)

    async def query_check() -> tuple[str, ...]:
        if ConnectorCapability.QUERY not in instance.descriptor.capabilities:
            return ()
        return await _check_query(engine, source, instance, workspace_id, config_id, config)

    async def fetch_check() -> tuple[str, ...]:
        if ConnectorCapability.FETCH not in instance.descriptor.capabilities:
            return ()
        return await _check_fetch(engine, source, instance, ingest, workspace_id, config_id, config)

    async def secrets_check() -> tuple[str, ...]:
        return await _check_secrets(instance, workspace_id, config_id, config)

    return (
        refresh_check,
        checkpoint_check,
        scope_check,
        query_check,
        fetch_check,
        secrets_check,
    )


async def _run_checks(
    checks: tuple[Callable[[], Awaitable[tuple[str, ...]]], ...],
) -> list[str]:
    """Run each check, reporting failures as violations instead of crashing.

    A connector that raises mid-check is non-conformant, not a harness fault:
    canonical :class:`ConnectorError` refusals are reported verbatim and any
    other exception is reported by type, so the suite always produces a
    readable verdict for the connector it was given.
    """
    problems: list[str] = []
    for check in checks:
        try:
            problems.extend(await check())
        except ConnectorScopeError as exc:  # a refusal outside the scope check
            problems.append(f"unexpected ConnectorScopeError: {exc}")
        except ConnectorError as exc:  # canonical refusal: the connector's fault
            problems.append(f"engine refused the connector: {exc}")
        except Exception as exc:
            problems.append(f"check raised {type(exc).__name__}: {exc}")
    return problems
