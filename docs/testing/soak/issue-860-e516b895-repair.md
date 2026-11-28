# Issue #860 — repair e516b895

## Frozen scope and initial state

- Assigned issue only: #860, including its explicit vulture exact-debt gate repair.
- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting HEAD `01064ed70d445f082463fed08231098a5dca28d0`; initial status clean. No incoming work to salvage.
- Frozen inspection set: repository instructions; execution-runtime, lease-fencing, rate-limiting, scheduling and deployment ADRs; production Compose; `scripts/soak/run_soak.py`; `tests/test_soak_promotion_gates.py`; `tests/test_prod_stack_boot_contract.py`; PostgreSQL learnings and task-backpressure implementation/tests; rate-limit middleware; current load profile/human evidence; four historical evidence JSON packs; vulture checker/ledger and CI arguments. Prior result is context, not validation.
- Edit scope: this report and only scanner-confirmed dead identities/ledger entries if the assigned gate finds them. No speculative runtime changes or new authority.
- Job directory `/home/dev/maistro/jobs/e516b8958137435aaf91dc8911208c7e` has no `check-*.log` files in its initial listing: not found; skipped. Execute checks independently.
- Ambiguity: no immutable RC image/configuration was supplied. Do not invent promotion identity or substitute the host-process emulator for deployed RC artifacts.

## Architecture reconciliation

Accepted ADR-081426-1f7c makes Attempt the physical execution identity and confines ExecutionRuntime to mechanics. ADR-081626-f383 puts execution authority/fencing in the canonical store. ADR-085 requires principal-keyed rate limits; it does not establish cluster-wide enforcement. Preserve Goal → Graph → Run → NodeRun → Attempt. Admission deduplication alone cannot prove physical-work fencing; local rejection alone cannot prove replica-selection non-bypass. ADR-046 is superseded: accepted ADR-082126-f69c requires recurrence to produce canonical Runs and rejects a second scheduler runtime. ADR-081 is Proposed, not an accepted authority; the shipped production Compose reference itself defines two application services.

## Validation

- Required exact-debt command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1361 reviewed identities / 1361 findings, zero unclassified, zero never-allowlist. Log: job directory `writer-vulture.log`. No ledger amendment or dead-code removal is supported by this scan.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info` — exit 1: cannot connect to Docker daemon. Client exists; no server available. This independently reproduces the prior environment blocker. Do not start a purported production soak without its deployment runtime.
- `uv run ruff check .` — PASS; log `writer-ruff-check.log`.
- `uv run ruff format --check .` — PASS, 2802 files; log `writer-ruff-format.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` — **88 passed, 5 skipped**, 367.46 seconds; log `writer-pytest.log`. All five skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL concurrency proof claimed.
- `uv run python` audit importing the current `failed_promotion_checks` and reading the four frozen evidence packs — PASS assertions that all four fail both `sustain_duration` and `exact_rc_artifact`. Machine-readable audit: job directory `writer-evidence-audit.json`. Round 5/6 observed durations are 90.17/90.43 seconds, not 14400 seconds.

Validation commands used 1200-second timeouts except the explicitly bounded Docker check. The test battery includes the real production rate-limit middleware and canonical credential resolver on independent ASGI instances (`tests/test_soak_promotion_gates.py:439–488`): the same identity receives `[200, 200, 429]` on each replica, for authenticated and unauthenticated cases. This falsifies shared-budget claims; it is not deployed concurrency evidence. The task-backpressure test exercises the actual router and canonical admission spine, while boot-contract tests validate configuration rather than booting containers.

## Acceptance assessment

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | **PARTIAL; acceptance UNVERIFIED.** `m3a-load-profile.md` defines traffic and thresholds, but `run_soak.py:1268–1289` supplies one API key and health/task/receipt/metrics traffic. Concurrent Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background-worker inclusion remain unjustified for a selected RC. |
| At least two deployed application replicas | **UNVERIFIED.** Compose defines both services; boot-contract tests pass. Docker daemon check fails; no RC replicas ran here. |
| Sustained saturation, queue growth, reclaim, retry, leak and restart observation | **UNVERIFIED.** All four historical packs fail the duration gate; focused tests cannot supply long-window observations. |
| No duplicate physical work; schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED.** Admission-oracle regressions pass but do not execute physical Attempts. Profile documents that the schedule probe cancels its queued Run and does not exercise sustained Goal reconciliation. No multi-replica physical-work observation executed. |
| Rate limiting/security/degraded behavior without replica-selection bypass | **NOT MET.** Executed production-middleware regression reproduces independent allowances (`rate_limit.py:25–30`). No cluster-wide enforcement proof; security/degraded behavior under RC load UNVERIFIED. |
| Complete telemetry with explicit thresholds | **PARTIAL; acceptance UNVERIFIED.** Profile thresholds and sampler regressions exist; application-loop latency, sustained PostgreSQL contention, resource leaks, worker/queue/error series were not captured from RC replicas. Driver loop lag is not application-loop lag. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED.** No current deployment failure injection possible. Historical process exit/rejoin does not establish Attempt/fence recovery. |
| Long-running exact RC artifact/configuration soak | **NOT MET.** Four-pack audit rejects duration/artifact evidence. `run_soak.py:635–645` explicitly rejects the host-process topology even at four hours; no immutable RC selection supplied. |
| Findings filed/reclassified at earliest invariant | **PARTIAL; external filing UNVERIFIED.** Human evidence classifies F11/F12 as M3-A evidence-validity defects. No new load run or new load finding here; GitHub mutations prohibited. |
| Human/machine evidence bound to exact hashes | **PARTIAL; promotion evidence UNVERIFIED.** Historical packs and human explanations exist, but none is a qualifying RC soak. This audit validates rejection, not image/configuration equivalence. |

## Handoff

**BLOCKED** for issue #860. The assigned exact-debt gate is green; no scanner-supported repair exists. Prior misleading H3/shared-store wording is already retracted in the current human evidence; no cosmetic rewrite is warranted. Only this report changes; no source, runtime configuration, ledger, historical evidence or tests changed. No test additions, so no inventory delta required.

Next: restore access to the deployment runtime, select immutable RC image/configuration identities, resolve non-bypass through the canonical enforcement path, and complete representative production workloads/telemetry before a ≥14400-second soak with active-work failure injection and Attempt/fence correlation. Every code/runtime-config change requires another qualifying soak. Local report commit is a handoff, not integration approval or issue completion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 deployment runtime, RC selection, replica-selection enforcement and qualifying soak"}`. All requested local checks finished; acceptance remains blocked.
