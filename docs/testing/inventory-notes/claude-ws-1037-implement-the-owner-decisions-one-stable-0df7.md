---
inventory-delta:
  packages/hive-conductor/backend/tests: +37
  tests/: +2
---
# claude-ws-1037-implement-the-owner-decisions-one-stable-0df7

#1037 slice: stable Workspace Agent identity and per-user default Workspace
(ADR-092326-7ed7). All +39 node IDs are new, and no existing test was moved,
renamed or removed:

- `tests/test_workspace_agent_identity.py`: 16 node IDs (13 functions, one
  parametrized over 4 malformed persona ids). They cover a stable id per
  Workspace, ten concurrent first calls, persona swap keeping the id, a swap
  racing first materialization, refusals for a missing, deleted or foreign
  Workspace, chat-id squatting, roster hygiene, and a SQLite restart leg.
  The three added by the review round cover a row another process
  materialized first being adopted rather than overwritten, a Workspace
  deleted while the Warden scan is awaited leaving no orphan Agent, and the
  delete cascade removing a Workspace Agent the deleting process never
  cached.
- `tests/test_default_workspace.py`: 16 node IDs. They cover:
  - first creation, concurrent and later calls, and per-user isolation;
  - deleted, revoked and demoted defaults, including a revoked default that
    stays retired after the caller is re-added;
  - a skipped unreadable claim and a blank-principal refusal;
  - a durable claim lost to another process, both when the winner can be
    composed here and when it cannot (retryable, no duplicate);
  - a SQLite restart leg;
  - a later generation another process claimed winning over the one this
    process cached, so a retired default is not handed back;
  - `POST /v1/workspaces/default`: repeat-call identity, its
    `workspaces.write` gate refusing a daily account, and a scanner outage
    mapped to 503.
- `tests/test_model_store_svc.py`: 5 node IDs for the storage primitives
  the fixes stand on -- `ModelStore.put_if_absent` (in-memory insert-once,
  adopting another process's durable row, and refusing a backend that cannot
  decide the conflict or a store with unique fields), `ModelStore.discard`
  reaching the backend for an uncached key, and `JsonStore.refresh`.
- root `tests/test_check_agent_store_writes.py`: +2 parametrized cases. The
  roster write gate now also treats `put_if_absent` and `discard` as
  mutations of `stores.agents`, so neither opens a writer outside the one
  service.
