# Issue #860 — repair checkpoint (9f01271d)

## Frozen scope

One item: issue #860 from the supplied dispatch snapshot. Worktree
`/home/dev/Git/wt/auto-860`, branch `auto-860`, initially clean at
`4d5c385b9ab2abb40f57eb840e02b2fe4722face`; supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2` resolves.

Inputs frozen for this round: supplied dispatch-context.json, prior result and
check-3.log; repository instructions; ADRs 085, 073126-c4e1, 081626-f383,
081426-1f7c and 082526-b36a; soak harness/profile/promotion tests;
PgLearningStore source/tests; production rate middleware/task router and
backpressure tests; vulture checker/workflow.

Permitted edits: this report, and only reproduced defects in the above files
with associated inventory notes; vulture ledger only for actual reviewed
scanner findings. No GitHub mutation or unrelated repair. No new test means
no inventory delta. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.

Initial evidence: no check-*.log files were present in this job directory.
The supplied prior check-3.log reports 24 DDL calls versus 21 expected.
Prior result is BLOCKED, not a develop-sync conflict. No merge is warranted.
Ambiguity: no designated immutable RC/configuration is established by the
assignment. A source HEAD alone is not assumed to designate an RC.

## Fresh validation checkpoint

All commands below completed with 1200-second timeouts against the starting
source HEAD (only this report changed):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities / 1323 findings; zero unclassified or forbidden. Gate selected baseline `4aa68edc0b6b`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q`: 103 passed, 6 skipped in 2.44s.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: PASS (component existence, not deployment evidence).
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified/discovered lifecycles.

The supplied schema failure does not reproduce. The requested exact vulture
scan has no unbanked identities; no evidence warrants a ledger amendment.

## Source and contract review

The schema test independently enumerates the three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:174–176`; production
fences its upgrades with the transaction/advisory lock at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
The old 21-versus-24 failure is already addressed in the starting tree.

The executed two-instance regression at `tests/test_soak_promotion_gates.py:439`
uses production middleware and demonstrates `[200, 200, 429]` independently on
each replica for the same identity. Switching replicas adds allowance. Production
constructs an `InMemoryRateLimiter` per middleware instance at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:95`. This proves
local enforcement, not the issue's replica-selection non-bypass requirement.
ADR-085 requires per-principal identity but does not prescribe a shared backend;
the #842 contract in that module explicitly permits N-times local allowance.
This contract boundary remains unresolved; do not waive #860 acceptance or
invent another authorization path to force it green.

`scripts/soak/run_soak.py:730` always rejects its host preflight as exact-RC
evidence. Executed CLI tests reject missing/null/preflight artifact records
even with synthetic four-hour results. No four-hour live run occurred here.
The process sampler regression uses a real uv child; HTTP receipt/admission
fixtures and boot-cleanup fixtures do not execute production physical Attempts.
The backpressure test does exercise the production router/queue and in-memory
canonical spine, including 429/Retry-After, per-principal isolation and retry.

ADR reconciliation: accepted release ADR 073126-c4e1 requires final artifacts
to be the soaked RC artifacts. ExecutionRuntime ADR 081426-1f7c owns mechanics,
not domain authority. Fencing ADR 081626-f383 assigns lease authority to the Run
store; later accepted ADR 082526-b36a adds renewal/reclaim. A receipt race or
process rejoin alone cannot prove that physical-work contract. No authority or
runtime changes were made in this round.

## Acceptance accounting

| Issue criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative release profile | **UNVERIFIED**. Existing profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background work (`m3a-load-profile.md:152`). RC applicability is not established. |
| At least two supported production replicas | **UNVERIFIED**. Executed tests use two middleware instances, not deployed RC replicas. |
| Sustained saturation, queue, reclaim, retry, leak and restart observations | **UNVERIFIED**. Real child sampler passes; no sustained RC run. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Receipt-probe tests do not execute physical effects or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED** overall; shared-allowance interpretation falsified by the executed production-middleware regression. Local limiting/backpressure pass. |
| Complete DB/loop/process/RSS/fd/queue/error telemetry with thresholds | **UNVERIFIED** at RC grade. Driver-loop latency and probe latency do not prove application-loop health or pool saturation. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests are not active-work recovery evidence. |
| Long-running exact RC/configuration; rerun after changes | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration established; host preflight correctly fails closed. |
| Findings filed/reclassified before promotion | Local classification only: allowance semantics is a security-contract prerequisite; missing physical-work/fencing evidence is an execution-correctness prerequisite. External filing **UNVERIFIED**; no GitHub mutation permitted. |
| Published machine/human evidence bound to artifact/config hashes | **UNVERIFIED**. This report binds focused checks to source HEAD, not a long-running RC artifact/configuration. |

## Disposition

**BLOCKED**. No reproduced CI defect or unbanked vulture identity exists to
repair. Only this report changed; no tests added and no inventory delta or
ledger edit is warranted. Inherited work is preserved. Commit locally only.

Next action is not another identical CI-repair dispatch: the release owner must
supply the designated RC artifact/configuration and resolve the replica-budget
contract. Then complete production workload/telemetry coverage and run the long
soak against that artifact. No deployment, live DB test or external filing is
claimed here; six database tests were skipped.

Progress: checked 1, done 0 (acceptance blocked), skipped 0 items, validation
errors 0; next: release prerequisites and production soak.
