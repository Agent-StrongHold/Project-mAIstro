---
id: ADR-092526-4391
title: "The durable user model is a separate UserModelFact record; same-user promotion into it is audited self-consent (amends SPEC-242)"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-09-25
history:
  - status: Proposed
    date: 2026-09-25
substrate:
  - maistro-engine#ADR-080
  - maistro-engine#ADR-082226-5104
implements: []
related:
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
  - maistro-engine#ADR-083026-3d92
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-092526-4391: The durable user model is a separate UserModelFact record; same-user promotion into it is audited self-consent

## Context

Issue [#1047](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1047) asks for a durable,
provenance-bearing model of one user that survives across Workspaces. What someone learns while
working in Workspace A (for example, "the user owns a Sony A7 IV") should help in Workspace B,
without B reading A's working memory and without leaking into unrelated tasks.

Nothing on `develop` provides this, and three existing pieces point in different directions:

- **Episodic memory decays by design.** ADR-080 and SPEC-240 make `EpisodicMemory` weaken without
  reinforcement ("memory must forget"). A user model must not do that. A fact such as "prefers
  metric units" should stay true until the user or the evidence changes it, not fade because nobody
  mentioned it for a month.
- **SPEC-242 has one widening path.** Every move to a broader scope goes through
  `propose_widen -> resolve_consent -> apply_widen` with a `ConsentTask` addressed to the owner
  (`maistro/memory/episodic/sharing.py`). If the owner of the fact and the owner of the target scope
  are the same person, that path asks the user to approve sharing a fact with themselves. It says
  nothing about same-user reuse.
- **Hive already stores a per-user profile.** `backend/services/profile_store.py`
  (ADR-083026-3d92, SPEC-083026-ef62) holds a flat document of preferences that the user writes
  through the profile panel and the `profile_get` / `profile_set` / `profile_delete` chat tools. It
  keeps an integer revision counter but no provenance, revision lineage or tombstones, and a
  delete is a hard delete. Building the user model as a second "User"
  object next to it would give two answers to "what do we know about this user".

ADR-082226-5104 already fixes where working memory lives. Each active Workspace gets its own
LadybugDB working graph. That graph is a disposable projection, and it is physically separate from
every other Workspace's graph.

The owner decided the two open questions on #1047 on 2026-09-25:

1. The durable user model is a new user-owned record type (`UserModelFact`) with revision lineage,
   sensitivity and shareability, tombstones and a temporal validity window. It is kept separate
   from decaying episodic memory and is revised or tombstoned explicitly.
2. Promoting a Workspace-scoped or Agent-scoped fact to the same user's USER scope is automatic
   self-consent with an audit entry, not a `ConsentTask`. Cross-user sharing still needs consent
   under SPEC-242.

This ADR records those two decisions. It also proposes the detailed rules needed to implement
them. Each rule that goes beyond the owner's words is marked **(proposed)** and is part of what
ratifying this ADR accepts.

## Decision

### 1. The user model is a separate `UserModelFact` record type

The durable user model is a **new user-owned record type**, `UserModelFact`. It is not
`EpisodicMemory` at USER scope with extra fields, and it is not a new `MemoryTier`. Each fact
carries at least:

| Field | Meaning |
| --- | --- |
| `user_id` | The canonical authenticated user id. It is the only owner key. |
| `fact_id` / `revision` / `supersedes_revision` | Revision lineage. A correction appends a new revision that points at the one it replaces; history is never rewritten in place. |
| `statement` + structured subject/predicate/value | What is believed about the user. |
| `provenance` | The evidence the fact came from: source record ids, source scope, Workspace/Project id, agent id, time. |
| `sensitivity` | How sensitive the fact is (for example, health or finances versus a camera model). It gates recall and display. |
| `shareability` | Whether and with whom the fact may leave the user's own principal. The default is "self only". |
| `valid_from` / `valid_to` | The temporal validity window ("lived in Austin, 2019-2024"). |
| `tombstone` | Set by an explicit deletion. It records who deleted the fact, when and why. |

The following rules apply:

- **No decay** (owner decision). SPEC-240's decay and reinforcement never touch a `UserModelFact`. A fact changes
  only through an explicit revision, a tombstone, or the end of its validity window.
- **Contradiction never overwrites silently** (from the #1047 acceptance criteria). New evidence that conflicts with a current fact
  produces either a new revision, whose lineage is kept and whose provenance names the new
  evidence, or a review item for the user (proposed). It never replaces the value in place.
- **A tombstone blocks re-promotion** (from the #1047 acceptance criteria). Once a fact is tombstoned, promotion must not recreate it
  from the same evidence. This includes a stale LadybugDB working graph that still holds the
  deleted fact. Only an explicit user action can bring it back, and that creates a new revision
  with its own provenance.
- **PostgreSQL is the system of record.** Following ADR-082226-5104 §§1, 5 and 6, the fact lives
  in PostgreSQL, survives restart, backup and restore, and is keyed to the canonical user id.
  Ladybug may cache a projection of it and is never authoritative for it. This ADR does not add a
  SQLite twin; ADR-082226-5104 §9 requires a concrete requirement before SQLite becomes another
  canonical store, and that is a separate decision.

### 2. Same-user promotion is automatic, audited self-consent

This amends [SPEC-242](../specs/SPEC-242-memory-cross-scope-consent.md).

When a fact scoped to a **Workspace, Project or AGENT** is promoted into the **same authenticated
user's** user model, the promotion is **automatic self-consent**. No `ConsentTask` is created, and
the promotion writes an **audit entry** (owner decision). The owner named Workspace- and
Agent-scoped facts. Project-scoped facts are included on the same basis (proposed): what makes a
promotion self-consent is that the source fact's authenticated owner is the target user, as the
conditions below require. Project or Workspace membership never establishes it. A `Project` has no
owner field, and a collaborative Workspace or Project has memberships for several principals, so
containment says nothing about whose fact it is.

The entry records the user id, the new fact id and revision, the source scope and Workspace/Project
id, the promoting agent or service, the provenance references, and the time. The entry is written
atomically with the fact, so a promotion without its audit entry cannot exist (proposed).

Self-consent applies only when **all** of these hold (proposed, derived from "same user"):

- The source fact's owner and the target user model's owner are the same canonical user id, taken
  from the authenticated principal. A user id supplied by the caller does not count.
- The target is that user's own user model, and the promoted fact's shareability defaults to
  "self only". Promotion does not widen who can read the fact beyond that one user.
- No tombstone exists for the same fact.

Every other widening still needs consent under SPEC-242's
`propose_widen -> resolve_consent -> apply_widen` flow. That includes widening a fact to **another
user** (owner decision) or to **TEAM, ORGANIZATION or GLOBAL** scope, and changing a user-model
fact's shareability beyond "self only" (proposed). SPEC-242's functions are typed over
`EpisodicMemory` today, so applying the same consent flow to a `UserModelFact` is follow-up work,
not something that exists. Self-consent is a narrow exception for "the same person,
into their own model". It does not bypass SPEC-242.

Promotion adds no authorization. Persona and relevance may decide *whether* a fact is recalled
for a task. They never decide *whether* a principal may read it (from the #1047 acceptance
criteria: "Persona affects relevance but not authorization").

SESSION-scoped facts are not covered by this ADR. Whether a fact that exists only in a session can
be self-promoted, or must first be consolidated into Workspace or Agent memory, is left open.

### 3. Hive's profile document is not a second user model

The Hive `profile_store` document stays what ADR-083026-3d92 made it: **user-authored preferences**
with one durable owner. It is not a user model, it is not a source that promotion reads from
silently, and the user model does not duplicate it. The relationship is one-directional. A value
the user sets in the profile is explicit, user-authored input and outranks an inferred
`UserModelFact` about the same thing, and inferred facts never write back into the profile
document (both proposed).
The user model and the profile are keyed to the same canonical user id, so there is one User and
two record kinds attached to it, not two User objects.

### 4. Another Workspace never traverses a Ladybug working graph

Cross-Workspace reuse happens **only** through promoted `UserModelFact` records read from the
durable store. Workspace B never opens, queries or traverses Workspace A's LadybugDB working graph
(ADR-082226-5104, §5). A fact that was not promoted stays in A's working memory and durable
Workspace-scoped records, and B cannot see it.

## Consequences

### Positive

- Workspaces can reuse what is known about a user without breaking Workspace isolation. B reads
  promoted facts, never A's working graph.
- Users are not asked to approve sharing their own facts with themselves. The audit entry keeps
  every promotion traceable.
- Corrections and deletions carry provenance and cannot be undone by a stale working graph.
- "Memory must forget" still holds for episodic memory, because the non-decaying record is a
  different type.

### Negative / Trade-offs

- There is a new record type, store protocol, PostgreSQL store and migration to build and
  maintain, in addition to episodic memory.
- The self-consent check depends on getting the canonical user id right. If the promotion path
  accepts a user id from anywhere other than the authenticated principal, it becomes a cross-user
  leak. Implementations must test the two-user isolation case.
- `MemoryScope` has no WORKSPACE or PROJECT value today. Workspace and Project binding is carried
  as ids next to the scope, so the implementation must state how the "source is Workspace- or
  Project-scoped" test is evaluated.

### Neutral

- This ADR decides the record shape and the consent rule only. The store, migration, promotion
  service, relevance-gated recall, context-assembly wiring, the Agent/API service and the
  cross-Workspace E2E are follow-up work on #1047.
- SPEC-242's `ConsentTask` data shape and functions are unchanged. This ADR adds one documented
  case in which they are not invoked. Extending them to `UserModelFact` is follow-up work.
