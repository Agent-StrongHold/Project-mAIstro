# Issue #860 — fresh validation and acceptance disposition

Snapshot: issue #860 from the supplied `dispatch-context.json`; worktree
`auto-860` at starting HEAD `7335099bb90fe02eaf04c4cb129ea07c329c6d44`.
No `check-*.log` files were present in the supplied job directory. The prior
result was read but treated only as a lead; conclusions below were rechecked
against current source, evidence, and tests. This is a validation checkpoint,
not a claim that the promotion acceptance is complete.

## Fresh evidence

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **PASS**, 84
  tests in 2.21s. This includes an executable production-middleware regression
  demonstrating the same authenticated principal and same client can receive
  `[200, 200, 429]` on each of two independent replicas. It proves independent
  per-process allowances, not cross-replica aggregate enforcement.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **PASS**: 1321 findings, all 1321 reviewed identities; zero unbanked identities. No ledger change is warranted.
- `docker info --format '{{.ServerVersion}}'` — **PASS**, Docker daemon reports
  29.1.3. Docker availability alone does not identify the promoted RC image,
  config, workload fixture, or recovery oracle; no unapproved deployment/soak
  was started.
- `docs/testing/soak/evidence/m3a-round109-shakedown.json` was freshly read:
  420.05s observed versus the 14,400s minimum; `exact_rc_artifact.ok=false`,
  topology `host-uvicorn-preflight`. Both limitations are explicitly enforced
  by `scripts/soak/run_soak.py::preflight_artifact_check` and the promotion
  checks. That historical preflight cannot be elevated into RC evidence by
  rerunning its evaluator or extending its duration.
- `scripts/soak/run_soak.py`'s driver contract and
  `docs/testing/soak/m3a-load-profile.md` were inspected. Profile's own
  “Remaining representative-profile gaps” section excludes multi-user/
  Workspace, Graph fan-out, successful tools/models, Design/Canvas and
  Goal/background reconciliation. It states process-group RSS is not cgroup
  evidence, driver loop lag is not application event-loop lag, and physical
  Attempt fencing/recovery and pool saturation/reclaim observations remain
  unverified.
- Relevant accepted contracts reviewed: ADR-081226-69ee (Graph → Run →
  NodeRun → Attempt lifecycle), ADR-081226-a66b (Run/NodeRun/Attempt ownership
  and one active Attempt), ADR-081626-f383 (execution lease/fencing; explicitly
  no expiry takeover absent reclaim authority), and ADR-085 (principal rate
  limiting). No alternate scheduler or execution authority is introduced.

## Acceptance disposition

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative RC workload profile | **UNVERIFIED**. The checked-in profile lists the above workload omissions and supplies no selected immutable RC with applicability decisions. |
| At least two application replicas | **UNVERIFIED for the promoted RC**. Profile topology is Compose x2; round 109 is host uvicorn, not the production image/configuration. |
| Sustained saturation, queue/reclaim/retry, memory/fd/process leak and shutdown observations | **NOT MET**. Round 109 is 420.05s (<14,400s); historical metrics do not establish the missing long-window production observations. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal across replicas | **UNVERIFIED**. Admission checks and one schedule occurrence do not run sustained physical Attempts or prove recovery/fencing; ADR-081626-f383 does not permit inferred lease-expiry takeover. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT MET for aggregate rate-limit non-bypass**. The test above demonstrates fresh independent allowances on two real middleware instances. The production middleware owns an `InMemoryRateLimiter` per instance (`packages/maistro-server/src/maistro_server/api/rate_limit.py`); the current profile explicitly describes N× aggregate allowances rather than a shared principal budget. |
| Required PostgreSQL/app-loop/worker/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED for RC**. Existing preflight records partial telemetry; no RC application loop/pool saturation/worker series was captured. |
| Kill/restart during active physical work, drain/fencing/recovery | **UNVERIFIED**. Process rejoin and terminal Run count are not a physical-work loss/duplication oracle. |
| Long-running exact-RC soak after code/config freeze | **NOT MET**. Round 109 fails duration and artifact gates; no exact RC identity/configuration was designated or soaked. |
| Findings reclassified to earliest broken milestone invariant | **UNVERIFIED**. This run produced no new load finding to reclassify, and no evidence establishes disposition of the existing production gaps. |
| Machine- and human-readable evidence bound to image/package/commit/config hashes | **PARTIAL / NOT PROMOTION-GRADE**. Preflight has historical evidence; it identifies itself as host-uvicorn and cannot attest the promoted Compose image/config digest set. |

## Result

**BLOCKED**, not promotion approval. The focused deterministic suite and exact
vulture gate pass, but they cannot satisfy deployment- and four-hour-soak
criteria. No production source changes or tests were added because a bounded
code edit cannot establish exact-RC deployment/long-duration evidence, and the
observed process-local rate-limit behavior conflicts with the issue's
non-bypass acceptance. No inventory delta is needed (no tests added). Do not
interpret this validation-only checkpoint as an implementation fix.

Next required evidence: release ownership must designate/freeze the exact RC
image and normalized configuration; decide and implement the supported
cross-replica rate-limit contract without violating accepted ownership; provide
representative workload, telemetry and physical Attempt recovery oracles; then
run and publish at least 14,400 seconds on that unchanged multi-replica RC.
