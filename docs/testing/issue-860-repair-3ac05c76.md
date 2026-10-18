# Issue #860 — bounded repair result (3ac05c76)

## Scope and disposition

Only issue #860 was processed in `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting at `158b1efb86b63a510ee33689f57a2478302cd74b` against
base `ab8b3737fa64f8d840f421ef87ca506c509444ff`. Initial tree was clean.
The supplied dispatch snapshot was used without fetching or mutating GitHub.
No current-job `check-*.log` files were present at the initial snapshot.

**BLOCKED for issue acceptance; no reproduced CI defect to repair.** The exact
requested vulture command passed with 1322 reviewed identities matching 1322
findings, zero unclassified and zero never-allowlist findings. No ledger change
is justified. The explicitly supplied historical `98a11313.../check-3.log`
contains a pytest failure expecting 21 schema statements but observing 24,
not a scanner failure. Current `test_pg_learnings.py:171` already includes the
three validation audit columns; its regression passes without modification.

This checkpoint is the only changed file. No tests, runtime behavior, gates,
ledger, grants or historical evidence changed. No inventory delta is needed.

## Executed validation

All commands used long timeouts (600 seconds for vulture; 1200 for the test
and lint batches). Logs are in job directory
`/home/dev/maistro/jobs/3ac05c76da8c46c89c5251b8a81cd81e/`.

| Command | Observed result | Log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322 identities = 1322 findings | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped | `worker-pg-tests.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 72 passed | `worker-soak-tests.log` |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed | `worker-server-tests.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS; 3301 files formatted | `worker-format.log` |

These are deterministic checks, not production load evidence. PostgreSQL tests
marked skipped are not counted as live database validation. No long soak was
executed and no exact promotion artifact/configuration was selected by this lane.

## Architecture reconciliation

Read repository instructions, the documentation authority map, ADR-081
(**Proposed**), ADR-081626-f383 (**Accepted**) and ADR-082426-82c7
(**Accepted**). The accepted contracts distinguish occurrence admission from
physical execution, and durable fencing from expiry/takeover semantics.
The latter require explicit reclaim authority; this repair must not invent it.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, the canonical Run store,
and the existing authorization path. Process-local rate budgets are explicitly
documented in `maistro_server/api/rate_limit.py:32`; their local correctness does
not prove the stronger replica-independent acceptance criterion in #860.

## Acceptance audit

| # | Issue criterion | Current executed evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC load profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:167` excludes multiple users/Workspaces, fan-out and successful tool/model calls. Selected-RC applicability is not established. |
| 2 | At least two supported production replicas | **UNVERIFIED.** Executed two-instance ASGI middleware tests, not a deployed RC topology. |
| 3 | Sustained saturation, reclaim, backoff and leak observation | **UNVERIFIED.** Executed short regressions only. No sustained production load or lease-reclaim experiment. |
| 4 | No duplicate physical work | **UNVERIFIED.** `scripts/soak/run_soak.py:1067` explicitly cancels an admission-only Run that never executes. Passing admission-probe tests cannot prove Attempt or Goal-reconciliation uniqueness. |
| 5 | Replica-independent security/rate/degraded enforcement | **UNVERIFIED, with counterevidence.** Executed `tests/test_soak_promotion_gates.py:439`: both authenticated and unauthenticated identities receive independent `[200, 200, 429]` allowances on each production middleware instance. `rate_limit.py:94` constructs an in-memory limiter per instance. |
| 6 | Thresholded production telemetry | **UNVERIFIED.** Executed real child RSS/descriptor sampler regression; this is not a production pool/query/lock/loop/queue/error telemetry series. |
| 7 | Kill/restart during active work with fencing/recovery | **UNVERIFIED.** The focused tests do not establish recovery of a physical Attempt in a deployed RC. |
| 8 | Long soak of exact RC artifact/configuration | **UNVERIFIED.** `scripts/soak/run_soak.py:744` always rejects the host preflight as exact-RC evidence. Three four-hour-evidence CLI rejection tests passed; these simulate evidence, not four hours of traffic. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED.** This handoff records blockers only; no complete milestone disposition was established and no GitHub mutations were performed. |
| 10 | Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED.** Logs and this source-bound checkpoint are not an immutable production soak evidence pack. |

## Next action

Do not retry the same passing scanner as a solution to production acceptance.
Select the immutable RC and supported configuration, resolve the replica-budget
contract, complete representative physical-work/recovery workloads and telemetry,
then run the long soak and disposition its findings. No integration approval is
implied by this local handoff commit.

Snapshot accounting: checked 1; done 0 acceptance-complete; skipped 0 issues;
errors 0 executed validation commands. Conditional ledger repair skipped because
there are no unmatched identities. Production acceptance remains blocked.
