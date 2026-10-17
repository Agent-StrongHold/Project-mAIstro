# Issue #860 — repair checkpoint (job 7396ee0e)

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting head: `b5b2f2c5bac2a9c18ef4193ae03fa24bcdfb3b4c` (verified);
  supplied develop base: `cd5618223cbdd9ac55d40695987e09fd8b4ef184`.
- Starting worktree clean; no incoming edits to salvage.
- Evidence snapshot: supplied `dispatch-context.json` and prior result
  `c6b011fe0cb74483b9a395adb69bb767/result.json`. No GitHub refresh/mutation.
- No `check-*.log` files present in the supplied job directory at entry.
- Read scope: repository instructions, relevant runtime/release/rate-limit ADRs,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_prod_stack_boot_contract.py`, server rate-limit/task route and tests,
  PG learning schema fence and tests, load profile and retained soak evidence,
  vulture gate/ledger, CI gate configuration and inventory notes.
- Write scope: this checkpoint; source/ledger changes only if the exact vulture
  scan demonstrates an actionable identity within this repair. No speculative
  limiter redesign, scheduler, or promotion-evidence rewrite.
- Assumption: this is the assigned writer/CI-repair lane, not a read-only verifier.
  Existing BLOCKED claims must be rechecked, not inherited as proof.

## Progress

Exact requested vulture command executed successfully: 1,338 findings matched
1,338 reviewed identities, zero unclassified and zero never-allowlist findings.
No unbanked identities were reported. Consequently there is no evidenced
source deletion or ledger amendment to perform; the CI-repair exception is not
permission to invent debt. No promotion claim.

The supplied issue body has ten acceptance criteria. Inspection confirms the
current driver is explicitly a host-process preflight; its profile identifies
missing representative workloads and production telemetry. The rate middleware
constructs a process-local limiter. Existing tests exercise that actual middleware
and can demonstrate the replica-selection allowance gap; these will be rerun.
ADR-085 requires principal-keyed rate limiting, not an alternate authorization
path. ADR-081626-f383 assigns physical execution authority to canonical Attempt
leases, so admission identity alone cannot prove physical-work fencing.
ADR-073126-c4e1 requires promotion of validated RC artifacts, not a substitute
host-process topology. These contracts are preserved, not waived. ADR-082526-b36a adds canonical
heartbeat/reclaim behavior; it does not turn a single admission race into
sustained recovery proof.

Fresh validation: `uv run ruff check .` and `uv run ruff format --check .`
passed (2,943 files). Soak/Compose contract tests passed (60); server task
backpressure test passed (1). The core PG learning test failed at line 172:
`test_ensure_schema_fences_ddl_behind_advisory_lock` expected 8 statements but
observed 21. This is actual evidence in an existing #860 regression test;
inspect the schema evolution before deciding whether source or assertion is stale.
Write scope extended to that existing test and its inventory note. Inspection
found thirteen epistemic column upgrades already correctly inside the fence;
the test's independently enumerated SQL prefixes now cover all 21 statements.
No production schema or fence change. After repair, the PG learning file passes
(34 passed, 6 skipped: PostgreSQL integration not configured). Core inventory
passes with 13,377 collected identities and delta zero. Backlog consistency
passes (168 items).

`git diff --check cd5618223cbdd9ac55d40695987e09fd8b4ef184` found one actual
whitespace failure: `docs/testing/soak/issue-860-c6b011fe-repair.md:80`, blank
line at EOF. The older three whitespace findings in the dispatch did not recur.
Write scope extended only to remove that observed extra terminal blank line;
now removed without changing the prior report's content.

## Focused repair evidence

- Existing regression failed before the repair (21 statements versus 8), then
  passed with the thirteen additional explicit column prefixes. Counts and
  locking checks were not relaxed; runtime code is unchanged.
- In-memory mutation compiled the production `ensure_schema` method without
  its advisory-lock statement and ran the repaired test through `pytest.main`.
  It failed at line 154 (first SQL was `ALTER TABLE`, not the lock). The wrapper
  asserted `pytest.ExitCode.TESTS_FAILED` and exited successfully. No source
  file was mutated on disk.
- Directly evaluated retained `m3a-round6-shakedown.json` using the current
  `failed_promotion_checks`: failures are `sustain_duration` and
  `exact_rc_artifact`. Observed duration is 90.43 seconds, required 14,400.
  Directly called `preflight_artifact_check`: `ok=False`,
  `topology=host-uvicorn-preflight`. A longer preflight cannot satisfy this.

## Acceptance assessment

| #860 criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md:152-163` explicitly lacks multiple users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal reconciliation. |
| At least two production replicas | UNVERIFIED. Compose contract tests pass, but render/startup assertions are not a deployed two-replica soak. |
| Sustained saturation, queue growth, expiry/reclaim, retry, leaks | UNVERIFIED. Current evaluator rejects the retained 90.43-second shakedown against the four-hour minimum. No new production load run. |
| No duplicate physical work; schedules/admission/Goal reconciliation | UNVERIFIED. Existing admission probe tests pass; neither their HTTP fixtures nor one schedule admission race proves physical Attempt fencing and sustained reconciliation. Canonical spine unchanged. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance. Both authenticated and unauthenticated production-middleware tests returned 200,200,429 on each independent replica. `maistro_server/main.py:593` installs that middleware. The task-ceiling retry/backpressure regression passes, not a deployed security soak. |
| Complete thresholded telemetry | UNVERIFIED in production. Existing process-group sampler tests pass, including real wrapper/child resource allocation. Driver loop latency is not application loop latency; detached workers remain uncovered. |
| Kill/restart active work without loss/duplication | UNVERIFIED. No new production recovery run. Rejoin and terminal counts do not demonstrate physical-work safety. |
| Long-running exact RC artifact/config | NOT MET by available evidence. Current artifact evaluator fails closed; supplied work contains no exercised immutable production RC/config identity. |
| Findings classified before promotion | Backlog consistency passed (168 items). Completeness remains UNVERIFIED; no GitHub mutations or issue closure. |
| Human/machine evidence tied to exact hashes | UNVERIFIED for current production artifact. This report is validation of the stated source head plus the focused test repair, not hash-bound RC soak evidence. |

