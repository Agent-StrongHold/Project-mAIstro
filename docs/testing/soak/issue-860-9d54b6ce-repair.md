# Issue #860 — CI-repair checkpoint (9d54b6ce)

## Frozen scope and initial result

Assigned writer worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
starting HEAD `67ed3c850879248e3a0e9caec0bc810a668eebd8`, develop base
`c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250`. Initial worktree was clean.
Only issue #860 and its explicit vulture CI-repair assignment are in scope.
The supplied dispatch and previous result are evidence, not verification.
No driver `check-*.log` files were present in the initial job-directory listing.

Executed the exact assigned command:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

PASS: 1342 findings match 1342 reviewed identities; zero unclassified and
never-allowlist findings. There are no demonstrated unbanked identities to
repair. The ledger-amendment instruction is interpreted as conditional on
actual retained unbanked findings, not permission to invent ledger churn.
No source, gate, ledger, grant or historical evidence change is justified by
this scan. Write scope is this handoff report only; no new tests or inventory
count changes are planned.

## Architecture and acceptance reconciliation

Read repository instructions, the documentation authority map and accepted ADRs
`ADR-081426-1f7c`, `ADR-081626-f383`, `ADR-082426-82c7`, and `ADR-085`.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: physical execution is
identified by Attempt, and the canonical Run store owns fencing. Occurrence
admission uniqueness does not establish physical-work uniqueness. The accepted
fencing ADR explicitly leaves expiry takeover undefined; do not invent a
reclaim scheduler to satisfy the issue wording.

Production rate limiting intentionally has process-local budgets
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30,72-78`).
The existing counterexample executes that actual middleware with the same
principal/IP on two instances and observes `[200, 200, 429]` independently on
each. This proves local enforcement, not replica-selection non-bypass of a
cluster-wide allowance. Resolving that contract discrepancy is not a vulture
ledger repair or permission to add another authorization path.

## Executed validation

Worker logs reside in job directory
`/home/dev/maistro/jobs/9d54b6ce033c4192a239fbf79d9a195a` as
`check-*-worker.log`; these are locally executed checks, not supplied driver logs.

| Command | Outcome |
| --- | --- |
| Exact vulture command above | PASS: 1342/1342; invocation confirmed against both CI workflows |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2985 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 95 passed, 6 skipped; skips are not acceptance evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS: 168 items |
| `uv run python scripts/check-doc-links.py` | PASS: zero broken relative links |
| `git diff --check c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250...HEAD` | PASS at starting HEAD; prior whitespace failure not reproduced |

An additional `uv run python` evaluation imported the current soak module and
asserted that retained `m3a-round6-shakedown.json` fails exactly
`sustain_duration` and `exact_rc_artifact`. It also asserted the current
`preflight_artifact_check()` returns false and the recorded 90.43-second window
is shorter than the required 14400 seconds. The retained hash record identifies
`b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned starting HEAD.
No new deployed load or recovery run was executed. Passing test fixtures and
historical JSON are not being relabeled as production soak proof.

## Every issue acceptance criterion

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:152-167` explicitly lacks users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and background reconciliation coverage. |
| At least two application replicas | UNVERIFIED for current RC: production Compose declares two replicas; passing boot-contract tests render/check configuration, not deployed traffic. |
| Sustained saturation, growth, expiry/reclaim, retry and leaks | UNVERIFIED: executed evaluator rejects the historical 90.43-second window; no long production run executed. Reclaim must respect the accepted ADR boundary. |
| Schedule/Run/Attempt and Goal physical-work uniqueness | UNVERIFIED: meaningful admission tests pass, but the historical schedule probe cancels its Run without physical execution (`evidence/m3a-round6-shakedown.json:11-15`). |
| Security/degraded behavior without replica-selection bypass | NOT MET as a cluster-wide allowance claim: passing production-middleware counterexamples at `tests/test_soak_promotion_gates.py:439-488` demonstrate fresh allowance on replica 2. Backpressure regression passes but does not prove all concurrent security behavior. |
| Full telemetry and thresholds | UNVERIFIED: process-group sampler tests pass; application-loop latency, worker coverage and sustained production measurements remain absent (`m3a-load-profile.md:158-167`). |
| Kill/restart active work with drain/fencing/recovery | UNVERIFIED: no current deployed recovery observation; historical process rejoin and terminal Run counts do not prove physical loss/duplication absent. |
| Long-running exact RC/config soak | NOT MET: `scripts/soak/run_soak.py:635-646` rejects host-process artifact equivalence; CLI regression tests prove even four-hour synthetic evidence cannot override this. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness; no new load findings or GitHub mutations in this round. Existing historical finding records do not establish complete classification. |
| Machine/human evidence bound to exact image/package/commit/config | UNVERIFIED for current RC: existing hashes describe an older preflight, not current application images. This report is validation evidence only. |

## Handoff

**BLOCKED**, not a reproduced CI ledger defect. Only this report changed. No
new tests were added, so no inventory delta is required. The previous acceptance
block remains unresolved: a representative production-path runner, immutable RC
image/config selection, physical Attempt/recovery observations, complete metrics
and a new long soak are still required. Do not repeat the vulture repair lane
without a new failed identity scan; a passing ledger cannot fix missing release
proof. No gates were weakened, no history discarded, and no remote mutations
performed. Local commit is a handoff, never integration approval.

Progress: checked 1, done 0 acceptance completions, skipped 0 issues, errors 0
validation-command failures; next: production-soak prerequisite work, not another
speculative ledger amendment.
