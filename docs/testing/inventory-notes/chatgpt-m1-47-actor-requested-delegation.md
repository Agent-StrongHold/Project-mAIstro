---
inventory-delta:
  packages/maistro-core/tests: +1
---
# #47 actor-requested delegation closeout

## Claim

Issue #47 has one remaining acceptance criterion after PR #559: actor-requested delegation is the default pattern rather than forced decomposition.

The production behavior already has the right shape. `Agent.handle()` asks the configured reasoning strategy for a `ReasoningResult`; delegation is entered only when that result names `delegate_to`. A configured `delegation_mode` and `sub_agents` list do not themselves dispatch work. The missing piece is a behavioral test that makes that default explicit and prevents a future orchestration optimization from silently turning available sub-agents into mandatory decomposition.

## Implementation plan

1. Add one discriminating test beside the existing `TestHandleDelegation` coverage in `packages/maistro-core/tests/agents/test_base.py`.
2. Configure a coordinator with an available sub-agent, `delegation_mode="sub_agents"`, and `sub_agents=("sub",)`.
3. Make the coordinator strategy return an ordinary completed response with no `delegate_to` request.
4. Assert the coordinator answer is returned and the sub-agent strategy was never invoked.
5. Keep the existing explicit-delegation tests as the positive half: when the strategy names `delegate_to`, the resolved target is invoked and its answer is returned.

No production code change is expected unless the test disproves the current reading.

## Collision boundary

Owned by this branch:

- `packages/maistro-core/tests/agents/test_base.py`, limited to the delegation behavior test block.
- this inventory note.

Explicitly outside the boundary:

- canonical `RunStore`, `NodeRun`, `Attempt`, durable graph execution, and consumer/recovery code;
- `agent.delegate_remote`, A2A transport, guest peer registration, and child-Run admission already implemented under #147/#559;
- Hive/Conductor state, scheduler, task backend, and production Workspace routing;
- capability/Invocation wiring and provider quota accounting;
- CI workflows, ratchet implementations, and quality ledgers.

This keeps the change independent of the current execution-consumer, Conductor durability, production Workspace routing, observability, quota, and quality-gate WIP clusters.

## Completion evidence

The issue can close when the new negative-path test passes beside the existing positive-path delegation tests. Together they prove delegation is available but is selected by the actor's reasoning result, not imposed merely because a decomposition target exists.
