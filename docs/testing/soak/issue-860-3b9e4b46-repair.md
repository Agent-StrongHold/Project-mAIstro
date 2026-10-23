# Issue #860 — repair snapshot (job 3b9e4b46)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `93fda869c23a7c217fe6972a10802f428a8db211`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree was clean; no incoming uncommitted work to salvage.
- Inspect the supplied dispatch snapshot, repository instructions and relevant ADRs.
- Process the reported schema-fence regression in
  `packages/maistro-core/tests/persistence/test_pg_learnings.py` against
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`.
- Run the requested exact vulture gate; review only its actual findings, with
  `quality/vulture-baseline.json` amendments only if warranted by this CI repair.
- Validate existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and the adjacent server backpressure test.
- Allowed repair documentation: this report and an inventory note if tests change.
  No unrelated implementation, remote mutations, or historical branch cleanup.

## Initial evidence and assumptions

The supplied prior `check-3.log` reports 24 schema statements versus 21 expected.
The immediately preceding result reports BLOCKED, not a merge conflict. No
`check-*.log` files were present in the current job directory at initial snapshot.
The schema failure may already be repaired; reproduce before editing. The exact
RC artifact/configuration is not designated in the dispatch acceptance body;
local harness validation must not be presented as a qualifying RC soak.

## Fresh validation

All commands below ran in the assigned worktree with 1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | Exit 0; 256 packages resolved, 214 checked |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1323 reviewed identities / 1323 findings; zero unclassified; gate-selected base `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; no live PostgreSQL evidence |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3270 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | 17 suites match; 31128 unique identities; zero duplicate evidence |

The reported failure is stale: the current independent DDL expectation already
includes all three Gauntlet audit columns at `test_pg_learnings.py:173–178`.
The production method takes the advisory transaction lock before those upgrades.
No current vulture findings require repair or banking; no ledger was amended.
No tests were added or changed (inventory delta zero).

## Acceptance disposition: BLOCKED

| Issue criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`; its remaining-profile section explicitly omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker traffic. No designated RC configuration justifies their exclusion. |
| At least two application replicas | UNVERIFIED for deployed RC. The executed middleware tests instantiate two ASGI apps, not two promoted application images. |
| Sustained saturation, queue growth, lease reclaim, retries and leaks | UNVERIFIED. Sampler tests exercise real child memory/descriptor growth and incomplete measurements, but no long RC load was run. |
| No duplicate physical work across replicas | UNVERIFIED. Task probe tests reject absent/duplicate receipt identities, but receipt identity is not a physical-work witness. `run_soak.py:1044` cancels the schedule probe Run without execution. |
| Rate/security/degraded non-bypass | UNVERIFIED at deployment grade. Executed `test_replica_selection_has_an_independent_production_allowance` at `tests/test_soak_promotion_gates.py:439`: the same identity gets `[200, 200, 429]` on each replica. Local enforcement does not prove the stronger non-bypass claim. The server router test proves 202/429/Retry-After and admission after releasing a slot, not recovery. |
| Complete telemetry and thresholds | UNVERIFIED. `run_soak.py:1410` measures the driver's event-loop lag; profile acknowledges missing application-loop/worker and long-window observations. No fresh RC telemetry was captured. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED. Boot-cleanup tests pass but do not kill a deployed replica during physical work. |
| Long soak of exact RC artifact/configuration | BLOCKED / UNVERIFIED. Dispatch does not designate immutable RC artifacts/configuration. `run_soak.py:1552` always emits the failing preflight-artifact check from line 730. Executed synthetic four-hour CLI tests establish fail-closed behavior, not four hours of traffic. |
| Findings filed/reclassified before promotion | Local evidence and gaps recorded here. External filing/reclassification UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence bound to exact hashes | UNVERIFIED. This report identifies the tested source HEAD but is not a machine-readable deployed RC soak artifact. |

## Architecture and reconciliation

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no execution authority,
scheduler, event authority or authorization path was changed. Renewal/reclaim
in ADR-082526-b36a extends the older fencing ADR's explicit deferral; the deferral
cannot waive the issue's recovery validation requirement.

Production `maistro_server/main.py:648` installs `RateLimitMiddleware`;
`api/rate_limit.py:93` allocates its process-local limiter. The module documents
N-times aggregate allowance. ADR-085 requires per-principal enforcement but does
not establish that this process-local implementation proves #860's stronger
replica-selection claim. Record the discrepancy rather than introduce an
unassigned distributed limiter or silently waive acceptance.

## Handoff

Only this report changed; existing branch work was preserved. No current scanner
or schema regression was found, so there is no evidence-backed code/ledger fix to
make. The prior supplied failure must not be treated as a current failing check.
No merge conflict exists; no merge, push or remote mutation was performed.

Next prerequisites: designate immutable RC images and runtime configuration;
resolve workload applicability and rate-policy discrepancy; execute the exact
multi-replica topology with physical-work witnesses, full telemetry, active-work
recovery and at least four sustained hours. A longer host preflight is not a
substitute. Historical branch changes outside this frozen repair scope were not
revalidated; passing focused checks do not approve integration.

Progress: checked 1 issue, done 0 (release acceptance blocked), skipped 0,
validation errors 0. This local documentation commit is a handoff only.
