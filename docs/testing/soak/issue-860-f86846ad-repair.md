# Issue #860 — repair checkpoint (f86846ad)

## Frozen scope

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting
HEAD `7b42956d000be01d21a8e12a866af291b2cd50c3`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
The supplied dispatch snapshot is the only issue/PR source; no GitHub mutations.

Candidate edits are this report and `quality/vulture-baseline.json` only if the
requested scan identifies a real discrepancy. Validation is limited to
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`tests/test_prod_stack_boot_contract.py`, core `pg_learnings.py` and its adjacent
tests, server task admission/rate middleware and adjacent backpressure tests.
Repository instructions, relevant ADRs, production topology, and the existing
load profile provide read-only architecture context. No other issues or PRs
will be repaired.

## Initial evidence

Writer/repair role assumed from the lane assignment. No `check-*.log` files
were supplied in this job directory. Read the explicitly supplied historical
`98a11313167b41a98a420abfda80c292/check-3.log`: it failed the schema-fence test
with 24 statements versus 21 expected. That is a hypothesis to reproduce,
not permission to change a test or gate.

Fresh command (1200-second timeout):

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

PASS: 1322 findings / 1322 reviewed identities, zero unclassified and zero
never-allowlist findings. The gate resolved comparison base `321cbdb8fe9b`;
this is not the supplied lane base. No ledger change is justified by this scan.

## Fresh validation

All commands below used 1200-second timeouts:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **118 passed, 6 skipped**. Integration skips are not live PostgreSQL evidence.
  The historical schema-fence failure does not reproduce; the current independent
  expected-DDL list already includes the three validation audit columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:174–176`.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: **PASS**, 17 suites,
  31323 unique test identities, no duplicated evidence.

No test or runtime change was made, so no inventory delta is warranted. Only
this report changed. Passing checks do not establish production-soak acceptance.

## Production behavior and ADR reconciliation

Read repository instructions, the documentation authority map, accepted ADR-085
and ADR-081626-f383, production Compose, the existing load profile, and adjacent
production/test code. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The canonical Run store owns execution fences; ADR-081626-f383 explicitly does
not define lease-expiry takeover. Admission identity counts cannot substitute
for physical-work uniqueness, reclaim, or recovery evidence. No new execution,
event, Goal, scheduling, or authorization authority was introduced.

ADR-085 requires principal-keyed rate limiting. Current middleware explicitly
implements process-local budgets (`api/rate_limit.py:93` constructs the limiter).
Freshly executed `tests/test_soak_promotion_gates.py:439` uses that production
middleware and gets `[200, 200, 429]` independently from both instances for the
same identity, for authenticated and unauthenticated requests. This is meaningful
negative evidence for the replica-selection criterion, not a deployed soak.
Changing that contract is not an evidence-based vulture repair.

Freshly executed `tests/test_soak_promotion_gates.py:564` reaches the production
task router through two queues sharing one canonical admission spine: the local
receipt reads 200 and the peer reads 404. This agrees with the local queue lookup
in `packages/maistro-server/src/maistro_server/api/tasks.py:144`.

`scripts/soak/run_soak.py:744` marks the host-process preflight as not the exact
production Compose artifact. The executed CLI regression at
`tests/test_soak_promotion_gates.py:99` rejects missing/null/preflight identity
even with synthetic four-hour evidence. Running that emulator longer cannot
satisfy artifact equivalence. The production Compose is a reference build,
not a designated immutable RC in this assignment; no promoted digest/configuration
has been supplied. Do not remove the artifact gate to manufacture acceptance.

## Acceptance audit

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Existing profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas, and Goal/background workloads; no selected-RC applicability decision supplied. |
| At least two deployed application replicas | UNVERIFIED. Compose declares two, but this round executed ASGI instances, not a deployed production topology. |
| Sustained saturation, queue growth, reclaim, retries, memory/descriptor/process leaks and restart | UNVERIFIED. No sustained production load executed; sampler tests are not a leak-free-soak proof. |
| No duplicated physical work across schedules/tasks/Runs/Attempts/Goal reconciliation | UNVERIFIED. No physical-work accounting under production concurrency performed; admission assertions are insufficient. |
| Replica-resistant rate/security/degraded behavior | NOT PROVEN. Fresh production-middleware tests reproduce independent replica allowances; production-router receipt test reproduces peer 404. Backpressure tests pass, but deployed concurrent security/degraded behavior remains UNVERIFIED. |
| PostgreSQL, application-loop, process/RSS/FD, queue/error/timeout telemetry with thresholds | UNVERIFIED. No fresh production metric series. Driver-loop and sampler tests do not establish application-loop health or pool saturation. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No production active-work kill/restart executed. |
| Long soak of exact RC/configuration; rerun after changes | UNVERIFIED. No selected immutable RC was run; current runner explicitly fails artifact equivalence. Profile requires at least four hours. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completion. This local report records blockers; no completed representative run or classification audit, and no GitHub mutations. |
| Machine/human evidence tied to exact image/package/commit/config hashes | UNVERIFIED. This source-head check report is not a production soak evidence pack. |

## Disposition

**BLOCKED**, not merge-ready. The requested vulture mismatch and historical
schema assertion failure do not reproduce. No ledger amendment or speculative
runtime edit is warranted. The prior production acceptance block remains;
this commit is a handoff, not a completed repair or release approval.

Next action requires a designated immutable RC/configuration, a representative
canonical-runtime workload and production telemetry, resolution of the observed
replica allowance/receipt behavior, and an exact-artifact long soak with active
work restart and physical-work accounting. Repeating the stale check-3/vulture
repair dispatch alone cannot supply these missing inputs or evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
errors 0 in executed checks; 6 integration cases skipped. No refetch, merge,
push, or GitHub mutation performed.
