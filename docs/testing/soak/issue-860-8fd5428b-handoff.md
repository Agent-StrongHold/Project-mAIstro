# Issue #860 — repair handoff 8fd5428b

## Frozen scope and disposition

Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
Verified starting HEAD `9c7fecd377f978325c5115b5fe94706ebd5745e0`, clean tree;
assigned base `94781cf6b708a385f33a9aafcbe9f83a481b6858` resolves.
Read the supplied dispatch snapshot and prior result; neither substitutes for
validation. No driver `check-*.log` files were supplied. Fresh logs are in
`/home/dev/maistro/jobs/8fd5428bce194fad87bc404a53748c32/`.

**BLOCKED, not promotion-ready.** The requested exact-debt-ledger failure does
not reproduce: 1,338 reviewed identities match 1,338 findings, with zero
unclassified or never-allowlist findings. No identity needs amendment or removal.
No source, ledger, grant, test, or gate changes are justified by this scan.
Only this handoff changes; no test inventory delta is needed.

## Executed validation

All commands ran in the assigned worktree with 1,000-second tool timeouts.

| Command | Result / job log |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; `check-vulture.log` |
| `uv run ruff check .` | PASS; `check-ruff.log` |
| `uv run ruff format --check .` | PASS, 2,920 files; `check-format.log` |
| `git diff --check 94781cf6b708a385f33a9aafcbe9f83a481b6858...HEAD` | PASS; historical whitespace findings do not reproduce; `check-diff.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 92 passed, six skipped; `check-targeted-tests.log` |
| `uv run python scripts/check-backlog-consistency.py` | PASS; `check-backlog.log` |
| `uv run python -` importing the current soak driver and evaluating round6 JSON | Assertions PASS: `failed_promotion_checks` contains `sustain_duration` and `exact_rc_artifact`; `preflight_artifact_check().ok` is false; observed duration below minimum; `check-evidence.log` |

The six skipped tests require `MAISTRO_TEST_PG_DSN`; their database behavior is
UNVERIFIED. No production stack or long-running soak was executed this round.
The evaluator assertions prove rejection of inadequate evidence, not RC success.

## Acceptance audit

| Issue criterion | Fresh evidence / remaining gap |
|---|---|
| Representative users/Workspaces, requests, Graph fan-out, schedules, tools/models, Canvas and workers | PARTIAL profile only. `run_soak.py:1267-1290` uses one credential and a degraded health/task/read mix. `m3a-load-profile.md:152-166` explicitly records omissions. Representative RC workload UNVERIFIED. |
| At least two production application replicas | `deploy/docker-compose.prod.yml:25-78` declares two; boot-contract tests pass. Live exact-RC multi-replica exercise UNVERIFIED. |
| Sustained saturation, queues, expiry/reclaim, retries, memory/descriptors/process leaks | Round6 JSON:163-165,221-224 records 90.43 seconds versus 14,400 required. Long-window behavior UNVERIFIED. |
| No duplicate physical work for schedules/tasks/Run/Attempt/Goal reconciliation | Admission probe tests pass, not physical execution proof. The profile:197-200 states the raced schedule Run is cancelled without execution. Physical fencing and Goal reconciliation UNVERIFIED. |
| Effective rate limits/security/degradation without replica-selection bypass | NOT MET: `test_replica_selection_has_an_independent_production_allowance` passes for authenticated and unauthenticated traffic; both instances independently return `[200, 200, 429]`. Production `rate_limit.py:25-30,72-76` deliberately uses process-local state. Backpressure tests pass; sustained RC security remains UNVERIFIED. |
| Required telemetry with thresholds | Process-group sampler regression passes with real child memory/fd growth. `run_soak.py:1306-1320` measures driver-loop lag, not application-loop lag. Full RC measurements and threshold coverage UNVERIFIED. |
| Kill/restart active work with drain/fencing/recovery | Process rejoin and terminal Run counts do not prove physical-work recovery. Active-work RC validation UNVERIFIED. |
| Long soak of exact promotable artifact/config | NOT MET: current evaluator rejects historical evidence; `run_soak.py:635-647` explicitly cannot sign exact-RC evidence. No supplied frozen RC artifact/config was exercised. |
| Findings classified to earliest broken invariant | `BACKLOG.md:267-279` records the cluster-budget gap; consistency gate passes. No new load run or remote filing performed; classification completeness UNVERIFIED. |
| Machine/human evidence tied to exact image/package/commit/config | Historical shakedown is not this HEAD or the promoted Compose image. Current hash-bound RC evidence UNVERIFIED. |

## Architecture and next action

Read repository instructions, accepted ADR-081626-f383 (lease/fencing),
ADR-082826-b601 (canonical consumer), ADR-085 (principal limits), and
ADR-073126-c4e1 (release/RC promotion). ADR-081 is Proposed, not authority to
waive accepted contracts. Admission identity is not physical Attempt fencing;
principal identity is not proof of shared replica budgets. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`, canonical claims and authorization.
No competing runtime or weakened gate was introduced.

Resolve the existing `engine-116` cluster-budget contract before implementation;
supply the exact RC image/config and a representative production-topology runner,
then execute the >=4-hour soak with physical-work recovery and complete telemetry.
Repeating the host-process shakedown or banking nonexistent vulture debt cannot
resolve these prerequisites. Do not dispatch another identical CI-only repair
without new failed-gate evidence or the missing RC prerequisites.

Progress: checked 1 issue, completed 0, blocked 1, skipped 0 issues; validation
commands above passed, with six explicitly skipped database tests. This handoff
is committed locally; no push, GitHub mutation, or integration approval.
