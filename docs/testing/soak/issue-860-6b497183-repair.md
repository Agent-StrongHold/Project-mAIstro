# Issue #860 — repair checkpoint (6b497183)

## Frozen scope

Only issue #860, branch `auto-860`, starting at
`05636a6b86027c8865e0f0cd7822133bd53c6fe3`, base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Starting worktree was clean. No GitHub mutations or ref updates.

Review inputs: supplied dispatch-context.json, prior result 1b4d2345,
and reported check-3.log from job 98a11313. Implementation surfaces are
`scripts/soak/`, their existing tests, and the explicitly permitted
`quality/vulture-baseline.json` only if the exact gate reports real debt.
This report records validation; no speculative code or ledger changes.

Initial ambiguity: this is a CI-repair assignment, but the prior BLOCKED
result concerns missing exact-RC deployment evidence, not a known code fix.
Proceed by reproducing the named failure and exact vulture gate before editing
runtime code. The current job directory contains no check-*.log files.

Checkpoint: exact requested vulture command passed (exit 0); log in the
current job directory, `worker-vulture.log`. The reported check-3.log is a
historical 21-versus-24 schema DDL assertion, not a vulture failure. No ledger
edit is justified. The guessed prior-report filename and README glob were not
found; skipped. The actual prior report is `issue-860-f7e66743-repair.md`.
Independent targeted pytest passed: 102 passed, 6 skipped (database coverage
not established by skips). Root ruff check and format check both exited 0.
Vulture reported 1323 findings / 1323 reviewed identities, zero unclassified and
never-allowlist, checker-selected base `4aa68edc0b6b`.

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a, and
ADR-082826-08f0. Attempt is physical-work identity; later renewal/reclaim and
recovery-disposition contracts supersede the older expiry deferral. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no new authority is warranted.
Current schema regression independently includes the three audit-column DDLs
(`test_pg_learnings.py:175-177`) present in production (`pg_learnings.py:116-118`).
The historical failure does not reproduce; no code/test weakening is justified.

## Executed validation

Logs are under `/home/dev/maistro/jobs/6b497183b56f40c4a48a7ab87e7dbc3f/`.

| Command | Result / log |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q` | 102 passed, 6 skipped; `worker-tests.log` |
| `uv run ruff check .` | PASS; `worker-ruff-check.log` |
| `uv run ruff format --check .` | PASS, 3270 files; `worker-ruff-format.log` |

No tests added or removed; no inventory delta required. No quality ledger,
grant, runtime, deployment or gate edits. The sole changed file is this report.

## Acceptance review

These are fresh source inspections and executed tests, not inherited claims.
The dispatch supplies a source head but no designated immutable RC image and
runtime configuration. No deployed soak was launched; unit tests cannot replace
one. Production `Container._reclaim_abandoned_attempts` (`container.py:1222-1235`)
uses the canonical Run store and `AttemptLifecycleReconciler`, consistent with
the later accepted ADRs. Its existence alone does not prove recovery under load.

| Criterion | Evidence / disposition |
|---|---|
| Representative RC workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373-1395` uses one API identity and health/task/receipt/metrics traffic with no LiteLLM; this does not represent the required Workspace, Graph fan-out, tool/model and Design/Canvas mix. |
| Two application replicas | **UNVERIFIED for RC.** Existing runner starts host processes; `run_soak.py:730-741` explicitly labels these preflight, not the promoted deployment artifact. |
| Sustained saturation, queue, lease/retry, memory/descriptor/process leak observations | **UNVERIFIED.** No long-window load executed. Sampler tests passed but do not establish sustained deployed observations. |
| Physical-work uniqueness | **UNVERIFIED.** `run_soak.py:1507-1527` measures canonical Run status/admission counts, not Attempt physical execution. No fresh cross-replica schedule/task/Goal execution experiment. |
| Rate/security/degraded non-bypass | **UNVERIFIED for deployment; independent allowances reproduced.** Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) observes `[200,200,429]` on each production middleware instance for the same identity. `maistro_server/main.py:648` registers it and `api/rate_limit.py:90-98` creates a per-instance in-memory limiter. Per-replica rejection cannot prove a cluster-wide budget. |
| Complete telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410-1426` measures driver event-loop lag, not application-loop lag; no fresh deployed query latency, lock contention, pool saturation or complete required telemetry. |
| Kill/restart active work, graceful drain/fencing/recovery | **UNVERIFIED.** CLI/drain gate regressions passed, but no live Attempt restart experiment occurred. Rejoin and terminal Run counts alone are insufficient. |
| Long soak of exact RC artifact/configuration | **BLOCKED / UNVERIFIED.** `preflight_artifact_check` returns false at `run_soak.py:730-741` and is wired into main at line 1552. Executed CLI regression at `test_soak_promotion_gates.py:103` rejects otherwise-passing four-hour preflight evidence. Duration does not remove this blocker. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** This is local evidence only; no GitHub mutations authorized or performed. |
| Human/machine evidence bound to RC hashes | **UNVERIFIED.** This report and validation logs are not an immutable RC soak evidence pack. |

## Disposition

**BLOCKED for issue acceptance.** Named CI failure is stale at the assigned
head; exact vulture check is clean. Do not invent debt or repeatedly rerun the
host preflight as a substitute for the missing production experiment.

Next: supply the exact RC image/configuration, define the representative
production workload, resolve deployment-wide rate non-bypass against local
allowances through the existing policy authority, and perform the required
long soak with physical Attempt, recovery and complete telemetry evidence.
No competing execution or authorization mechanism was introduced.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC deployment and workload prerequisites"}`.
CI triage is complete; issue acceptance is explicitly blocked. Local commit is
a writer handoff, not integration or promotion approval.
