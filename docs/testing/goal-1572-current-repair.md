# Issue #1572 current CI repair

## Revalidation at c7df939e (job 89d6d0e383f1417fbfaca7b9f2bc7f95)

This section records a new, independently executed repair pass; the earlier
checkpoint below is preserved, not treated as current acceptance evidence.

- Frozen item: issue #1572 only, assigned worktree `/home/dev/Git/wt/auto-1572`,
  branch `auto-1572`. Verified starting HEAD
  `c7df939ef3c35e26f1c5b10a7503fc11da706f9a`; initial tree clean.
- Supplied develop base: `28614700bd9ab0223eac06924a204af4a5cc25d9` resolves.
  Inspection scope: existing issue diff, adjacent tests, relevant ADRs and named
  CI gates. Only this report is changed. No remote list was refreshed.
- Role ambiguity resolved as writer from the explicit repair assignment.
  Read repository instructions, the supplied issue body/dispatch evidence,
  previous result artifact, and this job's `check-0.log` through `check-4.log`.
  Read accepted ADR-081226-9944, ADR-081226-a66b, ADR-087,
  ADR-082426-2192 and ADR-092326-97c4. No architecture exception is proposed.

### Independently executed commands

Logs are under `/home/dev/maistro/jobs/89d6d0e383f1417fbfaca7b9f2bc7f95/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,328 reviewed identities / 1,328 findings, zero unclassified/forbidden (`vulture-before.log`). No ledger amendment warranted. |
| `uv run python scripts/check-execution-lifecycles.py` | FAIL: GoalStatus lacks already-landed authorization; trusted base `9bd1a93eefc4`, 19 classified / 20 discovered (`lifecycle.log`). |
| `uv run pytest tests/test_check_execution_lifecycles.py -x -q` | 28 passed, 1 failed at `tests/test_check_execution_lifecycles.py:374`, reproducing the same policy failure (`lifecycle-tests.log`). |
| `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q` | 1,813 passed, 311 skipped, six adjacent aiosqlite closed-event-loop warnings (`core-validation.log`). |
| `uv run pytest tests/migrations -x -q` | 38 passed, 125 skipped (`migrations.log`). |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3,145 files. |
| `uv run python scripts/check-m1-convergence-freeze.py --base 28614700bd9ab0223eac06924a204af4a5cc25d9` | PASS: no unapproved architecture island. |
| `uv run alembic heads` | PASS: single head `061`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS (`inventory.log`). |
| `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` | FAIL: cannot connect to Docker daemon; PostgreSQL execution unavailable. |
| `git diff --check` | PASS before report update; rerun before commit. |

The supplied develop ref also has no GoalStatus authorization. No unresolved
merge exists. `scripts/ratchet_provenance.py:478` loads authorizations from the
base, so a candidate grant cannot authorize this change. Do not remove or
obscure the legitimate Goal domain lifecycle to evade that policy.

The named `integration-scope` failure is **UNRESOLVED**, not attributed to the
lifecycle gate: `scripts/check-integration-scope.py:20-27` aggregates specialized
integration checks, not execution-lifecycles or vulture. The supplied driver
logs do not identify its failed producer. No aggregate success is inferred and
no fabricated `--result` values are passed to the aggregator.

### Acceptance map for this pass

Read the actual conformance, binding, wiring, restart and installed-base tests,
together with production Goal authorization/wiring and Container composition.
The following evidence comes from the commands above, not prior claims.
All Goal test paths below are under `packages/maistro-core/tests/goals/`.

| Criterion | Executed evidence / explicit limits |
| --- | --- |
| Three-backend Goal/GoalRevision round-trip | `test_goal_store_conformance.py:171` passes memory/SQLite. PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal and concurrent single winner; terminal finality | Conformance tests at lines 197, 229, 278 pass memory/SQLite. Independent durable writers and PostgreSQL UNVERIFIED (concurrent calls use one store object). |
| Subgoal parent/Project lineage and recorded Agent transition | Conformance tests at lines 294 and 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passes memory/SQLite admission and terminal-transition preservation. No Goal revision is advanced after admission in these tests; that scenario and PostgreSQL UNVERIFIED. |
| Two-Workspace isolation; foreign equals missing | Conformance tests at lines 398 and 472 pass through real `WorkspaceAuthorizer`/`ScopedGoalStore`, memory/SQLite. PostgreSQL UNVERIFIED. |
| Production composition and Container exposure | `test_goal_wiring.py:41,132` passes real factory/seam tests. Server `main.py:344` and Hive `backend/adapters/maistro_core.py:194` call the shared factory; `container.py:2377` wires Goals. Both deployed durable process compositions UNVERIFIED. |
| Durable restart readback with bound Run provenance | `test_goal_restart_readback.py:36` passes SQLite store close/reopen. It does not restart deployed processes or advance Goal revision after admission. PostgreSQL and deployed-process legs UNVERIFIED. |
| No competing execution authority | Convergence-freeze command passes against supplied base. Separate execution-lifecycle policy gate fails as above. |
| Preserve merged 056/057 identities/ancestry and append coordinated Goal ID | Installed-base static graph/snapshot tests pass; single head 061 follows 060. Central reservation UNVERIFIED. |
| Actual c560d4c/4675101 populated installed-base upgrades without restamping | Live upgrade tests skipped. PG17 and PG18 UNVERIFIED. |
| Post-upgrade tables, preserved user-model/Run rows, planner artifacts and reopened bound provenance | Live tests skipped; both PostgreSQL majors UNVERIFIED. |
| Fresh install, single head/unique IDs, downgrade/refusal, reapplication and earlier quota ancestry audit | Static migration checks and head check pass. Live PG17/18 and complete earlier-history compatibility audit UNVERIFIED. |

Additional observed durability risk: `goals/wiring.py:62-77` falls back to an
in-process Goal store when a configured PostgreSQL pool lacks Goal tables.
`test_goal_wiring.py:101` explicitly passes by asserting that fallback, so its
name about refusing an unmigrated pool is not fail-closed evidence. This needs
resolution before claiming the issue's durable production boundary; it is not
a vulture finding and was not changed speculatively in this CI-repair pass.

### Current handoff: BLOCKED

Only this report changed; no production code, tests, inventory counts, ledgers,
grants or gates changed. No test additions require an inventory-delta note.
Progress: checked 1 item, done 0 repairs, skipped 0 items, errors 1 reproduced
policy blocker plus unavailable PostgreSQL infrastructure. Commit this evidence
checkpoint locally, preserving all incoming work.

Next: an authorized owner must independently land the GoalStatus authorization;
provide the actual failed integration producer log and working PG17/18
infrastructure. Then repair evidenced defects and validate the remaining
acceptance legs, including the observed unmigrated-PostgreSQL fallback. This is
not integration approval. No GitHub mutations or issue closure actions.

---

## Frozen scope

- Assigned issue: #1572 only; branch `auto-1572`.
- Starting HEAD: `cf7e21ed30655599a33719f7d82d2affa682c1db` (verified); worktree initially clean.
- Supplied develop reference: `e1b13dcd15dedd637404c38dfe1900921aba2b8c` (resolved).
- Evidence snapshot: `/home/dev/maistro/jobs/5e1344732b374b9eb9b8a80b8aac0ea6/dispatch-context.json` and check-0.log through check-4.log. No remote enumeration or mutations. Read the previous job's `result.json`, but independently reran the validations below rather than inheriting its verdict.
- Files in repair scope: canonical goals and Run binding implementation/tests already present, relevant CI gate scripts (inspection only), `quality/vulture-baseline.json` (only if exact scan proves reviewed debt), and this report. No other ledger/grant edits permitted.
- Role ambiguity: prompt includes verifier and writer directions; lane explicitly assigns repair, so proceed as writer with focused validation and local commit.

## Initial evidence

Driver logs report dependency sync success, lint success, format success, goal tests 46 passed / 16 skipped, and core inventory success (14,961 identities). These are driver evidence, not independently re-executed acceptance claims.

The supplied develop-to-HEAD diff includes substantial unrelated divergence. This round will not attempt a speculative synchronization or modify those files. The branch already includes prior repair reports; inspect them and reproduce the named gates before changing production code.

## Results

First-hand exact vulture command passes: 1,328 reviewed identities / 1,328 findings, zero unclassified/forbidden. No vulture ledger amendment is justified.

First-hand `uv run python scripts/check-execution-lifecycles.py` fails: `maistro.goals.model::GoalStatus` lacks already-landed authorization (19 classified / 20 discovered). Trusted base selected by the gate is `9bd1a93eefc4`, not the supplied develop tip. This is a policy blocker outside the permitted ledger repair. Do not disguise or delete the legitimate Goal domain lifecycle to evade it.

Read the captured issue body, including its installed-base migration acceptance additions.

Executed focused core validation: `uv run pytest packages/maistro-core/tests/goals packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py -x -q`: **1,813 passed, 311 skipped**, six adjacent Run SQLite worker/event-loop warnings (full output in this job's `worker-core.log`). `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` fails: daemon unavailable; PostgreSQL legs remain unverified.

`uv run pytest tests/test_check_execution_lifecycles.py -x -q`: **28 passed, 1 failed** at line 374, reproducing the missing trusted-base GoalStatus authorization.

`uv run pytest tests/migrations -x -q`: **38 passed, 125 skipped**. `uv run python scripts/check-m1-convergence-freeze.py --base e1b13dcd15dedd637404c38dfe1900921aba2b8c`: PASS. `uv run ruff check .` and `uv run ruff format --check .`: PASS (3,145 files formatted).

Source confirms server `main.py:344` and Hive `backend/adapters/maistro_core.py:194` call the shared Container factory; `container.py:2377` selects the Goal store. `scripts/check-integration-scope.py:20-27` aggregates specialized integration jobs, not lifecycle or vulture. Exact failed producer evidence is still needed; no causal attribution or aggregate success is inferred.

`uv run alembic heads`: PASS, single head `061`. `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 14,961 unique identities and zero duplicate evidence. `git diff --check`: PASS. Inspection of the supplied develop ref's authorization file found no GoalStatus grant. No unresolved merge exists, and a speculative develop merge would not supply that missing authorization.

