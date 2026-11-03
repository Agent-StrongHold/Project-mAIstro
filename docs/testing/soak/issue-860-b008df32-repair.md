# Issue #860 repair — b008df32

## Frozen scope and fresh results

Assigned issue #860 only, worktree `/home/dev/Git/wt/auto-860`, starting HEAD
`a47a7f408df35eb9355cb5158d6c0bad6e51b0da`, supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Starting worktree clean; no conflict
or uncommitted salvage. Supplied dispatch snapshot used without GitHub mutation.
Inspection scope: soak harness/profile/tests, adjacent schema-fence and task
backpressure tests, production rate middleware, applicable ADRs and gates.
Potential changes limited to this report and the explicitly permitted vulture
ledger if the exact scan demonstrates unbanked identities. No new tests planned.

No driver `check-*.log` files were present in this job directory. Read the supplied
prior `98a11313167b41a98a420abfda80c292/check-3.log`: schema fence expected 21
statements but observed 24. Fresh targeted validation does not reproduce it.

Executed against starting HEAD (logs in the assigned job directory):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1323 reviewed identities / 1323 findings, zero unclassified or never-allowlist findings. Reported ratchet base `4aa68edc0b6b`. No evidence warrants a ledger edit.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **103 passed, 6 skipped**. Skipped tests do not count as integration evidence.

- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: **PASS** (component existence only).
- `uv run python scripts/check-merge-markers.py`: **PASS**.
- `uv run python scripts/check-backlog-consistency.py`: **PASS**, 168 items.

The assigned historical gate failure is stale at this HEAD. The test at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175` already
expects the three Gauntlet audit columns declared by production at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:116–118`.
Do not change a passing schema expectation or debt ledger cosmetically.

## Architecture and production evidence

Read repository `AGENTS.md`, `docs/README.md`, accepted ADR-081226-69ee
(Graph/Node), ADR-081626-f383 (Attempt lease/fencing), ADR-085 (rate/quota), and
proposed ADR-081 (deployment). Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`. The accepted fencing ADR explicitly excludes lease-expiry takeover
from its current boundary. Issue acceptance does not authorize an alternative
reclaim authority or scheduler. ADR-085 requires principal-keyed rate limits;
it does not establish a shared multi-replica budget. These are unresolved
acceptance boundaries, not waived requirements.

Production installs `RateLimitMiddleware` in
`packages/maistro-server/src/maistro_server/main.py:648`. Each instance constructs
an `InMemoryRateLimiter` in `api/rate_limit.py:93`. The freshly executed test at
`tests/test_soak_promotion_gates.py:439` uses two instances of that production
middleware: the same IP/credential receives `[200, 200, 429]` from each instance,
while the exhausted first instance still returns 429. This demonstrates extra
allowance after replica selection; it is not a live deployed security soak.

`deploy/docker-compose.prod.yml:10–12` is explicitly a reference requiring
production digest pinning. No immutable promotion RC/configuration is designated
in this assignment. `scripts/soak/run_soak.py:730–741` always reports
`exact_rc_artifact.ok=false` for its host-process topology. The executed CLI
regressions at `tests/test_soak_promotion_gates.py:103` reject missing, null and
preflight artifact records even with synthetic four-hour evidence. Running this
emulator longer cannot establish RC artifact equivalence.

## Acceptance matrix

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:151–168` admits missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background traffic. Applicability requires the selected RC configuration. |
| At least two application replicas | **UNVERIFIED** for deployed RC. Tests exercised two ASGI middleware instances, not deployed application replicas. |
| Sustained pool/queue/reclaim/retry/leak observations | **UNVERIFIED**. Sampler/accounting tests passed; no long-running load executed this round. |
| No duplicate physical work | **UNVERIFIED**. Profile lines 199–204 distinguish single-occurrence admission from physical Attempt/Goal work; probe Run is cancelled without execution. |
| Concurrent rate/security/degraded behavior and no replica bypass | **NOT PROVEN**. Production middleware tests demonstrate independent replica allowances. Task backpressure tests pass, but are not deployed security evidence. |
| Full telemetry and explicit thresholds | **UNVERIFIED** at RC grade. Profile distinguishes driver-loop lag from application-loop lag and admits missing worker/saturation/reclaim observations. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Cleanup tests are not proof of physical-work recovery; no deployed restart performed. |
| Long-running exact RC/configuration soak | **BLOCKED / UNVERIFIED**. No designated immutable RC/configuration; current runner cannot certify it. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Rate-scope discrepancy revalidated locally; no GitHub mutation or new load finding claimed. |
| Machine/human evidence tied to exact artifact hashes | **UNVERIFIED** for RC. Local deterministic logs bind to starting HEAD only; historical bundles are not fresh promotion evidence. |

## Handoff and residual risks

Only this report changed. No production/test/ledger/grant/gate edit is justified
by the supplied failure and fresh checks. No test changes, so no inventory delta
is required. No merge conflict or destructive operation occurred. The accumulated
branch contains unrelated changes relative to the supplied develop base; this
bounded repair does not certify that entire diff. Full-tree pytest and live DB
integration were not run; six skipped tests are explicitly not proof.

Resume only after an immutable RC/configuration is designated, the replica-budget
acceptance discrepancy is resolved through the canonical security path, and the
production workload/telemetry gaps are addressed. Then execute the required long
soak; any code/runtime-config change requires a new soak. Do not redispatch the
stale schema failure or a presumed vulture failure without fresh failing evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and production soak prerequisites"}`.
Disposition: **BLOCKED**, not integration approval.
