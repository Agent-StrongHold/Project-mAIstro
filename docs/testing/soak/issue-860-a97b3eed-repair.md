# Issue #860 — a97b3eed validation handoff

## Snapshot and reproduced result

Assigned issue #860 only, branch `auto-860`, starting commit
`466e9af0fedabbf497d7fdb00365635a57d99ff2`, supplied base
`56332162cf636e9a1e8a7e346101803ed6ec7b1f`. Initial worktree was clean.
The job directory had no driver `check-*.log` files. Captured issue/PR evidence
and the supplied prior result were inspected, not treated as instructions.

The requested exact vulture scan was executed afresh and **passed**:
1,342 reviewed identities match 1,342 findings; zero unclassified and zero
never-allowlist findings. The selected trusted merge base is `c560d4ccad82`.
There are no reported unbanked identities to review, remove or amend.
Changing `quality/vulture-baseline.json` without a finding is unwarranted.
The previous BLOCKED result is a release-evidence blocker, not an observed
vulture failure. No new production code, tests or inventory counts are changed.

## Validation executed

All commands below passed (exit 0), with 1,200-second timeouts for the validation
batches. Logs are `worker-*.log` in job directory
`/home/dev/maistro/jobs/a97b3eedd5f14c80a7577d986800bd2b`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1,342 exact identities, no unbanked or stale debt. Arguments match
  `.github/workflows/vulture-ratchet.yml:82-86`.
- Same command with
  `RATCHET_BASE_REV=56332162cf636e9a1e8a7e346101803ed6ec7b1f` — also passed;
  resolved trusted merge base remains `c560d4ccad82`.
- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 2,985 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — **75 passed in 2.79 seconds**. Existing tests cover fail-closed promotion
  checks, real subprocess resource sampling, production middleware's independent
  replica budgets, and task admission backpressure. This is not a deployed soak.
- `uv run python scripts/check-ratchet-provenance.py` — passed, including
  delegated gates; emitted syntax and local HTTP CORS warnings, not failures.
- `uv run python scripts/check-shipped-surface-truth.py` — passed.
- `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`
  — passed; prior whitespace findings do not reproduce.
- `uv run python -` — imported the current soak runner and evaluated retained
  `evidence/m3a-round6-shakedown.json`; asserted rejected checks are exactly
  `['sustain_duration', 'exact_rc_artifact']` and the current
  `preflight_artifact_check()['ok']` is false. Assertions passed, evidence rejected.

## Architecture and acceptance

Read repository instructions, documentation authority map, ADR-081, ADR-085,
ADR-081426-1f7c and ADR-081626-f383, production Compose, middleware wiring,
the relevant runner/evaluator and adjacent tests. ADR-081 is Proposed, not an
accepted waiver. Accepted ADR-085 requires per-principal enforcement but does
not establish a shared replica budget. Accepted execution/fencing ADRs bind
physical execution to canonical Attempts; admission counts alone cannot prove
physical uniqueness. Lease-expiry takeover is explicitly outside ADR-081626-f383's
current boundary. No competing scheduler, Goal store, execution/event authority
or authorization path was added; `Goal -> Graph -> Run -> NodeRun -> Attempt`
is unchanged. Acceptance is not relaxed to match the preflight's capabilities.

| Issue acceptance criterion | Evidence and verdict |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:152-164` explicitly lacks concurrent user/Workspace population, Graph fan-out, successful model/tool calls, Canvas, Goal and background-worker workloads. |
| At least two deployed application replicas | **UNVERIFIED for RC**. Production Compose defines two replicas; middleware tests instantiate two ASGI applications, not the production containers. No live RC deployment executed here. |
| Sustained saturation, queues, leases, retry, leaks and restart observations | **UNVERIFIED**. Retained JSON records 90.43 seconds, not the required 14,400; current evaluator rejects it. No sustained workload executed this round. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED**. HTTP admission gate tests passed, but historical schedule probe cancels its Run without physical execution (`m3a-load-profile.md:197-200`). This does not prove physical Attempt fencing or Goal reconciliation. |
| Security/degraded behavior cannot be bypassed by replica selection | **NOT MET for a shared allowance**. `tests/test_soak_promotion_gates.py:439-488` passed for authenticated and unauthenticated identities: replica 2 accepts two requests after replica 1's allowance is exhausted. Production installs this process-local middleware at `main.py:627`. Complete deployed security/degraded behavior remains unverified. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Thresholds exist in the profile, but application-loop lag, worker counts and long-window resource evidence remain absent; driver-loop lag is not application-loop lag. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Existing historical exit/rejoin counters do not prove physical work recovery or no duplication. No live restart performed. |
| Long-running exact RC artifact/configuration soak | **NOT MET**. `run_soak.py:635-646` returns a failed exact-artifact gate for its host-process topology; retained evidence also fails duration. Extending that runner alone cannot satisfy the criterion. |
| Findings classified to earliest broken milestone invariant | **UNVERIFIED for completeness**. Existing findings are retained, but no new RC load was performed and no GitHub mutation is permitted. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for current RC**. Retained machine evidence fails exact-artifact evaluation; human profile explicitly identifies the runner as an emulator, not production Compose. No current RC image/config evidence was produced. |

## Handoff

**BLOCKED** on release acceptance, not vulture. The requested CI failure does
not reproduce. Only this report changed; no code, tests, gates, ledgers or grants
were amended, and no inventory delta is required because no tests were added.
This local commit is a validation handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0}`. The item was checked;
issue completion remains blocked. Next requires an authorized release owner to
select the exact RC image/configuration, resolve the replica-budget contract,
and execute a representative production soak for at least four hours with full
physical-work/recovery and telemetry evidence. Do not redispatch this unchanged
vulture repair without a concrete failing log or changed source: another ledger
scan cannot supply the missing production evidence.
