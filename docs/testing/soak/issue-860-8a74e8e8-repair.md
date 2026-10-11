# Issue #860 — bounded repair validation (8a74e8e8)

## Frozen scope and initial checkpoint

- One item: #860 from the supplied dispatch-context.json; no GitHub refreshes.
- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, clean at
  `fbbacc4a7098731a6da723c056bea5bd7a2f1359`.
- Supplied base `435dc1937e0407ab4de198ffcced49860bb14ad2` resolves.
- Inputs: supplied prior result and failed check-3.log, repository instructions,
  ADRs 085, 073126-c4e1, 081626-f383, 081426-1f7c, 082526-b36a;
  `scripts/soak/run_soak.py`, `docs/testing/soak/m3a-load-profile.md`,
  `tests/test_soak_promotion_gates.py`, production rate middleware/main/task
  router, adjacent task backpressure and PgLearningStore tests/source,
  vulture checker and CI workflow.
- Permitted edits: this report; exact vulture ledger only for actual reviewed
  findings; the listed source/tests and associated inventory note only if a
  failure reproduces. No unrelated repair, execution authority or grant change.
- Current job directory supplied no check-*.log files. Prior check-3.log reports
  24 schema statements versus 21 expected; reproduce before changing tests.
- Ambiguity: a branch HEAD is not a release-owner-designated immutable RC.
  Assume no RC designation unless supplied evidence identifies one; do not
  manufacture promotion evidence or waive replica-selection non-bypass.
- Accepted release ADR requires the final artifacts to be the soaked RC
  artifacts. Fencing ADR assigns execution authority to the canonical Run store,
  not this harness. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.

## Results

Fresh validation on the assigned source HEAD (1200-second timeouts):

| Command | Executed outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings; zero unclassified or forbidden. Gate selected base `4aa68edc0b6b`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q` | 103 passed, 6 skipped in 2.58s. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3270 files. |
| `uv run python scripts/check-deployment-claims.py` | PASS. Existence check only, not deployment proof. |
| `uv run python scripts/check-execution-lifecycles.py` | PASS: 19 classified/discovered lifecycles. |

The reported schema failure does not reproduce. The independent expected DDL
list already includes the three validation audit fields at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:174–176`.
Production takes the advisory lock inside the transaction at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
No scan finding warrants a ledger amendment; changing the ledger despite this
result would be cosmetic, not the requested evidence-based repair.
The vulture invocation matches `.github/workflows/vulture-ratchet.yml:82–85`.

## Reachable behavior and acceptance accounting

Production installs `RateLimitMiddleware` at `maistro_server/main.py:648` and
constructs an in-memory limiter per instance at `api/rate_limit.py:95`.
The executed test at `tests/test_soak_promotion_gates.py:439` exhausts one
replica, then observes another accept the same identity: each returns
`[200, 200, 429]`. This falsifies a shared allowance interpretation of
non-bypass. ADR-085 mandates per-principal identity but does not select a
shared backend; the existing #842 contract explicitly documents process-local
limits. This unresolved contract boundary needs owner resolution, not an
invented authorization path or an acceptance waiver.

The task backpressure regression exercises the real router/queue/canonical
in-memory spine, including 429/Retry-After, separate principals and retry after
a slot frees. It does not execute physical Attempts against a database.
The sampler regression uses a real uv child, while admission HTTP responses
and four-hour CLI evidence are synthetic fixtures. Those tests prove harness
behavior only. `scripts/soak/run_soak.py:730` always rejects the host preflight
as an exact RC. The later accepted lease ADR (082526-b36a) adds renewal/reclaim
to 081626-f383; neither receipt deduplication nor process rejoin proves that
physical-work contract.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative users/Workspaces, request mix, fan-out, schedules, tools/models, Design/Canvas, workers | **UNVERIFIED**. Profile exists but explicitly lists missing workloads at `m3a-load-profile.md:152`; applicability to a designated RC remains unresolved. |
| At least two supported application replicas | **UNVERIFIED** at deployment grade. Executed tests use two middleware instances, not deployed RC replicas. |
| Sustained pool/queue/reclaim/retry/memory/descriptor/process/shutdown observations | **UNVERIFIED**. Real child sampler passed; no sustained RC run executed. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Receipt-probe regressions cannot establish physical Attempt effects or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Shared allowance interpretation falsified by the executed middleware test; local limiting and canonical backpressure pass. Full criterion **UNVERIFIED**. |
| Complete DB, event-loop, process, RSS, descriptor, queue and error telemetry with thresholds | **UNVERIFIED** at RC grade. Profile has thresholds; driver-loop and probe latency are not application-loop and pool-saturation measurements. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests do not prove active physical-work recovery. |
| Long-running exact RC/configuration, repeated after changes | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration established; host preflight guard correctly fails even synthetic four-hour evidence. |
| Findings filed/reclassified to earliest broken milestone invariant | Local classification: replica-selection semantics are a security-contract prerequisite; missing physical-work/fencing proof is an execution-correctness prerequisite. External filing **UNVERIFIED**; no GitHub mutations permitted. |
| Machine-readable and human-readable evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**. This report binds focused checks to source HEAD, not a long-running RC artifact/configuration. |

## Disposition and handoff

**BLOCKED**, not merge/promotion approval. There is no reproduced CI defect to
repair and no supplied immutable RC designation to soak. No production, test,
ledger or grant changes were made. Only this report changed; test inventory is
unchanged, so no inventory-delta note is required. All inherited work remains
preserved. Commit this report locally; do not repeat the same clean scan as a
substitute for release evidence.

Next: release owner supplies the exact RC/configuration and resolves the rate
allowance contract; complete representative workload coverage and execute the
production-topology long soak with physical Attempt effects and full telemetry.
No deployment, long soak, live DB test or external filing is claimed here.

Progress: checked 1, done 0 (acceptance incomplete), skipped 0, validation errors 0;
next: release prerequisites and production soak. Local report is the checkpoint.
