---
inventory-delta:
  packages/maistro-core/tests: +18
---

# Agent calls consume configured admission (#1084)

After composition onto repaired #1956, the two factory cases and admitted
client wiring are owned and counted by that prerequisite. This residual note
counts only the eighteen original Agent adapter cases retained by #1981.

`GovernedLLMClient` consumes the configured `AdmittedModelCalls` rather than
constructing a Binding from constructor Workspace/Project strings. Complete and
incremental stream calls resolve the persisted Run/NodeRun/Attempt, actor and
operator Binding through the existing owners. The factory reuses a matching
runtime client, and refuses conflicting admitted-call dependencies. Explicit
standalone library client injection remains unchanged; the Hive production
composition always supplies its configured helper and shared governed client.

The low-level `create_agents` factory is an explicit dependency-injection API,
not a universal authorization boundary. Omitting `admitted_calls` or passing
`None` retains the caller-supplied client. The shipped-composition claim here is
limited to its sole production call site, Hive `_construct_runtime`, which
always supplies the configured helper and the same governed client retained for
materialization. Out-of-tree standalone callers are not claimed governed by
merely using the factory.

## Evidence

- Eighteen focused Agent adapter cases cover persisted actor/Binding/usage joins,
  invented identities, missing/disabled/ambiguous/foreign Bindings, missing
  credentials, revocation before replay, streaming incrementality, deterministic
  close and stale/missing streaming execution context. Only final HTTP is
  replaced by MockTransport in these admission tests.
- Two prerequisite factory cases (already counted by #1956) prove shared client identity and refusal of a
  conflicting helper. Existing factory composition cases now name the admitted
  helper instead of the removed partial-authority argument set.
- Before implementation, four focused regressions failed against the dependency
  base: no Invocation under the declared Binding, revoked Binding still allowed
  dispatch, invented correlation still allowed dispatch, and stream used the
  nonstream response parser. These same cases pass after the repair.
- Existing #1827 identity tests retain their exact failure-atomic `set_turn`,
  stale-context, task-isolation and effect-key assertions against a recording
  admitted-call boundary. Existing #1829 transport assertions are preserved with
  persisted admission and final HTTP MockTransport. Quota/adoption fixtures now
  use persisted executions; the common fixture is in `tests/_admitted_model_fixture.py`.
- Real configured Hive startup and later-materialized Agent joins, including
  TurnID-versus-RunID and revocation, are covered separately by
  [the Hive proof note](1084-hive-agent-admitted-calls.md).

## Boundaries

This is the Agent Binding/actor caller slice over the published #1977 and #1956
work. It does not synchronize paused #1870, add a private execution authority,
create operator grants, borrow default scope, or change isolated transports.
Public Hive chat/Responses cutover remains held for the SPEC-197 owner decision.
No full local Hive suite or live gateway was executed. Suite inventory is
collection-only; focused tests do not claim installed-profile or live-provider
release proof.
