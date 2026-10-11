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

## Independent revalidation — job 0463f353

This follow-up preserves the original checkpoint rather than adding another
near-identical handoff. Frozen item: #860 only, branch `auto-860`, clean starting
HEAD `5c65f3c9fc10e358722ee27be332e0dac86d25ee`, assigned base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Read the supplied issue acceptance,
prior result, actual historical `98a11313/check-3.log`, repository instructions,
and the five accepted ADRs listed above. The current job supplied no
`check-*.log` files. No conflict or uncommitted work required salvage or merging.

Fresh commands (1200-second timeouts), not inherited verification claims:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings / 1323 reviewed identities; zero unclassified or forbidden; selected baseline `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped in 1.73s |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q` | 66 passed in 2.37s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run python scripts/check-deployment-claims.py` | PASS |
| `uv run python scripts/check-execution-lifecycles.py` | PASS |

Raw command output is in
`/home/dev/maistro/jobs/0463f353cac5497ab18e1f3aab5cf432/worker-*.log`.
The old 24-versus-21 schema assertion is already repaired: the current test
independently includes the three audit columns at lines 174–176, and production
still acquires its transaction-scoped advisory lock before the upgrades at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
No actual vulture finding warrants amending the ledger. This is a documentation
checkpoint only: no source/test/ledger changes and no inventory delta.

Acceptance was checked against the reachable harness and production middleware,
not inferred from passing gates:

1. Representative profile: **UNVERIFIED**. `m3a-load-profile.md:152` explicitly
   identifies missing users/Workspaces, Graph fan-out, successful model/tool,
   Design/Canvas and Goal/background workloads.
2. Two deployed RC replicas: **UNVERIFIED**; ASGI middleware instances are not
   deployed artifact evidence.
3. Sustained saturation/reclaim/retry/leak observations: **UNVERIFIED**; no
   sustained live run was executed in this round.
4. No duplicate physical work: **UNVERIFIED**; admission/receipt and schema
   tests do not prove physical Attempt fencing across deployed replicas.
5. Concurrent security/degraded behavior and replica non-bypass: local limiting
   and backpressure tests pass, but the executed regression at
   `tests/test_soak_promotion_gates.py:439` demonstrates fresh allowance on the
   second replica for the same identity. Cluster-wide non-bypass remains
   **UNVERIFIED**, and is falsified if interpreted as one shared allowance.
6. Complete telemetry with thresholds: **UNVERIFIED** at RC grade; sampler
   tests cannot establish application-loop health or sustained pool contention.
7. Active-work kill/restart, drain/fencing/recovery: **UNVERIFIED**; boot-cleanup
   tests do not prove recovery of physical work.
8. Long exact-RC soak: **BLOCKED / UNVERIFIED**. No immutable RC/configuration
   was designated in the assignment. Do not guess it from the source HEAD.
   `scripts/soak/run_soak.py:730` returns `ok: False` for its host-process
   artifact; executed promotion tests enforce this boundary.
9. Findings filed/reclassified: local classification remains security-contract
   scope and execution-correctness evidence prerequisites; external filing is
   **UNVERIFIED** and prohibited in this lane.
10. Hash-bound machine/human RC evidence: **UNVERIFIED**. The logs and this
    report bind focused validation to a source HEAD, not a promoted artifact.

ADR reconciliation remains unchanged: final artifacts must be the soaked RC
(ADR-073126-c4e1); execution mechanics cannot become domain authority
(ADR-081426-1f7c); the Run store owns fencing, with renewal/reclaim governed by
ADR-081626-f383 and ADR-082526-b36a. ADR-085 specifies principal identity, not a
shared limiter backend. Do not silently weaken #860's acceptance or introduce a
new authorization authority to reconcile the rate-budget ambiguity.

**Disposition: BLOCKED, not another CI defect.** Release-owner input must
establish the RC/configuration and replica-budget contract; representative
production workload/telemetry and a fresh long soak remain necessary. No live
DB or deployed RC acceptance is claimed. Checked 1 item; done 0 acceptance
items; skipped 0 items; validation errors 0. Only this checkpoint is committed.
