---
inventory-delta:
  tests/: +10
---

# #459 cross-product parity harness

Branch: `chatgpt/m1-459-cross-product-parity`
Base recovered from zero diff and fast-forwarded to `develop@93401f3485ebb815dedc1b0c6b7ad1d7e767fa32` before mutation.

## Scope

This branch owns the cross-product parity **test harness and the #446 repair seams**. It does not close #459.

The repair is limited to canonical inspection authorization, the BuilderPipeline canonical composition, public scheduler/Evolve invocation entry points, the Hive engine chat composition, and their parity evidence. It does not change the canonical Run/Graph store, migration, workflow, quality gate, or ontology.

## Ownership audit

Before mutation the existing #459 branch was verified as a zero-diff released lane with no open PR. The live open-PR set was audited for Builders, Evolve, scheduler, Conductor/DAG, ontology, golden baselines, Canvas and Invocation ownership. Ownership was rechecked while the branch was active so replacement PRs are recorded rather than stale draft numbers.

Relevant active dependencies observed during the audit:

- Builders canonical execution: PR #744 / issue #734.
- Evolve canonical execution: PR #733 / issue #51.
- scheduler canonical admission: PR #759 / issue #231.
- Conductor Workspace/DAG scope prerequisite: PR #770 / issue #766.
- Conductor canonical live Run inspection: issue #65, currently with no open PR. Its acceptance explicitly requires canonical stores/events rather than product-private execution state and visibility of Run/NodeRun/Attempt, Invocation, artifact, event and provenance evidence.
- importable interoperability ontology: replacement PR #870 / issue #458. Closed draft #758 was superseded on the same implementation lane.
- immutable golden behavioral baselines: replacement PR #869 / issue #463. Draft #771 was superseded by the replacement PR.
- Canvas canonical execution: PR #746, audited only; product implementation remains out of scope.
- Invocation convergence: PR #762, audited only; product implementation remains out of scope.

A branch discovered from CI, `chatgpt/issue-736-canonical-dag-run-route`, was also audited. Issue #736 and its closed draft PR #743 document the shipped DAG Run-button convergence attempt, but that lane stopped at the missing authorized Workspace/Project selection seam and carried no production route change. It is therefore a dependency-history signal, not a competing #459 implementation owner.

The repair for #446 wires the DAG-run route through the inspection service rather than importing
`services.dag_run_store` directly. When the Engine has a canonical Run store, inspection
lists and resolves canonical Runs first; the projection remains an event/detail receipt and
standalone compatibility path. Control continues to dispatch through the canonical Run
service, so projection terminal state cannot replace canonical lifecycle truth.

## Harness architecture

`tests/cross_product_parity/harness.py` provides reusable contracts rather than product behavior:

1. `open_durable_profile` calls the repository's supported `maistro.runs.wiring.wire_execution_spine` with a real SQLite connection. The resulting Project, Run, Graph-template, schedule and continuation stores are the normal durable integration profile, not in-memory doubles.
2. `Dependency`/`SourceProbe` records named upstream ownership and concrete public-seam evidence. A blocked scenario is accepted only when its missing state is tied to a tracking issue/PR plus an observable missing/legacy source seam.
3. `assert_identity_projection` requires exact shared Workspace, Project, Graph, Run, NodeRun, Attempt, Event, Invocation, artifact and provenance identities wherever the canonical observation exposes them. It rejects alternate Run-ID aliases and product-private terminal states.
4. `assert_ontology_identity_projection` consumes #458's executable ontology for concepts actually defined there. Event and artifact/provenance identities are intentionally not invented as ontology-v1 concepts; the generic exact-ID contract covers them when exposed.
5. `load_golden_scenario` and `assert_matches_golden` consume #463's fixture files and matcher directly. Expectations are not copied into #459.

No `skip`, `importorskip`, expected-failure marker, or other test suppression is used. The repository autonomous-merge policy treats newly introduced suppressions as integrity findings, so unavailable scenarios instead execute assertion-backed dependency-state checks and return before a dependency-owned interface is imported. If any subset of dependencies lands, only the remaining concrete blockers are accepted.

## Collected parity contracts

The named suite currently contributes eleven integration tests:

1. The supported SQLite execution spine persists the identical canonical Run, Graph, Workspace, Project and admission provenance across connection close/reopen.
2. An identical cross-product identity projection is accepted.
3. A deliberately introduced second Run ID mapping and a product-private terminal state both fail the parity contract.
4. Builders -> Conductor scenario 1 runs the shipped BuilderPipeline canonical composition rather than constructing its executor directly.
5. Scheduler -> shared inspection scenario 2 runs the live cadence entry point and observes through Conductor inspection.
6. Evolve -> shared inspection scenario 3 runs the public EvolutionService cycle and observes through Conductor inspection.
7. The Hive chat scenario runs the shipped engine chat door
   (`EngineService.route_request` -> `MaistroCoreBridge` -> `Container.route_request`)
   over the durable SQLite spine: one ordinary conversation-only turn admits a
   canonical Run with `chat` admission provenance and session correlation,
   executes exactly one NodeRun/Attempt, resolves its agent from the boot-
   materialized workspace roster (`agents/` shipped manifests, fail-closed), and
   the Conductor inspection seam resolves the same Run through the canonical
   store.
8. Scenario 4 consumes the #458 executable identity ontology once it lands.
9. Scenario 6 consumes #463's independent golden fixture/matcher once it lands.
10. Strict closeout rejects blocker-only producer passes.
11. A harness-integrity test rejects test-suppression escape hatches in this suite.

## Acceptance status

The original #459 commit was scaffold/evidence, not completion evidence. The #446 repair
adds executable Builders, scheduler, and Evolve producer scenarios over durable canonical
Run/NodeRun/Attempt state and registers a strict CI invocation. The remaining statements
below describe the original scaffold's independent guarantees, not a current blocker.

Already proven independently by this branch:

- the harness runs against the real supported durable SQLite spine;
- restart preserves the canonical identity/provenance observation used by the suite;
- the shared-ID parity contract rejects a planted second Run identity and product-private terminal state;
- unavailable product scenarios are explicitly tied to named source-level dependency evidence without skips/suppressions;
- #458 and #463 are consumed as external authorities rather than recreated.

The strict closeout suite now executes the four producer scenarios — Builders,
scheduler, Evolve, and Hive ordinary conversation chat — against the canonical
spine and fails closed in CI when any scenario cannot run. Each producer uses a
shipped composition entry point (Builders session pipeline, live scheduler
cadence, EvolutionService cycle, the Hive engine chat door with its boot-
materialized workspace roster) and the Conductor inspection seam where the
product exposes one. The Hive chat scenario has no dependency gate: it always
executes, so the strict-closeout CI step cannot pass while Hive's ordinary chat
is off the canonical spine. Broader identity coverage and #459's own closeout
acceptance remain governed by #459 and its downstream dependencies; the four
executed producer scenarios are this branch's contribution, and the gap between
them and #459's full scenario set stays visible as unexecuted #459 work rather
than as a green strict-closeout step.
