---
id: ADR-083026-6e2a
title: "Graph continuation, not events.checkpoints, is the canonical graph recovery checkpoint"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate: []
implements: []
related:
  - maistro-engine#ADR-082826-d9f5
  - maistro-engine#ADR-082826-08f0
  - maistro-engine#ADR-081226-7248
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_checkpoint_authority.py
ac-modules: {}
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-6e2a: Graph continuation, not events.checkpoints, is the canonical graph recovery checkpoint

## Context

M1 recovery convergence has accumulated three records that use the word checkpoint but do not own the same thing.

1. Durable Graph execution persists the canonical `Run`, `NodeRun`, and `Attempt` history in `RunStore`, while `GraphContinuationStore` persists Graph-only traversal state such as the frontier, blackboard, routing history, `TraversalCheckpoint`, and `TraversalCommit`. `CanonicalDurableRunStore` assembles those two halves by the same canonical `run_id`. This is the live resume path and has in-memory, SQLite, and PostgreSQL persistence.
2. `orchestrator.waves` has `TaskCheckpoint`, a domain-specific recovery record keyed by `task_id` and versioned by recipe/code-registry versions. It is consumed by the wave orchestration path. It is not the universal execution or Graph recovery authority.
3. `maistro.events.checkpoints` defines a second canonical-looking `Checkpoint`, `CheckpointRef`, store protocol, in-memory store, and SQLite store keyed by `run_id`. Nothing in production constructs or reads one. Its `canonical_checkpoints` table is created only by the SQLite store's private schema, has no Alembic migration, and has no PostgreSQL twin. The package `maistro.events` re-exported the module and referenced all of its store methods in a keep-alive tuple, which made static reachability and dead-code signals look healthier than the runtime path was.

ADR-082826-d9f5 already decided the ownership boundary: `RunStore` is the sole authority for universal execution state, and Graph continuation lives beside it keyed by canonical `run_id`. Keeping another canonical-looking recovery record would recreate the second execution universe that convergence is removing.

## Decision

`RunStore` plus `GraphContinuationStore` is the canonical checkpoint/recovery record for durable Graph execution.

A Graph restore is authoritative only when both halves resolve under the same canonical `run_id`:

- `RunStore` owns the `Run`, `NodeRun`, and `Attempt` identities and lifecycle.
- `GraphContinuationStore` owns only Graph-specific resumable state and traversal evidence.
- `CanonicalDurableRunStore` assembles a recovery record only when the continuation key resolves to an existing canonical Run with that same key. Continuation state cannot create, substitute for, or resurrect a Run identity.

`maistro.events.checkpoints` is a superseded prototype, not an unfinished production subsystem. It is removed together with its package re-exports, SQLite-only shadow schema, self-contained tests, and Vulture keep-alive tuple. We will not add an Alembic migration or PostgreSQL implementation for `canonical_checkpoints`, because doing so would establish a second recovery authority rather than complete the existing one.

`TaskCheckpoint` remains a wave-orchestration domain record. Its `task_id` is valid within that domain, but it is not a key accepted by canonical Graph restore. The name overlap disappears when the unused events checkpoint types are retired; no behavior change to the wave path is required by this decision.

## Recovery invariant

A private task/checkpoint identity must never become authoritative merely because resumable state exists under that key. If a continuation exists under an identifier for which `RunStore.get_run(identifier)` returns no canonical Run, `CanonicalDurableRunStore.get(identifier)` returns no recovery record. Conversely, a canonical Run with no continuation is not fabricated into a resumable Graph record.

This is the executable form of M1-E2's rule that retired duplicate lifecycle stores cannot become authoritative after restore.

## Consequences

### Positive

- There is one answer to which persisted record may resume Graph execution.
- Static reachability no longer treats a package re-export as evidence that an unused checkpoint subsystem is product-reachable.
- Vulture is no longer silenced by references whose only purpose was to make an unused store look used.
- Future recovery work extends the already durable continuation/spine pair instead of creating a fourth persistence family.

### Negative / compatibility

- The unused `maistro.events.checkpoints` Python API is removed. Repository search found no production consumer, so preserving a compatibility import would retain the false reachability and undermine the decision.
- Historical SQLite files created directly by tests or private experimental callers may contain a `canonical_checkpoints` table. No supported production migration ever created or read that table, so it is intentionally not migrated into the canonical spine.

### Unchanged

- Durable Graph resume behavior and continuation persistence do not change.
- `TaskCheckpoint` and wave recovery behavior do not change.
- `RunStore`, `GraphContinuationStore`, traversal checkpoint semantics, and current execution-consumer work are outside this change.
