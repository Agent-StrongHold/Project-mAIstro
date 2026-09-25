---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---
# auto-1113 verifier-repair round: census truth + split jammed matrix row

Verifier-writer round at head `5eb048b0117a` (branch `auto-1113`). The driver
recorded no `check-*.log` artifacts for this job, so every claim below was
re-executed in the worktree. Two defects found and fixed, both documentation:
no production code changed.

## What was wrong

1. `docs/architecture/CONVERGENCE-MATRIX.md` (boundary section) still claimed
   #1113 "le[ft] the in-process path ... as the explicit no-Container
   standalone fallback" — the reachable pre-convergence Graph lifecycle the
   issue retired. It contradicted the same file's recurrence/schedules row,
   which already described the fail-closed post-#1113 behavior.
2. The develop merge (`c89c011e6`) jammed the `Repo tooling` ownership row
   onto the same physical line as the `Recurrence / schedules` row
   (`...#1113, #1120 || Repo tooling | ...`), so
   `scripts/check-convergence-matrix.py` failed with "rows in the ownership
   table only: Repo tooling". Present at HEAD before this round; an
   incomplete conflict resolution, not a regression of this round.

## Fixes

- Boundary bullet now states the actual contract: since #1113 there is no
  no-Container execution fallback; `run_registered_dag` fails closed with
  `GraphExecutionUnavailableError` and the scheduler tick leaves the
  occurrence owed.
- Split the jammed line into two table rows. Gate now reports
  `OK: 52 subsystems classify all 1125 production modules`.

## Re-executed evidence (all green)

- `uv run ruff check .` / `uv run ruff format --check .` — pass.
- `uv run pytest` targeted: hive `test_dag_agents.py`,
  `test_canonical_dag_runner.py`, `test_graph_spine_architecture_gate.py`,
  `test_graph_runner.py`, `test_dag_run_scope.py`,
  `test_dag_run_history_durability.py` (133 passed);
  `test_optimizer.py`, `test_substrate_tools.py`, `test_engine_service.py`,
  `test_scheduler.py`, `test_dags_routes.py`,
  `test_dag_execution_transport_parity.py`, `test_hitl_door.py`,
  `test_hitl_timeout_cancel.py` (227 passed);
  `test_dag_recovery.py`, `test_canonical_recovery_cadence.py`,
  `test_agent_port_truthful_unavailable.py`, `test_attention_projection.py`,
  `test_dag_condition_trust.py`, `test_node_metrics_are_measured.py`
  (75 passed); core `tests/graph/durable_runs` incl. `test_legacy_archive.py`
  (551 passed, 39 skipped).
- Gates: `check-convergence-matrix.py`, `check-wiring-reads.py`,
  `check-execution-lifecycles.py`, `check-doc-links.py`,
  `check-m1-convergence-freeze.py --base b906cc577fbb`,
  `check-vulture-baseline.py packages/*/src --min-confidence 60` — all pass;
  vulture reports 0 unbanked identities, so no ledger amendment was made.

## Recorded reconciliation (criterion: legacy records "readable/resumable")

Pre-convergence records are readable field-for-field (Run, NodeRuns,
Attempts, traversal history, operator `maistro archive list/show` CLI — 14
tests in `test_legacy_archive.py`), but resume is refused by name
(`LegacyRunNotResumable`, "read but not resumed"). Accepted
ADR-082826-d9f5/AC-6 governs: re-admission under a new identity would mint a
second record for one execution, and an id-preserving replay path would be
the second system of record #1113/#44 remove. The issue's stop condition
(new shipped work must not be created outside the canonical spine) takes
precedence over the literal "resumable"; the refusal is on the operator
screen, not only in the exception.
