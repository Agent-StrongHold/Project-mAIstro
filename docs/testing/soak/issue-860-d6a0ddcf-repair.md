# Issue #860 — focused CI-repair checkpoint

## Frozen scope and initial evidence

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD `8935e3e3b128e124bcc9c04e31f9ea40783126a3`;
  supplied base `2154f845347c9541016288c760f8da3f5cd2e064` resolves.
- One item: #860. Frozen inputs: this job's `dispatch-context.json`, prior
  `0efcef84223a4797be413ce7c668f299/result.json`, and reported historical
  `98a11313167b41a98a420abfda80c292/check-3.log`. No current-job check logs
  were present at initial inspection. No GitHub re-fetch or mutation.
- Review surface: existing soak runner/profile/tests, schema-fence and task
  backpressure implementation/tests, relevant ADRs and CI configuration.
  Candidate edits: this report and only evidence-backed scanner/schema fixes
  (with tests/inventory notes if a code repair proves necessary).
- Assumption: writer CI-repair lane; not a read-only verifier. The ledger
  exception does not justify arbitrary edits when no unbanked identities exist.
- Fresh mandated vulture command passed: 1,323 findings / reviewed identities,
  zero unclassified and zero never-allowlist. No ledger amendment warranted.
- Historical check-3 failure is schema-fence expected DDL count 21 versus 24.
  It is not a vulture failure. Fresh regression execution follows below.

## Validation and disposition

**BLOCKED for production acceptance; historical CI failure does not reproduce.**
Only this report changes. No test additions or inventory delta; no source,
ledger, grant, policy or gate changes are justified by the executed checks.

Commands executed in the assigned worktree, each with a 1,200-second timeout:

| Command | Fresh outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,323 reviewed identities, no new debt; matches `.github/workflows/quality.yml:1078–1081` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 37 passed, 6 skipped (1.59 s); skips require `MAISTRO_TEST_PG_DSN` |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed (2.35 s) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,277 files |
| `uv run python scripts/check-doc-links.py` | PASS: 2,708 Markdown files, zero broken links |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |

The schema-fence test already contains the three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`, and
independently checks the ordered DDL body. The stale 21-versus-24 failure does
not warrant weakening or rewriting it. No live PostgreSQL race was validated.

## Architecture and reachable evidence

Read repository instructions, `docs/README.md`, ADR-082826-b601 (Accepted),
ADR-085 (Accepted), ADR-081 (Proposed), the existing load profile and adjacent
regressions. Canonical execution remains `Goal -> Graph -> Run -> NodeRun ->
Attempt`; the accepted consumer ADR forbids a second execution/claim authority.
The probe at `scripts/soak/run_soak.py:1067–1091` cancels its admitted Run
without executing it. Admission uniqueness is not physical-work uniqueness.

`preflight_artifact_check()` at `scripts/soak/run_soak.py:744` returns false
and is wired into actual result generation at line 1579. The executed
`tests/test_soak_promotion_gates.py:106` regression proves that an otherwise
passing synthetic four-hour preflight cannot pass the CLI. This prevents false
promotion; it does not supply the missing production runner/evidence.

The production app installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its limiter is
instance-local (`api/rate_limit.py:93`). The executed test at
`tests/test_soak_promotion_gates.py:439` sends the same identity to two instances
and observes `[200, 200, 429]` on each, for authenticated and anonymous traffic.
Local enforcement is proven, replica-independent allowance is not. ADR-085's
principal-keyed requirement is not permission to invent another authorization
path. The profile explicitly limits its claim to process-local enforcement.
ADR-081 is Proposed and cannot waive the issue's acceptance requirements.

## All ten acceptance criteria

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED**: `m3a-load-profile.md` explicitly lists missing users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. |
| At least two production replicas | **UNVERIFIED**: ASGI instances are not deployed production replicas; no exact-RC topology was exercised. |
| Sustained saturation, queues, reclaim, retries, leaks and restart | **UNVERIFIED**: short regression tests do not establish these observations. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**: schedule probe admits then cancels without execution. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent per-instance allowances reproduced; deployment-level non-bypass and security/degraded behavior **UNVERIFIED**. |
| Complete PostgreSQL, application-loop, worker, memory, descriptor, queue and error telemetry with thresholds | **UNVERIFIED**: no qualifying live series captured; driver-loop latency cannot establish application-loop latency. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED**: no production active-work experiment performed. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**: existing runner explicitly fails exact-RC equivalence regardless of duration. |
| Load findings classified before promotion | Backlog consistency passed; production findings completeness **UNVERIFIED**, no new load experiment or GitHub mutations. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**: this source-validation report is not an immutable production-soak bundle. |

## Handoff

Missing prerequisite: selected immutable RC artifact/configuration and a supported
representative workload contract, with production-path execution/recovery and
telemetry oracles. Resolve the replica-selection budget claim, then execute the
qualifying exact-RC soak and publish hash-bound raw/human evidence. A longer host
preflight or redispatch of the old schema log cannot satisfy these requirements.
No sync conflict or incoming uncommitted work existed. All inherited work is
preserved; the broad inherited branch diff is not certified by this focused round.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; command errors
0. CI-repair check complete with no reproducible defect. Next: production evidence
work, not speculative scanner edits. Local commit is a writer handoff only.
