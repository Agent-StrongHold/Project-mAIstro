---
inventory-delta:
  packages/hive-conductor/backend/tests: +25
  packages/maistro-core/tests: +2
---
# #1113: require canonical authority for new Hive Graph work

Base: `develop@30144ad0f508a6ee5d67c719ed04df5692fb64ea`.
This is a fresh implementation and fresh test evidence, not a recovered prior patch.

## Change and count

The original 24 new Hive cases cover missing Container/RunStore/Graph-continuation
owners, refusal before admission/configuration/resolution/traversal, engine
capability health, canonical admission failures, shipped HTTP and replay/live
stream failure framing, and SQLite checkpoint-zero recovery for both the
registered and legacy DAG entrypoints. The two new blocking fitness cases
require unconditional canonical admission and reject the retired fallback.

Existing execution tests now bind explicit canonical in-memory fixtures.
Historical document-shaped HITL/Attention fixtures remain explicit test input,
not a reachable production fallback. Scheduler definition/cursor unit tests
use an explicit fixture-owned canonical Project; the dedicated no-bridge test
now asserts that no firing is recorded and the occurrence remains owed.
No existing test cases were dropped. Resolver-only construction remains valid
without a Container, and deadlines, actor/scope, metrics, legacy conditions,
tools, model behavior and recovery are preserved by the selected regressions.

## Fresh fail-first evidence

Before production edits, the initial 13 admission/health regression cases
produced **11 failed, 2 passed** against the base. Failures reached configure
or resolver callbacks without a complete spine, returned the fallback store,
or lacked health capability reporting. Both architecture checks also failed
against files read directly from the base commit. The final implementations
pass those same checks.

## Verification

- Selected affected Hive suites: **473 passed**. This includes DAG service and
  route tests, HTTP/WS parity, scheduler, engine startup/health, recovery,
  metrics, governed quota, HITL and Attention. External socket connections
  were blocked by the local verification harness; model/tool terminals in
  these tests are fakes.
- Core canonical-store, identity/execution, archived-record and new fitness
  selection: **65 passed**, with `MAISTRO_TEST_PG_DSN` empty.
- Existing authenticated model-Graph E2E fixture: **6 passed**. Its terminal
  gateway is a fake HTTP server at `127.0.0.1:0`; the verification harness
  allowed only that fixture's exact bound address, with process proxy env
  removed so local fixture traffic could not reach an external proxy.
  Three existing Pydantic serializer warnings remain.
- `ruff check .`, `ruff format --check .`: pass.
- CI-exact `uv run mypy` over all nine package `src` roots: pass,
  **949 source files**. The narrower core-only check also passes (714 files)
  with workspace sources on `MYPYPATH`; its initial bare invocation lacked
  the optional bootstrap package locally. No source/type workaround was added.
- Convergence matrix, execution-lifecycle, model-egress/direct-effect,
  wiring-read, contract-marker, Vulture (CI scan arguments), radon and
  relative-document-link gates: pass. No quality baseline was changed.
- Exact-base committed diff coverage: all **6 changed source files** measured;
  the gate passes unchanged **90% line / 80% branch** floors. Its first valid
  committed run caught the public scope resolver as one uncovered changed
  line; the existing scope test now proves that read-only path without a
  Container and the gate passes. A staged-only zero-file run is not evidence.
- Affected suite inventory: Hive **3375**, core **13422**, exactly the deltas
  above, with no duplicate test evidence.

## Limits and preserved compatibility

The two SQLite tests close every original connection after a checkpoint-zero
crash. Another connection first sees the same canonical QUEUED Run; a fresh
connection then recovers that exact admitted Run ID. NodeRun/Attempt records
are created canonically during recovery, not claimed to have existed before
the simulated crash. This is SQLite fixture/connection evidence, not a live
PostgreSQL or multi-process distributed durability proof. No migration or
storage-backend policy changes are made.

