# auto-53 verify pass (job bed13ac1, head 74f57b233)

Independent re-execution at HEAD `74f57b233c2c0437ded36c93b1e1f1523cea4301` (base `8bb344e32`). No source changes; this note records the verification only (no inventory delta).

Executed:
- `uv run pytest packages/maistro-core/tests/test_container_chat_runs.py -q -x` -> 35 passed
- Hive 10-file verifier battery -> 184 passed
- `uv run ruff check .` -> clean; `check-suite-inventory.py` (hive + core) -> ok
- Parity/session/streaming/materialization/cancel/scope suites -> 110 passed
- Full `packages/hive-conductor/backend/tests` -> 2658 passed, 1 skipped
- Core chat/conduit/runs subset -> 899 passed, 203 skipped

Acceptance evidence: shipped DAG route runs exactly one canonical Run (legacy `execute_dag` forbidden); every `/chat/complete` and `/chat/stream` branch (normal, gate-refused, interview, dashboard-disabled) crosses `execute_conversation_turn` -> Container.route_conversation_request -> Conduit with Run/NodeRun/Attempt evidence and stable `workspace_agent_id` provenance; stub runtime fails closed (`test_agent_port_truthful_unavailable`); failed canonical nodes cannot project as completed; #1036 inspection reads canonical Run truth with DagRunStore as presentation projection. No premature closure keywords in branch commits or PR body ("Refs #53" only).

