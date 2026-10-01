# Issue #860 — assigned-head CI repair revalidation

## Frozen scope

- One item: issue #860, branch `auto-860`, starting head
  `f13b43461111fcd173cc25127f4192bc5e8c6c6b`.
- Assigned base resolves to `4e7ef1ab1ceb41edb175baa06557ab18f4657162`;
  no develop-sync conflict was reported and no integration is attempted.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/`, adjacent task backpressure / PG learnings tests,
  production rate limiter, relevant ADRs and vulture checker/ledger.
- Edit this handoff and only evidence-backed issue-860 or requested vulture
  repairs if validation establishes a defect. No unrelated base divergence work.
- Initial worktree was clean. Prior result was read, not accepted as fresh proof.
- Job `94915f75b5334cd4b55c797762bf9632` contains no `check-*.log` files at
  initial inspection; driver checks are unavailable, not assumed green.

## Ambiguity / assumption

No exact release-candidate image/configuration is assigned. Existing host-process
preflight evidence cannot substitute for a designated production-artifact soak.
Revalidate local gates and report any remaining promotion criteria as unverified;
do not invent release designation or file GitHub findings (mutations prohibited).

## Results

- Required vulture command passed freshly (1800-second timeout): 1402 findings /
  1402 reviewed identities, unclassified=0, never_allowlist=0. No unbanked
  identities were emitted, so no speculative code or ledger amendment is justified.
- Read accepted ADR-081426-1f7c (Attempt physical identity), ADR-081626-f383
  (canonical store fencing), ADR-082426-82c7 (occurrence admission), ADR-085
  (principal rate limits). Admission-only probes cannot prove physical execution;
  no competing scheduler, authority or authorization path is introduced.
- Source inspection confirms per-instance `InMemoryRateLimiter` in production;
  the historical shared-store claim has already been corrected at this head.
  Complete exact-RC acceptance remains distinct from preflight regression gates.

## Fresh executed validation

Commands used 1800-second timeouts in the assigned worktree:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1402 reviewed identities / findings, no unbanked identities |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 102 passed, 5 skipped, 11.62 seconds |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 2624 files already formatted |
| `uv run python -` importing the actual soak driver and evaluating preserved round-6 JSON | PASS: asserted failures exactly `sustain_duration`, `exact_rc_artifact`; 90.43 seconds observed against 14400 required; current artifact check false |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 27 passed, 5 skipped; all skips explicitly require `MAISTRO_TEST_PG_DSN` pointing to migrated PostgreSQL |

The middleware regressions execute real limiter instances for both authenticated
and unauthenticated identities. Each replica returns `[200, 200, 429]` for the
same identity; a healthy local limiter is not a shared allowance. Backpressure
coverage exercises the real task router and canonical in-memory spine. Neither
this nor the fake-connection DDL tests are PostgreSQL multi-replica soak evidence.
No live PostgreSQL or production Compose soak was executed this round.

## Acceptance disposition

| Criterion | Evidence and remaining requirement |
| --- | --- |
| Representative RC profile | PARTIAL: inspected `m3a-load-profile.md`; one-key degraded workload omits concurrent users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas, Goal/background work. RC applicability UNVERIFIED. |
| Two production replicas | UNVERIFIED: `deploy/docker-compose.prod.yml` declares two services, but existing driver boots host processes rather than those images. |
| Sustained saturation, reclaim, retry and leak observation | UNVERIFIED: actual evaluator rejects preserved 90.43-second shakedown against 14400 seconds. Regression execution does not replace sustained traffic. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: schedule probe admits then cancels a queued Run. One durable admission does not establish physical Attempt effects/fencing or Goal convergence. |
| Rate/security/degraded non-bypass across replicas | NOT MET for a shared allowance: fresh middleware regression confirms independent budgets. Canonical identity/security tests pass locally; complete degraded RC traffic UNVERIFIED. |
| Required metrics and explicit thresholds | PARTIAL: sampler regression observes real uv-child RSS/FD growth, but no fresh soak series. Driver loop lag is not application loop lag; full pool/worker/queue pressure and leak/error thresholds UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no fresh RC restart or physical-effect correlation; preserved exit/rejoin evidence is insufficient. |
| Long-running exact RC and re-soak after code/config changes | BLOCKED: no designated immutable RC/configuration supplied; current host driver explicitly rejects exact-artifact equivalence, including at four hours in executed CLI regressions. |
| Findings classified/filed before promotion | PARTIAL: existing F1–F12 local classification retained. External filing UNVERIFIED; GitHub mutations prohibited. |
| Hash-tied machine/human evidence | PARTIAL: preserved JSON/human pack ties historical preflight to hashes, not a promotable exact-RC soak. RC evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not promotion or integration approval. Existing shared-store and
wrapper-metrics overclaims were already corrected at the assigned head. No
fresh scanner failure or runtime repair is established by this validation.
Only this report changes; no tests added/removed (inventory delta zero), no
ledger/grant amendment, no runtime/configuration edits, no evidence rewritten.

Next: designate the exact promotable images/configuration, resolve cluster-rate
semantics with the owning security/deployment work, complete production-path
workload/physical-effect/metric oracles, and publish a new >=4-hour exact-RC soak.
Do not repeat a host preflight and count elapsed time as artifact proof.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
Local checkpoint commit required; final diff validation recorded below.
