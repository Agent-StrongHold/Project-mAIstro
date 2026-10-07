# Issue #860 repair checkpoint

Scope snapshot: issue #860 only, branch `auto-860`, starting HEAD
`77edfe72e1880df6b2aefaa1b6f0067e127c15c1`, supplied develop base
`28614700bd9ab0223eac06924a204af4a5cc25d9`.

Incoming state: an unfinished merge of the exact supplied base, with one
unmerged file, `.gitleaksignore`. Preserved unstaged and staged changes in
`/home/dev/Git/wt/incoming-860.patch` and `incoming-860-index.patch`.
No incoming work will be discarded. The existing merge already targets the
frozen base; finish that merge rather than moving to a newly fetched base.

Repair scope: resolve `.gitleaksignore` preserving both sides, run the requested
exact vulture gate and review retained identities in
`quality/vulture-baseline.json`, validate the existing #860 soak implementation,
and document evidence here. No unrelated issue implementation or ledger edits.
No test additions planned unless validation identifies a scoped regression.

The job directory contains no `check-*.log` files at intake. Read the supplied
prior failure artifacts instead. Issue acceptance includes an exact-RC long
soak; passing local unit tests alone cannot prove promotion readiness.

## Conflict and ledger repair results

Resolved `.gitleaksignore` by retaining both sets of historical fingerprints
and removing only merge markers. `uv run pytest
tests/test_gitleaksignore_contract.py -x -q` passed (log:
`/tmp/860-conflict-contract.log`). The file is staged as resolved.

The exact requested vulture scan passed (`/tmp/860-vulture-initial.log`).
`git diff --numstat 28614700bd9ab0223eac06924a204af4a5cc25d9 -- quality/`
was empty: the merged ledgers equal the frozen develop base, with no lost
rows. There are no unbanked identities to amend; no speculative ledger edit
is warranted. The supplied old schema failure expected 21 statements and
observed 24; inspect and rerun the current regression before treating that
historical failure as actionable.

## Fresh validation

Commands used 600–1,200 second tool timeouts. Logs are local `/tmp/860-*.log`
artifacts; the outcomes below are recorded durably here.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | PASS (`860-sync.log`) |
| `uv run ruff check .` | PASS (`860-ruff.log`) |
| `uv run ruff format --check .` | PASS, 3,151 files (`860-format.log`) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,328 findings, zero unclassified/never-allowlist (`860-vulture-initial.log`); matches CI arguments |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 PostgreSQL-dependent skips (`860-schema.log`) |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 108 passed (`860-acceptance.log`) |
| `uv run python scripts/check-merge-markers.py` | PASS (`860-merge-markers.log`) |
| `git diff --check && git diff --cached --check` | Unstaged PASS; staged reports an incoming develop blank line at EOF in `docs/testing/inventory-notes/1335-attempt-toctou-cancellation-fence.md:109`. Preserved unchanged; not a #860 source/test defect. The chained commit did not execute; commit retried separately. |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28,959 unique identities, no duplicate evidence (`860-inventory.log`) |
| `uv run python -` importing the current soak driver and evaluating `m3a-round30-shakedown.json` | PASS: rejected for duration and artifact identity (`860-evidence-evaluation.log`); historical evidence evaluation, not a new soak |

The old failing test already independently enumerates all 24 DDL statements,
including the three Gauntlet audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:173-177`.
`PgLearningStore.ensure_schema()` retains its transaction-scoped advisory lock
before DDL (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`).
No test assertion needed repair. No new tests were added, so no inventory delta
was introduced by this repair. Incoming develop tests and inventory notes were
preserved with the merge.

## Architecture and acceptance disposition

Read repository instructions, `docs/README.md`, accepted ADR-032, ADR-062
(including its retired entry-point warning), and ADR-081626-f383. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. The lease ADR guarantees durable
execution authority and stale-writer rejection, not blanket exactly-once
physical side effects. Receipt deduplication is not a substitute for recovery
and physical-work evidence. No new execution or authorization authority was
introduced, and no gate, runtime configuration or historical evidence changed.

| #860 acceptance criterion | Current evidence / remaining blocker |
| --- | --- |
| Representative users/Workspaces, Graph fan-out, schedules, queue, tool/model, Canvas/Design and worker profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:153-172` explicitly lists missing classes; no selected-RC justification closes them. |
| At least two application replicas in supported production topology | **UNVERIFIED live.** Executed ASGI tests exercise two middleware instances, not two deployed RC images. |
| Sustained saturation, growth, expiry/reclaim, retry and leak/shutdown observations | **UNVERIFIED.** No new sustained run; existing sampler tests cannot prove a long production window. |
| No duplicated physical work for schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED.** Admission tests cover the canonical seam, not physical workers; the profile's schedule probe cancels its queued Run without executing it. |
| Concurrent rate/security/degraded behavior without replica-selection bypass | **Not proven.** `tests/test_soak_promotion_gates.py:439-488` freshly demonstrates independent allowances for the same authenticated/unauthenticated identity on two real middleware instances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:31-36` documents process-local budgets, and `main.py:648` installs that middleware. Broader deployed behavior remains **UNVERIFIED**; do not silently redefine the issue's non-bypass criterion. |
| PostgreSQL/query/lock, application-loop, worker/process/RSS/FD, queue/error/timeout telemetry and thresholds | **UNVERIFIED at promotion grade.** Driver-loop latency is not application-loop latency; no new complete RC telemetry series. |
| Active-work kill/restart, drain/fencing/recovery without loss/duplication | **UNVERIFIED.** Boot/promotion regressions pass, but no active Attempt was killed and recovered in production this round. |
| Long exact-RC/config soak, repeated after changes | **Not met by evaluated evidence.** Historical round 30 lasted 420.08 seconds versus 14,400 required. `scripts/soak/run_soak.py:730-741` unconditionally rejects the host-process topology as exact-RC evidence. |
| Findings filed/reclassified to earliest broken milestone | **UNVERIFIED for completeness.** Existing findings are retained; no GitHub mutations are permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for a promotion RC.** Existing historical JSON is rejected by the current artifact gate; this handoff is repair evidence only. |

## Handoff

**BLOCKED for issue acceptance.** The develop merge conflict is repaired and
focused validation passes. The stale schema failure and ledger scan are not
currently actionable defects. Further deterministic reruns cannot produce the
missing exact-artifact soak. Next: select immutable RC/configuration, complete
representative workload and telemetry/physical-work oracles, resolve the
replica-selection budget requirement, then run at least four hours against
that exact production artifact. Runtime changes require a new soak.

This round changes only the conflict resolution in `.gitleaksignore` and this
handoff beyond the preserved incoming develop merge. No ledger amendment was
necessary; no tests, production code, grants or gates were altered by the
repair. The merge is committed locally, not pushed or approved for integration.
Issue progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}.
