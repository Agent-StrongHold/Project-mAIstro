# Issue #860 — bounded repair validation (20692b05)

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `6d95632aa6e3027434fefb73420975430be06182`.
- Develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Starting worktree clean; no uncommitted salvage required.
- Inputs: supplied dispatch-context.json, prior result 877a6040, prior failed
  check `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
- Review scope: repository instructions, relevant execution ADRs,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`,
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`, adjacent tests,
  and the exact vulture gate/ledger if actual findings require repair.
- Planned edit: this validation report; production/test/ledger edits only if
  fresh evidence identifies a focused repair within this scope.
- No check-*.log files were present in this job directory at initial inspection.

## Ambiguity and assumption

This is a writer repair lane, not a read-only verifier lane. Prior claims are
untrusted until rechecked. No exact release candidate artifact/configuration is
identified in the assignment; do not invent one or treat synthetic harness
traffic as promotion evidence. No GitHub mutation or execution-authority changes.

## Results

Fresh validation (1200-second timeouts):

- Exact assigned vulture invocation: PASS, 1322 reviewed identities / 1322
  findings, zero unclassified or never-allowlist findings. Arguments match
  `.github/workflows/vulture-ratchet.yml:82-85`. No ledger change justified.
- Read historical check-3.log: schema-fence assertion observed 24 DDL statements
  against 21 expected. It is not a vulture failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3301 files).

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  99 passed, including both authenticated/unauthenticated independent-replica
  allowance regressions and fail-closed exact-artifact CLI tests.
- `git diff --check`: PASS.

These checks alone do not establish production soak acceptance. No tests were
added or changed, so no inventory delta is needed.

## Architecture and reachable behavior

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383 and
ADR-085. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. The lease ADR
explicitly does not define expiry takeover; satisfying this issue must not
invent reclaim authority. Principal-keyed rate limiting is not proof of a
shared cross-replica allowance.

Fresh source inspection matches the executed tests:

- `pg_learnings.py:215` fences schema DDL inside one transaction. The independent
  expected-DDL list in `test_pg_learnings.py:174` includes the three validation
  audit columns missing from the historical failed check. No assertion weakening
  is needed.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the production
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs its in-memory limiter.
  `tests/test_soak_promotion_gates.py:439` uses that middleware on two ASGI apps
  with the same identity and observes `[200, 200, 429]` independently on each.
  This is executed production-seam evidence, not a deployed soak.
- The executed receipt-load regression uses the production task router and a
  canonical admission spine, observing a peer-local 404. It does not demonstrate
  durable receipt visibility or successful physical execution across replicas.
- `scripts/soak/run_soak.py:744` returns `ok=false` for exact artifact equivalence;
  `:1579` includes it in emitted checks. CLI tests reject absent/null/preflight
  artifact records even with a synthetic four-hour duration.

## Acceptance matrix

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md:169` identifies missing concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. No selected immutable RC configuration establishes applicability. |
| Two deployed replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26` and `:75` define two replicas, but this round executed ASGI seam tests, not deployment traffic. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff and leaks | UNVERIFIED. No sustained deployed run. Six database-dependent tests skipped; passing unit tests cannot replace those observations. |
| No duplicate physical work | UNVERIFIED. Admission tests reject empty/conflict-only/missing-identity evidence; receipt identity does not prove physical schedule/task/Run/Attempt/Goal uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT SATISFIED at the rate-limit seam: the executed same-identity regression demonstrates independent replica allowances. Other deployed security/degraded guarantees remain UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED. No new production PostgreSQL, application-loop, worker/process, RSS/FD, queue or error/timeout series. Driver-loop sampling is not application-loop sampling. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED. Backpressure route regression proves 429 + Retry-After and resumed admission, not physical-work recovery. No replica killed during real work. |
| Long exact-RC soak | UNVERIFIED. Host-process runner fails exact-artifact gate by construction; simulated four-hour evidence is rejected in executed CLI tests. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness. Independent replica budgets and peer receipt visibility are correctness prerequisites, not throughput optimization. Recorded locally; no GitHub mutation. |
| Machine/human evidence tied to exact hashes | UNVERIFIED for production soak. This report identifies starting source HEAD, not an RC image/package/configuration or a soak result. |

## Disposition and handoff

BLOCKED, not integration approval. The historical CI failure is already resolved
at the assigned starting HEAD; the exact vulture ledger is synchronized. No
unbanked identities exist to amend. Only this report changed; no source, tests,
ledger, grants or gates changed. There was no develop-sync conflict.

Next actionable input is a selected immutable RC image/configuration and a
representative workload decision. Resolve replica-local enforcement/visibility
through the existing production seams, then run the supported topology long
enough to observe physical-work uniqueness, active-work recovery and complete
telemetry. Do not substitute another short emulator run or repeat this passing
CI repair without new failure evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next: production-soak prerequisites above. Local validation
completed: 136 passed, 6 skipped; exact vulture, lint and format all passed.
