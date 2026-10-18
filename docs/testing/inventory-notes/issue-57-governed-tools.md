---
inventory-delta:
  packages/maistro-core/tests/tools/test_governed_contracts.py: +4
  packages/maistro-bootstrap/tests/test_agent_loop_command_contract.py: +3
  packages/maistro-core/tests/agents/strategies/test_react.py: +4
  packages/maistro-core/tests/agents/artificer/test_strategy.py: +2
---
# Issue 57 governed tool contracts

Adds adversarial coverage for the M2 tool boundary:

- Agent effective allowlists and unknown model-selected schemas refuse before a
  backend call.
- Host-owned JSON schemas reject missing/extra arguments and raw command text.
- High-impact tool predictions persist exact materialized arguments, provider,
  pre-state digest, policy version, and Invocation identity; mismatches append a
  durable canonical event and are not reported as success.
- The bootstrap command tool accepts only structured `argv` and executes with
  `run_argv`, never an implicit shell string.

## Verification round (2026-10-18)

Strategy-level enforcement tests added: `ReactStrategy.reason` and
`ArtificerStrategy._handle_tool_call` refuse (a) model-selected names outside
`allowed_tools`, and (b) allowed names with no host-declared schema, in both
cases before Sentinel pre-call and before any executor dispatch; an allowlisted
valid call still executes. `Agent._build_strategy_kwargs` derives
`allowed_tools` from `identity.tools` — the same declaration that builds the
model-facing tool definitions — so the model cannot widen authorization.

Residual scope still open on #57 (not closed by this branch):

- `GovernedToolExecutor` is library-only: no shipped production path constructs
  it yet, so shipped tool traffic does not yet produce canonical Invocation or
  expected-effect evidence.
- The shipped `TOOL_EFFECT` inventory entries in
  `quality/direct-effect-call-sites.json` (6 sites, owner `#57`:
  `hive.web_search`/`hive.browse_url` in `chat_completion.py` and
  `legacy_dag_node.py`, `browser.search_web`/`browser.browse` in
  `tool_executor.py`) remain dispositioned `MIGRATE_TO_GOVERNED_INVOCATION` and
  are unmigrated. (PR #506 counted 7; one site left the inventory with the #56
  egress work — current authoritative count is 6.)
- Issue #847 (adversarial tool-name/schema/argument tests) must close before
  #57 closes.
