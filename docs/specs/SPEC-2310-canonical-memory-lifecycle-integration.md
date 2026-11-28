---
id: SPEC-2310
title: "Canonical memory consolidation, sharing, approval, promotion and mutation NodeRuns"
kind: spec
status: Proposed
created: 2026-11-02
layer: Memory
contracts: [boundary, behavioral]
related: [SPEC-241, SPEC-215, ADR-080, ADR-091, ADR-082226-5104]
issues: [2310, 804, 1046]
---

# SPEC-2310: Canonical memory lifecycle integration

## Scope and authority

Close #2310 by making existing episodic consolidation, sharing, learning approval/promotion and mutation operations reachable from real canonical Graph -> Run -> NodeRun -> Attempt execution. **Do not** create a scheduler, agent, durable memory store, approval ledger, effect runner or event/audit authority. PostgreSQL is durable authority; Workspace hot graph is a disposable projection. Existing learning lifecycle and memory-exposure policy remain authoritative. Team scope is deferred; supported v1 scopes are Workspace, user, global. Historical enum values are not permission to expose legacy scopes.

## Existing seam

`maistro.memory.working.dreaming.collect_candidates` is read-only; `maistro.memory.episodic.consolidation.consolidate` returns `MergeProposal` and `ContradictionFlag`; `apply_merge` and `apply_contradiction` transform records; `run_batch` takes persistence callbacks and does not establish canonical execution. Existing SPEC-241 pure-function tests do not prove production reachability. `quality/reachability-dispositions.json` lists five CONNECT modules. Preserve the existing episodic-weight semantics; do not conflate them with Research Lab's truth classification.

## Graph contract (logical stages, not a new execution engine)

1. **Candidate NodeRun (read):** receives authorized Workspace/actor/Goal scope and bounded candidate request; reads canonical episodic memory or a safely hydrated same-Workspace projection; returns stable candidate ids, versions/content fingerprints, source provenance and snapshot identity. Fail closed on missing scope or failed durable read; no empty-success fallback.
2. **Proposal NodeRun (pure/compute):** consumes candidate snapshot, deterministic similarity/contradiction judge identities and thresholds, and produces versioned `MergeProposal` / `ContradictionFlag` with input ids, source versions, rationale, judge version, Run/NodeRun/Attempt correlation and review disposition. No durable mutation.
3. **Policy/approval stage:** canonical authorization and ADR-057 exposure gates run for each proposed effect. Resolve review requirements using existing HITL approval lifecycle; WAITING/PAUSED states use canonical wakers, never a private poller. A user accepting an edit does not automatically endorse a proposition as belief.
4. **Apply NodeRun (effectful):** re-check authorization and optimistic candidate versions, apply each authorized proposal via injected authoritative store/effect boundary, and atomically commit record revisions, lineage and canonical audit/outbox events. Absorbed memories are tombstoned, never physically purged. Contradictions are retained and flagged; do not silently choose a winner. Stale candidates require re-proposal rather than blind overwrite.
5. **Projection refresh:** invalidate/rebuild disposable per-Workspace working graph from committed canonical state; projection failures are observable and do not roll back or replace authoritative durable writes.
6. **Completion:** canonical Run/Goal truth reports proposals, applied/skipped/rejected/conflicted counts and durable evidence refs; a terminal Run alone does not prove Goal completion.

These are **behavioral contracts**: implement using the repository's actual Graph definition/Node handler/Invocation APIs after verifying their signatures. Do not invent an independent Graph registry or new execution schema. Recurrence uses existing schedule-to-Run semantics; immediate trigger enters the same canonical path.

## Five-module disposition matrix

| Module | Required production consumer / exit |
|---|---|
| `maistro.memory.episodic.consolidation` | Proposal and apply NodeRuns via canonical episodic store |
| `maistro.memory.episodic.sharing` | Authorized, consent-checked share NodeRun; same-user reuse must not expose private Workspace projection |
| `maistro.memory.learnings.approval` | Canonical HITL policy stage invoked by learning promotion; no private approval lifecycle |
| `maistro.memory.learnings.promoter` | Governed promotion NodeRun using existing `LearningStore.promote_learning` evidence/validator fields |
| `maistro.memory.mutations` | Governed mutation persistence NodeRun; only after existing validation, policy and effect checks |

If a module is genuinely superseded, document replacement and behavioral parity and mark RETIRE with `replaced_by`; do not delete simply to pass reachability.

## Authorization and provenance

All read/list/traverse/propose/apply/retry/replay paths enforce canonical principal, Workspace membership, effective scope and user/global sharing policy. Same-user across Workspaces is not blanket authorization. No cross-Workspace traversal of another private working projection. Persist actor, delegated principal where relevant, Workspace, Goal, Graph, Run, NodeRun, Attempt, source ids, input versions, decision/policy version, approval reference, output ids and timestamps. Do not embed secrets or unauthorized source text in events or errors.

## Retry and recovery

An effect has stable logical identity derived from canonical invocation and proposal identity; duplicate delivery/reclaimed Attempts cannot duplicate a merge, tombstone, promotion, share or audit effect. Check candidate versions at apply. On crash before commit: no partial durable effect. After commit but before acknowledgment: retry returns the prior committed result. After restart: authoritative PostgreSQL reads reconstruct results and working projections. Failure is explicit; do not substitute in-memory/SQLite durability on the PostgreSQL production path.

## Test and closure matrix

- [ ] Real entrypoint creates a Graph/Run with candidate -> proposal -> approval (when required) -> apply NodeRuns; capture exact tested commit and Run/NodeRun IDs.
- [ ] Merge path and contradiction path produce correct, non-destructive durable state, including input provenance and flags.
- [ ] Concurrent update invalidates stale proposal; retry and crash-injection prove exactly-once logical effects and recoverable completion.
- [ ] Denied foreign Workspace, user and global-share operations fail closed; same-user cross-Workspace path respects explicit scope and authorization.
- [ ] Approval accepted, rejected, timed out and resumed use canonical HITL/Run state; rejected mutation does not write.
- [ ] Learning promotion and skill mutation follow existing validation/exposure policies, with immutable validation evidence.
- [ ] Real PostgreSQL restart with a new process/pool recovers records, lineage, events and graph rebuild. No skipped database leg reported as pass.
- [ ] Reachability and disposition gates green on exact head; remove only modules demonstrably reachable or properly retired.
- [ ] No new authoritative lifecycle, scheduler, store or UI-only action.

## Dependency boundary

#804 owns persistent Goal reconciliation and wakers; #105 owns retained observation/full-result log PostgreSQL durability. #2310 must not locally repair these through duplicate infrastructure. SPEC-241's historical checked acceptance is pure-function scope, not proof of this integration. Research Lab semantic propositions are separately specified and are not a new closure condition for #2310.
