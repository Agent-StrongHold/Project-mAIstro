# Hive Agent admitted model calls (#1084)

The composition-adapter suite includes two parametrized cases for actual
boot-roster and later-materialized Agents
(`test_configured_hive_agents_use_admitted_execution_and_usage`). Each
provisions a Workspace/Root Project via `create_container` against a temporary
SQLite database, closes that provisioning container, and starts the real Hive
bridge with an operator-declared model Binding for that persisted scope. A
real Agent executes through canonical chat admission and Attempt execution;
only the final provider HTTP transport is replaced with `httpx.MockTransport`.

The proof joins the completed Invocation to the admitted actor, Workspace,
Project, Run, NodeRun and leased Attempt, verifies the configured Binding's
model pin and scoped credential, and checks exactly one Invocation-attributed
usage event. A domain TurnID distinct from the canonical RunID preserves the
#1956 execution-identity regression coverage. The materialized Agent retains
its own definition-Workspace-restricted client while sharing the bridge's one
`AdmittedModelCalls` helper with the boot Agent. Each case then revokes that
Binding and executes the same Agent under a fresh canonical admission,
requiring refusal with no new Invocation, HTTP call or usage event.

Landed on `cursor/port-1981-1084-admitted-calls-c4f8` / PR #2418 (inventory
delta for these cases is recorded in
`cursor-port-1981-1084-admitted-calls-c4f8-623a.md`).

Focused command (from the worktree root):

```sh
uv run pytest \
  packages/hive-conductor/backend/tests/test_maistro_core_adapter.py::test_configured_hive_agents_use_admitted_execution_and_usage -q
```

No public Hive chat/Responses implementation or full Hive suite is exercised
or changed by this focused proof.
