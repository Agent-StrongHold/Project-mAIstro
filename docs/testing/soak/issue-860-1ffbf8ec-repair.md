# Issue 860 repair — 1ffbf8ec

## Frozen scope

Assigned issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `43cb6677522546677550a7b46c96c9855ce92d31`,
base `2154f845347c9541016288c760f8da3f5cd2e064`. Initial tree clean.
No GitHub mutations or ref changes planned.

Snapshot: supplied dispatch-context.json, supplied prior result.json and
check-3.log; repository instructions and relevant ADRs; schema implementation
and adjacent persistence tests; soak driver and promotion tests; exact vulture
scanner and CI configuration. Candidate edits are limited to an evidenced
schema-test repair, reviewed vulture identities if the prescribed scan finds
any, corresponding inventory note, and this report. No blanket ledger edits.

Initial evidence: supplied check-3.log reports 24 schema statements versus 21
expected. Prior result is BLOCKED and does not prove current failure or success.
Current job directory contains no check-*.log files in its initial listing.
Assumption: this is a writer CI-repair round, not permission to replace the
canonical runtime or to claim preflight traffic as exact-RC production evidence.

## Progress

- Verified starting HEAD and clean worktree; read supplied prior artifacts.
- Exact requested vulture scan passed: 1323 findings / 1323 reviewed identities,
  zero unclassified and zero never-allowlisted findings. No ledger change warranted.
- Current schema test command exited 0. The historical missing-three-columns
  expectation is already repaired at test_pg_learnings.py:177–179; no speculative
  schema or test edits warranted. Detailed counts and acceptance audit follow.

## Executed validation

All validation commands used 1200-second timeouts in the assigned worktree.

| Command | Fresh outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323 identities, no unbanked debt |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; live PostgreSQL skips are not proof |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | 80 passed |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 27 passed |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `uv run python scripts/check-adr-index.py` | PASS |

The prescribed vulture invocation matches `.github/workflows/quality.yml:1078`.
Raw schema/vulture logs are in this job directory as `worker-schema.log` and
`worker-vulture.log`. Other outputs are in the worker tool transcript.
No tests changed or added, so no inventory delta is required. No ledger edits:
there are no scanner findings to repair or newly retained identities to bank.

## Architecture and acceptance audit

Read repository instructions, `docs/README.md`, the current load profile,
production schema and limiter, adjacent tests and accepted ADRs
ADR-081226-a66b, ADR-081626-f383 and ADR-085. The canonical model remains
Goal -> Graph -> Run -> NodeRun -> Attempt. Reconciliation with issue text:
lease expiry is not permission to invent recovery authority; ADR-081626-f383
explicitly leaves expiry takeover undefined and retains one active ordinary
Attempt. ADR-085 requires principal-keyed limits; passing a process-local
limiter test is not proof of replica-selection non-bypass.

Fresh production-path counterexample: the two parameterizations of
`tests/test_soak_promotion_gates.py:439` construct actual RateLimitMiddleware
instances with the same IP and credentials. Each accepts two requests before
429; exhausting the first does not exhaust the second. The production limiter
is created per instance at `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`.
This reproduces independent allowances, not a deployed security soak.

The exact-RC rejection at `scripts/soak/run_soak.py:744` is unconditional.
The executed four-hour preflight regression supplies synthetic duration;
it does not run a four-hour soak. At line 1067 the schedule probe cancels its
queued Run without executing it. Admission uniqueness cannot establish
physical-work uniqueness. These are observed scope limitations, not an
invitation to weaken promotion gates.

| Issue acceptance | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED: `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background work. |
| At least two deployed application replicas | UNVERIFIED: ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queues, reclaim, retries, leaks and shutdown | UNVERIFIED: no sustained deployment run executed; reclaim requires accepted authority. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED: current schedule probe is admission-only and cancels its Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent per-replica allowances reproduced by passing regression; full deployed criterion UNVERIFIED, not satisfied by local 429s. |
| Full telemetry and explicit thresholds | UNVERIFIED: sampler unit checks passed, but driver-loop lag is not application-loop lag and no deployment telemetry was captured. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no deployed active-work restart executed. |
| Long exact-RC artifact/config soak | UNVERIFIED: existing driver explicitly rejects its own preflight topology; no exact immutable RC/config supplied in this lane. |
| Load findings classified to earliest broken milestone | Backlog gate PASS; complete load-derived classification UNVERIFIED. No new live-load findings or GitHub mutations. |
| Published human/machine evidence with image/package/commit/config hashes | UNVERIFIED: this report records local checks, not a hash-bound production soak. |

## Handoff

Verdict: **BLOCKED**. The historical CI failure is already fixed; the ledger is
exact. No actual evidence justifies source, test or ledger modification. Only
this report changes; all inherited work is retained. A writer handoff is not
integration or promotion approval.

Next action requires an identified immutable production RC/config, a workload
covering physical execution and required product surfaces, deployed telemetry,
resolution of replica-selection policy at the existing enforcement path, and
an exact-artifact >=4-hour soak. Re-running this historical schema failure or
clean vulture scan cannot resolve those blockers.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 0;
blocked 1. CI repair investigation complete with no reproducible CI defect.
Stop here rather than repeating clean checks or adding speculative changes.

