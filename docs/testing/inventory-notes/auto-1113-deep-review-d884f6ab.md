# auto-1113 deep review round 2 @ d884f6ab00a0f592582994b3f4dc713512a45a86

Second-round adversarial verification of lane L1113 (issue #1113, PR 1309) at the
assigned head. Base `origin/develop` = ca4caec7d319 (verified ancestor of HEAD:
0 behind, 18 ahead). Driver checks in this job: uv sync, ruff check/format, 413
Hive tests, suite inventory — all green.

## Previous blocks resolved

- **"develop sync conflict preserved in worktree" — REFUTED.** `git merge-base
  --is-ancestor origin/develop HEAD` succeeds; tree clean at the assigned head;
  no MERGE_HEAD; nothing to resolve. The two stashes in the repo belong to other
  lanes (`repair-1396`, `repair-1321`) and were not touched.
- **Round-1 findings 1–3 (legacy archive resume / ADR conflict) — REFUTED as lane
  defects.** The lane diff touches zero files under `packages/maistro-core`,
  `docs/specs`, `docs/adr`, or `quality/`. `ArchivedGraphRun.resume()` raising
  `LegacyRunNotResumable` (legacy_archive.py:78-83) is ADR-082826-d9f5/AC-6's
  ratified contract: archived pre-convergence runs are *readable* (reader +
  `list_by_status` + CLI consumer `maistro/cli/_archive.py`) and *refused
  resumption by name* precisely so no second system of record grows. Issue
  #1113's acceptance cites "the documented legacy/archive compatibility path",
  and the documented path is exactly this; the "conflict" was spec-vs-spec
  misreading. 14 archive tests pass locally (re-run this round).
- **Round-1 finding 4 (CI pending) — SUPERSEDED by hard evidence, see below.**

## New findings (CI on this exact head, refreshed read-only)

1. **`Quality gate (Pillars 1–4, 7, 8)` FAILED** — reproduced locally with the
   exact CI command (`check-ac-state.py --run-tests --ratchet --mandate
   <develop base>`); three counter failures:
   - `markers_without_criterion: 4 exceeds the ceiling of 2`. The lane added 4
     markers naming unregistered criteria: `M1-E-1113/AC-3`
     (test_dag_agents.py:255,274; test_dag_run_history_durability.py:651) and
     `M1-E-1113/AC-1` (test_dag_agents.py:290). `M1-E-1113/*` is a GitHub issue
     id, not a declared spec/ADR criterion.
   - `design_coverage: 37.9642 falls below the floor of 38.0924`. Fully
     explained and branch-attributable: the lane removed the
     `@pytest.mark.ac("ADR-082526-3ca6/AC-5")` markers (superseded tests
     retagged with `M1-E-1113/*`), dropping 1 of that ADR's 5 criteria from
     `reachable`; (1/5)/156 decisions = 0.1282pp — exactly the observed
     shortfall. Repair: register the M1-E-1113 criteria in a spec (or retag the
     4 markers to declared criteria that the tests still prove) — that alone
     fixes both counter breaches; then re-run `--ratchet --bank` if the ledger
     still demands it.
   - `design_coverage: 3 note(s) already clear it on their own` — stale
     authorization grants (auto-1138, auto-1158, auto-48) must be pruned from
     `quality/ratchet-authorizations.json`.
2. **`hive-conductor-e2e-ui` FAILED** (Playwright `expect(...).toBeTruthy()`
   twice; hive container logging httpx Connection refused during diagnose).
   Cause UNVERIFIED from logs (could be a HITL/DAG-surface behavior change in
   this lane or infra flake; non-UI `hive-conductor-e2e` passed). Lane owner
   must triage.
3. **`integration-scope` FAILED** transitively (it requires
   `hive-conductor-e2e-ui` success). `test`, coverage gate, and `gates-ran`
   were still in progress/pending — CI not green.

## Acceptance verification (all ten criteria)

1. run_registered_dag fail-closed — PROVEN: dag_agents.py:101-116,153-163 raise
   `GraphExecutionUnavailableError` before any `create_run`; test_dag_agents.py:290-303; executed locally.
2. execute_dag, no compat scope — PROVEN: canonical_dag_runner.py:327-346
   requires canonical stores; zero repo matches for `hive-standalone-compat` /
   `_COMPAT_SCOPE`; tests test_canonical_dag_runner.py:390-509.
3. Bridge absence → explicit unavailable/degraded — PROVEN: unavailable result
   (canonical_dag_runner.py:533-535); 503 HITL (routes/hitl.py:76-93);
   optimizer/substrate/chat/validation gate surfaces; scheduler fails closed.
4. Fallback store removed/gated — PROVEN: zero production references to
   `InMemoryDurableRunStore`; AST gate test_graph_spine_architecture_gate.py.
5. Legacy readable / no new pre-convergence Runs — PROVEN per documented
   contract (ADR-082826-d9f5/AC-6); readable reader + CLI; 14 tests pass.
6. Restart/replica — PROVEN: test_dag_run_history_durability.py:74 (restart),
   :431 (cross-replica reload); canonical recovery tests; executed locally.
7. Canonical Workspace/Project scope authority — PROVEN:
   services/dag_execution_scope.py resolves through `workspace_authority`;
   scope mismatch refusals tested.
8. EngineService truthful degraded mode — PROVEN: engine.py:99-106
   `graph_execution_available`; unavailable surfaces everywhere Graph work is
   requested; test_engine_service.py:611-628.
9. Architecture regression gate — PROVEN (see 4).
10. Authority census — PROVEN locally: `check-convergence-matrix.py` OK (52
    subsystems / 1133 modules); matrix rows retracted to fail-closed truth.

## Verdict

NEEDS-REPAIR — local acceptance evidence is complete, but required CI is red on
this exact head for concrete, repairable reasons (finding 1 fully diagnosed;
finding 2 needs triage). Not MERGE-READY until the ratchet counters are repaired
and the e2e-ui/integration-scope checks pass.
