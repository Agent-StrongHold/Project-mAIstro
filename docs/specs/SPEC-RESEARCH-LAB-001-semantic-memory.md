---
id: SPEC-RESEARCH-LAB-001
title: "Research Lab canonical semantic-memory domain and product contracts"
kind: spec
status: Proposed
created: 2026-11-02
layer: Memory
contracts: [boundary, behavioral]
related: [SPEC-2310, SPEC-241, ADR-013, ADR-080, ADR-091, ADR-082226-5104]
---

# Research Lab: semantic memory domain and interaction contract

## Product and architecture invariant

Research Lab is a Workspace product surface and domain extension of canonical memory, **not** an independent memory system. Canonical PostgreSQL holds durable records; the hot graph, vector index, mind map and assembled context are projections. Reuse canonical Workspace/principal authorization, memory exposure, Graph/Run/NodeRun/Attempt, Goals, scheduler, HITL, Effects/Events/Audit and Invocation budgets. UI, API and Workspace Agent must call the same backend operations. This spec is post-convergence product work, not a requirement to close #2310.

## Canonical domain model (logical contract, physical schema deferred to existing PostgreSQL migration authority)

All records have stable IDs, owner/scope, provenance, created/recorded timestamps and immutable revision lineage. Domain IDs are references, not new memory authorities.

| Record | Required semantics |
|---|---|
| Topic | First-class concept/root with label, Workspace context and graph membership edges; no exclusive ownership of connected propositions |
| SourceDocument | Original notes/media/document reference, author, captured/learned dates, revisions, content hash and stable passage/page/timestamp anchors; preserve exact original revisions |
| Proposition | Normalized claim, contextual qualifiers, identity and version; no implicit endorsement or truth assertion |
| Belief | Believer principal, proposition, context, accepted_at, acceptance provenance, active/withdrawn/superseded status and version; explicit user endorsement only |
| Relationship | Stable typed directed/symmetric semantic edge, context, provenance, revision and confidence in *classification of the relation* where assessed |
| Evidence | Source anchor, proposition, stance support/oppose, reliability assessment, independent-origin group, evaluation context and dates |
| Derivation | Joint ordered/set premises, conclusion, deductive/inductive/abductive method, rule identifier, validity/evaluation status, provenance and versions |
| TruthAssessment | Proposition + evaluation context, enum truthiness, calibrated probability of classification correctness, evidence snapshot, assessor/model/version and assessed_at |
| AuthorityPolicy | Source/domain/task-specific priority, applicable context, effective dates, provenance; does not mutate source reliability |
| KnowledgeChange | Before/after references, actor, reason, canonical Run/NodeRun/Attempt where agent-produced, approval/effect/audit refs and recorded_at |

Truthiness enum: `SUPPORTED`, `REFUTED`, `DISPUTED`, `UNVERIFIED`, `CONTEXT_DEPENDENT`. Confidence is a number in [0,1] measuring correctness of the classification, not probability of truth. Context-dependent may later become a qualifier after evaluation. Memory tier/weight remains retrieval prioritization, never truth or belief. The graph may contain unresolved claims with provenance and no support.

## Logical semantics and inference

Adopt established formal semantics as appropriate: predicate/description logic and RDF/OWL relationship conventions, PROV-O for provenance, defeasible logic and bipolar argumentation for conflicting support. Standards specify meaning, not a mandated graph DB. Axiom, premise and conclusion are **contextual roles**, not fixed mutually exclusive node types. An axiom is an accepted starting assumption within a framework; no derivation required. Belief does not imply objective truth. A conclusion can become a premise elsewhere. A deduction involving multiple premises must be represented as a joint derivation, not independently sufficient implication edges.

Relationship families: ontological (`IS_A`, `INSTANCE_OF`, `PART_OF`), logical (`IMPLIES`, `EQUIVALENT_TO`), evidential (`SUPPORTS`, `CONFLICTS_WITH`, `DERIVED_FROM`), causal (`CAUSES`, `INFLUENCES`) and contextual/temporal (`APPLIES_IN_CONTEXT`, `SUPERSEDES`, `PRECEDES`). `RELATED_TO` is non-inferential. Each relation has documented direction, symmetry, transitivity, inverse and allowed endpoint constraints; no unsupported inference (e.g. correlation does not entail causation).

## Evidence and belief rules

A conflict is explicit and both claims persist. Evidence supporting one incompatible claim can oppose the other *when the logical/contextual relation warrants it*. Maintain positive and negative support separately; distinguish strong disagreement from absence of evidence. Track source dependence and avoid counting copied claims multiple times. Avoid feedback amplification through cycles. Automatic truth reassessment and better-supported interpretation are permitted, including an unresolved outcome; never delete a losing proposition.

