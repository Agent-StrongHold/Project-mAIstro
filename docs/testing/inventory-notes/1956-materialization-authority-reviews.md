---
inventory-delta:
  packages/maistro-core/tests: 11
  packages/hive-conductor/backend/tests: 20
---

# #1956 materialized model authority and wire contracts

## Dependencies and bounded reuse

The repair composes reviewed #1954 (nullable provider sampling and DAG tools)
and #1977 (the existing admitted-model owner and strict Binding pins). It reuses
that admission owner; it does not create a second resolver or authorize a
Binding from a definition. The bounded #1981 pieces carried forward are the
Agent client/factory admission wiring and existing Agent-name/delegation-depth
effect scope. Public chat, server admission and Agent streaming changes remain
outside this repair. The client keeps its one-completion compatibility stream.

## Regression evidence

On the published #1956 head, three isolated probes reproduce default-Workspace
Binding selection, None becoming 0.7, and a custom /openai API base gaining /v1.
A real in-memory Project/Run/NodeRun/leased Attempt probe additionally observes
that the Invocation loses the persisted Project, actor and operator Binding.

The permanent transport tests then fail 11 cases on the composed prerequisite
baseline, with four controls passing. They use the actual Hive runtime and
materialized Agent constructors, in-memory canonical authorities and MockTransport;
only boot container/factory infrastructure is substituted. The repairs preserve
actual admitted scope/actor/Binding/credential and Invocation usage. Definition
Workspace mismatch (including blank strings), absent/disabled/revoked Bindings,
and missing leases cause zero HTTP. A live client's revocation is rechecked
before replay. Explicit zero sampling and omitted sampling are asserted against
actual HTTP payloads; custom, trailing-slash, root and /v1 API bases are asserted
against actual request URLs. Existing root-mode clients still append /v1.

A second fail-first test demonstrates one physical call instead of two for
separate Agents sharing one admitted Attempt. Existing name/delegation-depth
scoping fixes that collision and tests retain same-visit replay without a new
physical call. Existing exact execution-identity, tool-choice, Agent quota and
factory tests use admitted fixtures. New core cases cover five definition-scope
restrictions, four effect-scope cases and two factory composition cases (+11).
Hive adds 20 transport/admission cases. No suite baselines or grants are changed.

Verification uses isolated source overlays and CI-shaped coverage producers,
with inspected focused tests only. No full local Hive fixtures, Vault, live model
gateway or paid provider are used. PostgreSQL/full-suite verification remains CI's
responsibility; focused passing tests do not claim a full-suite pass.
