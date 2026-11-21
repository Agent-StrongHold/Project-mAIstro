# Issue #860 — repair validation 84ecdeef

## Frozen scope and initial result

Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, clean starting
HEAD `e30d0072552a90553ae7c9c91ebe8ef85dd9bc58`; supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Process only issue #860, not its
linked PRs. Repair candidates are the learning-schema regression test and
`quality/vulture-baseline.json`, only if fresh failures justify changes; otherwise
only this handoff. Read-only scope: supplied dispatch/prior artifacts, repository
instructions, execution/fencing ADRs, soak profile/runner/tests and related
production admission/rate-limiting behavior. No current-job check logs existed
in the initial job-directory listing.

Fresh reproduction (1,200-second timeout):

- Mandated `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,322 reviewed identities/findings, zero unclassified or never-allowlist identities. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. Historical supplied check-3 failure (24 statements versus 21 expected) does not reproduce.

Assumption: no immutable RC/configuration is designated in the supplied issue
acceptance text. Do not treat historical success claims or unit tests as an
executed production soak. Acceptance review and validation follow below.

## Completed focused validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 73 passed in 2.12 seconds.
- All validation commands used 1,200-second timeouts. No source or test changes
  were justified; no test inventory delta or ledger amendment is needed.

The existing expected DDL list at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:176` already includes
all three validation audit columns omitted in the historical failed check.
Production `pg_learnings.py:215` takes the advisory lock within the transaction
before schema upgrades. The six skipped tests are not live PostgreSQL evidence.

Read accepted ADRs `081426-1f7c` and `081626-f383`: preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. The latter intentionally leaves
live-Attempt expiry takeover undefined; do not invent a competing reclaim
scheduler to satisfy the issue. No architectural or authorization changes made.

## Acceptance review

| Issue criterion | Fresh evidence / remaining status |
| --- | --- |
| Representative RC profile | UNVERIFIED. Reviewed `m3a-load-profile.md`; its remaining-gaps section excludes concurrent users/Workspaces, fan-out, successful model/tool operations and Goal workloads without a selected RC applicability decision. |
| Two deployed replicas | UNVERIFIED. Executed two-instance ASGI tests, not production deployment replicas. |
| Sustained saturation, growth, expiry/reclaim, retries and leaks | UNVERIFIED. Short tests do not establish long-window behavior. |
| No duplicate physical work, admissions and Goal reconciliation | UNVERIFIED. Admission assertions are not physical Attempt execution/recovery or sustained Goal reconciliation evidence. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall. Executed `tests/test_soak_promotion_gates.py:439`: each production middleware instance allows [200, 200, 429] independently for the same principal/IP. Production `api/rate_limit.py:32` explicitly documents that scope. Backpressure tests pass locally. |
| Production telemetry with thresholds | UNVERIFIED. Profile defines thresholds, but no fresh production time series; driver loop lag is not application loop latency. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED. No physical active-work restart performed. |
| Long exact-RC soak | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly returns a failed exact-artifact check for its host-process topology; running it longer cannot supply the missing proof. |
| Findings classified to earliest milestone | UNVERIFIED for completeness without the production run; no GitHub mutations performed. |
| Machine/human evidence bound to artifact/config hashes | UNVERIFIED for promotion. This report identifies tested source, not an executed immutable RC image/configuration. |

The executed production-router receipt test at
`tests/test_soak_promotion_gates.py:564` also observes local 200 and peer 404.
`packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the local queue.
Do not interpret this test's passing status as proof of cross-replica receipt durability.

## Handoff

**BLOCKED** on production acceptance. The supplied CI failure is stale on this
HEAD; the requested vulture scan has no unbanked identities. Changing the ledger
or tests anyway would be cosmetic, not a repair. Only this report changed.

Next requires a designated immutable RC/configuration, an exact-artifact runner
and representative workloads/telemetry, reconciliation of the replica allowance,
receipt and reclaim limitations, then the required long production soak. Another
identical passing CI repair cannot resolve these blockers. No integration or
issue-closure approval is implied.

Progress: checked 1 issue; done 0 acceptance sets; skipped 0 issues; errors 0
validation commands. Existing work preserved; handoff committed locally.
