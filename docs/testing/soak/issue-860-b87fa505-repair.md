# Issue #860 — bounded repair b87fa505

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `01fd86849b05c920bf4b2124025e99715087f320`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolved locally).
- Initial worktree clean; no salvage needed. No current-job check logs were
  supplied. Read supplied prior `98a113.../check-3.log`: schema-fence test
  expected 21 statements but observed 24. Reproduce before changing it.
- Inspect existing soak harness/profile/promotion tests, persistence schema and
  adjacent tests, relevant ADRs and CI gate configuration. Execute exact vulture
  gate; only amend its ledger if actual retained unbanked identities require it.
- Candidate edits limited to the cited schema test/implementation, soak harness
  and tests if validation identifies a concrete defect, the vulture ledger if
  required, inventory note if tests change, and this report.
- Ambiguity: no promoted RC artifact/configuration was designated in the lane
  brief. Do not invent one or label host/unit validation as an RC soak.
- No GitHub operations or new execution/authorization authorities.

## Results

Fresh exact vulture scan PASS: 1323 reviewed identities / 1323 findings,
zero unclassified and never-allowlist findings (checker base `4aa68edc0b6b`).
No ledger amendment is warranted. Fresh cited core test file: **37 passed,
6 skipped**; historical failure does not reproduce. The independent ordered
assertion already includes the three validation audit columns at lines 175–177.
No code repair or test weakening is warranted for the supplied failure.
The remaining focused checks also passed. No implementation changes were
justified by this round's observations.

## Executed validation

All commands used `uv run`, in the assigned worktree, with 1200-second timeouts.

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323/1323 identities; exact arguments match `.github/workflows/quality.yml:1078–1081` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped database coverage is not acceptance evidence |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 65 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed |

No tests added/removed, so no inventory delta. No ledger/grant changes, runtime
changes, GitHub mutations or deployment operations. The sole changed file is
this report. The supplied historical check log is stale for this head, not a
current CI failure.

## Architecture reconciliation

Read repository instructions, documentation authority map and accepted
ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and ADR-082826-08f0.
The later renewal/reclaim and recovery-disposition decisions resolve the older
fencing ADR's explicit deferral of expiry takeover. Attempt remains physical
execution identity; Run counts cannot prove physical-work uniqueness. Recovery
must follow the canonical lifecycle seam, not a new scheduler or authority.
No architecture changes were made.

## Acceptance checked at this head

Source review plus executed regressions below do **not** constitute a live RC
soak. Historical evidence packs were not promoted to current acceptance.

| #860 criterion | Evidence and disposition |
|---|---|
| Representative RC workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic, with no LiteLLM. `m3a-load-profile.md` explicitly records missing concurrent users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal/background-worker coverage. RC applicability is not settled. |
| At least two deployed application replicas | **UNVERIFIED for RC.** `run_soak.py:730–741` identifies its topology as host-uvicorn preflight. No fresh deployed replicas were exercised this round. |
| Sustained saturation, queues, reclaim, retries and leak observations | **UNVERIFIED.** Sampler tests passed, but unit/process probes are not sustained deployment observations. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `run_soak.py:1507–1527` observes terminal Run/admission counts, not physical Attempt execution. Admission-probe regressions passed but do not prove this criterion. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED for deployment; independent local allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439` exercises actual production middleware: the same identity obtains `[200,200,429]` independently from each instance, both authenticated and unauthenticated. The middleware allocates its own `InMemoryRateLimiter` at `packages/maistro-server/src/maistro_server/api/rate_limit.py:90–98` and is registered at `main.py:648`. Local enforcement does not establish a cluster-wide non-bypass guarantee. |
| Full PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` measures driver-loop lag, not application-loop lag. No complete RC telemetry window was collected. |
| Kill/restart during active work and prove drain/fencing/recovery | **UNVERIFIED.** Drain regression tests passed; no live RC Attempt was killed/recovered. Exit/rejoin and terminal Run counts are insufficient. |
| Long soak of exact RC artifact/configuration | **BLOCKED / UNVERIFIED.** `preflight_artifact_check` always returns false (`run_soak.py:730–741`) and is wired into evaluated thresholds at line 1552. Executed `test_four_hour_preflight_cannot_pass_cli` (`tests/test_soak_promotion_gates.py:103`) rejects even otherwise-passing four-hour host evidence. No immutable RC image/configuration was designated. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Local findings recorded here; external issue changes were neither authorized nor performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This report is validation evidence for the named source head, not an RC soak evidence pack. |

## Handoff

**BLOCKED**, not merge-ready or integration approval. The assigned CI repair
was checked; no current failure or unbanked identity exists to fix. Repeating
short host runs cannot satisfy the missing exact-RC acceptance criteria.

Next: the release owner must designate the immutable RC artifact/configuration
and representative workload applicability, and resolve deployment rate-budget
semantics through existing policy authority. Then execute the long production
soak, collecting physical Attempt/recovery observations and complete telemetry.
Any runtime/config change invalidates prior soak evidence. This lane must not
invent those inputs or silently weaken the acceptance criteria.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC deployment prerequisites; issue acceptance blocked"}`.
Local commit of this report completes the writer handoff only.