The accepted ADR-082826-d9f5 AC-6 archive contract is unchanged: historical
pre-convergence Runs remain readable/reproducible and explicitly refuse
resumption as `LegacyRunNotResumable`. No replacement identity is minted.

The whole Hive/core test suites and live PostgreSQL, real-provider, sandbox
infrastructure, merge and deployment checks were not run. This bounded slice
must not be represented as completing any remaining broader #1113 proof.

## CI repair: explicitly unconfigured PM walkthrough

Published head `d96be1dd1ef9b23905067606fcd25173df014a1c` exposed two stale
expectations in `tests/e2e/pm-workflow.spec.ts`: both required an `execution_id`
from a stack whose `docker-compose.test.yml` deliberately supplies no core
bridge, canonical database or model gateway. UI job `111801426087` in run
`37321421391` failed those two cases; Integration Scope job `111801155723` in
run `37321421268` only reported that required UI job's failure.

The same two Playwright cases remain and now require explicit
`CanonicalGraphUnavailable`, no projected Run and a 404 when an existing DAG
definition ID is wrongly supplied as a Run-feedback target. No synthetic Run
identity, skipped test, new runtime authority, permission grant, workflow or
production-source change was introduced. The PM walkthrough documents this
unconfigured harness instead of promising successful stub execution.

The existing HTTP refusal regression now exercises create/activate/run/list
and feedback refusal, including no Outcome write. One new positive test,
`test_feedback_route_records_thumb_for_a_completed_canonical_graph_run` in
`backend/tests/test_feedback_route.py`, performs real canonical Graph admission
and completion with only the model terminal faked, then proves HTTP feedback
persists the exact canonical Run/Project/actor. Earlier feedback tests used
projection fixtures; this case explicitly protects the canonical success path.
This raises the Hive delta to **+25**, current collection **3376**; the core
**+2** delta is unchanged.

Fresh validation: the authority and feedback suites pass **51 tests** with TCP
blocked; one existing-style Pydantic serializer warning from the DAG update
route remains. Playwright successfully parses/discovers **17 cases** in the PM
workflow using the installed **1.62.1** runner. Docker is not installed here,
so the CI-pinned **1.52.0** browser/full-stack run is still pending CI; local
collection is not represented as a browser execution. Ruff, formatting,
whitespace and relative-document-link checks pass.

## Develop integration refresh (2026-10-17)

The existing draft branch is refreshed against
`develop@ab8b3737fa64f8d840f421ef87ca506c509444ff`. The six production files
remain the original Hive-only retirement scope. There are no net core-store,
migration, workflow or quality-ledger changes relative to this base.

The executor conflict preserves both mandatory canonical admission and the
landed #1332 cancellation correlation hook: one captured Container supplies
admission, continuation, effects and traversal; `on_admitted` runs once after
`create_run` and before physical work. A raising projection sink remains
logged and isolated. The scheduler retains the current canonical ScheduleStore
selection. Newer chat-cancellation fixtures now compose the canonical Run and
continuation stores together; missing authority produces an explicit failed
projection with no canonical correlation or cancellable Run. Existing cases
remain, and the inventory delta above is unchanged.

Fresh verification on the integrated candidate:

- Authority/admission/cancellation and blocking fitness selection: **41 passed**.
  Independent review also ran the authority/chat selection: **39 passed**.
- Affected Hive coverage selection: **442 passed, 14 skipped**. All **six**
  changed production files pass the unchanged **90% line / 80% branch** diff
  coverage floors against the exact develop base.
- Core Graph plus the new Hive fitness cases: **1,951 passed, 125 skipped**;
  no live PostgreSQL DSN was configured.
- Full Hive run: **3,620 passed, 26 skipped, 24 failed**. Twenty failures were
  caused by the executor's inherited SOCKS proxy without the optional
  `socksio` package. A fresh **151-test** rerun of all affected files passes
  with process proxy variables removed and non-loopback TCP blocked; its
  model gateway is the existing loopback fake. The remaining four Docker
  attestation failures reproduce identically on untouched develop: this
  executor has no Docker CLI. Those source and test files are unchanged.
  This is not reported as an all-green full-suite run.
