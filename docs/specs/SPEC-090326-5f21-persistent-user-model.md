---
id: SPEC-090326-5f21
title: "Persistent same-user model — consolidation, scope, provenance, and contextual retrieval"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-03
substrate:
  - maistro-engine#ADR-090326-a91c
  - maistro-engine#ADR-080
  - maistro-engine#ADR-082226-5104
implements:
  - maistro-engine#ADR-090326-a91c
related:
  - maistro-engine#SPEC-241
  - maistro-engine#SPEC-242
  - maistro-engine#SPEC-243
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
  - data
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-090326-5f21: Persistent same-user model

## Purpose

Specify the M3 product floor for a durable model of the authenticated user that can be learned across their Workspaces and selectively reused by different Workspace Agents without cross-Workspace Ladybug traversal or cross-principal leakage.

This is the implementation contract for #1047. It extends existing canonical memory; it does not introduce a second profile, identity, recommendation, Persona, or memory authority.

## Definitions

### Origin evidence

An observation, memory, conversation statement, user correction, artifact/effect outcome, Goal/Run result, or other canonical evidence that may support a fact about the user.

Origin evidence retains its own original scope. Nothing in this SPEC implicitly widens that evidence.

### User-model fact

A durable canonical memory record whose owner/scope is the same authenticated user and whose content has been explicitly promoted/consolidated as a useful fact about that user.

Examples include:
- preference: dislikes cilantro;
- possession: owns Canon 7D;
- plan: wants focal-range coverage from X to Y;
- interest: follows a particular racing series;
- working preference: wants Workspace sessions restored for longer absences.

A user-model fact is not the user's identity record and does not grant authority.

### Workspace-private memory

Memory whose canonical scope/owner remains Workspace, Project, private Agent, team, org, or another non-user scope. It may contribute evidence to a later user-model promotion only when policy allows, but remains inaccessible cross-Workspace until a distinct durable user-scope fact is created.

## Canonical record shape

The implementation MAY reuse/extend the existing memory model rather than creating a new table, but must be capable of representing at least:

```python
@dataclass(frozen=True)
class UserModelFact:
    fact_id: str
    user_id: str
    kind: str
    statement: str
    normalized_value: object | None
    confidence: float
    first_observed_at: datetime
    last_observed_at: datetime
    last_reinforced_at: datetime | None
    valid_from: datetime | None
    valid_until: datetime | None
    status: Literal["active", "contradicted", "superseded", "deleted"]
    provenance_refs: tuple[MemoryEvidenceRef, ...]
    source_workspace_ids: tuple[str, ...]
    sensitivity: str | None
    share_policy: str | None
    persona_relevance_hints: tuple[str, ...]
    corrected_by_user: bool
    revision: int
```

The concrete schema may differ, but the semantics above must be queryable and durable.

`user_id` is the canonical internal user identity. Email, UPN, display name, chat session id, Persona id, Workspace id, API key text, or Entra claim strings must not replace it.

## Promotion / consolidation

### Rule 1 — origin does not imply user scope

A memory being created in a Workspace owned by the user does **not** automatically make it a user-model fact.

### Rule 2 — Dreaming performs explicit promotion

Dreaming/consolidation may produce a promotion proposal when evidence suggests the information is a durable fact about the user and policy permits user-scope retention.

Conceptually:

```python
@dataclass(frozen=True)
class UserFactProposal:
    user_id: str
    kind: str
    statement: str
    evidence: tuple[MemoryEvidenceRef, ...]
    confidence: float
    temporal_validity: TemporalValidity | None
    sensitivity: str | None


def propose_user_facts(evidence: Sequence[MemoryEvidence]) -> Sequence[UserFactProposal]: ...

def apply_user_fact(proposal: UserFactProposal, *, policy: UserMemoryPolicy) -> UserModelFact: ...
```

The proposal/application boundary must preserve the source evidence rather than copying a model-generated summary with no traceability.

### Rule 3 — repeated and corroborating evidence strengthens confidence

Repeated observations may reinforce a fact. Contradictory evidence lowers confidence, marks the fact contradicted/reviewable, or creates a superseding revision. It must not silently overwrite the prior state.

### Rule 4 — external discovery is evidence, not user truth

A web page, video, search result, product listing, social post, or other externally discovered content cannot directly create a fact about the user. It may become source evidence only after a canonical user interaction/outcome/consolidation process supports the derived user fact.

## Scope and authorization

The access test has two phases:

1. **May this actor read the memory at all?** canonical identity/authorization/scope policy.
2. **Should this fact enter this context?** relevance and user preference.

Same-user behavior:
- An authorized Workspace Agent acting for user U may read active canonical `user`-scope facts owned by U.
- The Agent does not require a separate per-fact `shared_with_agent` marker merely because its Agent id differs from the Agent that first observed the evidence.

Private-memory behavior:
- A Workspace/Agent/private memory that has not been promoted to user scope remains governed by SPEC-242's explicit sharing/widening contract.
- A different user can never receive U's user-model fact through this path.

