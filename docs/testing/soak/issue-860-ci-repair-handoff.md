# Issue #860 CI repair handoff

## Current checkpoint — job 5af6c6f2

Frozen scope: issue #860; assigned `auto-860` worktree; reported schema-fence
failure, exact vulture gate, existing soak acceptance surfaces, and this handoff.
Starting HEAD `8835071663ae48168b5a3afbf5d05f3d929a734a` verified; tree clean.
Supplied base `2154f845347c9541016288c760f8da3f5cd2e064` resolves. No merge
conflict exists. Read local dispatch evidence, prior result, and the cited
`98a11313167b41a98a420abfda80c292/check-3.log`; this job directory had no
`check-*.log` files. No GitHub operations performed.

Assumption: repair actual reproducible CI defects, not select an arbitrary RC
or turn a preflight emulator into release evidence. Read repository instructions,
accepted ADR-085 and ADR-082826-b601, the current runner/profile, production
rate middleware and adjacent tests. Preserve Goal -> Graph -> Run -> NodeRun ->
Attempt. Admission uniqueness is not physical execution proof; per-principal
keys do not establish shared replica budgets. No architectural waiver inferred.

Fresh validation (1,200-second command timeouts):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,323 reviewed identities / findings; zero unclassified or never-allowlist findings. Selected comparison base `3c761d14db94`. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS, 37 passed, 6 skipped. The reported 24-versus-21 DDL mismatch is already repaired: test lines 175–177 include the audit columns. Skipped PostgreSQL coverage is not proof of concurrent database boot.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 81 passed. Includes actual production middleware replica-selection probes, receipt-router probes and CLI promotion-gate regressions; not a deployed soak.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,277 files formatted.
- `uv run python scripts/check-doc-links.py`: PASS, 2,704 Markdown files, zero broken relative links (before this handoff-only update).

Acceptance checked against current reachable behavior, not historical pass claims:

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: `m3a-load-profile.md` lists missing users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. |
| Two production replicas | **UNVERIFIED**: two middleware instances are not deployed RC applications. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED**: no sustained production experiment executed. |
| Physical-work deduplication and Goal reconciliation | **UNVERIFIED**: schedule probe cancels its queued Run; admission counts are not execution oracles. |
| Replica-selection non-bypass/security/degraded behavior | **Not proven**: executed `tests/test_soak_promotion_gates.py:439` demonstrates fresh 200/200/429 allowance on each replica for the same identity. `rate_limit.py:94` constructs per-instance in-memory state; deployment-level security/degraded soak remains **UNVERIFIED**. |
| Complete telemetry and thresholds | **UNVERIFIED**: driver-loop lag is not application-loop lag; profile explicitly leaves required observations incomplete. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**: regression tests do not perform a production active-work recovery experiment. |
| Long-running exact RC/config soak | **UNVERIFIED**: `run_soak.py:744` rejects this host runner as exact artifact evidence even at four hours; executed CLI regressions preserve that gate. |
| Findings filed/reclassified | **UNVERIFIED** this round: limitations recorded locally; no new load experiment or remote filing. |
| Hash-bound machine/human production evidence | **UNVERIFIED**: fresh tests identify source behavior, not an immutable RC image/config soak. |

**BLOCKED.** No source/test/gate/ledger change is evidence-backed; only this
handoff changes, with no test inventory delta. The prior acceptance block is
not resolved by passing CI. Required next input: selected immutable RC image and
configuration, representative production-path workloads and physical-work/
recovery/telemetry oracles, resolution of replica-budget semantics, then a
qualifying >=4-hour soak. Do not redispatch the historical schema assertion as
an unfixed defect. Local writer checkpoint only, not integration approval.

Progress: checked 1 issue, acceptance-complete 0, skipped 0, validation errors 0;
next: exact-RC prerequisites and qualifying soak. Earlier checkpoints below are
preserved history, not substitutes for these freshly executed checks.

## Current checkpoint — job e73dc99b

This section supersedes the historical validation results below, not their
preserved evidence. Scope: issue #860 only, assigned `auto-860` worktree;
starting HEAD verified as `52df6ce565b1964c342bf93369ac3af9afa40868`, supplied
base `2154f845347c9541016288c760f8da3f5cd2e064` resolves. Initial tree clean.
Read the supplied dispatch snapshot, previous result, and historical
`98a11313167b41a98a420abfda80c292/check-3.log`. No current-job `check-*.log`
files were present. No remote operations or re-enumeration of issues/PRs.

Assumption: this is the writer's evidence-backed CI repair round, not permission
to choose an arbitrary release artifact or replace execution authority. Frozen
repair scope was the reported schema-test/vulture findings and this handoff;
existing soak profile, runner, adjacent tests and ADRs were inspected for
acceptance. No broader production redesign was attempted.

