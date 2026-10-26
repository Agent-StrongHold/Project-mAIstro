# Issue #860 — bounded repair 1f2d553a

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`cdb3867a1bf96c6eae9c457ae561b27b6dc654a3`, base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
The initial worktree was clean. No salvage needed. No remote mutations.

Review scope: repository instructions, relevant execution ADRs, existing
`scripts/soak/` implementation, `tests/test_soak_promotion_gates.py`, existing
soak documentation, cited prior failure, and the exact vulture gate. Potential
edits are limited to evidence-driven soak repairs, reviewed retained vulture
identities in `quality/vulture-baseline.json` if the gate requires them, associated
tests/inventory notes if needed, and this report. No other issues/PRs are processed.

Current-job directory has no `check-*.log` files. Prior result reports BLOCKED;
those claims will not be treated as freshly validated. Ambiguity: the dispatch
requests both a CI repair and complete release acceptance, but does not designate
an exact RC artifact/configuration. Proceed with bounded CI and regression
validation; do not represent smoke/unit checks as a production soak.

## Results

- Required exact vulture command passed: 1322 reviewed identities, 1322
  findings, zero unclassified. No ledger amendment is justified.
- Historical check-3.log read: expected 21 versus 24 schema DDL statements.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q` passed: 37 passed, 6 skipped. The cited failure is not reproduced;
  skipped PostgreSQL tests are not evidence of deployed concurrent boot safety.
- Prior handoff read. The remaining block concerns release acceptance, not a
  merge conflict. No develop sync is warranted by the supplied evidence.

## Fresh validation commands

Commands ran in the assigned worktree with 600–1200 second timeouts.

| Command | Result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 findings / 1322 reviewed identities |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 93 passed |

No tests were added or changed; no inventory delta is required. Only this report
changed. No ledger/source/test repair was warranted by fresh command evidence.

## Architecture and reachable behavior

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081426-1f7c,
ADR-081626-f383 and ADR-082526-b36a. Preserve the canonical
Goal → Graph → Run → NodeRun → Attempt model. The later lease ADR extends
fencing with optional TTL/renewal/reclaim; restarting a process does not by
itself authorize reclaim of another live worker. Admission deduplication alone
is not proof of physical-effect uniqueness. No architecture changes made.

- `packages/maistro-core/tests/persistence/test_pg_learnings.py:172-174` now
  independently expects the three validation audit columns absent from the
  historical failure. Fresh tests pass without weakening the schema fence.
- `packages/maistro-server/src/maistro_server/main.py:648` mounts the production
  rate middleware; `api/rate_limit.py:32-37` explicitly documents process-local
  budgets. Executed `tests/test_soak_promotion_gates.py:439` obtains
  `[200, 200, 429]` independently on each instance for the same identity.
  This is a local middleware probe, not a deployed ingress bypass experiment.
- `main.py:735,755` mounts the task router; `api/tasks.py:144` reads the queue.
  Executed `tests/test_soak_promotion_gates.py:564` observes 200 on the admitting
  ASGI instance and 404 on its peer with a shared canonical admission spine.
- `scripts/soak/run_soak.py:744-755` rejects exact-RC equivalence unconditionally
  for its host-process preflight. The executed promotion suite verifies that
  duration cannot override the artifact gate.

## Acceptance assessment

| Criterion | Executed evidence / status |
|---|---|
| Representative RC workload | UNVERIFIED. Reviewed `m3a-load-profile.md`: one-key preflight lacks concurrent Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal workloads; RC applicability remains undesignated. |
| Two deployed application replicas | UNVERIFIED. Executed ASGI probes are not deployed replicas. |
| Sustained saturation, queues, reclaim, backoff and leaks | UNVERIFIED. No sustained production experiment or resource series run. |
| Physical-work uniqueness across schedules/task/Run/Attempt/Goal | UNVERIFIED. Fencing/recovery regressions pass but do not establish physical-effect uniqueness under load. |
| Replica-resistant rate/security/degraded behavior | UNVERIFIED overall. Independent middleware allowances and peer receipt loss reproduced; backpressure regressions pass. No deployed ingress proof. |
| Production telemetry and explicit thresholds | UNVERIFIED. Documented thresholds are not fresh production observations; driver loop latency is not application loop latency. |
| Active-work kill/restart, drain, fencing/recovery | UNVERIFIED. No process interruption performed in this round. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. No immutable RC image/effective configuration designated by the assignment; existing runner fails its exact-artifact gate by design. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes, but no new load/classification audit; no GitHub mutations performed. |
| Hash-bound machine/human production evidence | UNVERIFIED. This handoff records local validation and source HEAD, not a production RC evidence pack. |

## Handoff

Verdict: **BLOCKED** on release acceptance, not on a reproduced deterministic
CI failure. Do not amend a passing ledger or rerun the host emulator for four
hours and call it exact-RC evidence. No promotion gate or ownership path changed.
Next: designate immutable RC artifacts and effective config, resolve workload
applicability and replica-budget/receipt limitations, then run the required
production soak with physical-effect/fence observations, active-work disruption,
application telemetry, and hash-bound results. Classify observed failures before
promotion. A new CI repair dispatch needs a fresh failing command, not the stale
21-versus-24 schema expectation.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues; errors 0
validation commands. This local documentation commit is a blocked handoff, not
integration approval. Residual risks are the unverified acceptance rows above.