## Handoff

The stale schema-fence assertion and observed whitespace defect are repaired.
No reproducible vulture debt exists; leave `quality/vulture-baseline.json`
unchanged. No new tests or test IDs; inventory note records a zero delta.

Issue #860 remains **BLOCKED** for promotion. Required next work is an explicitly
selected immutable RC/configuration, production-path representative workloads and
telemetry, resolution of the replica-selection allowance gap, and a four-hour
recovery soak of that exact artifact. Do not keep dispatching a vulture-ledger
repair for this passing scan or treat these unit tests as promotion evidence.

Changed files in this round: the PG learning regression test,
`docs/testing/inventory-notes/m3a-860-epistemic-schema-fence.md`, this report, and
the EOF-only fix in `issue-860-c6b011fe-repair.md`. Production code, gates, ledger,
execution/authorization authorities and retained evidence are unchanged.

Progress: checked 1 assigned issue; done 1 focused test/whitespace repair;
skipped 0 assigned issues; 2 initial validation failures repaired. Acceptance
remains incomplete.

Final validation after repair (all exit 0):

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — 2,943 files formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  — 34 passed, 6 PostgreSQL integration skips.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — 1 passed.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  — 60 passed.
- `git diff --check cd5618223cbdd9ac55d40695987e09fd8b4ef184` — passed.

Earlier exact vulture, scoped core inventory and backlog gates also passed as
recorded above. No production PostgreSQL/Compose soak was executed; database
integration skips remain a validation limitation. Local commit follows; no push.
