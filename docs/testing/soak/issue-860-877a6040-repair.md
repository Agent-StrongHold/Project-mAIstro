# Issue #860 — repair checkpoint (877a6040)

## Frozen scope

- Issue #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `ec08cb82d0a9b25b9ba0c69c4fe7445029855b53` (verified);
  supplied develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot, prior result `d0944f896387418ba24f4bf207b82f60`,
  reported `98a11313167b41a98a420abfda80c292/check-3.log`, and current local
  vulture gate. No remote enumeration or GitHub mutations.
- Read scope: repository instructions, applicable ADRs, existing soak runner/profile,
  production rate-limit/task paths and adjacent acceptance tests, vulture checker/workflow.
- Write scope: this report; `quality/vulture-baseline.json` only if the exact scanner
  identifies reviewed retained identities; issue-related production/test fixes only
  if fresh evidence justifies them (with an inventory note for new tests).

## Initial observations

The supplied prior result is BLOCKED, not promotion evidence. This job directory
contains no driver `check-*.log` files at initial inspection. The assignment is a
writer repair round; fresh commands will determine whether a ledger edit is needed.
The historical check-3 failure is a schema-fence assertion (24 observed DDL
statements vs 21 expected), not a vulture failure. Fresh reproduction:

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 findings / 1322 reviewed identities, zero unclassified or never-allowlist.
  No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. The supplied failure does not reproduce.

The frozen issue body contains ten acceptance criteria, including exact-RC long
soak, physical-work uniqueness and replica-selection-resistant enforcement.
Linked PR #1672 is only a draft claim-stake; none of the supplied linked PR bodies
provides production soak acceptance.

## Architecture review

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383 and ADR-085.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority is unchanged.
ADR-081626-f383 expressly leaves lease-expiry takeover outside its contract;
this issue must not introduce implicit reclaim or a competing scheduler to
satisfy that criterion. ADR-085 principal keying is not a shared-replica budget.

Current code explains the historical schema-test discrepancy: the independent
expected-DDL list at `packages/maistro-core/tests/persistence/test_pg_learnings.py:174`
includes the three validation-audit columns now shipped in production. The schema
transaction takes its advisory lock first at `pg_learnings.py:215`.

`packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates an
in-memory limiter for each middleware instance; `main.py:648` installs it on the
production app. The existing regression at `tests/test_soak_promotion_gates.py:439`
exercises that real middleware with the same identity against two ASGI instances.
This is a meaningful seam test, but not a deployed soak.

## Focused validation (fresh execution)

Commands used 1200-second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files already formatted |
| `git diff --check` | PASS |

Together with the reproduction above, 136 tests passed and 6 skipped. No test
was added or changed, so there is no inventory delta. Vulture invocation matches
`.github/workflows/vulture-ratchet.yml:82`. No source, ledger or grant changed.

## Acceptance audit

| Issue criterion | Evidence and status |
| --- | --- |
| Representative RC workload profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:169` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background reconciliation. No selected RC configuration establishes those exclusions as inapplicable. |
| At least two deployed application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26` and `:75` define two replicas; executed tests instantiate ASGI apps rather than deploy them. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | UNVERIFIED. No sustained deployed load executed. Six database-dependent schema tests skipped; unit results are not database-concurrency or soak evidence. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED. Admission probe tests reject empty/all-conflict/missing-identity results, but receipt identity is not physical execution uniqueness. Canonical fencing/reclaim contracts remain unchanged. |
| Replica-selection-resistant rate/security/degraded behavior | NOT SATISFIED at the production rate-limit seam. The executed authenticated and unauthenticated regression observes `[200, 200, 429]` independently on both replicas for the same identity. Production `RateLimitMiddleware` constructs local state. Other deployed security/degraded guarantees remain UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED. No new deployed PostgreSQL, application event-loop, worker/process, RSS/descriptor, queue or error/timeout series. The profile distinguishes driver-loop lag from application-loop lag. |
| Active-work restart, drain, fencing and recovery | UNVERIFIED. No deployed replica killed/restarted during active physical work. Existing task route test proves canonical admission backpressure returns 429 + Retry-After and admission resumes after a slot frees, not physical recovery. |
| Long exact-RC artifact/configuration soak | UNVERIFIED. `scripts/soak/run_soak.py:744` returns `ok=false` for artifact equivalence. Executed CLI tests (`tests/test_soak_promotion_gates.py:106`) fail closed for missing/null/preflight artifact records even with synthetic four-hour duration. Those tests are not a four-hour run. |
| Load findings filed/reclassified before promotion | UNVERIFIED for completeness. Replica-local enforcement is an unresolved correctness prerequisite, not an M6 throughput concern. This report records it locally; no GitHub mutations performed. |
| Machine/human soak evidence bound to exact hashes | UNVERIFIED for production. This report binds local validation to the starting source HEAD only, not an RC image/package/configuration or observed soak. |

## Disposition / next action

**BLOCKED — not integration approval.** The assigned historical CI failure is
already repaired at the starting HEAD, and the exact-debt ledger passes without
amendment. Editing either would be speculative. There is no sync conflict and
no reason to merge a new base for this round.

Only this report changed. No new soak evidence is claimed. Preserve the existing
fail-closed gates. The next actionable work requires a selected immutable RC
artifact/configuration and representative profile, resolution of the independent
replica allowance through existing enforcement seams, and a long supported-topology
run observing physical work, active-work recovery and complete telemetry. A longer
host-process preflight cannot substitute for that evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. The bounded CI investigation is complete; the production
promotion prerequisites above remain unresolved.