## Architecture and acceptance review

Read accepted ADR-081226-9944 (product ownership), ADR-081226-a66b (Run/NodeRun/Attempt), ADR-087 (schema evolution), ADR-082426-2192 (server Container), and ADR-092326-97c4 (shared PostgreSQL Workspace authority). No alternate scheduler, authorization seam or Goal owner is introduced by this round. Do not reconcile the policy failure by changing GoalStatus into an unscannable representation.

Tests and the production wiring/authorization were inspected, rather than treating test counts as acceptance. All test references below are under `packages/maistro-core/tests/goals/` unless stated otherwise.

| Acceptance criterion | Current executed evidence and limits |
| --- | --- |
| Goal and GoalRevision round-trip on all three backends | `test_goal_store_conformance.py:171` passes memory and SQLite (including content and reopened-store equality). PostgreSQL UNVERIFIED. |
| Append-only revisions, stale refusal, one concurrent winner; final terminal states | Conformance tests at lines 197, 229 and 278 pass memory/SQLite. Concurrency uses one store object; independent durable writers and PostgreSQL UNVERIFIED. |
| Subgoal parent/Project lineage and recorded Agent transition | Conformance tests at lines 294 and 333 pass memory/SQLite. PostgreSQL UNVERIFIED. |
| Run admission binding and immutable historical revision | `test_run_goal_binding.py:102,115` passes memory/SQLite through `admit_direct_work` and terminal transition. Tests do not advance Goal revision after admission, so that historical-provenance scenario and PostgreSQL remain UNVERIFIED. |
| Cross-Workspace isolation; foreign equals missing | Conformance tests at lines 398 and 472 pass memory/SQLite through real `WorkspaceAuthorizer` in `ScopedGoalStore`; PostgreSQL UNVERIFIED. |
| Both production compositions and Container exposure | `test_goal_wiring.py:41,132` passes real in-memory factory/seam tests; server and Hive source callers confirmed above. Both deployed durable process compositions UNVERIFIED. |
| Restart supported durable composition with same Goal/revisions/bound Run | `test_goal_restart_readback.py:36` passes SQLite close/reopen of store connections. It does not restart a deployed Container/process, and does not advance Goal revision after admission. Deployed process and PostgreSQL evidence UNVERIFIED. |
| No competing executor or product-private lifecycle | Convergence freeze passes against supplied develop SHA. Execution-lifecycle policy gate remains blocked on missing authorization. |
| Preserve merged 056/057 meaning/ancestry, append unused coordinated Goal ID | `tests/migrations/test_goal_installed_base_upgrade.py:389,416` static graph/snapshot tests pass; single head 061 follows 060. Central reservation UNVERIFIED. |
| Populated actual c560d4c/4675101 forward upgrades without restamping | Existing installed-base live tests skipped; both PG17 and PG18 UNVERIFIED. |
| Post-upgrade Goal tables, user-model/Run data, planner artifacts, version and reopened bound provenance | Existing installed-base live tests skipped; both PostgreSQL majors UNVERIFIED. |
| Fresh install, unique IDs/single head, downgrade/refusal and reapplication; older quota ancestry audit | Static migration tests and single head pass. Live PG17/18 legs and complete earlier shipped-history compatibility audit UNVERIFIED. |

