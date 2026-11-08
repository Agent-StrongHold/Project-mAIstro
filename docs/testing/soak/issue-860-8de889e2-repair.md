# Issue #860 bounded repair — 8de889e2

## Frozen scope

- Assigned issue only: #860; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `94670cdbe69bc3709f93133002cf1893ab0c7d10`.
- Supplied comparison base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Process the supplied schema-fence failure and exact vulture ledger gate, then
  validate the issue's soak acceptance. No GitHub mutations or unrelated repairs.
- Candidate repair files frozen to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production module `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` only if the specified scan demonstrates debt,
  an inventory note if tests change, and this report.
- Adjacent inspection: repository instructions, supplied dispatch snapshot/prior
  result/log, applicable ADRs, soak runner/profile/promotion tests and CI gates.

## Initial evidence

The supplied previous `check-3.log` failed the schema-fence test with 24 observed
DDL calls versus 21 expected. This is historical evidence, not a fresh failure.
The supplied prior result is BLOCKED for missing exact-RC production soak evidence.
No `check-*.log` files were present in this job directory at initial inspection.
The broad supplied-base diff includes unrelated histories; this round will not
attempt to rewrite them or claim they were reviewed.

## Results

Fresh exact vulture scan passed: 1,323 reviewed identities/findings, zero
unclassified or never-allowlist identities; gate-selected base `3c761d14db94`.
No ledger amendment is warranted. Fresh schema tests passed: 37 passed, 6 skipped
(1.49 seconds). The expected DDL already includes the three audit columns at
lines 175–177; the supplied historical failure does not reproduce. No production
or test repair is justified by these checks.

Ambiguity resolved: CI repair is actionable only on fresh defects; passing unit
checks do not prove production soak acceptance. Continue with bounded acceptance
review, without inventing an RC artifact or treating a host preflight as a soak.

Fresh validation (600-second timeout for initial checks, 1,200 seconds for the
remaining battery):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS as above; exact CI scan arguments.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. No live PostgreSQL evidence claimed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: 81 passed (2.40 seconds).
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2,706 Markdown files, no broken relative links.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

The executed middleware regression at `tests/test_soak_promotion_gates.py:439`
reproduces an independent 200/200/429 allowance on each of two instances for the
same identity. This demonstrates local enforcement, not a shared replica budget.
The executed promotion regression rejects even a four-hour host preflight;
`scripts/soak/run_soak.py:744` explicitly reports artifact equivalence false.
These checks do not execute the production topology.

## Acceptance accounting

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED**. `m3a-load-profile.md` explicitly omits concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal/background reconciliation. No selected RC profile supplied or executed here. |
| At least two production application replicas | **UNVERIFIED**. `deploy/docker-compose.prod.yml` declares two replicas, but no production deployment was exercised. ASGI instances are not deployed replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/descriptor/process leaks, shutdown/restart | **UNVERIFIED**. No sustained production experiment executed. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. The documented schedule probe admits then cancels without physical execution; admission uniqueness is not physical-work fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent local allowances reproduced by the executed production-middleware regression. `api/rate_limit.py:94` constructs in-memory state, wired in `main.py:648`. Deployment-level security and degraded behavior remain **UNVERIFIED**; local enforcement does not prove non-bypass. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Profile distinguishes driver-loop lag from application-loop lag; required saturation/reclaim/long-window observations are missing. No qualifying measurements captured here. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. No active-work production recovery experiment executed. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**. Executed regression proves the existing runner refuses even four-hour preflight evidence; it does not prove an exact-RC soak. |
| Load findings filed/reclassified before promotion | Existing backlog consistency PASS; new load findings **UNVERIFIED**, as no load experiment ran. No GitHub mutation performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**. This report binds local checks to the starting commit, not to a selected immutable production artifact/configuration or production measurements. |

## Architectural reconciliation

Read repository instructions, documentation authority map, the supplied issue
body and prior evidence, relevant production wiring and adjacent tests, and
ADR-082826-b601, ADR-085 and ADR-081. Accepted ADR-082826-b601 requires the
canonical consumer and transition claim: preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; a soak must observe that execution,
not introduce another scheduler or claim mechanism. Accepted ADR-085 requires
principal-keyed rate limiting, but does not prove replica-shared enforcement.
ADR-081 is Proposed, not accepted authority. The shipped Compose reference still
claims two replicas and asks operators to pin image digests. Neither draft
architecture nor preflight success waives the issue's production evidence.

## Disposition and handoff

**BLOCKED** on production acceptance. Historical schema failure is already
resolved; exact vulture scan is clean. No production/test/ledger edit is supported
by fresh failure evidence. Only this report changes; no tests added, so no suite
inventory delta. No gates weakened, existing work discarded, or GitHub mutated.

Next requires a selected immutable RC image/configuration, representative workload
coverage and physical-work/recovery/telemetry oracles, resolution of the
replica-selection budget claim, and a qualifying production soak (profile minimum
four hours). Re-running host preflight longer cannot satisfy this. Historical
artifacts/comments were not treated as proof of current-HEAD acceptance.

Progress: checked 1 issue, acceptance-complete 0, skipped 0 issues, validation
errors 0. CI repair disposition complete (no defect reproduced); production
acceptance unresolved. This local commit is a writer handoff, not integration
approval.
