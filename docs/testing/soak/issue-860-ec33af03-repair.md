# Issue #860 — bounded repair ec33af03

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `d75d546b61de3cb617c70be0a6621c3fca1ac7bf`; supplied base: `34795962548a33f6b6f7e1234dcea201a9df96ef`.
- Clean starting worktree; no incoming edits to salvage.
- Inspect repository instructions, relevant execution/deployment ADRs, existing
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, prior result and supplied failing log,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py` and adjacent tests.
- Potential edits limited to the reproduced schema-fence regression, explicitly
  authorized `quality/vulture-baseline.json` identities if the exact scan requires
  them, necessary inventory note, and this report. No scheduler/auth redesign.
- Snapshot source: supplied `dispatch-context.json`; no GitHub mutations or refresh.

## Initial evidence and assumptions

The job directory has no `check-*.log` files at intake. Supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 DDL statements versus
21 expected in the schema-fence test. This is historical evidence, not yet a
reproduced failure. Prior result `1635a91bbe13428ea23ade5e4a056a3f/result.json`
reports BLOCKED on production soak evidence. Assume this is a bounded CI repair,
not authority to invent an RC artifact or replace production rate limiting.
The base-to-head diff includes substantial inherited divergence outside #860;
this round preserves it and does not claim to validate those unrelated changes.

## Validation

- Exact required vulture command passed: 1,328 reviewed identities/findings,
  zero unclassified and never-allowlist. No ledger amendment is warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped (not live PostgreSQL proof). The historical failure
  is not reproducible: the current independent expectation includes all three
  Gauntlet audit columns. No test weakening or code repair is warranted.
- Logs: job directory `worker-vulture.log`, `worker-schema.log`.

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  66 passed, including production middleware with independent replica allowances.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,159 files.
- `uv run python scripts/check-deployment-claims.py`: PASS (static claims only).
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- All validation commands used 1,200-second timeouts and logs in this job's
  `worker-*.log` files. No new or changed tests: inventory delta is unnecessary.

## Architecture reconciliation

Read accepted ADR-081226-a66b (one execution hierarchy), ADR-081626-f383
(store-owned execution fencing), ADR-082526-b36a (renewal/reclaim, extending the
previous fence contract), ADR-085 (per-principal limiting), and proposed ADR-081
(deployment/DR). Admission deduplication is not physical-work uniqueness, and a
proposed deployment ADR is not an acceptance waiver. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing authority introduced.

The production application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates
an `InMemoryRateLimiter` per instance (`api/rate_limit.py:93`). The freshly
executed `tests/test_soak_promotion_gates.py:439` demonstrates the same identity
receives `[200, 200, 429]` independently on each instance. This is documented
local enforcement, not evidence of the issue's replica-selection non-bypass
criterion. No authorization-path redesign is justified in a CI ledger repair.

## Acceptance disposition: BLOCKED

| Criterion | Freshly checked evidence / limit |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:147` explicitly lacks concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas, Goal/background workers; no selected-RC applicability justification supplied. |
| Two production replicas | **UNVERIFIED** for this candidate. `deploy/docker-compose.prod.yml:26` and `:77` define two application services; the executed ASGI middleware tests do not deploy them. |
| Sustained saturation, queue growth, reclaim, retries, leaks, restart | **UNVERIFIED**. No long production run executed; historical round-30 evidence fails the current duration gate. |
| Physical-work uniqueness across replicas | **UNVERIFIED**. Backpressure tests explicitly start no executor; the profile's schedule admission probe cancels the queued Run rather than executing work. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**; independent per-replica allowances reproduced by the production-middleware test. Local backpressure passes but does not prove cluster-wide enforcement. |
| Complete production telemetry with thresholds | **UNVERIFIED**. Profile distinguishes driver-loop lag from application-loop lag and acknowledges missing sustained pool/reclaim/leak observations. |
| Active-work kill/restart and recovery | **UNVERIFIED**. No exact-RC active-work restart executed; process rejoin and terminal Run counts alone are insufficient. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**, current runner explicitly ineligible. Executed importlib probe of `run_soak.py` against `evidence/m3a-round30-shakedown.json`: failures exactly `sustain_duration`, `exact_rc_artifact`; current `preflight_artifact_check()` returns false. |
| Findings reclassified to earliest broken milestone | **UNVERIFIED** completeness. This report records blockers; no GitHub mutations permitted or performed. |
| Published hash-bound machine/human production evidence | **UNVERIFIED** for this candidate. Validation logs and this handoff are not a production soak or proof of artifact identity. |

Artifact probe log: job directory `worker-artifact.log`. This directly executes
current gate logic, not a prior verification claim. The reference Compose builds
from source and requires operator gateway/configuration inputs; no immutable
promotion RC/configuration was assigned. The existing host runner uses pg18
(`run_soak.py:54`), unlike the reference Compose pg17 (`docker-compose.prod.yml:81`),
another reason not to equate host preflight with the promoted topology.

## Changes and next action

Only this report changed. No production code, tests, inventory, ledger, grants,
or inherited branch changes were modified. The requested vulture repair and
historical schema failure have no current failing evidence to repair.

Supply the immutable promotion RC/configuration and a production-topology runner
covering the missing workload and physical-work/recovery probes. Reconcile the
replica-selection rate budget through the existing authorization path. Then run
the minimum four-hour profile with complete production telemetry and hash-bound
evidence. Repeating the passing CI checks or lengthening the host preflight
cannot establish acceptance. No production soak was attempted in this round.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
This local handoff is not integration approval. `git diff --check` and local
commit verification are the final checks.
