# Issue #860 — job 5e62acbd repair checkpoint

## Frozen scope

Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `177136f0587de136d6472d9abe8eecd28db9d922`,
comparison base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial working tree is clean; no incoming diff needs salvage.

Process the supplied dispatch snapshot, supplied prior result and check-3 log,
repository instructions and soak-related ADRs, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, existing soak profile/evidence,
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`,
and the exact vulture gate (`quality/vulture-baseline.json` only if actual
retained findings require it). No linked PR or issue enumeration or GitHub
mutation. This note is the checkpoint/output file for this item.

Ambiguity: the prompt includes verifier and writer instructions; the explicit
repair lane and mandatory local commit identify this worker as writer.
No `check-*.log` exists in the supplied current job directory at initial
inspection. The supplied prior check log will be inspected instead.

## First validation checkpoint

- Exact requested vulture scan: exit 0, 1,322 reviewed identities and 1,322
  findings, zero unclassified/never-allowlist findings. No evidence warrants
  a ledger amendment; none made. The gate reports its own base `321cbdb8fe9b`.
- Supplied historical check-3 failed because the schema-fence test expected
  21 statements but observed 24. Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` exits 0;
  the historical failure is not reproduced on the assigned HEAD.
- `uv run ruff check .` and `uv run ruff format --check .`: both exit 0.
- Logs: `/tmp/860-5e62-{vulture,schema,ruff,format}.log`.

The supplied prior result was BLOCKED on exact-RC evidence, physical-work
fencing and representative coverage, not vulture. The existing profile
explicitly identifies the current runner as host-process preflight and not
promotion-signing. Focused production-seam tests and ADR review completed below. No promotion
claimed.

## Architecture reconciliation

Reviewed repository `AGENTS.md`, `docs/README.md`, accepted ADRs
`ADR-081226-69ee`, `ADR-081226-a66b`, `ADR-081426-1f7c` and
`ADR-081626-f383`, plus deployment ADR-081 (still **Proposed**, not an
accepted waiver). Graph snapshots, canonical Run/NodeRun/Attempt ownership,
and the domain/runtime boundary remain unchanged.

ADR-081626-f383 explicitly excludes lease-expiry takeover/recovery supersession
from its current contract. The issue's request to observe reclaim cannot
justify inventing reclaim authority in this lane. This is an unresolved
acceptance/contract dependency, not a passing criterion.

`deploy/docker-compose.prod.yml` defines two application services, PostgreSQL
primary/replica, Redis, shared storage, and an external model gateway. Its
reference configuration is not a frozen promotion image/config identity.
`scripts/soak/run_soak.py:744` always returns a failed exact-artifact check;
longer runtime cannot convert the host-process preflight into that deployment.

## Focused validation results

All commands ran in the assigned worktree with 1,000-second tool timeouts:

| Command | Executed result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,322 accounted-for identities |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,301 files formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped cases are not validation evidence |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 72 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed |
| `git diff --check` | PASS |

Additional logs: `/tmp/860-5e62-soak-tests.log` and
`/tmp/860-5e62-backpressure.log`. No tests added or removed, so no inventory
count delta or new inventory note is required. No ledger/gate changes.

The 72 soak tests include actual production middleware and task-router probes:

- `tests/test_soak_promotion_gates.py:439`: the same identity receives
  `[200, 200, 429]` independently on each middleware instance. Production
  `packages/maistro-server/src/maistro_server/api/rate_limit.py:95` constructs
  an independent in-memory limiter. Six-path rejection evidence does not
  prove a shared allowance or replica-selection non-bypass.
- `tests/test_soak_promotion_gates.py:564`: admission through the real task
  router and shared canonical admission spine yields a local receipt 200,
  followed by 404 from the peer queue. Production `api/tasks.py:146` reads
  `queue.get`, not a cross-replica durable receipt store. ASGI transport is
  not a deployed two-replica soak.
- The server backpressure test proves 202 below capacity, 429 with
  `Retry-After` when full, principal isolation, and admission after release.
  It does not prove physical execution/recovery under sustained load.

## Acceptance matrix (all ten criteria checked)

| Issue criterion | Evidence and remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED: profile documents one API key and missing users/Workspaces, Graph fan-out, successful tools/models and Design/Canvas/worker coverage; no complete selected-RC workload executed here |
| Two deployed application replicas | UNVERIFIED: Compose declares two services; freshly executed tests use ASGI instances, not that deployment |
| Sustained saturation, queue/reclaim/retry/leaks | UNVERIFIED: no sustained run this round; reclaim authority is not established by the accepted fencing ADR |
| Physical-work uniqueness and Goal reconciliation | UNVERIFIED: admission/receipt tests do not execute physical work; historical one-occurrence admission is insufficient |
| Replica-resistant security/degraded behavior | UNVERIFIED as a whole; independent replica allowances freshly reproduced; canonical capacity backpressure passes |
| Production telemetry and thresholds | UNVERIFIED: profile has thresholds but no new application-loop, pool/worker/leak time series on the selected RC |
| Active-work kill/restart/drain/fenced recovery | UNVERIFIED: process exit or terminal Run counts are insufficient; no active-work recovery experiment executed here |
| Long exact-RC soak | UNVERIFIED: preflight refuses exact artifact equivalence; no >=4-hour immutable-RC run |
| Findings classified before promotion | UNVERIFIED for completeness: historical evidence pack classifies findings, but no completed promotion soak exists; no external filing or other GitHub mutation performed |
| Machine/human evidence bound to exact hashes | UNVERIFIED for promotion: existing packs explicitly provisional and tied to older heads; this checkpoint is validation evidence only |

## Handoff

Verdict: **BLOCKED**, not merge-ready. Only this checkpoint file changed.
The requested vulture repair has no reproducible remaining defect; changing
its ledger would be unsupported. The supplied historical schema failure is
also no longer reproducible. Do not repeat a ledger-only repair as a substitute
for the unmet soak criteria.

Next requires an identified immutable RC image/configuration, a representative
production-topology runner/workload, resolution of the replica-budget and
reclaim-contract gaps through canonical authorities, and then a >=4-hour run
with physical Attempt correlation and complete telemetry. None is waived by
passing unit tests. Historical artifacts and all existing implementation were
preserved. Local commit records this checkpoint; no integration approval.

Progress: checked issue items 1, completed acceptance sets 0, skipped items 0,
validation-command failures 0; next is the blocked production-evidence work.
