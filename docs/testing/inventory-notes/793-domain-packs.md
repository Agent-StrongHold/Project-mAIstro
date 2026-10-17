---
inventory-delta:
  packages/maistro-design/tests: +1
  packages/hive-conductor/backend/tests: +1
---

# #793 (M7-A4) — domain packs of one Run: pack contract tests

`packages/maistro-design/tests/test_packs.py` (+1, 26 tests) covers the new
`maistro_design.packs` subpackage: the pack contract (`DomainPack`,
`PackId` closed enum, `ExecuteBackend`, `FencePoint`, `PackGraphShape`), the
Goal-scoped Rubric catalog projection (`rubric.GoalRubricCatalog`), the
canonical `GraphTemplate` projection (`pack_graph_template`), and the one
registry (`PackRegistry.builtin()` over in-repo YAML manifests).

`packages/hive-conductor/backend/tests/test_design_packs_route.py` (+1,
5 tests) covers the new `GET /design/packs` selector route: exactly the three
shipped packs, one uniform entry shape, no per-pack route in the OpenAPI
schema, and canvas appearing only under `execute_backends`.

## What is actually asserted

- **AC-1** — three manifests load through one registry; the loader iterates
  the closed `PackId` enum, so a member without a manifest is a loud
  `PackManifestError` and a manifest without a member cannot load
  (`parse_manifest` is the single parse path).
- **AC-2** — each pack instantiates a Rubric catalog onto canonical Goal
  identity (`goal_id` + `goal_revision` validated by
  `INTEROP_ONTOLOGY_V1.validate_projection`); `catalog_id` is minted per
  instantiation and `DomainPack` carries no catalog-identity field.
- **AC-3** — every pack's template instantiates and executes through the real
  canonical durable executor (`run_durable_graph` +
  `InMemoryDurableRunStore` + deterministic stub phase nodes, the established
  `tests/graph/durable_runs` pattern): completed `Run`, one `NodeRun` +
  `Attempt` per shape node, all lineage-linked.
- **AC-4** — the same Goal (`goal_id`/`goal_revision` in Run provenance)
  through `product` and `book`: shared Workspace/Project identity, both Runs
  canonical and completed, while template `content_hash`, fence pattern, and
  Rubric dimension sets differ.
- **AC-5** — no pack id names a backend; canvas appears only in
  `execute_backends` and on execute-phase node `binding_ids`; product binds
  canvas, book does not.
- **AC-6** — uniform `PackSummary` listing (substrate) plus the HTTP route
  assertions above (product surface).

Tests carry `contract`/`scope` markers per ADR-032 only — no `ac` markers,
so no new AC ids are claimed in the AC-state ledger; the issue-criterion
mapping lives in this note and in the test module docstring.

## Deliberate scope boundaries recorded

- Fence points are **declared contract data** (which phases gate on
  park/redirect/accept); their *execution* (the durable HITL park) stays with
  the canonical loop runtime — the acceptance criteria for #793 do not
  require fence execution.
- Phase node kinds (`pack.explore` etc.) are loop-runtime bindings resolved
  by the executor's `NodeResolver`; the CI stubs stand in for the real phase
  executors (M7 follow-up), which is why the execution tests prove the
  canonical spine, not LLM behavior.

## Dependency note

`pyyaml` is re-declared in `maistro-design` (first removed by #514 as
unused): the pack registry genuinely parses in-repo YAML manifests now, so
the dependency is real. `uv lock`/`uv sync --locked` re-verified offline.
