---
inventory-delta:
  packages/maistro-core/tests: +21
---

# m4e-harness-targets

Implementation round for EPIC M4-E (issue #25, "Harness components as
evolvable targets") — the epic-level substrate both child streams (#783
root-Agent Graph/harness adaptation, #822 Codex App Server HarnessRunner
provider) consume.

## What was added

`packages/maistro-core/src/maistro/graph/harness_targets.py`:

- `HarnessTargetKind` — the closed vocabulary of evolvable harness component
  classes (prompt, tool_selection, skills, memory_retrieval_policy,
  planning_strategy, subagent_definitions, graph_topology, authorized_code).
- `HarnessComponentTarget` / `HarnessEvolutionProposal` — the artifact an M4-A
  optimizer emits: base template, target components, rationale, and mandatory
  producing-Run provenance (ADR-083026-e602). Malformed candidates (edges
  outside the candidate topology) are refused at proposal time.
- `materialize_candidate()` — registers the proposal as the template's **next
  candidate** version, stamping proposal/run/target provenance into the
  version metadata. Overrides `GraphTemplate`'s `"active"` lifecycle default,
  so an optimizer artifact cannot self-activate by being stored.
- `apply_harness_proposal()` — the only sanctioned path from proposal to live
  template: materialize, then route through
  `maistro.graph.templates.promote_audited` (attempt → promoting → committed →
  active) under a required `PromotionApproval` and audit sink, i.e. harness
  improvement consumes the governed promotion machinery (#21/#116) rather than
  self-activating.

Physical work stays on the canonical Graph -> Run -> NodeRun -> Attempt spine:
proposals name their producing Run, foreign harness sessions are untouched, and
no second promotion authority is introduced.

## Tests (`packages/maistro-core/tests/graph/test_harness_targets.py`)

21 tests across the same three-backend store fixture used by
`test_template_store.py` (memory/sqlite/postgres; postgres skipped without
`MAISTRO_TEST_PG_DSN`):

- the target enum equals exactly the epic's component set; unclassifiable
  kinds are refused; proposals without targets/producing-run, with blank
  target fields, are refused; candidate edges outside the candidate topology
  fail at proposal time
- materialization: creates a candidate (never active) version, leaves the
  active base as what unversioned lookups resolve, stamps provenance, refuses
  unknown template / unknown named base version / no-active-base /
  explicitly-named candidate base / foreign-workspace proposals / topology
  claims without topology changes, honors a named *active* base version, and
  allocates fresh version numbers per application
- application: promotes only through the governed path with recorded audit
  entries, `approval` is a required argument (no default to forget), an audit
  failure before the state change blocks promotion leaving the candidate
  intact, and provenance survives promotion on the live version

## Coverage classification

Per ADR-082526-cb51 (diff coverage measured scope is declared): measured scope
is `packages/maistro-core/src/maistro/graph/harness_targets.py` — 100% lines
and 100% branch arcs under the suite (85 statements, 26 branches, 0 missing;
the only exclusion is the `pragma: no cover` post-promotion re-read guard).
