# Issue #860 — bounded repair 7156f247

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `c210cfa42ece4613e3b63da4c2040b7b2395fbcd`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree clean; no salvage required. No GitHub mutations.
- Inspect existing soak implementation/tests, relevant ADRs and CI scanner;
  modify only this report and `quality/vulture-baseline.json` if the authorized
  scan demonstrates reviewed retained debt. No speculative runtime changes.
- Validation scope: existing soak tests, focused package tests, ruff and relevant
  CI gates. No new tests planned; inventory remains unchanged.
- Current job directory contained no `check-*.log` at initial inspection.
  Prior result reports BLOCKED; this is not treated as fresh validation.

## Ambiguity / assumption

The brief requests both issue acceptance and a vulture CI repair. Treat these
as distinct: a passing scanner cannot certify a production soak. No exact RC
image/configuration or deployed target is identified in the assignment; do not
substitute a host-only harness for production acceptance.

## Progress

- Required vulture command executed successfully: 1322 findings match 1322
  reviewed identities, zero unclassified/never-allowlist entries. No ledger
  repair is justified. Output: `/tmp/860-7156-vulture.log`.
- Supplied historical `check-3.log` read: schema test expected 21 statements
  but observed 24. Fresh reproduction passes: 37 passed, 6 skipped. Current
  production and test schema include the additional audit columns.
- Existing ASGI tests explicitly distinguish local rate enforcement and local
  task receipts from cluster-wide semantics; they do not constitute a soak.

## Fresh validation

All commands used 1000–1200 second timeouts; all exited zero. Logs are local
validation artifacts, not a production evidence pack.

| Command | Outcome | Log under `/tmp/` |
|---|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1322 reviewed identities = 1322 findings; no repair needed | `860-7156-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; no live PostgreSQL proof | `860-7156-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed | `860-7156-soak.log` |
| `uv run ruff check .` | passed | `860-7156-ruff.log` |
| `uv run ruff format --check .` | 3301 files formatted | `860-7156-format.log` |
| `uv run python scripts/check-suite-inventory.py` | 17 suites, 31323 unique identities, no duplicates | `860-7156-inventory.log` |

No tests added/changed; no inventory note or baseline edit required. The
vulture invocation matches `.github/workflows/quality.yml:1079`. Its default
provenance reports base `321cbdb8fe9b`; this is not a claim that CI will select
the supplied dispatch base. No grants or ledgers were amended.

## Architecture reconciliation

Read repository instructions, documentation authority hierarchy, accepted
ADR-081226-a66b (logical lifecycle), ADR-081626-f383 (physical lease fencing),
ADR-082426-82c7 (occurrence admission), and proposed ADR-081 (deployment).
The canonical model remains `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Admission uniqueness is not physical-work uniqueness. The accepted fencing ADR
explicitly does not define automatic lease-expiry takeover; issue wording does
not authorize a new reclaim authority. The deployment proposal is not an
accepted waiver of the issue's exact-artifact requirement.

## Acceptance matrix

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` documents a single-key, degraded-provider preflight, with user/Workspace, fan-out, successful tool/model, Design/Canvas and background-worker gaps. |
| Two deployed application replicas | UNVERIFIED. Executed two-instance production-middleware/router ASGI probes, not a deployed exact-RC topology. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks | UNVERIFIED. No long production run executed; unit tests cannot establish these observations. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED. Existing admission probes do not execute the schedule probe's physical work or sustained Goal reconciliation. |
| Replica-resistant rate/security/degraded behavior | NOT PROVEN. Executed `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]` independently on each production limiter for the same identity. Backpressure test passes, but does not establish cluster-wide protection. |
| Production telemetry and explicit thresholds | UNVERIFIED. No fresh production time series. Driver-loop latency and a driver PostgreSQL probe are not application-loop/query/pool telemetry. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. No production restart performed. Process exit/rejoin alone cannot prove physical-work recovery. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` rejects host preflight artifact equivalence. Executed CLI tests verify rejection even for synthetic four-hour evidence. No immutable RC image/configuration supplied. |
| Findings classified at earliest broken invariant | UNVERIFIED. No fresh production campaign or complete disposition evidence; no GitHub writes performed. |
| Machine/human evidence bound to image/package/commit/config | UNVERIFIED. This report binds local checks only to the starting source commit, not to a promoted deployment. |

Production reachability: `api/rate_limit.py:93` constructs a limiter per
middleware instance; `api/tasks.py:144` reads the injected queue. Executed
`tests/test_soak_promotion_gates.py:564` uses the production router and shared
canonical admission, and observes own-replica 200 versus peer 404. These are
contract probes, not live load evidence or license to replace canonical owners.

## Handoff

**BLOCKED.** Historical schema failure and requested vulture debt are not
present at this head. No speculative repair, test weakening or cosmetic ledger
amendment was made. Only this report changed. No merge conflict exists, so the
conditional develop-sync instruction was not applicable.

Next: supply/select the immutable RC artifact and production configuration;
resolve representative-workload coverage and replica-budget/receipt semantics
with their canonical owners; run the long production soak with physical work,
telemetry and restart/recovery, and publish hash-bound evidence. Another green
unit run or a longer host emulator run cannot remove this blocker.

Progress: checked 1 issue, done 0 issue acceptances, skipped 0 issues,
validation errors 0. Local validation/handoff completed; all production-grade
acceptance criteria remain unproven. Commit this report locally; no integration
approval or issue closure is implied.
