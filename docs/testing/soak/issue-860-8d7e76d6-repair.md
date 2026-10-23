# Issue #860 — repair checkpoint (job 8d7e76d6)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD verified: `e557f9ab1b7733d89314d1b2817ceae74c577b5b`.
- Supplied develop base: `658a8f78c1800d264759a81dc8d87dd447f0f7f2`.
- Worktree initially clean. No incoming edits to salvage.
- Snapshot: supplied `dispatch-context.json`; no GitHub refresh or mutations.
- Repair targets: actual exact-debt-ledger failures in `quality/vulture-baseline.json`
  and implicated production identities only, plus this evidence report. Additional
  source/test edits require actual validation evidence; no scheduler/authority changes.
- Inspect existing soak harness, adjacent tests, relevant ADRs and supplied prior
  evidence; validate #860 acceptance without claiming a new RC soak.
- No `check-*.log` files were present in the supplied job directory at start.

## Assumption and status

This is the explicit writer/CI-repair lane, not the read-only verifier lane.
The permitted ledger amendment does not authorize weakening promotion gates or
claiming that historical shakedowns prove the assigned RC.

## Initial result

The exact requested vulture command exited 0; there is no reproduced ledger
failure to repair. No ledger amendment or production change is justified by
that result. The prior job result is BLOCKED, not an unresolved merge conflict.
The supplied base resolves locally. Current acceptance validation is pending;
the profile explicitly identifies the host-uvicorn runner as non-promotional.

Fresh lint/format and branch whitespace checks all exited 0 (`uv run ruff check
.`, `uv run ruff format --check .`, `git diff --check
658a8f78c1800d264759a81dc8d87dd447f0f7f2...HEAD`). The prior reported EOF
whitespace failure does not reproduce against the supplied base. Vulture reports
1338 findings / 1338 reviewed identities, no unclassified or prohibited identities;
its resolved trusted base is `cd5618223cbd`, recorded rather than conflated with
the dispatch base. Logs are retained in the assigned job directory.

`uv run pytest tests/test_soak_promotion_gates.py
tests/test_prod_stack_boot_contract.py -x -q` passed **60 tests**. This includes
real production middleware counterexamples (same principal/IP exhausts replica
1 yet receives fresh allowance on replica 2), fail-closed four-hour preflight
checks, and a real uv child process resource-sampling test. Compose contract
tests render configuration; they do not boot the production deployment.
`uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
-x -q` passed **1 test**. `uv run python scripts/check-backlog-consistency.py`
exited 0. These are fresh local results, not copied verification claims.

Architecture reconciliation: accepted ADR-085 requires per-principal rate
limiting, while production middleware explicitly documents process-local limits.
This does not prove #860's stronger replica-selection non-bypass criterion.
Accepted ADR-081626-f383 and ADR-082526-b36a require canonical Attempt fencing
and renewal/reclaim; admission counts alone do not prove physical-work safety.
ADR-081 remains Proposed and cannot waive acceptance. No execution, scheduling,
Goal, authorization, or event authority is changed.

The current evaluator was also executed against retained
`evidence/m3a-round6-shakedown.json`: **90.43 s** versus **14400 s** required;
failed checks are `sustain_duration` and `exact_rc_artifact`. Its reported
`artifact` field is absent, not proof of a current RC identity. Its actual
`hashes.git_head` is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this
lane's starting HEAD; no historical hash was rewritten.
Additional CI commands exited 0:

- `uv run python scripts/check-ratchet-provenance.py` (49 consumers;
  pre-existing syntax/CORS warnings, no gate failure).
- `uv run python scripts/check-shipped-surface-truth.py`.
- `uv run python scripts/check-suite-inventory.py` (15 suites, 26365 unique
  collected identities; collection is not execution).

No tests were added or changed, so no inventory delta note is needed.

## Acceptance review (all ten issue criteria)

| Criterion | Fresh evidence and remaining status |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. Profile lines 152–165 explicitly leave users/Workspaces, Graph fan-out, successful tools/models, Canvas and Goal workers uncovered. |
| At least two application replicas | **UNVERIFIED on the RC**. Compose configuration has two services and contract tests pass; ASGI instances and historical host processes are not an executed production deployment. |
| Sustained saturation, reclaim, retry and leak observations | **UNVERIFIED**. Re-evaluated retained evidence lasts only 90.43 s; no new sustained run was executed. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. Existing admission tests pass, but retained schedule evidence lines 12–16 cancels the probe Run rather than executing it. Physical fencing/reconciliation needs a production-path workload. |
| Security/degradation and no replica-selection bypass | **NOT MET as written**. Executed authenticated and unauthenticated middleware counterexamples show independent allowances. `main.py:593` installs this middleware; `rate_limit.py:72` creates an in-memory limiter per instance. The passing local enforcement tests are not a cluster-budget proof. |
| Complete telemetry with thresholds | **UNVERIFIED**. Sampler tests pass, but `run_soak.py:1305–1312` measures driver-loop lag, not application-loop latency. Profile lines 157–165 acknowledge missing worker/pool/lease/leak evidence. |
| Active-work replica kill/restart and drain/fencing/recovery | **UNVERIFIED**. Historical exit/rejoin summaries do not prove physical-work ownership or recovery on this RC; config assertions are not live restart tests. |
| Long-running exact RC artifact/configuration | **NOT MET**. Current evaluator rejects historical duration/artifact; `run_soak.py:635–646,1465` always marks its host-process topology non-promotional. |
| Findings classified before promotion | **PARTIAL; completeness UNVERIFIED**. `BACKLOG.md:267–280` records the cluster-budget gap and the backlog consistency gate passes. No GitHub mutations or new issue filings were performed. |
| Machine/human evidence tied to current artifact/config hashes | **UNVERIFIED**. Retained JSON and prose exist but target `b31c5fdaa63b…`; no current immutable application image/production configuration soak was produced. |

## Handoff

**BLOCKED**, not a CI-ledger repair success or release approval. Changed file:
this report only. No production, test, ledger, grant, gate or historical evidence
changes were justified. All executed validation commands passed, but the tests
prove limited contracts and counterexamples, not the missing soak acceptance.
No new services or background processes were started by this worker outside the
existing tests' managed subprocesses.

Do not repeat the same exact-debt-ledger repair dispatch without a new failing
identity log: the requested gate already passes. Next work requires an agreed
cluster-budget contract (existing `engine-116` gap), a production-Compose-aware
runner covering the omitted workloads/telemetry, and a selected immutable RC
image/configuration followed by a fresh >=4-hour run and physical-work recovery
observations. None can be replaced by banking scanner identities or relabeling
the host preflight.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
validation command errors 0; next: unblock the production soak prerequisites.
Local evidence checkpoint is committed; no push, PR, merge, or issue mutation.
