# Issue #860 — bounded repair validation (job 3d741e30)

## Frozen scope

- Assigned issue only: #860; branch `auto-860`; clean starting HEAD
  `2ea6231dd606d5e1c0c4d5c9d977f7fd222cf528` verified locally.
- Supplied base resolves to `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Inputs: supplied dispatch-context.json, prior b008df32 result, and
  98a11313/check-3.log. No check-*.log files supplied in this job directory.
- Validation targets: scripts/soak/run_soak.py, tests/test_soak_promotion_gates.py,
  packages/maistro-core/{src/maistro/persistence/pg_learnings.py,tests/persistence/test_pg_learnings.py},
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py,
  and exact vulture gate. Ledger edits only if fresh scan supplies evidence.
- Planned edit surface: this report; conditional evidence-based repair to the
  targets above and corresponding inventory note if tests change.
- No remote mutations, branch sync, or unrelated repairs. The starting tree has
  no uncommitted salvage and no merge conflict.

## Initial evidence / ambiguity

The supplied failure reports 24 schema statements versus 21 expected statements.
The prior result claims this is already fixed, but that claim is not validation.
The issue requires an exact designated RC artifact/configuration. The dispatch
assigns a source head, not an artifact or production configuration. Proceed by
checking local acceptance coverage, without inventing an RC designation.

## Executed validation

- Exact requested vulture command: **PASS**, 1323 findings / 1323 reviewed
  identities, zero unclassified and never-allowlist findings. Gate reports base
  `4aa68edc0b6b`; no ledger amendment is justified by current scanner output.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **103 passed, 6 skipped**, 2.48 seconds. No live DB acceptance inferred from skips.
- Logs: `/tmp/860-3d741e30-vulture.log`, `/tmp/860-3d741e30-pytest.log`.

The supplied schema failure does not reproduce: the current expectation includes
all three Gauntlet columns at test_pg_learnings.py:171–175, matching production
pg_learnings.py:116–118. No test change or inventory delta is needed.

Read AGENTS.md, docs/README.md, accepted ADR-081226-69ee, ADR-081626-f383,
ADR-085, and proposed ADR-081. The accepted execution lease contract explicitly
excludes expiry takeover; issue wording cannot authorize a competing reclaim
scheduler. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. ADR-085's
principal-keyed limit does not itself prove a shared multi-replica allowance.

- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: **PASS** (existence gate,
  not a deployed topology test).
- `uv run python scripts/check-merge-markers.py`: **PASS**.
- `uv run python scripts/check-backlog-consistency.py`: **PASS**, 168 items.

## Reachable behavior and acceptance

Production installs RateLimitMiddleware at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates
an InMemoryRateLimiter at `api/rate_limit.py:93`. The freshly executed
`tests/test_soak_promotion_gates.py:439` test exercises two production middleware
instances with the same IP/credential: each independently returns 200, 200, 429;
the first stays exhausted while the second accepts. This is meaningful evidence
of independent allowances, not evidence of deployed cluster-wide enforcement.
The module documents that scope explicitly; changing the security contract is
not a justified response to a stale schema-fence failure.

`scripts/soak/run_soak.py:730` returns `exact_rc_artifact.ok=false`, and the run
uses it at line 1552. The CLI tests at test_soak_promotion_gates.py:103 demonstrate
that missing/null/preflight artifact evidence fails even with synthetic four-hour
duration. `deploy/docker-compose.prod.yml:10–12` calls itself a reference and
requires production digest pinning. A source head is not an immutable promoted
image/configuration selection. The artifact ambiguity remains **UNRESOLVED**.

| Issue acceptance criterion | Evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. m3a-load-profile.md:151–168 records missing concurrent Workspace/users, Graph fan-out, successful tools/models, Canvas/Design and background workloads. The selected RC must determine applicability. |
| Two application replicas | **UNVERIFIED** for deployed RC. Executed two ASGI middleware instances only. |
| Sustained saturation, queue, reclaim, retry, leak observations | **UNVERIFIED**. Sampler tests passed, including real child process measurements; no sustained deployment run performed. |
| No duplicate physical work | **UNVERIFIED**. Admission receipt tests are not physical Attempt fencing tests. run_soak.py:1050–1067 cancels the schedule probe Run without executing it. |
| Concurrent rate/security/degraded behavior without replica bypass | **NOT PROVEN**. Independent per-replica allowances reproduced by the production-middleware test above. Task backpressure test passes through the real router/spine, but does not prove distributed security under load. |
| Complete telemetry and thresholds | **UNVERIFIED** at RC grade. Profile has thresholds but acknowledges missing application-loop, saturation/reclaim, worker and long-window observations. Driver-loop sampling is not application-loop latency (run_soak.py:1410–1417). |
| Active-work kill/restart, graceful drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests do not establish recovery of active physical work; no deployed kill/restart executed. |
| Long-running exact RC/configuration | **BLOCKED / UNVERIFIED**. No designated immutable RC/configuration; current runner cannot certify it. Extending preflight duration does not remedy this. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Existing rate-scope discrepancy confirmed locally; no new load discovery claimed and no GitHub mutations performed. |
| Machine/human evidence with exact artifact/config hashes | **UNVERIFIED** for RC. This report and local test logs describe the starting source HEAD, not a promoted artifact. Historical soak bundles are not current acceptance evidence. |

## Handoff

Only this report changed. No production, test, inventory, gate, grant or ledger
changes were warranted by fresh evidence. No merge conflict exists. The supplied
failure is stale; the requested exact-debt ledger gate passes without amendment.
The accumulated branch diff against the supplied base includes unrelated changes;
this bounded check does not certify that entire diff. Six skipped tests and no
live database or production soak leave integration behavior unverified.

Next required inputs/work: designate the immutable promotion RC/configuration;
resolve the replica-budget acceptance discrepancy in the canonical security path;
complete representative workloads and telemetry; execute the exact-artifact long
soak with physical-work recovery assertions. Any subsequent code/runtime-config
change invalidates that soak. Do not restart this stale CI repair absent a new
failing command or changed prerequisite.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
Disposition: **BLOCKED**. This is not promotion or integration approval.