Fresh commands, each validation batch allowed 1,200 seconds:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,323 findings / 1,323 reviewed identities, zero unclassified or never-allowlist findings. Gate-selected comparison base `3c761d14db94`. No retained unbanked identity or eliminated identity exists to amend; ledger unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 118 passed, 6 skipped in 2.46 seconds. Skips are not acceptance proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,277 files already formatted.
- `uv run python scripts/check-doc-links.py`: PASS, 2,704 Markdown files, zero broken relative links.
- `git diff --check`: PASS after the handoff update.

The historical 24-versus-21 DDL assertion failure does not reproduce. Current
`test_pg_learnings.py:175–177` already includes the three audit columns emitted
by `pg_learnings.py:117–119`; the test checks the complete ordered DDL inside
one advisory-locked transaction. Removing DDL or weakening that assertion would
not be an evidence-backed repair. No code, test, ledger or grant changes are
justified by the executed checks. No tests changed, so no inventory delta.

Read accepted ADR-082826-b601 and ADR-085, plus Proposed ADR-081. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; admission uniqueness is not proof
of physical-work fencing. ADR-085 principal keys do not establish shared replica
budgets. Proposed deployment guidance does not waive issue acceptance.

| Acceptance criterion | Current evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. |
| Two production application replicas | **UNVERIFIED**: executed two-instance middleware tests are not deployed RC replicas. |
| Sustained saturation, reclaim, retries, leaks and shutdown | **UNVERIFIED**: no sustained production workload executed this round. |
| Physical-work deduplication and Goal reconciliation | **UNVERIFIED**: profile's schedule probe cancels its Run without execution; admission counts cannot prove physical-work fencing. |
| Replica-selection non-bypass, security/degraded behavior | **UNVERIFIED** for deployment; executed `tests/test_soak_promotion_gates.py:439` confirms independent middleware allowances: the same identity receives 200/200/429 on each instance. Production `rate_limit.py:94` constructs an in-memory limiter per instance. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**: profile/sampler tests exist, but driver-loop lag is not application-loop latency; no qualifying production measurements. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**: no active-work production recovery experiment executed. |
| Long-running exact-RC/config soak | **UNVERIFIED**: `run_soak.py:744–755` always rejects host preflight artifact identity. Executed four-hour preflight CLI regressions confirm duration cannot override this. |
| Findings filed/reclassified before promotion | **UNVERIFIED** this round: limitations recorded locally; no new load experiment or remote filing. GitHub mutations prohibited. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED**: these checks identify source HEAD, not a qualifying RC image/config soak. |

**BLOCKED**, not merge-ready: CI findings supplied for repair are not currently
reproducible; the earlier acceptance block remains. Do not keep dispatching the
historical schema failure as a current defect. Next required input is the
immutable RC/configuration intended for promotion, followed by representative
production-path workloads, physical-work/recovery and application telemetry
oracles, resolution of replica-budget semantics, and a qualifying >=4-hour
soak. A longer run of this host-process harness cannot satisfy the artifact gate.
Only this existing handoff changed; no historical measurements were rewritten.

Progress: checked 1, acceptance-complete 0, skipped 0 issues, validation errors 0;
next: exact-RC prerequisites and qualifying soak. Local writer handoff only.

## Frozen scope

- Assigned issue: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `43c8df6699c3ae4e729875d65a25aec33c05f440`.
- Verified supplied develop base: `91996e19223db61bab49ce2e8a8d5b8f6eb2728e`.
- Initial worktree clean; no incoming changes to salvage.
- Job directory contains no `check-*.log` files. Driver checks therefore cannot be assumed.
- Snapshot: explicit vulture exact-debt-ledger repair; the three previously reported soak Markdown whitespace findings; existing soak runner/profile/evidence/tests and relevant architecture read-only for acceptance review. This handoff records results. No other issues or remote mutations.
- Ambiguity: the task requests CI repair while the issue requires a long exact-RC production soak. Proceed with evidence-backed gate repair only; do not claim a replacement soak or promotion approval.

## Progress

- Initial refs and worktree checked.
- Required exact vulture scan passed: 1,342 findings / 1,342 reviewed identities, zero unclassified or never-allowlist findings, comparison base `91996e19223d`. No ledger amendment or source deletion is evidence-backed.
- Prior result read; existing load profile explicitly identifies host-process preflight limitations and representative-workload gaps.
- Reproduced all three reported trailing-blank-line defects via `git diff --check 91996e19223db61bab49ce2e8a8d5b8f6eb2728e`. Removed only those terminal blank lines, retaining historical report content.
- `uv sync --locked --extra dev`: PASS. `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (2,889 files).
- Focused soak/production-stack/learning-store/task-backpressure tests: 88 passed, 5 skipped. Replica-selection regressions execute real production middleware and confirm independent allowances; application installs it at `packages/maistro-server/src/maistro_server/main.py:593`.
- Historical shakedown JSON independently read: 90.43 seconds, duration check false, code identity `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, no exact-RC artifact check. It cannot certify the assigned HEAD. The current evaluator still rejects it; final evaluation recorded below.
- Post-repair `git diff --check 91996e19223db61bab49ce2e8a8d5b8f6eb2728e`: PASS. `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`: 27 passed, 5 skipped explicitly for missing `MAISTRO_TEST_PG_DSN`; no database-integration claim made.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: PASS, 29.7.2. Docker availability is not the remaining blocker; no exact RC identity/configuration was supplied and the existing runner is not an exact-artifact runner.

