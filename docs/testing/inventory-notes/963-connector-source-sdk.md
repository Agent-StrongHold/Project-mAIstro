---
inventory-delta:
  packages/maistro-core/tests: +60
---

Issue #963 (M9-E2) adds the connector/source SDK — `maistro.connectors` — with the
canonical sync engine, scope/secret enforcement, and the shared conformance suite.

`packages/maistro-core/tests/connectors/` (+60 total) covers the six acceptance
criteria. `test_sdk_public_surface.py` (+14) drives an external-style connector that
imports only the public SDK through the engine: full provenance on every record
(connector id/version, source/external identity, item version, content hash,
Workspace/config scope, ingest timestamp), unchanged-item dedup, in-place update on
version or content drift, explicit tombstones where source silence changes nothing,
multi-page cursor walks, QUERY and FETCH paths, clock injection, and capability gating
refusals. `test_sync_checkpoints.py` (+5) is the AC-3 core: a fault injected at the
item-commit/checkpoint seam makes the first run crash after committing its pages, and
the recovery run replays the unsaved cursor with zero loss and zero duplicates; further
tests pin per-page watermark resumption, (workspace, connector, config) checkpoint
addressing, and two-Workspace independence. `test_scope_and_errors.py` (+13) proves the
undeclared-Workspace refusal happens before connector code runs and leaves no records or
checkpoints, that undeclared secret names raise `ConnectorScopeError` while declared-but-
unprovisioned ones raise `LookupError`, that sessions cannot be re-scoped, and that raw
`httpx` 429/transport/503 failures normalize to the canonical errors (parsed
`Retry-After`, checkpoint untouched) with a page-budget failure for non-terminating
cursors. `test_conformance.py` (+15) runs the shared suite over the in-tree reference
and external-style connectors (both pass with zero violations), over multi-page streams,
and over deliberately broken connectors that fail with named violations; it also drives
`maistro connectors verify`/`describe` end-to-end through the CLI for conformant,
broken, unloadable, and non-connector targets, in both `module:Class` and `module.Class`
spellings. `test_conformance_teeth.py` (+13) proves the suite cannot pass vacuously:
sabotaged stores (never persisting, leaking checkpoints across Workspaces, mismatched
cursors) and misbehaving connectors (shifting replays, nondeterministic queries, wrong-
identity fetches, fabricated fetches, repeated secret names, empty versions/capabilities,
mid-check scope escapes, arbitrary crashes) each produce their named violation.
