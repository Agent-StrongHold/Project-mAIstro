# Issue #860 repair checkpoint — c8284a80

## Frozen scope

Only issue #860, branch `auto-860`, starting at
`fc85736bbd69ec20fbf4d36d43d6d1aeacfc1b17`, base
`2154f845347c9541016288c760f8da3f5cd2e064`. Starting worktree clean.
No PR or remote mutations. Supplied dispatch snapshot is the sole issue list.

Repair targets: supplied `98a11313/check-3.log` schema-fence assertion and
exact vulture per-identity gate. Inspect only related schema implementation,
tests, soak driver/profile/promotion tests, relevant ADRs and CI configuration.
Potential edits are confined to those tests/implementation if reproduced,
`quality/vulture-baseline.json` if the exact scan requires reviewed amendments,
this checkpoint and an inventory note if test cases change.

Initial evidence: supplied failure reports 24 DDL statements against 21 expected.
Prior result reports BLOCKED, not exact-RC acceptance. No `check-*.log` files
were present in the current job directory at initial inspection.
Assumption: this writer round should repair reproducible CI failures, not
invent a release candidate or substitute a host preflight for production soak.

Fresh reproduction: exact vulture command passed (1323 reviewed identities /
1323 findings, zero unclassified/never-allowlist; scanner base `3c761d14db94`).
Schema tests passed: 37 passed, 6 skipped. Historical failure is already fixed:
`test_pg_learnings.py:175–177` includes the three Gauntlet audit columns.
No evidence-backed ledger or schema repair is needed. Inventory delta zero.

## Additional executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run python scripts/check-deployment-claims.py`: passed (named components
  exist; this is not evidence of a running deployment).
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified /
  19 discovered lifecycles.
- `git diff --check`: passed.

Exact vulture arguments match `.github/workflows/vulture-ratchet.yml:82–85`.
Supplied develop base resolves locally; no merge conflict exists to repair.

## Architecture and reachable behavior

Read AGENTS.md, documentation authority map, accepted ADR-085,
ADR-081226-a66b and ADR-081626-f383, and proposed ADR-081. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. Physical fencing is not admission
uniqueness, and proposed topology text cannot waive acceptance. No competing
scheduler, execution, persistence or authorization authority was introduced.

`packages/maistro-server/src/maistro_server/main.py:648` installs the production
rate middleware. Its constructor (`api/rate_limit.py:90–98`) creates its own
InMemoryRateLimiter. Executed regression
`tests/test_soak_promotion_gates.py:439–487` obtains [200,200,429] separately
on two instances for the same authenticated or unauthenticated identity.
This is negative cluster-budget evidence, not deployed security proof.
`BACKLOG.md:267–279` already records this as engine-116, with a specification
decision outstanding. No new authorization path or guessed shared-store fix.

## Acceptance audit

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative RC workload | UNVERIFIED: inspected `docs/testing/soak/m3a-load-profile.md`, whose remaining-gaps section explicitly omits multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background traffic. |
| Two deployed application replicas | UNVERIFIED: executed ASGI instances are not deployed RC replicas. |
| Sustained saturation, queues, leases/reclaim, retries and leaks | UNVERIFIED: no sustained deployed load executed; six PostgreSQL-dependent schema tests skipped. |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED: `scripts/soak/run_soak.py:1067–1092` cancels the queued schedule probe without executing physical work. |
| Replica-selection non-bypass, security and degraded behavior | Negative evidence: executed middleware test demonstrates independent allowances; deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED: profile distinguishes driver/application loop lag and records missing worker/pool/lease and long-window observations. No new production telemetry. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED: no active Attempt restart experiment performed. |
| Long soak of exact RC/configuration | UNVERIFIED: `scripts/soak/run_soak.py:744–755` rejects host preflight unconditionally. Executed gate tests reject even four-hour preflight; no designated immutable promotion artifact/configuration was exercised. |
| Findings classified before promotion | Partial: engine-116 records the budget gap, and backlog validation passed. Completeness for a new RC soak UNVERIFIED. |
| Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED: this checkpoint is local validation metadata, not an RC production evidence pack. |

## Disposition

BLOCKED. Historical schema failure is already fixed and the exact debt ledger
matches the scan. No speculative code, test or ledger changes were made; only
this checkpoint changes. No test additions, inventory delta zero. No full-tree
pytest, live database or production soak was run. No GitHub mutations.

Next requires the designated immutable RC image/configuration, the canonical
cluster-budget specification decision, representative production traffic, and
at least four hours of exact-artifact load including physical Attempt recovery
and full telemetry. Repeating this stale CI repair cannot supply those missing
prerequisites. Existing branch work preserved; local commit is a handoff, not
integration approval.

Progress: checked 1 issue, done 1 local validation/handoff, skipped 0 issues,
errors 0 validation commands; acceptance complete 0. Next: production acceptance
work described above.
