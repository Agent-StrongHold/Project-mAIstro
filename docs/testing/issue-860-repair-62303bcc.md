# Issue #860 — repair validation 62303bcc

## Scope and disposition

Assigned branch/worktree: `auto-860`, `/home/dev/Git/wt/auto-860`.
Starting HEAD: `075ed961595d55f1a16adeb992c3e7f9ad788ae5`; supplied base:
`675db8be6c41b020ffffb224b2748c159c78a122`. Starting worktree was clean.
Only #860 was processed. No GitHub mutations, develop sync, or integration actions.
The supplied previous BLOCKED result concerns exact-RC acceptance, not a conflict.

The job supplied no current `check-*.log`. Inspected the historical
`98a11313167b41a98a420abfda80c292/check-3.log`: its schema test expected 21
statements but observed 24. The current independent expected-DDL list already
includes the three Gauntlet columns. This failure does **not** reproduce.
The explicit vulture repair scan also passes. No code, ledger, authorization,
or test change is supported by those findings; no inventory delta is needed.
Only this report changes in this round. Existing branch work is preserved.

## Executed validation

Logs: `/home/dev/maistro/jobs/62303bcc094340009d0e9ad52a3437b3/worker-*.log`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1326 reviewed identities / 1326 findings; zero unclassified or never_allowlist. Checker selected trusted base `e46ad6708fda`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped, 1.47 s. Skips are not live database proof. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 74 passed, 2.33 s. Includes real production middleware and real child-process sampler tests; mocked HTTP probes do not prove a deployed RC. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3195 files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python` importing the current soak evaluator against `docs/testing/soak/evidence/m3a-round30-shakedown.json` | PASS: asserted failed gates are exactly `sustain_duration` and `exact_rc_artifact`; observed 420.08 s versus 14400 s minimum. Current artifact check is false. Log `worker-evidence.log`. This is historical-evidence reevaluation, not a new soak. |
| `git diff --check` | PASS. |

## Architecture reconciliation

Read repository instructions, documentation authority map, and accepted ADRs
087 (schema evolution), 081626-f383 (Attempt execution fencing), 082426-82c7
(occurrence claims), 085 (principal limits), and 083026-a91e (absent metrics).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A unique admitted Run
is not proof of unique physical work. Restart/rejoin is not proof of lease
reclaim. Driver-loop metrics cannot stand in for application-loop metrics.
The process-local limit documented by #842 cannot waive #860's explicit
replica-selection criterion. No alternative execution or security authority
was introduced to make the evidence pass.

## Acceptance review

| Issue criterion | Evidence / status |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas, and Goal/background-worker workloads. No selected immutable RC inclusion/exclusion contract was supplied. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Two middleware instances are tested, not two deployed exact-RC replicas. Current runner boots host processes. |
| Sustained saturation, growth, reclaim, retries, leaks and restart observations | **UNVERIFIED.** Focused sampler tests prove resource observation, not long-window application stability. Executed evaluator rejects the historical shakedown's 420.08 seconds against the 14400-second minimum; no new load run was executed. |
| No duplicated physical work; Goal reconciliation | **UNVERIFIED.** Admission-oracle regressions pass. Profile at line 202 explains that the raced schedule Run is cancelled without execution and sustained traffic lacks schedules. No physical Attempt/Goal soak proof. |
| Security/degraded behavior and replica-selection resistance | **UNVERIFIED overall; contrary rate evidence reproduced.** `tests/test_soak_promotion_gates.py:439` exercises actual middleware and observes `[200, 200, 429]` independently on each replica for the same identity. Production `api/rate_limit.py:32` documents process-local state. Direct bursts reaching 429 do not prove a shared allowance. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Profile distinguishes driver-loop from application-loop delay and identifies missing detached-worker, saturation, reclaim and long-window observations. Passing sampler tests are not a complete production telemetry record. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup and gate tests pass, but no active physical-work fencing/recovery drill ran here. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED / BLOCKED.** `scripts/soak/run_soak.py:730` returns `ok=False` for its host-process artifact. Tests prove even four-hour preflight evidence cannot pass that gate. No exact-RC soak executed. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED complete.** Existing human evidence is historical classification, not proof of complete filing; no GitHub mutation permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config | **UNVERIFIED for RC.** Historical evidence exists, but the runner explicitly lacks exact production Compose image/configuration identity. No new promotion evidence published. |

## Handoff

**BLOCKED**, not merge-ready. Both dispatched CI repair targets are completed;
#860's production acceptance is not. Do not retry the obsolete schema failure
or amend a passing ledger to manufacture a change. Next work needs an explicitly
selected immutable promotion RC, a production-topology runner with representative
workloads and full telemetry, resolution of the replica-selection requirement,
and a minimum four-hour exact-artifact soak with correlated physical execution
and recovery evidence. A longer host-process preflight cannot meet this need.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`.
The skipped item is a new exact-RC soak, not a passing acceptance criterion.
This committed handoff is not integration or promotion approval.
