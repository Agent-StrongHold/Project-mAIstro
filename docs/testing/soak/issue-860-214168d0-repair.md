# Issue #860 — bounded repair checkpoint (214168d0)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`3e2b387261fc237f3eeb2cc2dcf732ace02d61cb`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial worktree is clean. No GitHub mutations or other issues are in scope.
Files eligible for repair: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
its production counterpart `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`quality/vulture-baseline.json` only if the required scan identifies reviewed debt,
this report, and a corresponding inventory note if tests change.
Other source, tests, ADRs and supplied dispatch evidence are read-only context.

## Initial evidence / assumptions

- Current job directory contains no `check-*.log` files.
- Supplied prior `98a11313.../check-3.log` reports schema-fence test failure
  (24 actual statements versus 21 expected); reproduce before editing.
- Supplied previous result is BLOCKED on exact-RC soak and cross-replica security.
  This is not assumed proven by the previous report; focused checks follow.
- This is a writer/CI-repair assignment. No exact RC image/configuration or
  production soak authorization is supplied; do not substitute ASGI/unit tests
  or synthetic local harness results for those acceptance criteria.

## Fresh validation

Commands executed in this worktree with 600–1,200 second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS, 1,322 reviewed identities and 1,322 findings, zero unclassified or
  never-allowlist findings. Gate-selected base: `321cbdb8fe9b` (not the supplied
  campaign base). No observed debt to amend; ledger/grants unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — PASS, 110 passed and 6 skipped in 2.23 seconds. Skipped PostgreSQL cases
  do not establish live database behavior.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3,301 files already formatted.

The historical schema failure is already repaired at the starting head:
`test_pg_learnings.py:176` independently enumerates the three audit columns.
The fresh test execution passes; no speculative source/test change is justified.
An initial context search named a nonexistent `docs/testing/soak/README.md`;
not found, skipped. This was not a validation failure.

## Architecture and observed blockers

Read repository instructions, documentation authority hierarchy, and accepted
ADRs `081426-1f7c` (ExecutionRuntime) and `081626-f383` (execution fencing).
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt model is unchanged.
The fencing ADR explicitly leaves live-Attempt lease takeover outside its
contract. Reconciliation: #860 does not authorize a competing reclaim authority.

Freshly executed tests establish these limited facts, not production soak:

- `tests/test_soak_promotion_gates.py:439`: real production rate middleware
  accepts `[200, 200, 429]` independently on both replicas for the same IP or
  credential. Replica selection obtains additional allowance.
- `tests/test_soak_promotion_gates.py:564`: real task router with shared canonical
  admission returns 200 for the local receipt and 404 from the peer queue.
- `scripts/soak/run_soak.py:744`: the preflight artifact gate unconditionally
  rejects equivalence to the promoted Compose image/configuration. More time
  in this host-process harness cannot satisfy exact-RC acceptance.
- Production task backpressure tests pass, but do not run a physical worker or
  establish active-work restart safety.

## Acceptance review

Read `docs/testing/soak/m3a-load-profile.md` completely and checked the
production rate middleware, receipt handler, and adjacent backpressure test.
Prior load-run claims in that profile were not independently reproduced here.

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC load profile | UNVERIFIED: profile explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker coverage; no selected RC configuration supplied to justify omissions. |
| 2 | At least two deployed replicas | UNVERIFIED: tests use two ASGI instances, not production deployments. |
| 3 | Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED: focused tests are short; no sustained production observations or live-Attempt reclaim experiment. |
| 4 | No duplicate physical work across replicas | UNVERIFIED: admission and receipt tests are not physical Attempt execution or Goal reconciliation under load. |
| 5 | Replica-resistant security/degraded behavior | UNVERIFIED overall; real middleware test demonstrates additional allowance from replica selection. Local backpressure is tested successfully, not cluster-wide security. |
| 6 | Required telemetry and explicit thresholds | UNVERIFIED: profile has thresholds but no fresh production pool/lock/loop/worker/RSS/descriptor/error series; driver loop lag is not application loop lag. |
| 7 | Active-work kill/restart with drain/fencing/recovery | UNVERIFIED: no physical worker or active-work restart experiment ran. |
| 8 | Long exact-RC soak | UNVERIFIED: immutable RC not supplied; current runner rejects exact-artifact equivalence regardless of duration. |
| 9 | Findings classified to earliest broken milestone | UNVERIFIED for completeness: no completed production load run; blockers recorded locally, no prohibited GitHub mutations. |
| 10 | Machine/human evidence bound to artifact/config hashes | UNVERIFIED for promotion: this report and executed unit checks are local validation only, not a hash-bound production soak. |

## Handoff

**BLOCKED**. Only this report changed; no source, tests, gates, ledger or grants
changed. No suite-count delta or inventory note is needed. Historical failure
is already repaired, and the exact vulture scan reports no unbanked identities.
Do not repeat a ledger-repair round to address these production acceptance gaps.
Next work requires a selected immutable RC/configuration, a representative
production-path workload, and resolution of replica-budget/receipt/reclaim
limitations before the required long production soak can establish acceptance.

Progress: checked 1 issue, done 0 acceptance sets, skipped 0 issues, errors 0
validation commands. All previous work is preserved. Commit this report locally;
no push, integration approval, or issue-closure action.
