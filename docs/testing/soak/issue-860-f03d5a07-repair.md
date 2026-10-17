# Issue #860 — job f03d5a07 validation and blocked handoff

## Frozen scope

- Assigned writer: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `57b518278474e61fe6a8677b8e237e1de3ebc124`.
- Assigned comparison base: `55a647059dcf07aa7ca0621e497f6ddf6becc956` (resolved by initial diff).
- Process only #860. Review surface: repository instructions; execution,
  scheduling, deployment and rate-limit ADRs; `scripts/soak/run_soak.py`;
  its promotion/boot-contract tests; production rate middleware, task
  backpressure and PostgreSQL learnings code and adjacent tests; production
  Compose; load profile, human evidence and the four historical JSON packs
  (`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`,
  `m3a-round6-shakedown`); exact vulture/provenance gates.
- Edit surface: this report, plus actual dead code/reviewed ledger identities
  only if the exact requested scan demonstrates a repair. No runtime change
  or soak certification is assumed.
- Initial job-directory listing has no `check-*.log` files. Driver checks
  unavailable; validation below is independently executed.
- Prior result and prior report read as historical claims, not proof.
- Ambiguity: no immutable RC image/configuration is supplied. A host-process
  preflight cannot substitute for the RC soak. No merge conflict is present.

## Checkpoint 1 — actual CI evidence

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
(600-second timeout): PASS, 1360 reviewed identities / 1360 findings,
zero unclassified, zero never-allowlist. Gate selects merge base `045cfdfbe3ea`.
No evidence supports deleting code or amending the already-matching ledger.

Current profile explicitly acknowledges missing representative workloads and
cannot certify its host-process runner as the RC artifact. Full acceptance
assessment and focused validation follow below.

## Checkpoint 2 — architecture and focused gates

- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS,
  2809 files (1200-second timeout).
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 46 quality JSON
  consumers and delegated gates; `uv run python scripts/check-shipped-surface-truth.py`:
  PASS (600-second timeout). Exact vulture CI arguments confirmed in
  `.github/workflows/vulture-ratchet.yml:82–85`.
- Production installs `RateLimitMiddleware` at `main.py:588`; each instance
  creates an `InMemoryRateLimiter` at `api/rate_limit.py:72`. Current human
  evidence at `m3a-soak-evidence.md:171` already retracts the old shared-store
  claim. No cosmetic correction to that already-corrected text is warranted.
- Accepted ADR-085 specifies per-principal identity, not shared replica state.
  ADR-081 is Proposed, not an accepted exception to #860. Accepted
  ADR-081626-f383 places fencing in the canonical Attempt store and explicitly
  leaves lease-expiry takeover to a later contract. ADR-082126-f69c makes
  schedule occurrences produce canonical Runs, not a second runtime.
  Admission races cannot certify physical-work recovery; no competing
  execution/authorization authority is introduced here.
- Docker daemon reachable (29.7.2). Created only this job's scratch PostgreSQL
  container `maistro-860-f03d5a07-pg` (`29ad5018a59f`),
  `pgvector/pgvector:pg18`, loopback port 45575, database `maistro_860`.
  This is test infrastructure, not an RC application deployment.

## Checkpoint 3 — executed acceptance validation

- With `DATABASE_URL=postgresql://postgres@127.0.0.1:45575/maistro_860`,
  `uv run alembic upgrade head`: PASS, full chain through 050.
- With `MAISTRO_TEST_PG_DSN` set to that scratch database,
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **93 passed in 2.49s, zero skipped** (1200-second timeout).
- Production-middleware replica-selection regressions at
  `tests/test_soak_promotion_gates.py:439–488` reproduce `[200, 200, 429]`
  on each instance for the same caller, authenticated and unauthenticated.
  Replica 2 admits more requests while replica 1 remains exhausted. These
  are real middleware instances under ASGI, not an RC application soak.
- Executed `uv run python` importing current `failed_promotion_checks`
  against exactly the four frozen historical packs: every pack rejects
  `sustain_duration` and `exact_rc_artifact`. Runs 5/6 record 90.17/90.43
  seconds versus 14400; older packs lack duration-gate records. Asserted
  rejection of both gates for every pack and asserted that the current
  `preflight_artifact_check()` returns `ok=false`: PASS.
- Stopped only this job's scratch container, preserving its data/container.
  No other Docker resources changed. `git diff --check`: PASS.

## Acceptance assessment

| # | Criterion | Current evidence / gap |
|---|---|---|
| 1 | Representative RC profile | PARTIAL; completion UNVERIFIED. Inspected `m3a-load-profile.md:151–166`: concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal/background-worker workloads are missing. No selected RC config justifies exclusions. |
| 2 | At least two application replicas | UNVERIFIED for RC load. Compose defines two servers and boot-contract regressions pass, but this round did not boot two RC applications. |
| 3 | Sustained saturation, queue growth, reclaim/backoff, leaks and shutdown | UNVERIFIED. All four historical packs fail duration. Focused passing tests do not demonstrate sustained behavior. |
| 4 | No duplicated physical work; Goal reconciliation | UNVERIFIED. Admission-oracle regressions pass, but the schedule probe cancels its queued Run without execution (`m3a-load-profile.md:191–196`). No physical Attempt correlation/reconciliation under load was executed. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: executed production middleware regressions demonstrate independent allowances. Broader RC concurrency/security/degraded behavior remains UNVERIFIED. |
| 6 | Complete telemetry with explicit thresholds | UNVERIFIED for RC. Process-group sampler regressions pass, not a new telemetry series. Profile acknowledges missing application-loop, worker, pool-saturation, lease-reclaim and long-window observations; several thresholds remain soft. |
| 7 | Active-work kill/restart with drain/fencing/recovery | UNVERIFIED. Historical process exit/rejoin is not physical Attempt recovery proof. No RC failure injection was run. |
| 8 | Long-running exact RC artifact/configuration soak | NOT MET. Current runner is host uvicorn (`run_soak.py:270–295`) and deliberately fails RC certification (`:635–645`). Historical packs fail duration and artifact gates. No immutable RC artifact/config supplied. |
| 9 | Findings filed/reclassified to earliest broken invariant | PARTIAL; external filing UNVERIFIED. Inspected local F11/F12 evidence-validity classifications; no new load finding or GitHub mutation. |
| 10 | Machine/human evidence tied to exact promoted hashes | UNVERIFIED for promotion. Historical packs are preserved unchanged and rejected by current evaluator. This report is focused validation, not a soak. |

## Final handoff

**BLOCKED for #860 acceptance.** The requested exact-debt-ledger scan is
already green; no unbanked identity exists to repair. The prior inaccurate H3
claim is already corrected. No production, config, ledger, grant or test changes
are supported by the CI evidence in this round. Only this report changes; no
new test inventory delta is necessary because no tests were added or removed.
Canonical Goal → Graph → Run → NodeRun → Attempt remains unchanged.

Next: supply the immutable RC image/configuration intended for #89, complete
representative production-path workloads/telemetry and physical Attempt
correlation, resolve replica-selection non-bypass through canonical enforcement,
then run a fresh ≥14400-second exact-artifact soak including active-work failure
injection. Any code/runtime-config change requires another soak. Repeating the
green vulture scan cannot satisfy these missing acceptance surfaces.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 RC artifact, representative runner, non-bypass and qualifying soak"}`.
Local commit is a blocked handoff only, not integration approval.
