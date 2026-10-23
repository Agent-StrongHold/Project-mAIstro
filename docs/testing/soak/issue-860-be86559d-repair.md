# Issue #860 — bounded CI repair (be86559d)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`b24e5fcffd641ae5a532365be5bbc0a1b77b56ab`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Candidate edit surfaces: this report and `quality/vulture-baseline.json` only,
with retained identities reviewed against their production callers and tests.
No PR operations or additional issues are in scope.

Initial worktree is clean. Current job directory contains no `check-*.log`.
The supplied prior result is BLOCKED, not acceptance evidence. This round will
rerun the specified scanner and focused soak checks; it will not substitute
unit tests for the missing exact-RC deployment soak. Ambiguity: no exact RC
artifact/configuration was provided; do not invent one.

## Results

The exact requested vulture command passed: 1322 findings / 1322 reviewed
identities, zero unclassified, zero never-allowlist findings; resolved base
`321cbdb8fe9b`. No identities require banking or removal, so editing the ledger
would be unjustified. The cited historical check-3 log fails on 24 DDL calls
versus 21 expected; current schema tests will be rerun before any conclusion.

Read accepted ADR-081426-1f7c and ADR-081626-f383: physical execution identity is
Attempt and the canonical Run store owns fencing. Admission deduplication is
not physical-work uniqueness. No competing scheduler or execution authority is
introduced. The existing host-process driver explicitly rejects exact-RC
artifact equivalence (`scripts/soak/run_soak.py:744`).

A guessed prior report filename was not found and skipped; `git show HEAD`
identified the actual report, which was read as historical context only.
README globs for the soak directories were not found and skipped. Neither
lookup failure is a failed production gate.

## Fresh validation

Commands used 1000–1200 second timeouts; all validation commands passed:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1322/1322 exact identities; matches both CI workflows |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; historical failure not reproduced |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; nonfatal invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

The schema expectation already covers the three validation-audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:177`, matching
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:116`. Its schema
fence is at line 216. Skipped tests are not concurrent PostgreSQL evidence.

Production reachability was checked: `maistro_server/main.py:648` installs the
limiter and lines 735/755 mount the task router. The real middleware constructs
an in-memory limiter (`api/rate_limit.py:93`), explicitly documenting N-times
aggregate allowances. The executed regression at
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently
on both instances for the same principal/address. The real task route reads its
queue (`api/tasks.py:145`); the executed regression at
`tests/test_soak_promotion_gates.py:569` observes admitting-replica 200 and peer
404 while sharing canonical admission. Neither test deploys an RC replica.

## Acceptance disposition (all ten criteria)

| Criterion | Fresh evidence / status |
| --- | --- |
| Representative RC users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Design/Canvas and workers | UNVERIFIED: `m3a-load-profile.md:165` explicitly lists missing workloads; selected RC applicability unresolved. |
| At least two deployed application replicas | UNVERIFIED: independent ASGI production-component probes passed, not deployed replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, memory/descriptor/process leaks and restart | UNVERIFIED: no sustained deployment load executed. |
| Physical-work uniqueness for schedules/task/Run/Attempt/Goal operations | UNVERIFIED: admission and receipt tests are not physical Attempt execution/recovery evidence. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED for deployment: fresh tests reproduce separate local allowances, not a shared budget. |
| Complete PostgreSQL/app-loop/worker/RSS/FD/queue/error telemetry and thresholds | UNVERIFIED: sampler regressions pass, but no full production time series; driver-loop lag is not application-loop lag. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no active-work deployment restart executed. |
| Long exact-RC artifact/configuration soak | UNVERIFIED: CLI regression rejects missing/null/preflight artifact evidence even with synthetic four-hour duration; `run_soak.py:744` cannot establish artifact equivalence. |
| Earliest-broken-invariant classification of load findings | UNVERIFIED for completeness: no new representative load findings collected; remote filing prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak: this is source-bound validation only, not an immutable deployment evidence bundle. |

Exact RC ambiguity is **UNRESOLVED** after checking the supplied assignment and
local contract. `deploy/docker-compose.prod.yml:11` explicitly calls itself a
reference requiring digest pinning; the app services build source. No artifact
selection can be inferred from that reference. Do not run another host-process
preflight and label it promotion evidence, or alter the accepted execution
model to satisfy the issue wording.

## Handoff

**BLOCKED**, despite the assigned CI checks passing. Only this report changed;
no production, test, ledger, grant or gate edits were warranted. No tests were
added or modified, so there is no inventory delta. Existing work was preserved.

Next: the release owner must select the immutable RC images and normalized
configuration, settle workload applicability, and arrange a fully instrumented
long production soak with physical Attempt/recovery observations. Evaluate the
observed replica-local limits and receipt visibility against that topology.
Repeating the stale schema/vulture repair cannot close these acceptance gaps.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0. Local commit is a blocked handoff, not integration
approval. No GitHub mutation performed.
