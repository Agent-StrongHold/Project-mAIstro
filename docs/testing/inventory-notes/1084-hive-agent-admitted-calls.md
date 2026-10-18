---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Hive Agent admitted model calls (#1084)

The existing composition-adapter suite gains two parametrized cases for actual
boot-roster and later-materialized Agents. Each provisions a Workspace/Root
Project in a temporary SQLite database, closes it, and starts the real Hive
bridge with an operator-declared model Binding for that persisted scope. A
real Agent executes through canonical chat admission and Attempt execution;
only the final provider HTTP transport is replaced with `httpx.MockTransport`.

The proof joins the completed Invocation to the admitted actor, Workspace,
Project, Run, NodeRun and leased Attempt, verifies the configured Binding's
model pin and scoped credential, and checks exactly one Invocation-attributed
usage event. A domain TurnID distinct from the canonical RunID preserves the
#1956 execution-identity regression coverage. The materialized Agent retains its own definition-Workspace-restricted client
while sharing the bridge's one `AdmittedModelCalls` helper with the boot Agent.
Each case then revokes that Binding and executes the same Agent under a fresh
canonical admission, requiring refusal with no new Invocation, HTTP call or
usage event. Existing adapter wiring assertions are updated without changing
their count.

Before the repair, both cases fail in real `Agent.handle` execution because
`GovernedLLMClient` asks for credentials under its fabricated `agent-runtime`
Project instead of the operator-declared canonical Root Project.

Focused command (from the worktree root):

```sh
PYTHONPATH=packages/hive-conductor/backend REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 \
  .venv/bin/python -m pytest --noconftest \
  packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -q
```

No public Hive chat/Responses implementation or full Hive suite is exercised
or changed by this focused proof.
