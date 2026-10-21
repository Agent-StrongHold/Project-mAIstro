---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# 292-cli-refusal-audit-and-degenerate-arcs

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #292 CI-repair round, `packages/hive-conductor/backend/tests` grows by
six collected node IDs in `test_cli_contract.py`, all tied to evidence the
failing gates surfaced:

- **CI-repair root cause (workspace-retirement):** `services/cli_commands.py`
  had made the new CLI service a new importer of two retiring surfaces
  (`routes/cli.py`, `stores.py::agents`), which failed
  `tests/test_check_workspace_retirement.py` in the `test` job, the
  `Quality / Workspace retirement` gate, the aggregate quality gate, and the
  coverage gate's root-suite producer. The repair routes the agent count and
  the roster through the same `list_agents` projection `GET /v1/agents`
  serves, and injects the CLI-session listing capability from the router
  (`cli_registry(list_sessions)`), so the service imports no retiring
  surface. The registry signature change is pinned by
  `test_sessions_renders_the_empty_store_line`, which can only construct the
  registry through the injected provider.

Four of the new tests close arcs the per-file diff-coverage math (90% lines /
80% branch floors) showed uncovered in the new module — each is a degenerate
path, not a happy-path restatement:

- `test_status_renders_no_degraded_services_when_health_is_clean` — the
  empty-degraded rendering (the suite's default health payload always lists
  degraded services);
- `test_agents_renders_the_empty_roster_line` — the explicit empty-roster
  line, end to end through the store the API reads;
- `test_agents_renders_a_registered_agent_through_the_same_projection` — the
  populated roster rendering, driven by a real `POST /v1/agents` (the
  comprehension was otherwise never executed anywhere in the suite);
- `test_sessions_renders_the_empty_store_line` — the empty-provider line at
  the handler boundary the provider injection makes testable (the wired route
  always materializes the default session first).

Two tests pin refusal behavior the repair made explicit:

- `test_handler_http_exception_keeps_its_status` — a capability-authored
  `HTTPException` passes through with its own status (not 503), is audited as
  `refused` with the status code, and lands in the session's durable trail.
  This test exposed that the passthrough left the refusal unaudited,
  contradicting the contract's "every execution and every refusal is
  audited"; the exec route now audits it (`outcome: "refused"`) and appends
  it to history, mirroring the timeout path.
- `test_sessions_renders_the_store_behind_get_sessions` — `hctl sessions`
  lists the record `POST /v1/cli/sessions` created (the store-injection
  contract's data path).

No pre-existing node IDs changed: the six additions are appended tests; the
frontend playwright suites live outside the pytest inventory.
