# Issue #860 repair checkpoint — ecb9d6b1

## Frozen scope

Only issue #860 in assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `bcf881df5e9e3cb1eb1692288d49c4496ed5bfbb`,
base `435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial worktree clean.
No PR processing or GitHub mutation. Use the supplied dispatch snapshot only.

Review scope: `AGENTS.md`, relevant ADRs, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
prior result and cited check log, prior repair note, vulture checker/workflow
and `quality/vulture-baseline.json`, affected server task admission and core
learning persistence modules/tests, current deployment configuration and
existing evidence. Candidate write scope: this report; vulture ledger or
reviewed genuinely dead identities only if the exact requested scan proves
repair necessary. No speculative source changes or new tests.

Ambiguity: dispatch requests CI repair but issue acceptance requires a long
soak of an exact promotion RC. These are separate obligations; passing CI
will not be represented as release acceptance. Current job directory has no
check-*.log files at initial inspection; inspect the explicitly cited prior
failure instead. No merge conflict exists at the starting HEAD.

## Fresh deterministic results

- Exact dispatched vulture command passed: 1323 reviewed identities / 1323
  findings, zero unclassified or never-allowlist findings. No ledger repair is
  supported by current evidence; leave the ledger unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Cited prior `check-3.log` failed on 24 versus 21
  expected DDL calls; that failure does not reproduce at the assigned HEAD.
- Prior result artifact read: it reports BLOCKED, not release acceptance.

Progress: reported deterministic failure checked; no speculative repair justified.

- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed**, including real production rate-limit middleware instances,
  exact-artifact rejection at the CLI boundary and admission backpressure.
- `uv run python scripts/check-deployment-claims.py`: **passed**; this checks
  named component existence, not deployment behavior.
- `uv run python scripts/check-merge-markers.py`: **passed**.
- `uv run python scripts/check-backlog-consistency.py`: **passed**, 168 items.
- `git diff --check`: **passed**.

Progress: focused deterministic validation complete; no failing command found.
No tests added or changed, so no inventory delta is required.

## Architecture and reachable behavior

Read repository instructions, documentation authority map, accepted ADRs
081226-69ee (Graph/Node), 081626-f383 (Attempt fencing), and 085 (principal
limits), plus **Proposed**, not accepted, ADR-081 (deployment). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no new authority is introduced.
The fencing ADR explicitly does not define expiry takeover; this cannot be
inferred from an admission-only race. ADR-085 does not establish a shared
replica budget. Neither caveat is an acceptance waiver.

The production application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; each instance builds
an in-memory limiter (`api/rate_limit.py:94`). Executed tests at
`tests/test_soak_promotion_gates.py:439` exhaust one instance and obtain
`[200, 200, 429]` on the other with the same credential/client identity,
for both authenticated and unauthenticated variants. This is reachable local
enforcement, not a deployed soak or replica-selection non-bypass proof.

The old fence mismatch is already accounted for by three Gauntlet columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`, matching
production upgrade declarations at `src/maistro/persistence/pg_learnings.py:116–118`.
There is no reason to remove those expectations or weaken the test.

`deploy/docker-compose.prod.yml:10–12` calls itself a reference artifact whose
images must be pinned; it builds application replicas and requires an external
model gateway. No immutable promotion RC/configuration is designated by this
assignment. The supplied snapshot's latest issue comments report the previous
blocker, and PR #1672 remains a draft claim-stake, not RC selection evidence.

## Acceptance matrix

| # | Acceptance | Fresh evidence / disposition |
|---|---|---|
| 1 | Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:151–168` explicitly omits concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. Applicability needs the selected RC configuration. |
| 2 | Two application replicas | **UNVERIFIED this round**. Executed ASGI tests have two middleware instances, not two deployed RC replicas. The driver is explicitly a host-process preflight (`run_soak.py:730–741`). |
| 3 | Sustained saturation, queues, expiry/reclaim, retries, leaks | **UNVERIFIED**. No long soak executed; passing sampler/accounting unit tests do not establish these observations. |
| 4 | No duplicate physical work | **UNVERIFIED**. Profile lines 199–204 acknowledge that the schedule probe cancels its queued Run without execution; admission deduplication is not Attempt fencing or Goal reconciliation under load. |
| 5 | Concurrent security/degraded enforcement and replica non-bypass | **NOT PROVEN**. 66-test run verifies local 429 enforcement/backpressure; the production-middleware test above demonstrates additional allowance on replica selection. Full deployed security exercise remains unverified. |
| 6 | Complete telemetry and explicit thresholds | **UNVERIFIED at RC grade**. Profile lines 163–168 distinguish driver lag from application event-loop lag and identify missing worker/saturation/reclaim observations. |
| 7 | Active-work kill/restart drain/fencing/recovery | **UNVERIFIED**. Cleanup tests pass, but process rejoin/terminal row counts alone are not physical-work recovery proof. |
| 8 | Long-running exact RC/config soak | **BLOCKED**. `run_soak.py:730–741` always rejects exact-artifact equivalence; executed CLI tests at `test_soak_promotion_gates.py:103` reject even four-hour preflight evidence. Designated immutable artifact/configuration not supplied. |
| 9 | Findings filed/reclassified | **UNVERIFIED for final promotion**. Local finding recorded here; no new load run or external filing. GitHub mutations are prohibited. |
| 10 | Hash-bound machine/human evidence | **UNVERIFIED for RC**. Existing historical preflight bundles are not evidence for the current unselected RC; this report records only fresh deterministic validation. |

## Handoff

Only this report changed. No source, test, ledger, grant or gate changes;
no merge/conflict resolution necessary. No additional soak launched because
extending the known host-process emulator cannot satisfy the exact-artifact
criterion. Do not repeat CI-repair rounds on the stale check-3 failure without
new failing evidence.

**BLOCKED**: designate the immutable RC and normalized production configuration,
resolve the replica-budget acceptance discrepancy without introducing a second
authorization path, and supply a production-path workload/telemetry plan covering
the matrix gaps. Then execute and publish the required long-running soak;
code/runtime configuration changes require a new soak. This round does not
certify the accumulated branch diff or authorize integration.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC and acceptance prerequisites"}`.
Focused validation completed; assigned issue acceptance remains blocked.