## Architecture reconciliation

Read repository instructions and accepted ADR-085, ADR-081626-f383,
ADR-082526-b36a and ADR-082426-82c7, plus Proposed ADR-081. Keep
Goal -> Graph -> Run -> NodeRun -> Attempt as the sole execution spine.
Occurrence uniqueness proves admission, not physical side-effect uniqueness.
The later lease ADR defines renewal/reclaim beyond the original fencing ADR;
reclaim must be exercised rather than presumed absent or silently replaced.
ADR-085 principal keys do not establish shared replica counters, nor waive #860's
replica-selection requirement. No new execution, authorization or scheduler
path is introduced.

## Final validation and acceptance

All commands below were executed locally with 1,200-second timeouts for the
validation batches; historical pass claims were not substituted for execution.

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **88 passed, 5 skipped** as detailed above.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 49 quality consumers and delegated gates checked; existing syntax/CORS warnings only.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 12,800 collected identities.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`: PASS, 502 collected identities.
- Inline `uv run python` imported the actual soak evaluator and loaded `evidence/m3a-round6-shakedown.json`: asserted failed checks are exactly `sustain_duration` and `exact_rc_artifact`, and that the current runner's artifact check is false. The historical JSON was not changed.

| #860 acceptance criterion | Executed/reviewed evidence and result |
| --- | --- |
| Representative release-candidate profile | PARTIAL: `m3a-load-profile.md:152-165` explicitly leaves users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background reconciliation unverified. Complete representative profile **UNVERIFIED**. |
| At least two supported application replicas | PARTIAL: production Compose defines two servers (`deploy/docker-compose.prod.yml:26-78`); historical preflight describes two host processes. Exact supported topology execution **UNVERIFIED**. |
| Sustained load observing saturation/reclaim/retries/leaks | NOT MET: evaluator executes against 90.43-second evidence versus 14,400 required (`evidence/m3a-round6-shakedown.json:163-165,221-225`). Long-window observations **UNVERIFIED**. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**: schedule probe cleanup cancels the admitted Run without execution (`evidence/m3a-round6-shakedown.json:12-16`); admission uniqueness is not a physical-work oracle. |
| Rate/security/degraded behavior non-bypass across replicas | NOT MET: executed production middleware tests (`tests/test_soak_promotion_gates.py:439-489`) give the same identity fresh allowance on replica 2. Other production security/degraded claims under a qualifying soak **UNVERIFIED**. |
| Required telemetry with pass/fail thresholds | PARTIAL: profile thresholds and sampler tests exist, but application-loop latency, worker completeness, saturation and qualifying RC measurements **UNVERIFIED** (`m3a-load-profile.md:152-165`). |
| Kill/restart with drain/fenced recovery | PARTIAL: historical JSON reports SIGTERM/rejoin; physical Attempt recovery under sustained active work **UNVERIFIED**. Evaluator tests are not a new failure-injection soak. |
| Long soak of exact promoted RC, rerun after changes | NOT MET: `scripts/soak/run_soak.py:635-647` always returns false for this host runner; evaluator rejects existing evidence. No selected immutable RC/configuration or new qualifying soak supplied. |
| Findings filed/reclassified before promotion | Locally VERIFIED: `BACKLOG.md:267-279` tracks engine-116 and explicitly blocks #860 promotion; human evidence classifies findings, including replica boot at M3-A (`m3a-soak-evidence.md:74-89`). Backlog consistency check passes. No GitHub mutation performed. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical JSON/human packs exist, but the JSON is tied to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this candidate or an exact RC image/configuration. Qualifying evidence **UNVERIFIED**. |

## Disposition

**BLOCKED for #860 acceptance.** The explicit CI-ledger failure did not reproduce;
there are no unbanked identities to review or amend. The three reproduced
whitespace failures are repaired. Changed files are this handoff and only the
trailing blank lines of `issue-860-13ec34d7-repair.md`,
`issue-860-62822668-repair.md`, and `m3a-round16-handoff.md` in this directory.
No source, runtime configuration, tests, gates, ledger, grants or historical
measurement data changed; no inventory delta is required because no tests changed.

The previous validation-budget block cannot be resolved by another passing scan
or short host preflight. Next: designate the immutable RC/configuration, resolve
the replica-budget contract, implement representative production workloads and
physical-work/telemetry oracles, then execute and publish >=4 hours on that exact
topology. Any code/runtime-config change requires a new soak. PostgreSQL
integration tests also remain unexecuted in this round (missing test DSN), not
silently counted as passes. This local commit is a blocked writer handoff, never
integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC prerequisites and qualifying soak"}`. Gate repair assessment complete; issue acceptance remains open.
