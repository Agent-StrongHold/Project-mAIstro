# Issue #860 — repair checkpoint (job 5b0743a9)

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `7e46cf156f91bdfcb8ca79ac73b5037c15fa8c75`, supplied base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree was clean; no incoming changes needed salvage.
- Inspect assigned dispatch, previous failure log, repository instructions,
  relevant ADRs, soak runner/promotion tests, and vulture gate/workflow.
- Candidate edits: this checkpoint; production code/adjacent tests and inventory
  note only for reproduced defects; `quality/vulture-baseline.json` only for
  reviewed identities reported by the explicitly assigned CI repair.
- No current-job `check-*.log` files were present in the initial job listing.
- Prior BLOCKED result is historical evidence, not acceptance verification.
- Ambiguity: assignment requests a CI repair and full production acceptance;
  passing local gates will not be represented as exact-RC soak evidence.

## Progress

Snapshot complete. No GitHub mutations or ref changes.

- Required exact vulture invocation passed: 1322 reviewed identities and 1322
  findings; unclassified 0; never_allowlist 0. No ledger amendment justified.
- Inspected historical `98a11313167b41a98a420abfda80c292/check-3.log`:
  schema-fence assertion expected 21 statements but observed 24.
- Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: **37 passed, 6 skipped**. Historical failure is not reproducible at
  this head; database skips do not prove live concurrency safety.
- Fresh `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**.
  These are local gate tests, not a production soak.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- The vulture arguments match `.github/workflows/vulture-ratchet.yml:82`
  and `.github/workflows/quality.yml:1079`:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`.

## Architecture and acceptance reconciliation

Read repository `AGENTS.md`, `docs/README.md`, accepted ADR-085 and
ADR-081626-f383, the supplied issue body, current load profile, production
Compose topology, runner, rate middleware and adjacent promotion/schema tests.
The current schema test explicitly includes all three validation audit columns;
production DDL remains under the transaction-scoped advisory lock. Removing
columns or loosening the test to reproduce an obsolete failure is not a repair.

ADR-081626-f383 places lease/fencing authority in the canonical Run store and
explicitly leaves lease-expiry takeover outside its current contract. Issue
#860's reclaim observations cannot justify an alternate scheduler or implicit
timeout takeover. ADR-085 requires per-principal limits; current production
middleware documents process-local allowances. This does not establish the
issue's stronger replica-selection criterion. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and the canonical auth resolver.

| # | Acceptance | Current evidence / disposition |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. No immutable production RC/configuration was selected this round. |
| 2 | Two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26,77` defines two replicas, but no live production deployment was exercised. |
| 3 | Sustained saturation/reclaim/retry/leak/restart observations | UNVERIFIED. No sustained production run executed. Local tests cannot establish these observations; reclaim must respect the accepted ADR boundary. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the admission probe without executing its Run. Admission identity tests are not physical side-effect/reconciliation proof. |
| 5 | Replica-independent rate/security/degraded behavior | NOT SATISFIED by current local limiter. Executed `test_replica_selection_has_an_independent_production_allowance` at `tests/test_soak_promotion_gates.py:439` for authenticated and unauthenticated clients: both instances independently return `[200, 200, 429]` for the same identity. Production middleware constructs `InMemoryRateLimiter` at `packages/maistro-server/src/maistro_server/api/rate_limit.py:94`. Full production security/degraded validation remains UNVERIFIED. |
| 6 | Production telemetry and explicit thresholds | UNVERIFIED. Profile contains thresholds, but driver-loop lag is not application-loop lag. No fresh production pool/query/lock/worker/queue/leak measurements. |
| 7 | Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No active-work interruption or recovery performed. Process rejoin and cancelled admission probes are insufficient. |
| 8 | Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` always rejects this host-process preflight as exact-RC evidence. Executed gate tests confirm that even synthetic four-hour evidence cannot bypass this check. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. This local report records blockers but does not establish their milestone disposition. No GitHub mutations permitted or performed. |
| 10 | Machine/human evidence bound to exact production hashes | UNVERIFIED. This validation handoff is not a production image/package/config-bound soak evidence pack. |

## Final disposition

**BLOCKED** on production acceptance, not the supplied CI gates. No unbanked
vulture identities or reproducible schema-test failure were found, so no source,
test, ledger, grant, runtime configuration or gate changes are justified.
Only this report changes; no test addition means no inventory delta is needed.

Next action requires selection of the immutable RC/configuration and a complete
representative workload, resolution of replica-independent enforcement through
the existing security path, and production physical-work/recovery/application
telemetry observers before the long soak. A repeat of these passing CI checks
or a longer host preflight cannot resolve those prerequisites. This local commit
is a validation handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "resolve production RC soak prerequisites and enforcement mismatch"}`.
Issue #860 remains unresolved; no remote actions were taken.
