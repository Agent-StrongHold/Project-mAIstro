# Issue #860 — repair checkpoint (job 57f2ad95)

## Frozen scope

Only issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `ab99852c50c32efaf4a85fdd016f420c3f8c4380`,
base `cfb6c3b647145dfcd3ad9b7a1c38f4713d949103`.
Inspection scope: repository instructions, relevant deployment/execution/rate
ADRs, existing load profile/evidence, soak harness and adjacent tests,
production rate limiter, exact-debt ledger gate, and prior result artifact.
Candidate edits are limited to this report and evidence-backed corrections to
`m3a-soak-evidence.md`; ledger changes only if the exact gate identifies debt.
No runtime changes or new test cases planned absent an observed defect.

## Initial observations

- Worktree clean; starting HEAD matches assignment.
- Current job directory contains no `check-*.log` files. Driver checks are not
  available here; do not treat earlier jobs' checks as current validation.
- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1342 findings / 1342
  reviewed identities, zero unclassified or never-allowlist identities.
  There is no demonstrated ledger repair to make.
- Assumption: this is a writer repair, not a verifier-only run. Missing exact
  RC promotion evidence must remain blocked; a host-process shakedown is not
  an equivalent replacement.

## Inspection checkpoint

- The prior H3 shared-store assertion is already corrected at the assigned HEAD:
  `m3a-soak-evidence.md` calls run 6 partial and explicitly states replica
  switching increases aggregate allowance. No duplicate cosmetic repair needed.
- Read ADR-081 (Proposed deployment guidance), ADR-085 (Accepted per-principal
  rate limits), ADR-081626-f383 (Accepted Attempt fencing), and
  ADR-082426-82c7 (Accepted occurrence admission). Reconciliation: admission
  uniqueness is not physical-work uniqueness; no new scheduler/store/auth path
  is warranted. ADR-085 does not make process-local enforcement a proof of
  #860's replica-selection requirement.
- Production Compose defines two application services, shared Redis/files,
  PostgreSQL primary/replica, and requires an external model gateway. The
  host-process provider-less shakedown does not exercise that artifact.
- Existing regression tests explicitly exercise real rate middleware with
  independent allowances, actual HTTP admission/backpressure wiring, and the
  sampler's live uv child. The PostgreSQL schema-lock unit test checks SQL
  ordering with a fake connection, not live cross-replica startup.
- Prior job result was BLOCKED, with no driver checks in its `checks` array.
  Its historical outcomes are not reused as this round's validation.

## Executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2857 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped**.
  Skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL claim is made.
  Includes authenticated/unauthenticated independent-replica allowance tests,
  fail-closed artifact gates, live child resource sampling, admission oracle
  negative cases, and production-router backpressure/retry tests.
- `git diff --check`: PASS.
- Exact vulture gate: PASS as recorded above; no ledger amendment justified.

No tests added/removed, so inventory delta is zero and no new inventory note is
required.
- Executed an inline `uv run python` import of `scripts/soak/run_soak.py`,
  loaded the unchanged round-6 JSON, and asserted its current failed checks
  equal `['sustain_duration', 'exact_rc_artifact']`: PASS. Observed duration
  90.43 seconds; `preflight_artifact_check()['ok']` is false.

## Acceptance disposition — BLOCKED

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md` defines a preflight mix and explicitly lists missing multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal-worker coverage. |
| Two application replicas | Production Compose names both services; round-6 JSON records two historical preflight processes. **UNVERIFIED for exact RC**; no new live topology run in this round. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED**: current evaluator rejects 90.43-second evidence against 14400 seconds. Historical wrapper-only memory/FD samples cannot prove application health. |
| Schedule/task/Run/Attempt uniqueness and Goal reconciliation | **UNVERIFIED for physical work**: admission probe cancels its queued Run (`run_soak.py:963-974`); no physical execution or recovery follows from one admission. No sustained Goal workload. |
| Security/degraded behavior and replica-selection non-bypass | **NOT MET** for non-bypass: executed production-middleware tests show the same identity receives independent `[200, 200, 429]` allowances on each replica. Historical unauthenticated metrics 401/degraded readiness 503 are not complete concurrent RC security proof. |
| All telemetry and explicit thresholds | **UNVERIFIED**: sampler reads PG sessions/locks/probe latency and Run counts; live uv-child sampler test passes. Driver-loop lag is not application-loop lag; comprehensive worker/leak/reclaim thresholds remain absent. |
| Kill/restart with active-work fencing/recovery | **UNVERIFIED**: historical process exit/rejoin and zero nonterminal Runs do not correlate physical Attempts or prove no lost/duplicated effects. |
| Long soak of exact RC artifact/config | **NOT MET**: executed evaluator rejects duration and artifact. No exact RC image digests/config selection supplied by the assignment; current driver deliberately cannot certify Compose regardless of duration. |
| Findings filed/reclassified to earliest invariant | Local F1–F12 classifications inspected. External filing **UNVERIFIED**; GitHub mutations prohibited. |
| Hash-bound machine/human RC evidence | Historical paired JSON/Markdown exists, but **UNVERIFIED for the RC to promote**. No image/config-bound promotion run produced in this repair. |

## Handoff

No new scanner debt or uncorrected prior H3 assertion was demonstrated. Only
this checkpoint/report changes; runtime, ledger, raw evidence and existing tests
are preserved. This is not a completed implementation of #860 and does not
resolve the previous BLOCKED state. Do not repeat emulator shakedowns or create
ledger edits to turn the gate green.

Next: select the immutable RC image/config/provider topology, finish the
representative workload and application telemetry/physical-effect oracles,
resolve the replica-selection policy/implementation mismatch, then run the exact
artifact for at least four hours with correlated active-work failure/recovery.
A runtime/config change after that run requires a new soak. Keep all execution
through Goal → Graph → Run → NodeRun → Attempt.

Progress: checked 1 issue, done 0, skipped 0, errors 0; one blocked handoff.
Local commit required; no push, PR, issue mutation, merge or destructive Git
operation performed.
