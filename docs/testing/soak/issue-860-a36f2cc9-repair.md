# Issue #860 repair — a36f2cc9

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `9f1e669e4c0f97346fe647fa4af5be10b02a2493` (verified); supplied develop base: `94781cf6b708a385f33a9aafcbe9f83a481b6858`.
- Initial working tree: clean; no incoming edits to salvage.
- Process only supplied dispatch evidence, issue #860 soak harness/tests/docs, and the explicitly authorized vulture ledger repair. No GitHub mutations or unrelated issue work.
- Candidate edits: this report; `quality/vulture-baseline.json` only if the required scan demonstrates retained unbanked identities; soak files only if inspected evidence warrants repair. No test additions planned without an inventory note.
- Ambiguity: the prompt contains both verifier and writer instructions. The explicit assigned repair and mandatory local commit are treated as the writer role.
- Job directory contains no `check-*.log` files at initial inspection. Validation will be executed locally rather than inferred.

## Progress

The required exact-arguments vulture scan passed: 1,338 reviewed identities,
1,338 findings, zero unclassified and zero never-allowlist. There is no observed
ledger defect to repair; no ledger edit is justified. Root ruff lint and format
checks passed (2,920 files formatted), and `git diff --check` against the supplied
develop base passed. Historical whitespace findings do not reproduce.

The supplied prior job reports the same blocker, but is not used as validation.
The current profile explicitly describes a host-process preflight, not an exact
production Compose artifact. Acceptance testing remains pending; no promotion
claim. Only this report has changed.

Focused existing tests executed: 92 passed, six PostgreSQL tests skipped because
`MAISTRO_TEST_PG_DSN` is unset. Backlog consistency passed (168 items). The
production-middleware counterexample passed for authenticated and unauthenticated
traffic: after exhausting one instance, the same identity gets fresh allowance
from the other. This is not a successful non-bypass proof or a live RC soak.

## Executed validation

Commands ran in the assigned worktree with 1,200-second validation timeouts.

| Command | Result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; exact CI arguments confirmed in `.github/workflows/quality.yml:963-966` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2,920 files |
| `git diff --check 94781cf6b708a385f33a9aafcbe9f83a481b6858...HEAD` | PASS |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 92 passed, six skipped; database tests require `MAISTRO_TEST_PG_DSN` |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `uv run python -` importing current `run_soak.py` and evaluating round6 JSON | Assertions PASS: failed checks include `sustain_duration` and `exact_rc_artifact`; preflight artifact check is false; 90.43 seconds is below 14,400; evidence HEAD differs from current HEAD |

The evidence evaluator printed historical HEAD
`b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this lane's starting HEAD.
Assertions show that insufficient evidence is rejected, not that production
acceptance passes. No live production stack or long-running soak was executed.
The six skipped PostgreSQL cases remain UNVERIFIED. No new tests were added;
there is no inventory delta.

## Acceptance audit (all ten issue criteria)

| Criterion | Fresh evidence and remaining limitation |
|---|---|
| Representative users/Workspaces, request mix, Graph fan-out, schedules, tools/models, Canvas and workers | PARTIAL definition only. `run_soak.py:1267-1290` uses one credential and a degraded health/task mix. `m3a-load-profile.md:152-166` records missing surfaces; representative RC coverage UNVERIFIED. |
| At least two application replicas in the supported deployment | `deploy/docker-compose.prod.yml:25-78` declares two and boot-contract tests pass. Live exact-RC exercise UNVERIFIED. |
| Sustained saturation, queue growth, leases/reclaim, retry/backoff, leaks, restart | Round6 JSON:163-165,221-224 has 90.43 seconds versus 14,400. Current evaluator rejects it; long-window behavior UNVERIFIED. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | Admission probe tests pass; the profile:197-200 explains that the schedule probe cancels its Run without executing it. Cross-replica physical Attempt fencing and Goal reconciliation UNVERIFIED. |
| Effective concurrent limits/security/degradation without replica-selection bypass | NOT MET for non-bypass: production middleware counterexample `tests/test_soak_promotion_gates.py:439-488` passed for both identity classes. Each instance independently returns `[200, 200, 429]`; production `rate_limit.py:25-30,72-76` is process-local. Task backpressure test passes, but full RC security/degradation UNVERIFIED. |
| PostgreSQL/loop/worker/RSS/fd/queue/error telemetry with thresholds | Sampler regression passes with real child memory/fd growth. `run_soak.py:1306-1320` measures driver-loop, not application-loop lag. Complete RC measurements and threshold coverage UNVERIFIED. |
| Kill/restart active work and prove drain/fencing/recovery | Process rejoin is not physical-work proof. Active-work RC recovery UNVERIFIED. |
| Long soak of exact RC artifact/config, repeated after changes | NOT MET: `run_soak.py:635-647` explicitly cannot sign exact-RC evidence. Current evaluator rejects historical duration/artifact; no frozen promotion artifact/config supplied or exercised here. |
| Findings filed/reclassified to earliest broken invariant | `BACKLOG.md:267-279` records the cluster-budget gap and consistency passes. No new load findings or remote filing; classification completeness UNVERIFIED. |
| Publish machine/human evidence tied to exact image/package/commit/config | Historical machine/human evidence exists but is not the current artifact. Evaluated evidence HEAD is stale; current hash-bound RC evidence UNVERIFIED. |

## Architecture reconciliation and disposition

Read repository instructions and accepted ADRs: ADR-081226-a66b (Run/NodeRun/
Attempt lifecycle), ADR-082126-f69c (recurrence produces Runs), ADR-085
(principal-based limits), ADR-073126-c4e1 (release artifact promotion).
Admission identity does not prove physical Attempt fencing. Per-principal keys
do not prove a shared multi-replica allowance. Nothing in these decisions makes
the historical host-process preflight equivalent to a promoted RC artifact.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no replacement scheduler,
authorization path, execution authority, or gate weakening is introduced.

**BLOCKED.** This round changes only this report and cannot resolve the existing
promotion prerequisites. The supplied CI failure and whitespace findings do not
reproduce, so speculative source or ledger changes would not repair evidence.
The existing `engine-116` entry explicitly requires the cluster-budget contract
to be decided before implementation. Next: resolve that contract, supply the
frozen RC image/config and representative production-topology workload, then run
the >=4-hour soak with complete telemetry and physical-work recovery assertions.
A repeated CI-only repair or longer host preflight cannot satisfy those gaps.

Checkpoint: checked 1 issue; done 0; blocked 1; skipped 0 issues; validation
command failures 0, with six explicitly skipped database tests. No GitHub
mutation, push, integration approval, or issue closure. The report is the only
file staged for a local handoff commit.
