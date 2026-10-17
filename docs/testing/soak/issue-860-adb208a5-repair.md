# Issue #860 — bounded CI repair adb208a5

## Frozen scope

- Sole issue: #860; branch/worktree: `auto-860`, `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `ef95a0b32a3de1ee183afe59cb0f930d3225a475` (verified clean).
- Supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Evidence snapshot: supplied `dispatch-context.json`, previous result
  `bcca9833499f4c488bf9d4a1c9cf206a/result.json`, historical
  `98a11313167b41a98a420abfda80c292/check-3.log`.
- Repair targets: existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, their existing inventory notes,
  `quality/vulture-baseline.json` only if exact scanner evidence requires it,
  and this report. Production dependencies are read-only inspection targets.
- No PR or issue enumeration/fetch; no GitHub mutations. Prior changes preserved.

## Initial observations / assumptions

No `check-*.log` files were present in this job directory at initial listing.
The prior result reports BLOCKED, not a develop-sync conflict. Do not infer an
unbanked vulture identity or alter a ledger without a fresh scanner result.
The supplied issue requires actual designated-RC soak evidence; passing local
regression tests cannot substitute for deployment, telemetry, or duration.

## Fresh validation checkpoint

- Exact mandated Vulture scan: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified or forbidden. Checker selected base `4aa68edc0b6b`.
  No scanner evidence justifies a ledger amendment.
- `uv sync --locked --extra dev`: PASS, 214 installed packages checked.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`:
  **103 passed, 6 skipped in 2.91s**. Live-PostgreSQL cases require
  `MAISTRO_TEST_PG_DSN`; not run in this command.
- Read the historical `check-3.log`: expected 21 DDL statements, observed 24.
  The current independent expected-DDL list explicitly includes the three
  validation-audit columns. Fresh execution does not reproduce that failure.
- Both existing production-middleware replica-selection tests ran: each replica
  accepts two requests before 429 for the same identity. This is evidence of
  multiplied local allowances, not proof of a shared cluster-wide budget.

## Remaining executed checks

All validation ran locally with 1200–1800 second timeouts; outputs are retained
in the job session trace.

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 31128 unique identities, zero duplicates |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence, not deployed operation |

The exact Vulture command was `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, matching
`.github/workflows/quality.yml:1078–1081`. The passing invocation did not use
an explicit dispatch-base override; its selected base is recorded above.

## Architecture and production reachability

Read repository instructions, documentation authority map, accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. Also read
ADR-081: its status is **Proposed**, not an accepted override of the issue.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. An admission identity
is not a physical-work witness. Reclamation requires expired unrenewed leases,
not an inference that another holder died because a replica restarted.

`packages/maistro-server/src/maistro_server/main.py:648` installs the tested
production `RateLimitMiddleware`; its constructor at `api/rate_limit.py:93`
creates an `InMemoryRateLimiter` per instance. Its documented N-times local
allowance is narrower than #860's replica-selection non-bypass requirement.
ADR-085's principal keying does not prove shared cross-replica enforcement.
This discrepancy is recorded, not waived or repaired with a competing
security path in this CI lane.

The current schema test at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:162–194` lists
24 DDL operations independently. Production
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216` takes
the schema advisory lock inside the transaction. The old 21-versus-24 mismatch
is already reconciled; changing it again would not address an actual failure.

## Acceptance assessment (all ten issue criteria)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative release-candidate load profile | **UNVERIFIED**. Read `m3a-load-profile.md:151–170`: concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background work remain gaps. No designated-RC applicability demonstrated. |
| At least two application replicas | **UNVERIFIED for deployed RC**. Read `deploy/docker-compose.prod.yml:26–78`, which declares two replicas. ASGI middleware tests use two instances, not deployed applications. |
| Sustained saturation, queue/reclaim/retry, memory/descriptor/process leak observation | **UNVERIFIED**. A 2.91-second test run and sampler regression are not long-window load evidence. No soak or new telemetry series ran. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED**. `m3a-load-profile.md:193–203` explicitly limits the schedule probe to admission and cancels its Run before execution. Gate regression tests do not prove physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**. Executed `tests/test_soak_promotion_gates.py:439–489` in both identity variants; each replica independently returns `[200, 200, 429]`. This reproduces aggregate allowance multiplication via production middleware, not a full deployed-security experiment. |
| Complete PostgreSQL/application-loop/worker/RSS/descriptor/queue/error telemetry with thresholds | **UNVERIFIED for RC**. Profile thresholds exist; sampler tests execute. No complete observed RC series or application-loop/pool-saturation proof produced. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED**. Boot-cleanup and gate regressions ran, but no active-work fault injection or physical recovery witness ran. |
| Long exact-RC/configuration soak, repeated after changes | **UNVERIFIED / BLOCKED**. Assignment designates a source head, not an immutable promotion image/configuration. `scripts/soak/run_soak.py:730–741` explicitly rejects its host-process topology as exact-RC evidence; executed CLI tests retain this boundary even at four hours. |
| Findings filed/reclassified before promotion | Local disposition recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. Existing rate-limit discrepancy belongs before M3 promotion, not a performance optimization. |
| Machine/human evidence bound to exact artifact/config hashes | **UNVERIFIED for RC**. This source-bound check record is not a promotion evidence bundle. Historical bundles were not recertified. |

## Final disposition / handoff

**BLOCKED** on release evidence, not on a reproduced Vulture or schema-test
failure. Only this report changed. No production code, tests, inventory,
ledger, grants or gates changed; no new test inventory delta is needed.
Existing changes are preserved. No fetch/merge was needed: this was not a sync
conflict. Local commit is a checkpoint, never integration approval.

Next: release owner must designate immutable RC image/configuration and
representative workload applicability; resolve the observed replica-budget
contract discrepancy through existing enforcement; implement missing
production-path physical-work/telemetry witnesses; execute the long soak and
publish its hash-bound evidence. Repeating an identical ledger repair cannot
supply these prerequisites. The inherited 427-file diff remains outside this
bounded repair's integration certification.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate RC and resolve production-soak prerequisites"}`.

