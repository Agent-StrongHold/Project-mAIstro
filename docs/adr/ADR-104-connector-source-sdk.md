---
id: ADR-104
title: "Connector/source SDK — out-of-tree ingestion with canonical provenance and incremental sync"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-05
substrate:
  - maistro-engine#ADR-011
  - maistro-engine#ADR-013
  - maistro-engine#ADR-032
  - maistro-engine#ADR-034
implements: []
related:
  - maistro-engine#SPEC-185
  - maistro-engine#ADR-103
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/connectors/test_sdk_public_surface.py
  - packages/maistro-core/tests/connectors/test_sync_checkpoints.py
  - packages/maistro-core/tests/connectors/test_scope_and_errors.py
  - packages/maistro-core/tests/connectors/test_conformance.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-05
---

# ADR-104: Connector/source SDK — out-of-tree ingestion with canonical provenance and incremental sync

## Context

M9-E2 (#963) requires that external data/document/feed/API connectors participate in
canonical knowledge ingestion **without core edits** and without losing source identity,
tenant scope, or refresh semantics. Before this ADR there was no supported way for an
out-of-tree connector to ingest: `maistro.integrations` is a set of hand-wired single-tenant
adapters, `maistro.skills.connectors` is marketplace *search*, and nothing stamped
connector provenance onto ingested memory. The epic's sibling SDKs (#961 providers,
#964 tools/Skills, #965 shared conformance) need the same posture: public contracts,
canonical seams, no private universes.

## Decision

Ship a connector/source SDK as the `maistro.connectors` package of maistro-core, with
four load-bearing rules:

1. **One port, driven only by the host engine.** A connector implements
   `ConnectorSource` (`descriptor`, `list_items`, `query_items`, `fetch_item`) and is
   invoked only through `SyncEngine`. The engine is the only path from connector items to
   an ingest store, and the only site that stamps provenance.
2. **Provenance is stamped at ingestion, completely.** Every item becomes a `SourceRecord`
   carrying connector id + version, source id, external id, item version, content hash,
   Workspace and config scope, and ingest time. There is no ingestion path that skips the
   stamp — records without provenance cannot exist.
3. **Checkpoints commit after items; scope is part of the address.** The cursor is
   persisted (per page) only after that page's items are committed, keyed by
   `(workspace_id, connector_id, config_id)`. A crash replays the last committed cursor,
   and version+content-hash dedup makes replay idempotent: at-least-once delivery with
   no duplicates and no loss.
4. **Deletion and change are explicit; scope and secrets are enforced by the host.**
   Only an item the source marks `deleted` becomes a tombstone (silence changes
   nothing); same version+hash skips (no duplicate re-ingestion); drift updates in place.
   A connector instance is frozen-bound to an allowlist of Workspaces, and secret
   resolution refuses every name not declared on the connector's descriptor — undeclared
   Workspace or secret access raises `ConnectorScopeError` before connector code runs.

Error semantics are canonical: raw `httpx` failures escaping a connector are normalized at
the engine boundary into `ConnectorUnavailableError` / `ConnectorRateLimitedError`
(with parsed `Retry-After`), leaving the checkpoint untouched so retries resume from the
same cursor. Capability gating refuses to drive anything the descriptor does not declare.

## Interface

Public surface (`from maistro.connectors import ...`), the entire integration an
out-of-tree connector needs:

```python
class MyConnector:            # implements ConnectorSource (Protocol)
    @property
    def descriptor(self) -> ConnectorDescriptor: ...   # id ("vendor.name"), version,
                                                       # capabilities, SecretRefs
    async def list_items(self, ctx: SyncContext) -> SyncPage: ...
    async def query_items(self, ctx: SyncContext) -> SyncPage: ...   # ctx.query
    async def fetch_item(self, ctx: SyncContext, external_id: str) -> SourceItem: ...

engine = SyncEngine(ingest_store, checkpoint_store)     # IngestStore/CheckpointStore ports
report = await engine.run(source, ConnectorInstance(descriptor, workspace_ids, secrets))
violations = await run_connector_conformance(source)    # shared built-in/external suite
```

Operator surface: `maistro connectors verify MODULE:CLASS [--workspace W ...]` runs the
shared conformance suite against a loaded connector and exits non-zero on violations;
`maistro connectors describe MODULE:CLASS` prints the declaration installers approve.

Hosts bind durable stores to the `IngestStore`/`CheckpointStore` protocols and their
canonical secret backend to the `SecretAuthority` port (the SDK ships in-memory reference
stores and a `StaticSecretAuthority` for conformance and tests). A declared-but-
unprovisioned secret raises `LookupError` (operator gap); an undeclared name raises
`ConnectorScopeError` (leak refusal).

## Acceptance criteria

Layered contracts per [ADR-032](ADR-032-contracts-as-acceptance-criteria.md):

- AC-1: an out-of-tree connector ingests and refreshes content through the public SDK
  only (`test_sdk_public_surface.py`, external-style fixture importing only
  `maistro.connectors`; `test_conformance.py::test_cli_verify_passes_a_conformant_connector`).
- AC-2: every ingested item preserves connector/source/version provenance
  (`test_every_ingested_item_carries_full_provenance`, conformance refresh check).
- AC-3: sync checkpoints are restart-safe (fault injection at the commit seam) and scoped
  to the correct Workspace/config (`test_sync_checkpoints.py`).
- AC-4: deletion/update are explicit — tombstones and in-place updates, no duplicate
  re-ingestion, silence is not deletion (`test_deletion_is_explicit_tombstone_and_stays_deleted`).
- AC-5: a connector cannot access undeclared Workspaces or secrets
  (`test_scope_and_errors.py`).
- AC-6: reference built-in and external-style connectors pass the same shared conformance
  suite; deliberately broken connectors fail with named violations
  (`test_conformance.py`).

## Consequences

- Provenance for connector-sourced knowledge is queryable from the record alone; memory
  tiers that later consume these records inherit the connector identity chain.
- Per-Workspace cursor isolation means one tenant's sync can never advance another's.
- The shared conformance suite is the single gate installers and CI (#965) both run;
  connector-specific behaviors outside the suite (real upstream deletion, outages) remain
  covered by engine tests with scripted sources.
- Durable (SQLite/Postgres) `IngestStore`/`CheckpointStore` twins are intentionally not
  part of this slice; the protocols are the contract, and #965's conformance work is the
  natural place to add them alongside the provider/tool SDKs.