Ladybug behavior:
- Another Workspace's Ladybug graph is never a source read path.
- Cross-Workspace reuse is always a durable-memory query by canonical user scope.

## Contextual retrieval

Authorization is insufficient for injection into an LLM context or product surface.

User-model retrieval must account for at least:
- current Persona purpose/relevance lens;
- Workspace/Project/Goal;
- current conversation/task/question;
- fact confidence;
- temporal validity and recency;
- explicit user preferences, pinning, suppression, or "do not surface" signals;
- negative feedback and prior irrelevance;
- applicable sensitivity/policy.

The existing SPEC-243 hybrid lexical/vector/weight score may remain the base memory relevance score. User-model retrieval adds an eligibility/contextual-relevance layer; it must not rewrite SPEC-243 into a universal personalization formula.

A conceptual interface:

```python
@dataclass(frozen=True)
class UserModelQueryContext:
    user_id: str
    persona_id: str | None
    workspace_id: str
    project_id: str | None
    goal_id: str | None
    task_text: str


def retrieve_user_facts(ctx: UserModelQueryContext, *, k: int) -> list[RankedUserFact]: ...
```

## Persona relationship

Persona may supply relevance hints and learning interests, but Persona:
- is not the owner of a user fact;
- cannot grant access to a fact;
- cannot promote private memory on its own authority;
- cannot turn a low-confidence inference into fact merely because it fits its role.

This allows two Workspace Agents to know the same user while caring about different parts of the model.

## User correction, privacy, and deletion

The canonical service must support:
- inspect: "what do you believe about me?";
- correction of a fact/value;
- explicit reinforcement or disagreement;
- suppression from contextual surfacing;
- marking a fact/private category non-reusable where policy allows;
- delete/forget according to retention/legal policy;
- provenance inspection.

A user correction is high-value evidence and must affect later retrieval/consolidation.

Deletion/forgetting must prevent a stale Ladybug projection or old consolidation candidate from silently recreating the deleted fact. Tombstone/revision semantics may be used to fence stale writes.

## API / Agent parity

The service is backend/API authority. The Workspace Agent and any UI inspect/edit the same service.

At minimum, public service semantics must exist for:
- list/query relevant facts;
- inspect one fact/provenance;
- correct/revise;
- suppress/unsuppress where supported;
- delete/forget where allowed.

A UI is optional and must not own a second profile state.

## Required behavioral proofs

### Cross-domain relevance surprise

Given:
- Workspace A establishes with durable evidence that user U owns a Canon 7D;
- Dreaming promotes that evidence into an active canonical user-scope fact;
- Workspace B is a software-development Workspace for U that has never discussed cameras;

When:
- a current software Goal requires camera/device defaults;

Then:
- B may retrieve the Canon 7D fact and offer it as a relevant default;
- the retrieval carries the fact's durable id/provenance/confidence;
- B never traverses A's Ladybug graph.

### Irrelevance negative proof

Given the same fact, when Workspace B is working on an unrelated database migration, the Canon 7D fact does not enter the selected user-model context merely because it is readable.

### Cross-user isolation

User V with similar Workspaces/Personas/content never receives U's fact.

### Private-memory negative proof

A camera-related observation that remains Workspace A/private scope and has not been promoted to user scope is unavailable to Workspace B.

## Acceptance criteria

- [ ] Durable user-model facts are keyed to canonical user identity and survive restart, backup, and restore.
- [ ] Origin evidence retains its original scope; promotion to user scope is an explicit consolidation operation.
- [ ] Promotion preserves provenance, confidence, temporal semantics, and source Workspace references.
- [ ] Contradictions cannot silently overwrite a fact.
- [ ] Same-user authorized Agents can query active user-scope facts without a redundant per-Agent share flag.
- [ ] Workspace/private memories remain governed by SPEC-242 until legitimately promoted/widened.
- [ ] No cross-Workspace Ladybug traversal is used for user-model retrieval.
- [ ] Canon 7D-style cross-domain E2E proves relevant cross-Workspace reuse.
- [ ] An unrelated-task E2E proves readable does not mean injected.
- [ ] Cross-user isolation is proven with colliding fact content and Persona names.
- [ ] User correction changes later retrieval and remains provenance-bearing.
- [ ] Delete/forget fences stale consolidation/working-memory re-creation.
- [ ] Agent and API use the same canonical service.
- [ ] External discovery cannot directly assert new durable facts about the user.

## Non-goals

- Optimizing Ladybug hydration/eviction beyond #776's M3 product floor.
- Choosing the final reranking model or thresholds; broader optimization belongs to M4 #301/#105.
- Making all Workspace memory user-global.
- Cross-principal/team/org consent UX beyond SPEC-242.
- Creating a marketing/advertising profile or engagement-ranking subsystem.

## Issue ownership

- #1047 — implementation owner
- #776 — per-Workspace Ladybug prerequisite/working projection
- #1046 — M3-E parent product epic
