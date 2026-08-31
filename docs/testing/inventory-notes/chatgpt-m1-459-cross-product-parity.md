---
inventory-delta:
  tests/cross_product_parity: +9
---

# #459 cross-product parity harness

Branch: `chatgpt/m1-459-cross-product-parity`
Base recovered from zero diff and fast-forwarded to `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32` before mutation.

## Scope

This branch owns the cross-product parity **test harness only**. It does not implement missing product convergence and does not close #459.

The diff is limited to `tests/cross_product_parity/**` plus this #459-specific evidence note. No Builders, Evolve, scheduler, Canvas/Turing, Conductor product implementation, canonical Run/Graph store, migration, workflow, quality gate, or ontology implementation is changed.

## Ownership audit

Before mutation the existing #459 branch was verified as a zero-diff released lane with no open PR. The live open-PR set was audited for Builders, Evolve, scheduler, Conductor/DAG, ontology, golden baselines, Canvas and Invocation ownership.

Relevant active dependencies observed during the audit:

- Builders canonical execution: PR #744 / issue #734.
- Evolve canonical execution: PR #733.
- scheduler canonical admission: PR #759.
- Conductor Workspace/DAG scope prerequisite: PR #770 / issue #766.
- Conductor canonical live Run inspection: issue #65, currently with no open PR. Its acceptance explicitly requires canonical stores/events rather than product-private execution state and visibility of Run/NodeRun/Attempt, Invocation, artifact, event and provenance evidence.
- importable interoperability ontology: PR #758 / issue #458.
- immutable golden behavioral baselines: PR #771 / issue #463.
- Canvas canonical execution: PR #746, audited only; product implementation remains out of scope.
- Invocation convergence: PR #762, audited only; product implementation remains out of scope.

The current `GET /v1/dag-runs/{run_id}` route still resolves `services.dag_run_store.get_dag_run_store`, so the shared Conductor inspection plane required for scenarios 1-3 is genuinely unavailable on this base. The harness records that as a source-level dependency on #65 rather than constructing a test-only substitute.

## Harness architecture

`tests/cross_product_parity/harness.py` provides reusable contracts rather than product behavior:

1. `open_durable_profile` calls the repository's supported `maistro.runs.wiring.wire_execution_spine` with a real SQLite connection. The resulting Project, Run, Graph-template, schedule and continuation stores are the normal durable integration profile, not in-memory doubles.
2. `Dependency`/`SourceProbe` records named upstream ownership and concrete public-seam evidence. A blocked scenario is accepted only when its missing state is tied to a tracking issue/PR plus an observable missing/legacy source seam.
3. `assert_identity_projection` requires exact shared Workspace, Project, Graph, Run, NodeRun, Attempt, Event, Invocation, artifact and provenance identities wherever the canonical observation exposes them. It rejects alternate Run-ID aliases and product-private terminal states.
4. `assert_ontology_identity_projection` consumes #458's executable ontology for concepts actually defined there. Event and artifact/provenance identities are intentionally not invented as ontology-v1 concepts; the generic exact-ID contract covers them when exposed.
5. `load_golden_scenario` and `assert_matches_golden` consume #463's fixture files and matcher directly. Expectations are not copied into #459.

No `skip`, `importorskip`, expected-failure marker, or other test suppression is used. The repository autonomous-merge policy treats newly introduced suppressions as integrity findings, so unavailable scenarios instead execute assertion-backed dependency-state checks and return before a dependency-owned interface is imported. If any subset of dependencies lands, only the remaining concrete blockers are accepted.

## Collected parity contracts

The named suite currently contributes nine integration tests:

1. The supported SQLite execution spine persists the identical canonical Run, Graph, Workspace, Project and admission provenance across connection close/reopen.
2. An identical cross-product identity projection is accepted.
3. A deliberately introduced second Run ID mapping and a product-private terminal state both fail the parity contract.
4. Builders -> Conductor scenario 1 asserts its exact active dependencies; when both public seams are present, the same test activates rather than using a substitute runtime.
5. Scheduler -> shared inspection scenario 2 follows the same dependency contract.
6. Evolve -> shared inspection scenario 3 follows the same dependency contract.
7. Scenario 4 consumes the #458 executable identity ontology once it lands.
8. Scenario 6 consumes #463's independent golden fixture/matcher once it lands.
9. A harness-integrity test rejects test-suppression escape hatches in this suite.

## Acceptance status

This commit is scaffold/evidence, not completion evidence for #459.

Already proven independently by this branch:

- the harness runs against the real supported durable SQLite spine;
- restart preserves the canonical identity/provenance observation used by the suite;
- the shared-ID parity contract rejects a planted second Run identity and product-private terminal state;
- unavailable product scenarios are explicitly tied to named source-level dependency evidence without skips/suppressions;
- #458 and #463 are consumed as external authorities rather than recreated.

Still required before #459 can close:

- execute actual Builders-created canonical work and observe the same canonical IDs through landed Conductor inspection;
- fire an actual schedule and observe its canonical Run through that same inspection plane;
- execute actual Evolve work and observe its canonical Run through that same inspection plane;
- exercise all applicable Workspace/Project/Graph/Run/NodeRun/Attempt/Event/Invocation/artifact/provenance identities exposed by those real product flows;
- feed real converged product observations, not only oracle-wiring examples, through the #463 matcher.

Until those dependencies land and the product scenarios execute, #459 must remain open.
