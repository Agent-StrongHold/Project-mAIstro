# #860 repair checkpoint — round 11

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`, starting head
  `58cd840afa4ab0a517e3c6169dae761a90b897fb`, base
  `4e7ef1ab1ceb41edb175baa06557ab18f4657162` (both resolved locally).
- Worktree was clean; no incoming changes to salvage.
- Repair scope: execute the requested exact-debt-ledger gate, review its reported
  source identities and their adjacent tests, amend `quality/vulture-baseline.json`
  only for retained identities, and record validation here. Inspect existing
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, soak profile /
  evidence, production rate middleware and related ADRs for acceptance evidence.
  No other issue, scheduler, authorization path, or deployment is introduced.
- Prior result inspected: job `9599351b373744d2a95eb47b60892eb5` reports BLOCKED.
  Its verification claims are inputs, not fresh validation.
- Current job directory `2bf756c5f1524a729aab67c40958d69d` contains no
  `check-*.log` files; driver checks cannot be corroborated from that directory.
- Assumption: this is the explicit writer/CI-repair round, not a read-only
  verifier run. RC promotion requires real exact-artifact evidence; a host
  preflight or unit suite cannot substitute for it.

## Results

- Required vulture command passed: 1402 reviewed identities / 1402 findings,
  zero unclassified and zero never-allowlist findings. There are no unbanked
  identities to repair or retain. No ledger amendment is justified.
- Inspected the existing load profile and human evidence: host preflight is
  explicitly non-promotable; round 6 records 90.43 seconds against 14400 required.
  The earlier H3 shared-store assertion is already retracted. No duplicate
  cosmetic repair is needed.
- Accepted ADR-085 requires per-principal rate limiting; ADR-081626-f383 assigns
  execution authority to canonical Attempt leases. Admission uniqueness does
  not establish unique physical work. No competing execution or auth authority
  will be introduced to manufacture acceptance.

## Fresh validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS (1402 reviewed identities, no debt change).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — **102 passed, 5 skipped in 10.68s**. PostgreSQL-dependent skips are not
  credited as live concurrency validation. Middleware regressions execute the
  production limiter, demonstrating independent allowances for the same identity
  on two instances. The sampler regression launches a real uv child and observes
  memory/descriptor growth. Mock HTTP admission tests validate the oracle, not
  real physical work under production load.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS (2624 files).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — PASS
  (4198 collected tests match inventory).
- Long validation timeouts: 1200/1800 seconds. No tests added or changed;
  inventory delta is zero, so no inventory-note amendment is needed.
- Read `AGENTS.md`, `CLAUDE.md`, accepted ADR-081426-1f7c and
  ADR-082426-82c7 in addition to the ADRs above. The canonical
  Goal -> Graph -> Run -> NodeRun -> Attempt model is unchanged.
- Inspected `deploy/docker-compose.prod.yml`: two application replicas use a
  local build in a reference topology, not a supplied immutable promotion RC.
  No designated exact RC artifact/configuration was supplied for this round.

- `uv run python -` imported the current driver and evaluated preserved round-6
  JSON: PASS assertions for 90.43 seconds below 14400 and failing gates exactly
  `sustain_duration`, `exact_rc_artifact`. `preflight_artifact_check()` returns
  false with topology `host-uvicorn-preflight`. Historical JSON is unchanged.
- Production reachability: `maistro_server/main.py:478` installs the inspected
  `RateLimitMiddleware`; the independent allowance is reachable production code.
- `git diff --check` — PASS.

## Acceptance disposition

| Criterion | Freshly reviewed / executed evidence and remaining gap |
| --- | --- |
| Representative RC profile | PARTIAL: profile documents request mix and thresholds but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal workloads. RC representativeness UNVERIFIED. |
| Two application replicas | Reference Compose defines two; exact production-artifact execution UNVERIFIED. Unit ASGI instances are not a deployment soak. |
| Sustained saturation, growth, reclaim, retry and leak observations | UNVERIFIED. Evaluator rejects historical 90.43-second run; no sustained RC run executed. |
| No duplicate physical work, admission and Goal reconciliation | UNVERIFIED. Admission-oracle tests pass, but mock receipts and historical occurrence admission are not evidence of physical Attempt effects or sustained Goal reconciliation. |
| Security/rate/degraded behavior not bypassable by replica selection | NOT MET for cluster-wide allowance: production-middleware regression observes `[200, 200, 429]` independently on both replicas for the same authenticated/unauthenticated identity. Full RC security/degradation UNVERIFIED. |
| Complete metrics with thresholds | PARTIAL: real child RSS/descriptor sampler regression passes; application event-loop, detached/container workers and sustained pool/queue/lock/leak thresholds UNVERIFIED. |
| Kill/restart during active work, fencing/recovery | UNVERIFIED: historical exit/rejoin is not correlated in-flight physical Attempt drain/reclaim/effect evidence. |
| Long-running exact-RC soak | BLOCKED: no designated immutable RC/configuration supplied and no qualifying evidence. Current driver deliberately rejects host preflight even at four hours. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing report records local F1–F12 classifications. External filing UNVERIFIED; prohibited in this lane. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical reports/JSON preserved, but qualifying RC image/package/commit/config evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. Only this handoff changes in round 11;
no runtime/configuration/test/ledger changes, no fabricated soak and no GitHub
mutations. The explicit CI gate already passes, so changing retained identities
would not address actual scanner evidence. The previous acceptance block is not
resolved by passing static gates or unit tests.

Release owner next steps: designate immutable RC image/configuration, resolve
aggregate rate-limit semantics with the owning security/deployment lane, complete
representative production workloads and physical-effect oracles, then execute
and publish a new >=4-hour exact-artifact soak. No new evidence here waives any
acceptance requirement. Missing measurements remain unverified, not zero.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
production-path sustained evidence}`. CI-repair validation completed; issue #860
remains blocked. This report is the local writer commit checkpoint.
