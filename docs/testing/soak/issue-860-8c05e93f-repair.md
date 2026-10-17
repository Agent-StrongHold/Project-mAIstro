# #860 repair checkpoint — job 8c05e93f

## Frozen scope and disposition

Only issue #860, assigned worktree `auto-860`, starting commit
`8894bdd21df83173a4e4aa163071479910a8786c`, supplied develop base
`ac69535ef165ded3ca82cd3428728569de3251fa`. Initial status was clean.
No conflicts or incoming edits needed salvage. No remote operations performed.

Repair targets were the supplied historical schema failure and prescribed
Vulture identity scan; soak runner/profile and adjacent tests were acceptance
inspection inputs. The only changed file is this checkpoint. A ledger amendment
was conditional on actual scanner findings; there were none, so changing the
ledger or source would be speculative. No tests were added or changed, hence no
suite inventory delta.

The current job directory had no driver `check-*.log` files. Inspected the supplied
historical `98a11313167b41a98a420abfda80c292/check-3.log`: its 24-versus-21 DDL
failure does **not** reproduce. The current independent test expectation includes
all three validation audit columns (test_pg_learnings.py:175–177). Production
holds the transaction advisory lock before DDL (pg_learnings.py:215–216).

Read repository instructions, the captured issue body, previous result and
relevant accepted ADRs: ADR-082826-b601 and ADR-085. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission uniqueness does not prove
physical execution uniqueness; no competing execution authority is warranted.
ADR-085's principal-keyed limits do not establish a cluster-shared allowance.
Current per-process behavior is not a waiver of the issue's non-bypass criterion.

## Fresh executed validation

All validation commands used 1200-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS: 1323 reviewed identities / 1323 findings; zero unclassified and
  never-allowlist findings. No ledger repair required.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  — PASS: 118 passed, 6 skipped in 2.61s. Skipped database tests are not live
  deployment evidence.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3277 files already formatted.
- `uv run python scripts/check-doc-links.py` — PASS, 2702 Markdown files,
  zero broken relative links.
- `git diff --check` — PASS.

## Acceptance evidence and gaps

| Criterion | Current disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: profile's remaining gaps explicitly exclude concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained reconciliation. |
| Two production replicas | **UNVERIFIED**: component ASGI tests ran, not an exact-RC deployment. |
| Sustained saturation, queues, reclaim, retries and leaks | **UNVERIFIED**: no sustained production load executed this round. |
| No duplicate physical work and Goal reconciliation | **UNVERIFIED**: schedule probe races admission then cancels without executing physical work (profile's Goal reconciliation scoping). |
| Security/degraded behavior and replica non-bypass | **UNVERIFIED** at deployment scale. Executed `test_replica_selection_has_an_independent_production_allowance` proves each production middleware instance independently permits 200/200/429 for the same authenticated or unauthenticated identity. |
| Complete telemetry and thresholds | **UNVERIFIED**: driver-loop lag is not application-loop lag; profile documents missing worker/pool/reclaim and long-window evidence. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**: no live recovery experiment executed. |
| Long-running exact RC soak | **UNVERIFIED**: `run_soak.py:744–755` explicitly returns `ok: false` for exact-RC identity; increasing host-process duration cannot satisfy it. No immutable designated RC supplied. |
| Findings filed/reclassified | **UNVERIFIED**: no new live experiment or remote filing; existing limitations recorded locally, remote mutations prohibited. |
| Machine/human hash-bound production evidence | **UNVERIFIED**: this report identifies source HEAD, not a production image/config soak. |

The production middleware constructs `InMemoryRateLimiter` at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:94`; the executed
regression at `tests/test_soak_promotion_gates.py:439` checks independent budgets,
not merely mocked 429 responses. Passing tests establish this limitation rather
than disproving it.

## Handoff

**BLOCKED** for promotion acceptance, not a reproduced CI defect. Do not repeat a
CI-only repair against the historical schema log as though it were current.
Next owner needs a designated immutable RC/configuration, a promotion-capable
runner with representative workload/telemetry, resolution of replica-selection
budget semantics, and the >=4-hour exact-artifact run with physical-work recovery
proof. No gate was weakened to make preflight evidence look production-grade.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0,
validation errors 0. This checkpoint commit is not integration approval.
