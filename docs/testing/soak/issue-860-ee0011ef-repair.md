# Issue #860 — repair checkpoint ee0011ef

## Frozen scope

- Assigned item: #860 only; branch `auto-860`, starting HEAD
  `697fe4e2dfec83363ec24086d91ff2a40b2b909f`, supplied develop base
  `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`.
- Starting worktree is clean; no incoming edits to salvage.
- Repair targets: `quality/vulture-baseline.json` only if the mandated scan
  establishes ledger drift; `scripts/soak/run_soak.py` and
  `tests/test_soak_promotion_gates.py` only if focused checks establish a
  repairable regression; this checkpoint and an inventory note if tests change.
- Read-only context: repository instructions, relevant ADRs, load profile,
  production rate-limit/admission wiring and adjacent tests, captured dispatch,
  supplied prior result/logs. No remote enumeration or GitHub mutations.
- No `check-*.log` files were present in this job directory at initial inspection.
- Ambiguity: this is a writer CI-repair assignment, not a verifier-only run.
  Run the exact scanner before considering ledger amendments. Historical
  BLOCKED results are hypotheses to verify, not current acceptance evidence.

## Progress

- Mandated exact vulture scan PASS: 1,326 findings / 1,326 reviewed
  identities; unclassified=0, never_allowlist=0. No ledger edit is warranted.
- Supplied prior check-3.log reports a schema-fence assertion (24 versus 21
  DDL statements), not a vulture failure. Fresh targeted pytest passes:
  37 passed, 6 PostgreSQL-dependent skips (1.78 s). The present test explicitly
  covers the three Gauntlet audit columns missing from the old failure.
- Captured final issue comments and prior result describe an acceptance
  blocker, not a merge conflict. No develop merge is indicated.
- Focused soak/boot/backpressure/rate-limit tests: 100 passed (3.08 s).
  This executes the production limiter reproduction: the same identity gets
  `[200, 200, 429]` independently from each replica instance. These ASGI tests
  are not an actual deployment or a shared cluster-budget proof.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS
  (3,195 files); `uv run python scripts/check-merge-markers.py`: PASS.
- Read accepted execution/runtime, fencing, lease-reclaim and release ADRs
  (081426-1f7c, 081626-f383, 082526-b36a, 073126-c4e1). Attempt is physical
  execution identity; authoritative leases belong to canonical persistence.
  Admission counts cannot replace physical-work fencing evidence, and a local
  branch preflight cannot stand in for the selected release artifact.
- `uv sync --locked --extra dev`: PASS. Fresh Python evaluation using the
  current driver rejects preserved `evidence/m3a-round30-shakedown.json`:
  `sustain_duration` and `exact_rc_artifact` fail. Observed historical duration
  420.08 seconds is below the current 14,400-second minimum. Also asserted
  `preflight_artifact_check()['ok'] is False`. This is negative validation of
  historical evidence, not a new soak.
- No production/test regression demonstrated by these checks; no code or
  ledger amendment justified.

## Executed commands

All validation used 1,200-second command timeouts.

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q
uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-merge-markers.py
uv sync --locked --extra dev
uv run python -  # import driver; assert historical duration/artifact failures
```

## Acceptance disposition

| #860 criterion | Reachable evidence and result |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` lists missing multi-user/Workspace, fan-out, successful tool/model, Canvas and Goal workloads. `scripts/soak/run_soak.py:1372–1395` uses one credential and a narrower traffic mix. |
| At least two replicas | **UNVERIFIED on RC.** `deploy/docker-compose.prod.yml:26–77` defines two application services. Boot-contract tests pass, but no exact-RC deployment ran here. |
| Sustained pool saturation, queue growth, lease reclaim, retries and leaks | **UNVERIFIED.** Current evaluator rejects historical 420.08-second evidence against the 14,400-second minimum. Sampler tests pass but cannot establish sustained behavior. |
| No duplicated physical work; Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the admission probe Run without executing it. Under the accepted ADRs, unique Run admission is not proof of unique physical Attempts. |
| Effective rate/security/degraded behavior without replica-selection bypass | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493` gets two fresh allowances for the same principal/IP. Production `api/rate_limit.py:32–37` explicitly documents process-local scope; no cluster budget is proven. Backpressure and rate-limit tests pass within their local contracts. |
| Complete telemetry with thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1424` measures driver event-loop lag, not application lag. Profile gaps include pool saturation, lease reclaim and long-window observations. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1436–1489` measures process exit/rejoin and HTTP counters, without an active-Attempt physical-work oracle. No new kill/restart experiment executed. |
| Long exact-RC/config soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` explicitly rejects its host preflight artifact. Fresh historical evaluation fails duration/artifact gates. The assigned branch HEAD is not a selected immutable promotion image/configuration. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED completeness.** The profile records historical findings, but no complete new production run/classification audit was performed. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for current RC.** Existing artifacts are preserved. This commit-bound report is validation evidence, not image/config-bound production soak evidence. |

## Handoff

**BLOCKED, not merge-ready.** Only this report changes; production code, tests,
quality ledger, gates, authorizations and historical soak artifacts are untouched.
No inventory delta is required because tests are unchanged. The incoming tree was
clean; no salvage or merge conflict arose. Local commit only, no remote actions.

Required next steps: select the immutable RC and runtime configuration through
existing release governance; complete representative production workloads,
application telemetry and active-Attempt observation; reconcile process-local
rate limiting with the replica-selection acceptance; then execute the minimum
four-hour exact-artifact soak. Do not retry this same green CI repair without new
failure evidence or those prerequisites. No competing execution/authorization
path or acceptance waiver was introduced.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC acceptance prerequisites}. CI repair disposition is complete;
the issue's release acceptance is not.
