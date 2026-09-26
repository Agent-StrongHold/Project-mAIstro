---
inventory-delta:
  added: []
  modified:
    - packages/hive-conductor/backend/tests/test_chat_brief_interview.py
  removed: []
  rationale: >-
    Develop-sync merge resolution for lane L53 (issue #53). One HEAD-side test
    expectation was reconciled to the ADR-092326-7ed7 behavior that develop
    merged through #1037: an explicit Workspace selection the caller cannot
    see resolves to the caller's default Workspace (answer still delivered,
    nothing filed in the foreign Workspace) instead of a bare 403. The test
    now proves the boundary that remains: no interview opens in the foreign
    Workspace and the model answers exactly once.
---

# auto-53 develop-sync merge resolution (round 2, job 0a69b6a8)

Merge of `origin/develop` (ca4caec7d) into `auto-53` (e1f16ddae), resolving
the three conflicts left in the worktree plus two semantic reconciliations
the auto-merge could not decide. Everything below is verified by the
batteries in "Evidence".

## Conflicts resolved

### `packages/maistro-core/src/maistro/container.py`

- Imports: kept develop's multi-line `chat_execution` import and added
  `ChatTurnRefused` (develop's refusal type, used throughout the merged
  file).
- `route_request`: kept HEAD's `_settle_chat_turn` refactor (the #1037 seam
  shared by `route_request` and `route_conversation_request`) instead of
  develop's inline try/except, and moved develop's
  `_release_chat_dispatch(run)` call into `_settle_unrecorded_dispatch` so
  the unrecorded-dispatch path releases the dispatch shield on **both**
  routes (develop only had it on `route_request`). Without this, merging
  would have silently dropped develop's retention-stall repair (#131) from
  the conversation seam.
- Removed a duplicate `return result` introduced while editing (caught by
  the vulture gate's unreachable-code check).

### `packages/hive-conductor/backend/routes/chat.py`

Both sides implemented #1037 (HEAD via `chat_execution.execute_conversation_turn`
-> `Container.route_conversation_request`; develop via `chat_runs.admit_turn`/
`execute_turn` at the route). Union taken:

- Contained turns (Warden refusals, dashboard-edit containment, brief
  interview) keep HEAD's `_contained_response`/`_contained_done_event`/
  `_brief_events(req, request, messages, interview)` paths so every answered
  turn still leaves canonical Run/NodeRun/Attempt evidence.
- Model-reaching turns use develop's `_admit` + `execute_turn` +
  `_RunStreamingResponse`/`cancel_unstarted`: admission happens before the
  response exists (unadmittable turn -> retryable 503, never a 200 stream
  that then fails), the stream's `done` event carries `run_id`, and a stream
  whose body never runs cancels its Run. HEAD's architecture admitted inside
  the generator, which cannot satisfy `test_a_stream_whose_body_never_runs_
  cancels_its_run`.
- `_authorize_selected_workspace` (HEAD's 403 on non-member explicit
  workspaces) removed: it directly contradicts develop's
  ADR-092326-7ed7-backed fallback (`chat_runs._turn_workspace`: a selection
  the caller cannot see resolves to their default Workspace), which develop's
  contract tests pin (`test_named_workspace_the_caller_is_not_a_member_of_
  files_nothing_there`). The security property survives: nothing is filed in
  the foreign Workspace, and `brief_turn` opens no interview there.
- Dead code from the superseded stream paths (`_single_done_event`) removed.

### `packages/hive-conductor/backend/services/dag_agents.py`

- `get_canonical_run_store`: develop's strict refusal (standalone ->
  `RuntimeError("canonical graph execution spine is unavailable")`) — HITL
  must never write pending human decisions to process-local state; pinned by
  `test_hitl_store_requires_the_canonical_graph_spine` and
  `test_hitl_timeout_cancel`.
- `run_registered_dag`: kept HEAD's strict container branch (either store
  missing -> refuse, develop's message wording) and HEAD's standalone
  canonical in-memory spine, and added develop's rule that standalone
  execution of a graph containing `human.*` nodes is refused
  (`test_standalone_registered_human_work_is_refused`).

## Semantic reconciliation outside the conflict markers

- `services/dag_run_inspection.py::_canonical_summary` (HEAD's #1036
  canonical-first listing) dropped `error`/`result` from list summaries;
  develop's `_canonical_projection` overlay carried them, and develop's new
  attention test reads the canonical Run's own error from the list surface
  (`test_a_failed_run_is_queued_with_its_error`). Restored both fields with
  develop's truthy-when-present semantics so terminal evidence rides with
  the summary, not only the detail.
- `tests/test_chat_brief_interview.py`: HEAD's
  `test_a_workspace_the_caller_is_not_a_member_of_is_refused` expected 403
  for a work request in an unshared Workspace. Under the merged
  ADR-092326-7ed7 behavior the interview is not opened there
  (`brief_turn` -> `is_workspace_request_authorized` -> None) and the model
  answers in the caller's default Workspace. Rewritten as
  `test_a_workspace_the_caller_cannot_touch_opens_no_interview_there`:
  single `done` event, no brief frame, model called exactly once.

## Evidence (all at the resolved tree, `.venv/bin/python -m pytest`)

- `packages/hive-conductor/backend/tests`: 2813 passed, 6 skipped.
- `packages/maistro-core/tests`: 10418 passed, 700 skipped, 1 xfailed.
- `packages/maistro-server/tests` + `maistro-canvas` + `maistro-turing`:
  975 passed, 66 skipped.
- `packages/maistro-rsi/tests` + `maistro-bootstrap`: 1010 passed, 1 skipped.
- root `tests/`: 3653 passed, 101 skipped.
- `ruff check .` and `ruff format --check .`: clean.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: exit 0, 1415 reviewed -> 1412 findings
  (three identities eliminated by dead-code removal; no baseline amendment
  needed — the ratchet only fails on growth).
- `check-ratchet-provenance`, `check-shipped-surface-truth`,
  `check-convergence-matrix`, `check-wiring-reads`,
  `check-enumerations-provenance`, `check-agent-store-writes`,
  `check-execution-lifecycles`, `check-backlog-consistency`,
  `verify-monorepo-layout.sh`: all exit 0.
- `mypy packages/maistro-core/src/maistro/container.py`: clean.