Forward-looking criteria (M2 Warden layering, M3 #804 reconciliation, M4 #783 self-impression compatibility) are design-satisfied by the single persistent identity seam (insert-once Workspace Agent, no synthesized per-turn root actor) — architectural, not independently provable by tests today.

## Repair-phase re-validation (job 9ec84196, HEAD 34a527bee)

The driver's earlier verify run (job b5f87a87, HEAD 4a296a26) failed
`test_created_dag_run_uses_one_canonical_run_for_history_projection` because its
stub Container lacked `capability_effects`; 74f57b233 repaired both the route
and the stub contract. Re-executed independently at this HEAD, no source
changes:

- `uv run ruff check .` / `uv run ruff format --check .` -> clean
- the exact 10-file verifier battery that failed in check-4 -> 184 passed
- `test_dags_routes.py::test_created_dag_run_uses_one_canonical_run_for_history_projection`
  + `packages/maistro-core/tests/test_container_chat_runs.py` -> 36 passed
- identity/consent suites (`test_workspace_agent_identity.py`,
  `test_default_workspace.py`, `test_chat_brief_interview.py`) -> 46 passed

The prior failure is closed at this HEAD.

## Repair-phase re-validation (job 65d64099, HEAD 777458f64, base 1dea30dfe)

Re-validation after merging develop `1dea30dfe` (Warden trust boundaries, deck
sanitization, credential_store_v2 retirement, Design Studio) into `auto-53`.
The earlier verify job e533c060 at `8ff261b15` had passed all seven
deterministic checks but failed to emit its result record (worker error, not a
tree defect), so this pass re-proves the merged tree:

- `uv run ruff check .` / `uv run ruff format --check .` -> clean
- the exact 10-file verifier battery from the historical check-4 failure ->
  184 passed
- full `packages/hive-conductor/backend/tests` -> 2665 passed, 1 skipped
- full `packages/maistro-core/tests` -> 10124 passed, 654 skipped, 1 xfailed
- `check-suite-inventory.py` (hive 2666, core 10779) -> ok
- `check-wiring-reads.py` -> ledger matches the current unread set

One real gate finding, repaired: `scripts/check-m1-convergence-freeze.py
--base 1dea30dfe` flagged `_StandaloneCanonicalGraphStore`
(`packages/hive-conductor/backend/services/dag_agents.py`) as a new
shared-owner-shaped type overlapping the Graph concept without a projection
marker. The class adds no storage of its own — every write goes through
`CanonicalDurableRunStore` over the canonical RunStore, and its `_rows` index
is a read-only presentation adapter refreshed from canonical writes — so the
repair documents that truthfully with the `M1 product-local projection: Graph`
docstring marker (comment-only change, no behavior change). The gate now
reports "no unapproved new architecture island" (exit 0).

No tests added or removed in this pass; inventory unchanged.

## Independent verify (job 0fbf8df2, HEAD d46a6450e, base 1dea30dfe)

Fresh execution by the independent verifier at the exact lane head; no source
changes made. All commands below were run in this worktree, not trusted from
logs:

- `uv run pytest packages/maistro-core/tests/test_container_chat_runs.py -q`
  -> 35 passed
- Hive 10-file verifier battery (the check-4 set) -> 184 passed
- `uv run ruff check .` -> clean
- `scripts/check-m1-convergence-freeze.py --base 1dea30dfe` -> exit 0
- `check-suite-inventory.py` for hive-conductor + maistro-core suites -> ok
- `test_workspace_agent_identity.py` + `test_agent_materialization.py` +
  `test_agent_port_truthful_unavailable.py` + `test_m0_tool_containment.py`
  -> 48 passed

Acceptance re-derived from the issue, mapped to evidence inspected in source:

- One canonical Run per shipped DAG execution (#736):
  `test_created_dag_run_uses_one_canonical_run_for_history_projection` asserts
  the FAILED Run list is exactly `[run_id]` with projection
  `canonical_run_id == run_id`; `test_run_dag_uses_one_canonical_run...`
  monkeypatches `graph_runner.execute_dag` to raise, proving the legacy path
  is unreachable. Route: `routes/dags.py::run_dag` -> `run_registered_dag`
  (`create_run(QUEUED)` then `run_durable_graph`).
- Chat canonical admission (#1037): every `/chat/complete` and `/chat/stream`
  branch (normal, dashboard-contained, gate-refused, interview) crosses
  `execute_conversation_turn` -> `Container.route_conversation_request`
  (`container.py:536`) -> ChatRunAdmitter + Conduit; tool-disabled callback is
  a thunk inside `_conduit_dispatch`, so M2 egress can replace it without a
  second executor.
- Run/NodeRun/Attempt evidence: `test_container_chat_runs.py:75-88` asserts
  distinct run_ids per turn, one NodeRun + one Attempt each, stable
  `workspace_agent_id` + session/request provenance.
- Conduit front door: `test_conversation_only_callback_enters_conduit_before_execution`
  wraps `conduit.route_request` and requires it to run before the callback.
- Stable Workspace Agent seam (#840): 14 identity tests (insert-once, first
  materialization race, persona swap keeps identity, sqlite restart durability,
  id-squat refusal, foreign-row refusal, delete-cascade) plus roster-scoped
  materialization through the single `instantiate_agent` factory path; a stub
  port fails closed (`test_agent_port_truthful_unavailable`).
- Non-chat resolution: `test_repeated_resolution_returns_one_stable_agent_per_workspace`.
- Child Graph/Run correlation: `run_registered_dag(parent_run_id=,
  parent_node_run_id=)` (services/dag_agents.py) with canonical store parent
  correlation tests (`maistro-core tests/runs/test_store.py:143,199`);
  chat-initiated delegation does not exist in M1 (tool-disabled), so the
  end-to-end chat->child case is design-satisfied, not test-proven.
- #1036 inspection: `test_canonical_dag_run_inspection.py` (waiting projection
  refreshes from recovery; canonical list includes runs without product
  history); DagRun projection copies canonical status and cannot contradict it
  (`test_run_dag_cannot_project_a_failed_canonical_node_as_completed`,
  `test_projection_preserves_a_waiting_canonical_run`).
- Failure truthfulness: `run_dag` returns `error` whenever the canonical Run
  did not complete (`routes/dags.py:617-620`); a broken projection store never
  rewrites execution (`test_run_dag_projection_failure_does_not_rewrite_execution`).
- Convergence freeze gate exit 0 at this head (the d46a6450e marker commit is
  comment-only for production code and truthful: `_StandaloneCanonicalGraphStore`
  adds no storage; writes go through `CanonicalDurableRunStore`).

Closure-keyword review: PR #1364 body says "Refs #53" only; no
fixes/closes/resolves in any commit message on the branch
(`git log --format=%B | grep -iE 'fixes #|closes #|resolves #'` -> no match).
No issue-closure actions performed by the verifier. Child-issue closure
(#736/#840/#1036/#1037) and CI status remain driver/GitHub actions -> UNVERIFIED
here by design; M2/M3/M4 layering and compatibility criteria are architectural
(single persistent identity seam, thunk-replaceable egress, parent-correlated
child Runs), consistent with the gate and code inspection above.

## Repair-phase re-validation (job fcd281d0, HEAD b948663e6 + vulture repair)

The prior repair round (job cb64945e) died on a provider timeout before doing
any work; the tree was clean at `b948663e6`. This round re-ran the failing
battery and then repaired the one remaining CI gate:

- The check-4 failure from verify job b5f87a87
  (`test_created_dag_run_uses_one_canonical_run_for_history_projection`) is
  closed at this HEAD: the exact 10-file verifier battery -> 184 passed.
- `uv run ruff check .` / `uv run ruff format --check .` -> clean;
  `packages/maistro-core/tests/test_container_chat_runs.py` -> 35 passed;
  `scripts/check-m1-convergence-freeze.py --base 1dea30dfe` -> exit 0;
  `scripts/check-ratchet-provenance.py` and
  `scripts/check-shipped-surface-truth.py` -> exit 0;
  `uv run mypy packages/maistro-core/src/maistro/container.py` -> clean
  (remaining mypy `maistro_bootstrap` import-not-found errors in `cli/` are
  pre-existing env gaps requiring `--extra bootstrap`, untouched by this diff).
- Vulture ratchet repair: the narrow CI scan
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`, per `.github/workflows/vulture-ratchet.yml`) flagged
  `Container.route_conversation_request` as NEW unauthorized debt vs trusted
  base `1dea30dfe`. The method is the live #1037 production seam, consumed by
  `packages/hive-conductor/backend/services/chat_execution.py` through a
  duck-typed `getattr` outside the `packages/*/src` scan scope, so the scan
  cannot see the call. Banking alone cannot pass (a floor-raise grant must
  already be landed at the merge-base — two-merge rule, ratchet_provenance.py),
  so the repair follows the repo's established `_vulture_*_usage` TYPE_CHECKING
  visibility precedent (`types/config.py`, `graph/execution_state.py`,
  `graph/traversal_commit.py`): a documented non-executing reference
  `container.py::_vulture_conversation_request_usage` keeps the reviewed
  downstream-consumed seam visible to the production-only scan. Gate re-run ->
  1415 reviewed identities -> 1415 findings, exit 0; no ledger row added (the
  finding no longer exists to bank).

No inventory delta: no test files added or changed this round.
