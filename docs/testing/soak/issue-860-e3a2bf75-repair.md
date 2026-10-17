# Issue #860 — e3a2bf75 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `dac921b5865d6bd55fe7ebc3ae66ea4be51fbb67` (resolved).
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Starting worktree clean; no incoming uncommitted work to salvage.
- Evidence: supplied dispatch-context.json, prior result 9ea48960, prior
  check-3.log from 98a11313. No check-*.log files supplied in this job directory.
- Review/validation scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, load profile, production rate-limit and
  task admission paths, `pg_learnings.py` and its adjacent tests, vulture gate
  and workflow. Edit only an evidenced defect in that scope, its inventory note,
  this report, and (only if actual scanner evidence requires it) the expressly
  authorized vulture ledger. No other issues/PRs will be processed.

## Initial evidence / assumptions

The historical check-3 failure expected 21 schema statements but observed 24.
It is not yet established that this failure exists at the assigned HEAD.
The preceding result reports unavailable exact-RC proof. Treat that as a claim
requiring inspection, not proof. No exact RC artifact/configuration is designated
in the lane prompt; do not invent one or promote local host traffic to RC proof.

## Fresh checkpoint: supplied CI failure does not reproduce

- Exact requested vulture command passed: 1323 findings, 1323 reviewed identities,
  zero unclassified. No ledger amendment is supported by scanner evidence.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`
  passed: 37 passed, 6 skipped (PostgreSQL DSN absent), 1.58 seconds.
- Current test lines 176–178 already include the three audit columns missing
  from the historical failure. No schema-test repair is needed.
- No nested AGENTS.md found in the scoped package/script/test/docs directories.

## Fresh checkpoint: focused validation

All commands used 1200-second timeouts; all passed:

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`
  — 74 passed in 2.33 seconds. Combined with schema tests: 111 passed, 6 skipped.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match, 31128
  unique identities, no copied-test duplication.
- `uv run python scripts/check-deployment-claims.py` — named deployment
  components/backends exist; static check, not deployed proof.

The vulture workflow (`.github/workflows/vulture-ratchet.yml:82`) uses the exact
arguments executed above. No new tests or runtime edits are justified by the
reported stale CI failure; no inventory delta or ledger amendment is needed.

## Architecture reconciliation

Read repository instructions, docs/README.md, accepted ADR-085, accepted
ADR-082526-b36a, accepted ADR-073126-c4e1 and proposed ADR-081. Proposed ADR-081
is not accepted authority. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The lease ADR requires renewal/fencing, not inferring worker death from restart.
The release ADR requires soaking the actual candidate artifact before promotion;
a host emulator cannot substitute. ADR-085 requires principal-keyed rates but
leaves implementation unspecified. The current production middleware explicitly
claims process-local limits, not a cluster-wide budget; that narrower claim
cannot silently waive #860's replica-selection non-bypass criterion. No new
authorization/scheduling authority or scope reinterpretation was introduced.

Additional workflow gates passed with 1200-second timeouts:
`uv run python scripts/check-ratchet-provenance.py` (53 quality JSON consumers
have provenance) and `uv run python scripts/check-shipped-surface-truth.py`
(matrix complete). The former emitted two SyntaxWarnings while scanning strings,
not a gate failure. `git diff --check` passed.

## Acceptance audit against current reachable paths

| Criterion | Executed evidence / remaining requirement |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic. `m3a-load-profile.md:152` acknowledges missing concurrent Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. Selected-RC inclusion/exclusion decisions are absent from the assignment. |
| Two application replicas | **UNVERIFIED at deployed RC level.** Executed tests instantiate two real middleware instances, not two promoted application containers. No live stack started in this repair. |
| Sustained saturation, growth, lease reclaim, retry/backoff, leaks and restart | **UNVERIFIED.** Sampler and sustained-admission accounting tests pass; they do not execute sustained deployed work. No long soak executed. |
| Exactly-once/fenced physical work | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1068` cancels the unexecuted schedule-probe Run. Unique admission identities and cancellation are not a physical-effect/fencing oracle. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; independent replica allowances reproduced.** `tests/test_soak_promotion_gates.py:439` passes for authenticated and pre-auth identities: each replica accepts two requests then rejects its third. `api/rate_limit.py:93` constructs a local limiter; `main.py:648` installs it. Selection increases the observed allowance. Backpressure test passes through the real task router/spine and validates 429/Retry-After plus recovery after a slot frees (`api/tasks.py:117`); this narrower proof is not cluster-wide security proof. |
| Telemetry and explicit thresholds | **UNVERIFIED at RC level.** Real wrapper/child sampler tests pass. `scripts/soak/run_soak.py:1410–1422` measures driver-loop lag, not application-loop lag. No fresh deployed connection/query/lock/queue/worker/RSS/fd/error series or complete RC thresholds validated. |
| Kill/restart active work, drain/fencing/recovery | **UNVERIFIED.** Fail-closed drain and cleanup unit tests passed, but no deployed fault injection or physical-effect uniqueness oracle was executed. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** No designated immutable promotion artifact/configuration supplied. `scripts/soak/run_soak.py:730–741` unconditionally rejects this host-process runner as exact RC. Executed synthetic four-hour-evidence tests prove rejection, not four hours of traffic. |
| Findings filed/reclassified | This report records findings locally; external filing/reclassification is **UNVERIFIED**. GitHub mutations prohibited. No stale schema/vulture finding is relabelled as newly reproduced. |
| Hash-bound machine/human RC evidence | **UNVERIFIED.** This source-linked validation report is not deployed machine-readable exact-image/package/config soak evidence. |

## Disposition and handoff

**BLOCKED — no integration or promotion approval.** The assigned stale CI failure
and alleged ledger gap both pass at current HEAD; no evidence supports modifying
source, tests, inventory or the ledger for them. Only this report changed, with
all inherited work preserved. No new test was added (no inventory-delta needed).
Six PostgreSQL tests skipped without a configured DSN. No live production soak
or container equivalence is claimed.

Next work is not another rerun of this same schema/vulture repair: the release
owner must designate the immutable RC artifact/configuration. Then complete the
representative workload, physical-effect/recovery oracle and application
telemetry; resolve replica-budget semantics without adding a competing authority;
execute the unchanged >=14400-second deployed multi-replica soak and publish its
hash-bound evidence. Any runtime/code change requires a new soak. This remains
unresolved by the current bounded repair rather than waived.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed
validation commands 0. Validation checkpoint complete and committed locally;
no push, PR, merge, comment or closure action. Worktree must be clean after commit.