An explicit user-endorsed belief can be changed only after presenting evidence and obtaining user review/acceptance. Reject/defer leaves the belief unchanged while truth assessment continues to evolve. Approving a graph edit is not belief endorsement. Agent-generated propositions are not user beliefs. Every change retains original provenance and temporal history.

## Time and source authority

Track valid-from/to (real-world applicability), recorded-at (system knowledge), learned-at (user acquisition), assessed-at and belief accepted/withdrawn-at separately. Reconstruct what the system knew at an earlier recorded time and what claims applied at a valid time. Instructor authority can be primary for course-expectation questions during a course but is not globally superior to independent research after the course; historical reconstruction can still treat the lecture as authoritative evidence of what was taught.

## Notes and extraction lifecycle

1. Autosave complete note text with immutable revisions and stable passage anchors; never overwrite a user's original with a summary.
2. Lightweight incremental extraction identifies candidate entities, propositions, questions and possible relationships; preserve attribution (e.g. 'professor says X' does not mean user believes X).
3. At checkpoint/session completion, deeper canonical Goal/Graph/Run work resolves identities, checks duplicates, evaluates sources, proposes edges, detects conflicts and updates authorized durable semantic records.
4. Re-editing a note creates a new revision and re-evaluation, not retroactive deletion of earlier evidence; provenance links remain inspectable.
5. All agent writes go through canonical governance and audit; failure/degradation is visible and original notes remain retrievable.

## Sharing, access and retrieval

Within one Workspace, automatically link related authorized nodes. Same-owner cross-Workspace sharing is simplified but never bypasses destination audience ACL checks. Different-owner sharing requires explicit authorization. Live references default; snapshots are independently versioned and remain subject to access rights. User/global memory reuse is via canonical scoped services, never direct traversal of another Workspace's isolated working graph. Traversal must not leak inaccessible node existence, edge counts, labels, summaries or inferred secrets.

Retrieval starts from active topic(s), can traverse any *authorized* connected semantic knowledge and ranks by relevance, not mere accessibility. Exponential weighted-distance decay: `R(d)=R0*exp(-lambda*d)`, where d is nonnegative accumulated semantic edge cost and lambda is calibrated/configurable. Strong relations may have lower cost. Bound traversal, account for cycles and multiple paths without unbounded amplification; retain a reproducible ranked provenance trail. Retrieval relevance is independent of truth assessment, logical validity and user belief.

## User-facing operations and parity

API/Agent/UI parity for: create/edit/revise notes; attach source; create/link topics; inspect/edit relationship; inspect evidence and derivation; accept/withdraw belief with explicit endorsement; view historical state; review conflict; share/revoke/snapshot; run research Goal; retrieve source-grounded context. UI includes note editor, mind map, source panel, evidence and belief review, and history navigation. All mutations enforce canonical scope and policy; no UI-only storage.

## Acceptance tests (must be implemented before shipping)

- [ ] Notes survive process restart with byte-identical original revision and anchored extraction lineage.
- [ ] Same proposition appears under two topics without duplicate canonical identity; same user can hold distinct context-dependent beliefs.
- [ ] A note quoting an instructor creates attributed claim, **not** a user endorsement.
- [ ] Explicitly endorsed belief stays unchanged when contradictory evidence updates truth assessment; accept/reject/defer review behavior audited.
- [ ] Conflicting evidence yields separate positive/negative support, detects shared-origin duplicates, and prevents cyclic confidence inflation.
- [ ] Multi-premise deduction remains conditional on its premises; inference provenance and validity separate from evidential truth.
- [ ] Bitemporal reconstruction returns prior assessment, belief and source authority correctly.
- [ ] Unauthorized Workspace traversal and cross-Workspace share fail closed, including side-channel graph metadata.
- [ ] Retrieval rank decreases exponentially over weighted distance in controlled fixtures, without changing proposition truthiness.
- [ ] Real PostgreSQL durability, fresh-process restart, canonical Run provenance, permission enforcement and UI/API/Agent parity are demonstrated on an exact commit.

## Delivery boundaries

Phase 1: durable domain contracts, migration, note revision, graph CRUD and provenance. Phase 2: extraction/reconciliation, evidence assessment, temporal query and retrieval. Phase 3: UI and agent-driven research after #2310/#804/#105 canonical dependencies. Exact evidence-combination algorithm, ontology subset and decay parameters are engineering selections to be benchmarked and documented; do not pretend illustrative scores are calibrated.
