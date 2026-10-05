---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +7
---
# #56: registered Binding pins, unregistered request aliases

This bounded residual from stale #1370 follows the existing
[#56 owner decision](https://github.com/Agent-StrongHold/Project-mAIstro/issues/56#issuecomment-5788410428):
an unknown Binding pin refuses, while an unregistered request alias continues
to the gateway with absent cost metadata. No fallback may widen a pin.

## Collected evidence

- Core adds six negative egress cases: unknown or registered-but-unavailable
  pins, each with no alias, an available conflicting alias, or an unknown alias.
  Every case asserts zero router selection, setup, gateway dispatch, and
  Invocation records. One additional resolver case checks that an unavailable
  request alias is not described as a pin.
- Hive adds three real activation-handler/Container-composition cases with
  fake terminal HTTP and vault access: no registered health-model metadata,
  configured metadata, and unavailable metadata. They check actionable refusal
  before `/model/new`, or registration followed by a governed completion using
  the configured costs. These invoke the route handler directly; HTTP auth
  middleware is outside their scope.
- Before the source repair, the three unknown-pin core cases dispatched instead
  of raising, the alias diagnostic failed, and the two Hive refusal/diagnostic
  cases failed. The configured success case already passed. The final focused
  set contains 34 passing cases, including existing alias, cost, router,
  credential, policy, deduplication, and retry regression coverage.
- Exact-head CI exposed two existing DAG quota fixtures which pinned a model
  against an intentionally empty registry. They now use the real in-memory
  registry with explicit test metadata, preserving strict pin refusal and all
  quota assertions. Both failures reproduced before the fixture repair; the
  expanded hermetic cohort passes 38 cases. No test identities were added or
  removed by this follow-up.

## Configuration prerequisite and limits

Hive's activation catalogue supplies gateway model names, not trusted price or
latency metadata. The existing supported path is `Settings.provider_config_path`
through the embedded adapter's `AgentConfig` and the Container's
`load_provider_registry`. The YAML model entry requires `name`, `provider`,
`cost_input`, `cost_output`, and `latency_p50_ms`; costs are cents per 1,000
input/output tokens. Operators must supply their actual metadata before using
that model as a Binding pin. This change does not infer prices, install a second
registry, or move credential-bearing gateway registration before authorization.

The committed Hive success test explicitly uses the selected in-memory backend;
it is not actor-scoped durable quota acceptance. A separate hermetic diagnostic
on this base's real file-backed SQLite Container also completed configured
activation with no installed quota budgets, but its Invocation actor stayed
blank while the canonical Run held the operator actor. The existing estimator
attributes that blank actor to `system`. That control-plane caller integration
limit remains outside this provider-selection leaf and must not be presented as
correct actor-scoped quota attribution.

No real gateway, external credentials, full Hive execution, merges, deployments,
or workflow dispatches were used for this evidence. Suite inventory collection
is read-only and distinct from running the Hive suite.
