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

## Fresh CI-repair review — job 536c66a5

Frozen scope: #860 only, clean `auto-860` at
`99b9e7e54d27b00cdcf70eb512f4cee9e2480ea2`, supplied base unchanged.
This is a writer validation checkpoint, not promotion approval. No merge was
pending. No current driver `check-*.log` files were supplied. Read the captured
issue acceptance and PR evidence in `dispatch-context.json`, the supplied prior
result, and the actual historical `98a11313/check-3.log` failure rather than
assuming the previous report was correct.

### Executed validation

Logs are in `/home/dev/maistro/jobs/536c66a5d3ab48c1a2801d7cf497f9d5/`.
Commands ran with 600–1,200 second timeouts.

| Command | Fresh result / log |
| --- | --- |
| `uv sync --locked --extra dev` | PASS; `worker-sync.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 findings, zero unclassified/never-allowlist; trusted base `28614700bd9a`, candidate `99b9e7e54d27`; `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `worker-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 108 passed; `worker-acceptance.log` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3,151 files; `worker-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 28,959 unique identities; `worker-inventory.log` |
| `uv run python scripts/check-merge-markers.py` | PASS; `worker-merge-markers.log` |
| `uv run python -` importing `scripts/soak/run_soak.py` and asserting historical round-30 rejection | PASS; `worker-evidence-evaluation.json`: `sustain_duration` and `exact_rc_artifact` fail |
| `git diff --check` | PASS before this documentation update; repeated before commit |

The schema failure is **not reproducible** at the assigned HEAD: the independent
DDL expectation already covers the three added audit columns. The production
transaction and advisory lock remain in `PgLearningStore.ensure_schema()`.
The exact vulture command matches `.github/workflows/vulture-ratchet.yml:82-86`
and reports no identities to repair or bank. Ledger amendment permission does
not justify inventing a change to a passing exact-debt ledger.

Production reachability was checked at `maistro_server/main.py:648`, which
installs `RateLimitMiddleware`. Its constructor creates a process-local limiter
(`api/rate_limit.py:95-100`). The executed two-instance tests at
`tests/test_soak_promotion_gates.py:439-488` demonstrate separate allowances
for both credentialed and pre-auth identities. This is not merely a mocked
429 assertion, but it is also not a deployed security soak. An attempted
lookup of `maistro_server/lifespan.py` returned not found; skipped that path,
with no claim of startup-path validation from it.

### Acceptance disposition (fresh review)

1. **Representative workload: UNVERIFIED.** The existing profile explicitly
   omits users/Workspaces, fan-out, successful tool/model traffic, Design/Canvas
   and sustained Goal reconciliation (`m3a-load-profile.md:153-172`). No RC
   selection was supplied to justify exclusions.
2. **Two production replicas: UNVERIFIED.** ASGI middleware instances in the
   executed tests are not deployed immutable RC replicas.
3. **Sustained saturation/reclaim/retry/leak observations: UNVERIFIED.** No
   long production run executed in this repair; short historical evidence
   cannot establish these properties.
4. **Physical-work deduplication and Goal reconciliation: UNVERIFIED.** The
   executed admission/backpressure tests leave Runs queued; receipt identity
   and single-occurrence admission do not observe physical worker effects.
5. **Replica-selection non-bypass/security/degradation: NOT PROVEN.** Fresh
   tests demonstrate independent process allowances; broader deployed
   enforcement remains UNVERIFIED. Do not redefine non-bypass as local 429s.
6. **Complete production telemetry and thresholds: UNVERIFIED.** Driver-loop
   latency is not application-loop latency; sampler tests do not provide an
   exact-RC telemetry series.
7. **Active-work restart/drain/fencing/recovery: UNVERIFIED.** No live Attempt
   was killed and recovered this round.
8. **Long exact-RC soak: NOT MET by evaluated evidence.** The current evaluator
   rejects round 30: 420.08 seconds versus 14,400 required, and host-process
   topology instead of the production artifact (`run_soak.py:730-741`).
9. **Finding filing/reclassification completeness: UNVERIFIED.** Existing
   findings preserved; no GitHub mutations performed.
10. **Exact image/package/commit/config-bound publication: UNVERIFIED for
    promotion.** Historical JSON was evaluated, not replaced or re-labelled
    as new RC evidence. This checkpoint is repair-validation evidence only.

Read accepted ADR-032, ADR-062 (including the retired entry-point warning),
and ADR-081626-f383. ADR-081 is **Proposed**, not accepted authority. The
accepted lease contract guarantees stale-writer rejection, not blanket
exactly-once physical side effects; issue #860 still requires observations at
those boundaries. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.

**BLOCKED for issue acceptance.** There is no evidenced schema or ledger defect
left to repair in this round. Only this existing handoff file changes; no
production code, runtime configuration, tests, historical evidence or quality
ledgers change. No test inventory delta is needed. Next: select immutable RC
and configuration, complete workload/telemetry/physical-work oracles, reconcile
the replica-budget requirement, then execute the required production soak.
Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}.
