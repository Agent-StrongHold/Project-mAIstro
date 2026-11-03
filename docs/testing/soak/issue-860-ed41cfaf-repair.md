# Issue #860 — repair checkpoint (ed41cfaf)

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `1ff9a17a1508f55c948ebcc75ef5a1bbbc95b614` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree: clean. No incoming edits to salvage.
- Inputs: supplied dispatch-context.json, prior fed13f53 result, prior 98a11313 check-3.log; no check-*.log files in the current job directory at initial inspection.
- Read scope: repository instructions, relevant execution/release ADRs, soak harness/profile/promotion tests, vulture checker and CI invocation.
- Write scope: this checkpoint and quality/vulture-baseline.json only if the mandated scan identifies reviewed retained debt. Any actual dead-code repair requires recording its exact file before editing.
- Ambiguity: repair assignment includes broad release acceptance but does not itself identify an immutable RC deployment/configuration. Do not substitute a local smoke run for release evidence.

## Progress

Verified assigned HEAD and clean worktree; read supplied issue acceptance and prior result. Prior assertions are not treated as fresh validation. Supplied develop base also resolves. No sync conflict exists.

Read repository instructions, documentation authority hierarchy, and accepted ADR-062, ADR-082126-f69c, ADR-082426-82c7 and ADR-082526-b36a. Canonical execution remains `Goal -> Graph -> Run -> NodeRun -> Attempt`. Schedule admission identity is not proof of unique physical work; process restart is not proof of lease reclamation. No competing scheduler or authorization path was introduced.

## Fresh validation

All commands below ran in the assigned worktree with 1,200-second timeouts; results are from this round, not copied prior claims.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,323 findings / 1,323 reviewed identities, zero unclassified or never-allowlist. Matches `.github/workflows/vulture-ratchet.yml:82`. No debt amendment justified. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q -rs` | PASS: 102 passed, 6 skipped in 2.40s. Six integration tests require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation claimed. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3,270 files already formatted. |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 31,128 unique identities, zero copied evidence. |

The supplied historical `check-3.log` fails the schema-fence test (24 statements versus 21 expected), not Vulture. The current independent expected-DDL list at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173` already includes the three Gauntlet upgrades. The named test passes in the executed suite. Re-editing it or banking guessed scanner findings would not repair an actual failure.

## Acceptance review

Reviewed the load profile, harness artifact gate and adjacent promotion tests, plus the production rate middleware. Tests execute that middleware through ASGI, not a deployed RC. `RateLimitMiddleware` constructs a per-instance `InMemoryRateLimiter` (`packages/maistro-server/src/maistro_server/api/rate_limit.py:94`). The test at `tests/test_soak_promotion_gates.py:439` exhausts one replica and obtains another `[200, 200, 429]` allowance on the second for both authenticated and anonymous identities. This reproduces process-local enforcement; it does not satisfy the stronger issue requirement. That policy mismatch requires explicit resolution, not a silent waiver.

| #860 criterion | Evidence / disposition |
| --- | --- |
| Representative release-candidate profile | UNVERIFIED: `docs/testing/soak/m3a-load-profile.md` explicitly identifies missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas/Design and Goal reconciliation. |
| At least two deployed replicas | UNVERIFIED: executed ASGI instances are not exact production RC replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leak observations | UNVERIFIED: no sustained RC load executed; sampler unit tests cannot supply these observations. |
| No duplicate physical work | UNVERIFIED: admission probes do not establish physical Attempt fencing or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED with counterevidence: the executed production-middleware test reproduces independent replica allowances. |
| Full telemetry and explicit pass/fail thresholds | UNVERIFIED: profile exists but no complete RC measurement series; driver loop lag is not application loop latency. |
| Active-work kill/restart proves drain/fencing/recovery | UNVERIFIED: gate tests pass but no live active-Attempt recovery experiment executed. |
| Long soak of exact promoted RC/configuration | UNVERIFIED: `scripts/soak/run_soak.py:730` deliberately rejects host-preflight artifact equivalence, including four-hour runs. Assignment does not designate an immutable promoted deployment/configuration. |
| Load findings filed/reclassified before promotion | UNVERIFIED: no new external disposition established; GitHub mutations prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for the RC: this source/check report is not deployed soak evidence. |

## Handoff

**BLOCKED**, not merge-ready. No currently failing gate justifies source or ledger changes. Changed only this report; no test additions or changes, so no inventory delta required. Existing branch work is preserved. No GitHub mutations performed.

Next required inputs/work: designate immutable RC image/configuration and an authorized execution environment; resolve the replica-budget acceptance mismatch; complete the representative production-path runner and full telemetry; execute active-work recovery and the >=4-hour exact-RC soak. Changes to runtime/code/configuration require a fresh soak. Starting another host preflight cannot resolve these blockers.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues, errors 0 executed validation failures; 6 database-dependent tests skipped. Residual risks are the ten unverified criteria above. This bounded check does not recertify all historical branch changes or authorize integration.
