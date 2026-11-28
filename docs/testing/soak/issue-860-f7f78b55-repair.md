# Issue #860 repair checkpoint — f7f78b55

## Frozen scope

- One issue: #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `a8c0d6d0806f763b005ff3ddabb60bd44bac3b99`; clean worktree.
- Inputs: supplied dispatch-context.json, prior result d4f627b2, prior check-3.log 98a11313. No check-*.log files were supplied in this job directory.
- Candidate edits limited to this handoff, `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its adjacent production schema implementation if reproduced evidence warrants, an inventory note if tests change, and `quality/vulture-baseline.json` only for reviewed scanner findings explicitly authorized by this repair assignment.
- Read-only acceptance inspection: soak runner/profile/docs/tests, relevant ADRs, production paths exercised by those tests, and gate scripts/workflows.

## Initial evidence and assumption

Prior check-3.log reports schema-fence expected DDL count 21 versus actual 24. This is historical evidence, not proof of a current failure. Reproduce before editing.
Prior result reports no designated exact RC artifact/configuration and failed replica-security/receipt claims. Revalidate the relevant reachable behavior; do not treat an ASGI probe or source-run shakedown as production soak evidence.
No GitHub mutation or cross-worktree operation is authorized. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority remains unchanged.

## Executed validation

- Required exact-argument vulture command: PASS, 1322 reviewed identities / 1322 findings, zero unclassified. No ledger change is warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped (1.30s). The historical failure is already repaired: expected DDL explicitly includes all three validation audit columns. No test or production edit is warranted for that stale failure.
- Read-only lookup of `docs/testing/soak/README.md`: not found; skipped. Runner explicitly points to `docs/testing/soak/m3a-load-profile.md` instead.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`: 93 passed (2.61s).
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

The production-middleware regression reproduces independent allowances for one identity on both instances; the production-router regression reproduces a local receipt 200 and peer 404. These are meaningful ASGI probes, not deployed ingress or sustained-load evidence. The existing runner refuses exact-RC equivalence even for synthetic four-hour passing preflight evidence. No new tests were added; no inventory delta is needed.

## Architecture reconciliation

Read accepted ADR-081426-1f7c (Attempt identity and runtime mechanics), ADR-081626-f383 (durable execution fence), and later ADR-082526-b36a (optional TTL, fenced renewal, heartbeat and reclamation). The later ADR supplies the reclamation contract deferred by the earlier fencing ADR. Any production experiment must exercise these existing authorities, not introduce a scheduler or infer worker death from restart alone. No architecture or policy changes were made.

## Acceptance assessment

| #860 criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | UNVERIFIED. Inspected `m3a-load-profile.md`: one credential, no concurrent Workspace population, fan-out, successful tool/model, Canvas or Goal workloads. Applicability to a designated RC remains unresolved. |
| At least two deployed application replicas | UNVERIFIED. Executed two-instance production-middleware/router ASGI probes only; no deployed multi-replica experiment. |
| Sustained saturation, queues, reclaim, retry/backoff and leaks | UNVERIFIED. No sustained production traffic or long-window resource series executed. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | UNVERIFIED. Fencing/recovery tests passed within the 93-test run; they do not prove cross-process physical-effect uniqueness under load. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall. `tests/test_soak_promotion_gates.py:439` reproduces `[200,200,429]` independently on each instance for one identity. This matches the explicitly process-local contract at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`, installed by `main.py:648`; it is not proof of a deployed ingress bypass or of cluster-wide enforcement. |
| Production telemetry and thresholds | UNVERIFIED. Profile defines thresholds, but driver-loop latency is not application-loop latency; no fresh required production series was captured. |
| Active-work kill/restart, drain, fencing/recovery | UNVERIFIED. No active-work process interruption executed. Receipt probe at `tests/test_soak_promotion_gates.py:564` returns 200 locally and 404 on peer via the actual router, which reads `queue.get` at `packages/maistro-server/src/maistro_server/api/tasks.py:144`. Router is mounted by `main.py:735,755`. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` deliberately rejects artifact equivalence; executed CLI regressions reject synthetic four-hour preflight evidence. Assignment does not designate immutable RC image/effective config. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes, but no new load experiment/classification audit occurred. GitHub mutations prohibited. |
| Machine/human evidence bound to artifact/config hashes | UNVERIFIED for production acceptance. This handoff records exact local source HEAD and validation only; it is not an RC soak evidence pack. |

## Disposition and next action

BLOCKED on production acceptance, not on the cited deterministic failures. The historical schema assertion is already repaired, and the exact required vulture scan matches the CI arguments in `.github/workflows/vulture-ratchet.yml:82-85` and `.github/workflows/quality.yml:1079-1082`. Changing the ledger without unbanked findings would be unjustified. No source/tests/ledger were changed; this handoff is the sole changed file.

Next owner must designate immutable RC artifacts and effective configuration, complete the representative traffic/applicability matrix, resolve replica-budget/receipt constraints, and execute at least four hours against that production artifact with active-work crash/drain and canonical TTL/fence observations. Record production telemetry and physical effects, not merely admission identities or terminal Run counts. A longer host preflight cannot satisfy the artifact gate. Avoid dispatching another identical schema/vulture repair absent a new failing command.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues; errors 0 validation commands. One absent documentation lookup was skipped as noted above. All validation used 1200-second command timeouts. Commit is a blocked local handoff only, never integration approval.
