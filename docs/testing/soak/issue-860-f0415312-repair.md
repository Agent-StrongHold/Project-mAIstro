# Issue #860 — bounded repair f0415312

## Frozen scope

- Issue #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `7b0f249fe746eb3ccdded37df3e694fd6b73d145`; assigned base: `26f86b4634bcf7c4b63394dc5e3dc217308e7e33`.
- Clean initial worktree; no salvage needed. No current-job `check-*.log` files were supplied.
- Inputs: captured `dispatch-context.json`, supplied prior result and check-3 log.
- Repair candidates frozen to `quality/vulture-baseline.json` if the prescribed scan finds reviewed retained debt, and this report. Read-only acceptance review: `scripts/soak/`, `tests/test_soak_promotion_gates.py`, load profile, relevant ADRs, runtime admission/rate-limit paths and adjacent tests. No speculative runtime changes or new execution authority.
- Ambiguity: no exact RC artifact/configuration is designated by the assignment. Do not substitute host-process smoke traffic for promotion evidence.

## Progress

- Prescribed Vulture scan passed: 1323 reviewed identities / 1323 findings,
  zero unclassified or forbidden; automatically selected base `4aa68edc0b6b`.
  No ledger drift exists to amend.
- Historical `98a11313/check-3.log` is a schema-test failure (24 statements versus
  21 expected), not a Vulture finding. Fresh targeted execution does not reproduce it.
- `uv sync --locked --extra dev`: passed, 214 packages checked.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`:
  **103 passed, 6 skipped in 2.54s**. All skips require `MAISTRO_TEST_PG_DSN`;
  no live PostgreSQL evidence is claimed.
- Logs: `/tmp/860-f0415312-vulture.log`, `/tmp/860-f0415312-pytest.log`.
  Commands used 1200–1800 second timeouts.

## Additional validation

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 31128 unique identities, no duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS, component existence only |
| `git diff --check` | PASS |

The exact scanner command was `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, matching the quality workflow. The automatic baseline is not represented as an explicit comparison against the dispatch base.

## Architecture and reachable behavior

Read repository instructions and the documentation authority map. Accepted
ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model, durable Attempt fencing and
renewal/expiry-based reclamation. Admission uniqueness or a restarted process
is not proof of physical-work uniqueness or safe takeover. No competing
scheduler, store, event or authorization authority is introduced.

ADR-085 requires per-principal rate keying; it does not prove shared replica
budgets. ADR-081, cited by the profile, is **Proposed**, not an accepted waiver
of the issue's production acceptance criteria.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`
  acquires the schema advisory lock inside the transaction. The independently
  enumerated test at `packages/maistro-core/tests/persistence/test_pg_learnings.py:162–194`
  now includes the three validation-audit columns missing from the historical
  failing expectation. Fresh execution passes without altering assertions.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs an instance-local
  limiter. Executed `tests/test_soak_promotion_gates.py:439–489` uses this real
  middleware and shows the same authenticated or unauthenticated identity gets
  `[200, 200, 429]` independently on each replica. It is not a full deployed
  concurrency exploit, but does disprove a shared allowance at this seam.
- `scripts/soak/run_soak.py:730–741` unconditionally fails exact-RC certification
  for its host-process topology. The executed promotion-gate tests retain this
  fail-closed behavior; a longer host-process run cannot repair this gap.
- `docs/testing/soak/m3a-load-profile.md:151–170` lists missing representative
  workloads and telemetry; lines 193–203 distinguish schedule admission from
  physical execution. The schedule probe cancels its queued Run without
  executing it. None of the historical bundles is recertified by this review.

## Acceptance matrix (all ten issue criteria)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: documented preflight omits multiple users/Workspaces, fan-out, successful tool/model work, Design/Canvas and background reconciliation applicability. |
| At least two application replicas | **UNVERIFIED for RC**: two ASGI middleware instances exercised, not two deployed immutable RC images. |
| Sustained saturation, growth, reclaim, retry, leaks and restart observation | **UNVERIFIED**: 2.54-second regression suite is not a sustained soak; no new load series executed. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**: admission checks do not witness physical execution uniqueness. |
| Rate/security/degraded non-bypass by replica selection | **Not proven**: executed production middleware tests reproduce independent allowances. Broader deployed security/degraded behavior **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/process/RSS/descriptor/queue/error telemetry with thresholds | **UNVERIFIED for RC**: no new complete telemetry series; driver-loop lag is not application-loop lag. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**: no active-work fault injection or recovery witness executed. |
| Long soak of exact promoted RC/configuration, repeated after changes | **UNVERIFIED / BLOCKED**: no designated immutable RC image/configuration supplied; host-process runner cannot certify it. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED** (GitHub mutations prohibited). Rate-budget discrepancy is a correctness prerequisite, not throughput tuning. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC**: this source-bound regression report is not a promotion evidence bundle. |

## Disposition and handoff

**BLOCKED** on production acceptance, not on the historical schema failure or
Vulture gate. Only this report changed; no runtime, test, ledger, grant or gate
changes are justified by the fresh failure evidence. No tests were added or
changed, so no inventory delta is needed. No develop-sync conflict was found;
no fetch/merge, push or GitHub mutation was performed. Existing work is preserved.

Next: the release owner must designate the immutable RC and runtime configuration;
resolve or govern the rate-budget discrepancy through the existing enforcement
path; complete representative workload, telemetry and physical-work witnesses;
and execute the long exact-RC soak with a hash-bound evidence bundle. Do not
repeat this schema/Vulture repair absent new failure evidence. This checkpoint
is not approval of the inherited branch diff, integration or promotion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate exact RC and complete production-soak prerequisites"}`.
Local commit required for this handoff; final response records its identity.
