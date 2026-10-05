---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +17
---

# Materialized Agent incremental streams (#1981)

The history-preserving composition retains the original #1981 head and repaired
#1956 as ancestors. #1956 owns the shared admitted client/factory wiring, the
Agent-name/delegation-depth effect scope, nullable sampling and exact Hive API
base. This residual adds incremental Agent streaming through the existing
AdmittedModelCalls and Provider lifecycle. Both completion and streaming enforce
the stored definition Workspace restriction; only None is unrestricted.

## Fail-first evidence

The composed old incremental client failed five permanent materialization
cases: foreign, empty and whitespace definition Workspaces streamed despite
the restriction, while omitted temperature became 0.7 on completion and streaming.
The other 32 cases passed. Forwarding required_workspace_id through the existing
helper stream authorization and retaining nullable sampling fixes those cases.
No resolver, Binding, grant, actor, retry identity or protocol SDK was added.

## Inventory and coverage

Seventeen existing materialization cases gain a stream variant, covering actual
runtime/definition construction, persisted scope/actor/operator Binding, missing
and revoked Bindings, live lease requirements, blank/foreign Workspace refusal,
omitted/zero sampling, and exact custom, trailing-slash, root and /v1 API paths.
The same canonical fixture supplies execution and credentials; only final HTTP
is replaced by MockTransport. Three real Agent.handle tail-delegation cases gain
stream variants, proving distinct Agent/depth effects and same-visit replay.
One additional stream test proves replay rechecks revocation and preserves one
Invocation and usage event. Existing incremental, tool-fragment, usage, replay,
backpressure and cancellation tests continue to exercise the canonical stream.

Original #1981 notes now count 18 adapter cases, five delegation cases and two
SQLite Hive composition cases. The two factory and four effect-scope tests already
carried by #1956 are not counted again. No inventory baseline or quality grant
is increased, and every prerequisite quality-ledger row is retained unchanged.

Only inspected MockTransport/SQLite tests and collection-only inventory are run
locally. Full Hive execution, live gateway/Vault, public chat Attempt handoff,
sandbox and unattended Evolve policy remain outside this repair. Hosted CI is
separate evidence and publication remains held pending runner recovery.
