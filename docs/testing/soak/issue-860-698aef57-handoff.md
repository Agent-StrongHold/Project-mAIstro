# #860 repair handoff — 698aef57

## Scope and result

**BLOCKED: production acceptance is not established.** This is a local writer
handoff, not integration approval. Frozen scope: issue #860 on `auto-860`, starting
HEAD `b01d23bd782c588c5390c8dbd4919eea6f8837f9`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Worktree started clean.

The requested exact-debt-ledger repair has no reproducible failure at this HEAD.
No source, tests, ledger, grants or gates were changed. Only this report was added;
there is no test inventory delta. Existing work was preserved.

The current job directory had no driver `check-*.log` files. Inspected the supplied
prior `98a11313167b41a98a420abfda80c292/check-3.log`: it reports 24 schema statements
versus 21 expected. The current test already enumerates all 24, including the three
validation audit columns (`packages/maistro-core/tests/persistence/test_pg_learnings.py:174`).
A fresh run passes; changing code to repair that historical log would be unjustified.

## Executed validation

Logs are in `/home/dev/maistro/jobs/698aef572a5e4a7997b6c46c92fe9f87/`.
All commands used 1200-second timeouts.

| Command | Outcome / log |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings / reviewed identities, zero unclassified or never-allowlist findings; `worker-vulture-before.log`. Arguments match `.github/workflows/quality.yml:1078`. Checker reports base `4aa68edc0b6b`; this is not a claim about every supplied-base gate. No debt warrants a ledger amendment. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 103 passed, 6 skipped in 2.45 s; `worker-pytest.log`. Skips are not database/soak evidence. |
| `uv run ruff check .` | PASS; `worker-ruff-check.log`. |
| `uv run ruff format --check .` | PASS, 3270 files formatted; `worker-ruff-format.log`. |

## Architecture reconciliation

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and
ADR-082826-08f0. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Physical execution identity is Attempt, not Run. The later renewal/reclaim and
recovery-disposition contracts fill the original fencing contract's deferred
recovery boundary: live leases prohibit recovery dispatch. Terminal Run counts
alone cannot prove physical-work uniqueness. No new execution, persistence,
event or authorization authority was introduced.

## Acceptance audit

The issue snapshot and prior handoff do not designate an immutable RC
image/configuration to promote. Branch HEAD is not assumed to be that artifact.
No production deployment or long soak was performed in this round.

| Criterion | Reachable behavior and fresh evidence / remaining gap |
|---|---|
| Representative release workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one credential and a health/task/receipt/metrics mix without LiteLLM. `m3a-load-profile.md` records missing users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal/background-worker workloads. Applicability needs an owner-designated RC profile. |
| At least two deployed application replicas | **UNVERIFIED for RC.** `run_soak.py:730–741` explicitly identifies host-uvicorn preflight rather than the promoted Compose artifact. No deployment executed here. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leak observations | **UNVERIFIED.** Existing sampler and accounting tests passed, not a sustained RC observation window. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** Existing admission tests passed; `run_soak.py:1507–1527` inspects Run counts/status, not physical execution uniqueness across all required paths. |
| Rate/security/degraded non-bypass under replica selection | **UNVERIFIED for deployment; independent local allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439` obtains `[200,200,429]` on each real middleware instance for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:90–98` constructs a process-local limiter, wired at `main.py:648`. This is documented per-replica enforcement, not a shared principal budget; it cannot establish the stronger issue claim. Resolve semantics through existing policy authority rather than inventing an alternate limiter in the soak. |
| Complete DB/application-loop/process/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` samples driver-loop lag, not application-loop lag. No complete production telemetry window collected. |
| Active-work restart, graceful drain, fencing and recovery | **UNVERIFIED.** Drain gate tests pass; process rejoin and terminal Run counts are insufficient for active Attempt recovery. No RC restart executed. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** Exact RC not designated. Executed `test_four_hour_preflight_cannot_pass_cli` (`tests/test_soak_promotion_gates.py:103`) rejects synthetic otherwise-passing four-hour evidence without the RC artifact. Production driver wires that failing artifact check at `run_soak.py:1552`; duration cannot cure the topology mismatch. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Findings retained locally. No GitHub mutation performed or authorized. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This report identifies source HEAD and local checks only, not a promoted image/configuration or release evidence pack. |

## Next action

Supply the immutable RC artifact/configuration and workload applicability decisions;
resolve the non-bypass claim against the documented per-replica rate policy; then
run the representative long production soak with physical Attempt/recovery
observations and complete telemetry. Any runtime/code change requires a new soak.
Do not dispatch the same stale schema failure or a guessed Vulture repair again:
both targeted checks pass at the supplied HEAD.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC prerequisites and production soak"}`.