## Handoff — BLOCKED

Changed file: only `docs/testing/goal-1572-current-repair.md`. No production code, tests, inventory counts, gates, ledgers or grants changed. No test additions, hence no inventory-delta note is needed. Incoming work is preserved. This report is an evidence checkpoint, not a claim of repair or integration approval.

The permitted vulture repair has no reproduced defect. The actual reproduced lifecycle failure requires an independently landed authorization under `scripts/ratchet_provenance.py:478`; candidate grants cannot authorize themselves. That policy action is outside this lane. The named integration-scope failure remains UNRESOLVED without its exact-head failed specialized producer evidence; do not synthesize passing `--result` inputs. Docker is unavailable despite the environment brief, so PostgreSQL acceptance cannot be proved here.

Next: obtain the actual integration-scope failing producer log, independently land the lifecycle authorization, and provide working PG17/18 infrastructure before retrying remaining acceptance. The captured check-run records do not establish the reported aggregate's failing producer at this starting head. This is an external-prerequisite handoff: repeating the same repair dispatch without those prerequisites cannot repair the reproduced policy failure. No GitHub mutations or issue closure actions performed.

Progress: checked 1 assigned item; done 0 repairs; skipped 0 items; errors 1 policy blocker reproduced by gate and test, plus unavailable Docker infrastructure. Commit this evidence-only checkpoint locally and leave the worktree clean.
