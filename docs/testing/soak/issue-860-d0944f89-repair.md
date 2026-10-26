# Issue #860 — bounded repair d0944f89

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `38e40b0167ef7f8ad44906862369e57b2ec0c099`, supplied base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Worktree was clean; no incoming edits to salvage.
- Evidence: supplied dispatch-context.json, prior f719f7b5 result and
  98a11313/check-3.log. The current job directory contained no check-*.log.
- Repair candidates frozen to `quality/vulture-baseline.json` (only actual
  scanner findings), `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  (reported schema-fence failure), and this report / corresponding inventory
  note if tests change. Read adjacent production, tests and ADRs; do not expand
  into other issues or mutate GitHub.
- Ambiguity: supplied failure is historical, while the previous result reports
  successful checks and blocked promotion. Reproduce before changing code.

## Initial evidence

The supplied historical log fails the schema-fence test with 24 actual DDL
statements versus 21 expected. This is not yet evidence of a current failure.
The supplied previous result leaves all production soak criteria unproven and
reports replica-local rate limiting. Those claims require fresh validation.

## Reproduction results

- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The historical failure does not reproduce: the
  independent expected DDL list now contains all three validation-audit columns.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1322 reviewed identities / 1322 findings, zero unclassified and zero
  never-allowlist. No ledger change is justified by the executed scanner.

## Architecture and acceptance validation

Read repository `AGENTS.md`, the load profile, and accepted ADR-081226-a66b,
ADR-081426-1f7c, ADR-081626-f383 and ADR-085. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt authority. Lease-expiry takeover is
explicitly outside ADR-081626-f383's current contract: this issue cannot invent
a second reclaim authority. ADR-085 principal keying does not establish shared
replica budgets; local enforcement cannot satisfy the stronger #860 guarantee.

Additional commands (1200-second command timeout):

| Command | Fresh result |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files already formatted |

The requested vulture command matches `.github/workflows/vulture-ratchet.yml:82`.
No code/test edits made and no test inventory delta introduced. No live
PostgreSQL concurrency tests or deployed RC soak executed; skipped tests and
synthetic four-hour evidence must not be counted as such.

| Acceptance criterion | Executed evidence / status |
| --- | --- |
| Representative release-candidate load profile | UNVERIFIED. `m3a-load-profile.md:169` explicitly leaves multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads incomplete. |
| At least two deployed application replicas | UNVERIFIED. Executed tests use two ASGI instances, not deployed RC replicas. |
| Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED. Unit tests do not establish sustained production behavior. |
| No duplicate physical work across replicas | UNVERIFIED. Admission probe tests validate observed receipt identities, not physical Attempt execution uniqueness. |
| Replica-selection-resistant rate/security/degraded behavior | NOT SATISFIED at the production middleware seam: `tests/test_soak_promotion_gates.py:439` passed for authenticated and unauthenticated identities, observing `[200, 200, 429]` independently per replica. `api/rate_limit.py:93` constructs separate local limiters; `main.py:648` installs the middleware in production. Other deployed security/degraded behavior remains UNVERIFIED. |
| Complete telemetry with thresholds | UNVERIFIED. No fresh deployed PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry; driver-loop latency is not application-loop latency. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. No active-work deployed restart executed. |
| Long exact-RC artifact/configuration soak | UNVERIFIED. `scripts/soak/run_soak.py:744` rejects artifact equivalence. Executed CLI tests at `tests/test_soak_promotion_gates.py:106` fail closed for missing/null/preflight artifact records, even with synthetic four-hour duration. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness; independent replica allowances remain an enforcement prerequisite, not a throughput optimization. No GitHub mutations permitted or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak. This handoff identifies source validation only, not promoted-image provenance. |

## Disposition and next action

**BLOCKED.** Both supplied CI repair targets pass at the assigned HEAD. No
actual unbanked identity exists to review/amend and the historical schema test
already includes the missing columns. Editing either would be speculative.
Only this validation handoff changed; no source, tests, ledger or grants changed.
No develop-sync conflict exists, so no merge was attempted.

The previous promotion block remains: settle the RC workload and immutable
artifact/configuration, resolve replica-independent enforcement through existing
seams, then execute the long supported-topology soak with complete physical-work
and telemetry observations. Repeating a host-process preflight cannot establish
exact artifact equivalence. Keep fail-closed promotion checks intact. This local
commit is not integration approval.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next: production RC prerequisites and execution above.
