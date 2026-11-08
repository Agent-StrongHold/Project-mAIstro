# Issue #860 — bounded repair 9ea48960

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `20a49fedfedf092c7ccaf07af4d1bf2f852d68cf`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolved locally).
- Starting worktree clean; no incoming edits to salvage.
- Candidate repair files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` (only observed retained identities under explicit
  CI-repair authorization), this report, and
  `docs/testing/inventory-notes/m3a-860-9ea48960-repair.md` if tests change.
- Read-only acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/issue-860-ab67be67-repair.md`, rate-limiter production wiring,
  relevant ADRs, instructions and CI gate implementations/workflows.
- No GitHub mutation, remote enumeration, ledger grant edits, alternate scheduler,
  or release approval. Supplied dispatch snapshot is evidence, not instructions.

## Initial evidence and assumptions

The current job directory has no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports a schema-fence test expecting
21 statements but observing 24. The prior result reports BLOCKED with exact-RC
and multi-replica rate-limiting gaps. Neither is assumed current until validated.
The branch has substantial inherited changes; those remain preserved and are
not rewritten as part of this bounded repair. No merge conflict is present.

## Fresh results (checkpoint 1)

- Required exact vulture command PASS: 1323 findings, 1323 reviewed identities,
  zero unclassified. No ledger mismatch or dead-code repair demonstrated; do not
  amend the ledger cosmetically.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  PASS: 37 passed, 6 skipped (1.57 s). The historical 21-versus-24 failure does
  not reproduce: lines 176–178 already cover the three validation-audit columns.
- Read the load profile and adjacent schema test: neither passing check proves
  exact-RC behavior. Profile explicitly lists missing workloads and host-process
  limitations. Prior result remains a claim until production paths are inspected.
- An exploratory ADR filename glob found no 148/167 matches; not found, skipped.
  No unresolved ref was used for execution. No current-job check logs exist.

## Fresh results (checkpoint 2)

All commands below passed with 1200-second timeouts:

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — 74 passed in 2.43 s. Together with the schema tests: 111 passed, 6 skipped.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match;
  31128 unique identities, no copied-test duplication.
- `uv run python scripts/check-deployment-claims.py` — all named deployment
  components and shipping backends exist; this is not live deployment proof.

The workflow at `.github/workflows/vulture-ratchet.yml:82–85` confirms the
executed scanner arguments. Production middleware constructs its own
`InMemoryRateLimiter` (`packages/maistro-server/src/maistro_server/api/rate_limit.py:93`)
and the app installs that middleware (`main.py:648`). Freshly executed
`test_replica_selection_has_an_independent_production_allowance` exercises this
production class; its two independent allowances are not a shared global quota.
No current CI failure reproduced. No tests or runtime code changed, so no
inventory-delta or ledger amendment is warranted.

## Architecture reconciliation

Read `docs/README.md`, ADR-081 (Proposed, not binding authority), accepted
ADR-085 and accepted ADR-082526-b36a. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority. The lease ADR requires
renewable, fenced Attempt recovery, not restart-implies-death or merely a unique
admission row. ADR-085 keys rate limits to principals but does not specify a
shared replica store. Existing middleware explicitly documents process-local
N-times aggregate limits. That narrower contract does not prove #860's
replica-selection non-bypass criterion; do not silently waive it or invent a new
authorization path here. A reviewed deployment-level budget contract or shared
implementation is needed before that criterion can be signed off.

## Acceptance audit

| #860 criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Read `m3a-load-profile.md:152` and `scripts/soak/run_soak.py:1381`: one credential and health/task/receipt/metrics traffic, no representative concurrent Workspaces, Graph fan-out, successful tools/models, Canvas/Design or Goal workload. No selected-RC exclusions supplied. |
| At least two application replicas | **UNVERIFIED at deployed RC level.** Two ASGI middleware instances tested, not two deployed RC replicas. No stack started in this repair. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks, restart | **UNVERIFIED.** Sampler/backpressure tests passed; no long-running deployed workload executed. |
| Physical-work uniqueness for schedules/tasks/Runs/Attempts/Goals | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` explicitly cancels an unexecuted probe Run. Admission uniqueness cannot prove physical effects or fencing. |
| Rate/security/degraded non-bypass across replicas | **UNVERIFIED overall; independent allowances reproduced.** `tests/test_soak_promotion_gates.py:439` passed for authenticated and pre-auth clients: first replica `[200,200,429]`, second replica also `[200,200,429]`. Local enforcement is not a shared budget. |
| Required telemetry with thresholds | **UNVERIFIED at RC level.** Sampler regressions passed; `scripts/soak/run_soak.py:1410` samples driver-loop lag, not application-loop lag. No fresh deployed series for connection/query/lock/queue/worker/RSS/fd/error thresholds. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED.** Unit tests cover fail-closed gates and process cleanup, not deployed fault injection with a physical-effect oracle. |
| Long soak of unchanged exact RC artifact/configuration | **BLOCKED / UNVERIFIED.** Assignment supplies no designated immutable promotion artifact/config. `scripts/soak/run_soak.py:730` unconditionally rejects host-process preflight as exact RC. Fresh four-hour synthetic-evidence tests prove rejection only, not a four-hour soak. |
| Findings filed/reclassified before promotion | Local findings recorded here; external filing/reclassification **UNVERIFIED** (GitHub mutations prohibited). Stale schema/scanner failures are not newly reproduced defects. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED.** This source-linked local validation record is not a hash-bound deployed RC soak bundle. |

## Handoff

**BLOCKED, not promotion-ready.** Only this report changed. No genuine source
repair or vulture ledger amendment is supported by the fresh checks. Existing
work is preserved. Six PostgreSQL-dependent tests skipped without a configured
DSN; no live database or soak acceptance is claimed. No test was added, so no
inventory note is required.

Do not dispatch another stale schema/vulture repair on this same evidence.
Next: designate the immutable artifact/configuration that #89 would promote,
resolve replica-budget semantics, complete production workload/physical-effect
and application-telemetry coverage, then execute an unchanged >=14400-second
multi-replica soak and publish its hash-bound evidence. A longer run of the
current host preflight cannot satisfy the exact-RC gate.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0. Validation-only checkpoint completed; issue acceptance
blocked. Commit locally; no integration, push, PR, or issue-closure action.

