---
id: ADR-092326-7ed7
title: "One stable Workspace Agent per Workspace; Workspace-less turns run in a per-user default Workspace"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-09-23
accepted: 2026-09-23
history:
  - status: Proposed
    date: 2026-09-23
  - status: Accepted
    date: 2026-09-23
substrate: []
implements: []
related:
  - maistro-engine#ADR-091726-7c2a
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_workspace_agent_identity.py
  - packages/hive-conductor/backend/tests/test_default_workspace.py
layer: Agents
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092326-7ed7: One stable Workspace Agent per Workspace; Workspace-less turns run in a per-user default Workspace

## Context

#1037 requires every Conductor chat turn, including conversation-only turns,
to enter the canonical Run seam under a stable Workspace Agent identity:
repeated turns in one Workspace resolve the same Agent, and each turn gets a
distinct Run. Two questions blocked it, and the owner answered both on
2026-09-23 (#1037):

1. **What is the Workspace Agent?** #804 describes a persistent agent per
   Workspace. Hive, however, had no single Agent that is *the* Workspace's.
   It had persona spawns (`{workspace}.{spawn}`), chat-created actions,
   CRUD rows, Forge rows and the manifest roster, and none of them was a
   stable identity for the Workspace itself.
2. **Where does a turn run when the surface selects no Workspace?**
   Dashboard, DeckBuilder, KnowledgeBase and Profile send no `workspace_id`.
   Only Chat does.

#840 permits exactly one product roster (`stores.agents`), written only by
`services/agent_materialization.py`. Workspace identity and membership are
owned by the canonical `WorkspaceStore` behind
`services/workspace_authority.py` (#37).

## Decision

**1. Each Workspace has one dedicated Workspace Agent.** It is a canonical
row in the one roster. It is materialized once per Workspace on first need,
through `agent_materialization.upsert_agent_definition`, so it gets the same
Warden scan-before-store and provenance stamp as every other definition. Its
id is `workspace-agent:{workspace_id}`, a pure function of the Workspace id.
No other producer can mint an id in that namespace: spawns and chat actions
key `{workspace}.{name}` with no dot in the name, CRUD rows are uuid4, Forge
rows are `forge-*`, and manifest rows use bare names. The persona is a
template reference on the row, `config.persona.template_id`, and defaults to
`program_manager`. Swapping the persona rewrites only that attribute. The id
and `created_at` do not change. A Workspace owner can still edit or delete the
row through the agents CRUD routes. After a delete, the next resolution
re-materializes the same id with a fresh `created_at` and the default persona. A Workspace the canonical store does not hold,
whether it was never created or has been deleted, gets no Agent. A row of
another Workspace that holds the id is refused, not adopted.
(`services/workspace_agent.py`)

**2. A Workspace-less turn runs in the caller's default Workspace, with that
Workspace's Agent.** The default is an ordinary canonical Workspace. It is
created on first need through `workspace_authority.create_workspace` with the
caller as owner. An insert-once claim, keyed `{user_id}#{generation}` in
Hive's persisted store, decides which Workspace is the default. The claim's
durable half is the backend's primary-key conflict (`put_if_absent`), so when
concurrent first requests race, exactly one claim wins. Each loser deletes the
Workspace it created and adopts the winner's. If the winner's Workspace
presentation is not yet loaded in the loser's process, the loser answers
`DefaultWorkspaceUnavailable` (retryable). It never mints a second default.
Resolution starts at the caller's latest generation. A default that was
deleted, or that the caller no longer owns, is therefore retired for good: the
next generation is claimed for a fresh Workspace, and re-adding the caller to
the old one never makes it the default again. (`services/default_workspace.py`)
`POST /v1/workspaces/default` returns the caller's default Workspace together
with its Workspace Agent id and persona. It keeps the `workspaces.write` gate
that every other `/v1/workspaces` mutation except plain creation carries. The
next slice's chat admission calls the resolvers directly rather than this
route.

The following options were considered and not chosen: reusing an existing
persona spawn as the Workspace Agent's identity, and refusing Workspace-less
turns.

## Acceptance criteria

- AC-1: Repeated resolutions for one Workspace return the same Agent id and
  `created_at`. A second Workspace gets a different id.
- AC-2: Ten concurrent first resolutions materialize exactly one Agent row,
  including on SQLite across a store reopen.
- AC-3: Swapping the persona keeps the id, and the new persona is read back.
  A malformed template id is refused before anything is written.
- AC-4: The first default-Workspace call creates a Workspace owned by the
  caller. Later and concurrent calls return the same Workspace. Another user
  gets their own. A lost durable claim converges on the winner, or answers
  retryably, and leaves no second Workspace. A deleted, revoked or demoted
  default is replaced, and it is never handed back, even after the caller is
  re-added to it. `POST /v1/workspaces/default` returns the same Workspace and
  Workspace Agent on repeat calls, and refuses a caller without
  `workspaces.write` without writing anything.
- AC-5: The roster gains only the Workspace Agents. It gains no demo rows and
  no duplicates.

## Consequences

### Positive
- The next #1037 slice can admit every chat turn as a canonical Run under one
  resolved Agent id, whether or not the surface selected a Workspace.
- M2 enforcement (#315, #66) has one Agent identity per Workspace to layer on.

### Negative / Trade-offs
- In-process serialization uses per-key `asyncio` locks. Across processes, the
  Agent's convergence comes from the deterministic id (every writer upserts
  the same row). A persona swap that races a first materialization in
  *another* process can therefore be overwritten by it. Hive runs as a single
  process today.
- A crash between creating a default Workspace and committing its claim
  leaves an unclaimed "Personal" Workspace that the caller owns. The next
  request creates and claims another one.
- The persona is recorded as a template reference only. Turning the reference
  into runtime behaviour is the next slice's concern.

### Neutral
- The Workspace Agent is a Workspace-scoped roster row, so it is listed with
  the Workspace's other agents and is removed by the existing workspace-delete
  cascade wherever that cascade runs.