- CI-exact ten-package mypy: **1,057 files passed**. Full Ruff and format,
  convergence/lifecycle/model-egress/harness-egress/wiring/contract-marker,
  cross-package-import, retired-guidance, agent-store-write, route-permission,
  principal-identity, release-consistency, document-link, radon and exact
  Vulture gates pass. Vulture remains **1,322 reviewed identities**.
- Inventory: Hive **3,670**, core **16,362**, both matching recorded counts.
  No new test-count change, quality grant or baseline update was introduced.

The October 5 CI checkpoint does not validate this refresh. Fresh exact-head CI
is required after publication. No local Docker/browser, live PostgreSQL,
#1113-specific multiprocess recovery or real-provider proof is claimed.
The PR remains a partial convergence draft; #1113, #44 and the parent epics
remain open. The separately published #1983/#1987 resolver composition must
still retain the single captured Container and its model admission decisions
when combined, and requires a combined retest.

## Develop integration refresh (2026-10-18)

The draft branch now includes
`develop@c2a22e55db71efa7f75a4e2f07dd063d34ae7eb2`, including the landed
#2144 Graph recovery-claim race repair, #2143 cancellation receipt repair and
#2146 parity CI split. The only merge conflict was the changelog; both the
canonical-authority and recovery-claim entries are retained. All six Hive
production files and the existing #1991 tests are unchanged from published
head `70da699be3f2e22b45aa12266b48a39f1f1094b8`. Core/server production,
workflow and quality-ledger trees match the new develop base exactly.
Independent source review confirmed the captured Container, mandatory
admission, isolated `on_admitted` callback and canonical ScheduleStore
contracts remain intact.

Fresh local validation of this integrated tree:

- Authority, admission/cancellation, recovery, HITL and fitness selection:
  **122 passed, 11 skipped**.
- Full core Graph suite plus Hive authority fitness: **1,963 passed,
  131 skipped**. This includes the landed recovery-claim race regressions.
- Full Hive suite: **3,640 passed, 26 skipped, 4 failed**. The four Docker
  attestation failures were independently reproduced on untouched develop
  `c2a22e55`: this executor has no Docker CLI. Their test, dispatch and
  execution-policy files are byte-identical to develop. This is not an
  all-green local full-suite claim.
- The test harness removed inherited proxy variables and refused non-loopback
  socket connections. Model HTTP fixtures used existing loopback fake servers.
  No live PostgreSQL DSN was configured. The temporary harness's spawn entry
  point was corrected before the clean full Hive run above; no repository test
  was altered to accommodate the harness.
- Full Ruff and formatting pass (**3,300 files**); CI-exact ten-package mypy
  passes **1,057 source files**. Convergence, execution-lifecycle, model-egress,
  foreign-harness-egress, wiring-read, contract-marker, agent-store-write,
  release-consistency, cross-package-import, retired-guidance and document-link
  gates pass.
- Committed diff coverage against `c2a22e55` measures all **six** changed
  production files and passes unchanged **90% line / 80% branch** floors.
  Exact-base Vulture, radon, route-permission and principal-identity ratchets
  pass: **1,322** reviewed Vulture identities and **137** reviewed C-or-worse
  blocks, with no added or stale debt.
- Inventories match: Hive **3,670**, core **16,423**, with no duplicate test
  evidence. The original **+25 Hive / +2 core** deltas are unchanged. No test
  inventory baseline, quality grant or ledger was modified.

Fresh exact-head CI must validate the published refresh, including PostgreSQL
and the Docker/browser jobs unavailable locally. The previous PostgreSQL claim
race failure is not treated as current evidence. This remains a partial draft:
#1113 and #44 remain open, and the SQLite reconnect tests still do not establish
the outstanding PostgreSQL or distributed recovery acceptance. The separate
#1983/#1987 model-caller composition and its combined retest remain outstanding.
