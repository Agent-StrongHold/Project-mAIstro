---
id: ADR-090326-a91c
title: "Persistent user model and adaptive Workspace experience"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-09-03
created: 2026-09-03
substrate:
  - maistro-engine#ADR-080
  - maistro-engine#ADR-082226-5104
implements: []
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
  - product
layer: Workspace
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Accepted
    date: 2026-09-03
    reason: "Explicit Workspace product decision: persistent same-user memory, adaptive Home, Workspace-Agent Attention, adaptive session restoration/settings, and bounded proactive curation."
---

# ADR-090326-a91c: Persistent user model and adaptive Workspace experience

## Context

MAIstro already has the right canonical pieces: a persistent Workspace Agent, canonical Workspace / Project / Goal / Run semantics, PostgreSQL + pgvector as durable memory, Ladybug as disposable per-Workspace working memory, Persona as persistent behavioral flavor, and governed Capability -> Provider -> Binding -> Invocation effects.

The missing decision is how those pieces combine into a long-lived user experience.

The product goal is not a collection of isolated assistants. The user should experience MAIstro as one persistent intelligence that increasingly understands them across time and across Workspaces, while each Workspace Persona remains a different lens on what is relevant. A food-blogging Workspace may learn camera equipment, restaurants and ingredient preferences. A software-development Workspace should later be able to use an already-consolidated camera fact when a software task suddenly becomes camera-specific, even if cameras were never discussed in that Workspace.

At the same time, that experience must not erase privacy/scope boundaries. ADR-080 part C currently says every cross-agent read requires explicit sharing. That is correct when information is being widened to another principal/owner/team/org, but it conflates that operation with an authorized Agent serving the **same user** reading canonical memory already scoped to that user.

The Workspace UI also needs a governing rule. MAIstro is an AI platform: users may live in Workspace Home, a specialized surface, the Workspace Agent conversation, or the API only. No particular page can be product authority.

## Decision

### 1. The durable user model is canonical user-scope memory, not a second profile database

MAIstro maintains an increasingly detailed model of the authenticated user by consolidating eligible evidence from their interactions across Workspaces.

The user model may contain provenance-bearing facts and preferences such as interests, goals, desires, dislikes, constraints, possessions, plans, habits, relationships, work context, tastes and recurring needs. These are ordinary durable memory records/projections in PostgreSQL + pgvector, tied to canonical user identity. They are not a new User object or a separate recommendation/profile store.

A consolidated user-level fact retains source provenance, confidence/uncertainty, first/last observed or reinforced time, contradiction/supersession information, temporal validity where applicable, and user correction/deletion state.

### 2. Same-user reuse is distinct from cross-principal sharing

A memory still defaults to its origin scope.

There are two different operations:

1. **Promoting evidence to canonical user scope for the same owner/user.** Dreaming may consolidate eligible evidence learned in one Workspace into a durable user-level fact. Any authorized Workspace Agent acting for that same user may later retrieve that user-level fact when relevant. This does not require a separate per-Agent "share with me" action because the durable record is already owned/scoped by the same user.
2. **Widening private information to another principal/owner/team/org.** ADR-080/SPEC-242 consent semantics still apply. Workspace-private, Project-private, private-Agent, team and org memory does not silently widen merely because the same platform can represent user-level memory.

Cross-Workspace reuse therefore happens through the durable user model. One Workspace never reads another Workspace's Ladybug graph.

### 3. Ladybug remains isolated per-Workspace working memory

Each active Workspace may have one disposable Ladybug graph. It contains hot associative context, current hypotheses, relationships, retrieved material and other working state. It may be discarded and rebuilt.

Ladybug is never durable authority and never a cross-Workspace memory bus. Dreaming may consume Ladybug relationships together with authoritative transcripts/memory/provenance as evidence; durable results are written through canonical memory persistence.

### 4. Persona is a relevance/learning lens, never authorization

Persona guides:
- what the Workspace Agent is curious about;
- what gaps it is inclined to ask the user to fill;
- what durable user facts it retrieves for a task;
- what it considers interesting/useful enough to surface;
- style, taste, purpose and behavior.

A general Persona may care broadly about cars, news, movies, work and hobbies. A food-blogging Persona may preferentially care about cuisines, restaurants, cameras/lenses, tripods, blogging platforms, travel and ingredients.

Persona never widens memory ownership, grants capabilities, or changes authorization.

### 5. Retrieval optimizes for surprising relevance, not indiscriminate leakage

Authorization to read user-scope memory is only the first filter. User-model facts enter current context only when relevant to the Persona, Workspace/Project/Goal, current conversation/task, recency/temporal validity, confidence, explicit preferences and negative evidence.

A camera fact should not appear in unrelated software work. It may appear immediately when the software Goal starts configuring image ingestion or camera defaults.

### 6. Workspace Home is adaptive composition over optional projections

Workspace Home is the baseline default landing surface. By default it may contain miniature projections of Goals, tasks/backlog, recent artifacts, Workspace-Agent chat, a micro Design surface, recent chat sessions/quick chat, current work and other relevant canonical resources.

Unpinned space is composed by the Workspace Agent from what it judges most useful now. That can include prior work or governed external discoveries such as articles, videos, images, news, products/deals or events.

Every region can be pinned, rearranged and resized. The user may pin 100% of Home and intentionally remove all Agent-composed space. Pinning changes presentation preference, not the identity or authority of the underlying resource.

### 7. No UI surface is required

Every substantive Workspace operation must be available through canonical backend/API services and usable by the Workspace Agent. UI surfaces are projections and controls over those services.

The Agent must never need to click or automate its own UI to change a Goal, task, setting, Attention item, layout preference or other canonical state. An API-only/headless user is a first-class user.

### 8. Workspace return behavior is adaptive rather than threshold-coded

Workspace Home is the fallback default, but sufficiently recent return restores the previous working surface/state.

"Recent" is policy based on both absolute absence time and absence as a proportion of the prior session, plus explicit/learned user preferences. A request such as "hold onto my sessions longer and take me back when I come back" materially expands that restoration policy.

Repeated immediate navigation to another surface may cause the Workspace Agent to ask whether the user wants that surface as the default. There is deliberately no universal count such as 35 visits. Explicit user defaults outrank learned preferences.

### 9. The Workspace Agent may edit user settings through canonical settings authority

The Agent may change ordinary user preferences/settings when the user asks or when an explicitly allowed adaptive-preference policy applies. These writes use the same canonical settings service/API as UI controls, are attributable/reversible, and cannot expand authorization.

### 10. Attention belongs to the persistent Workspace Agent

Attention is not tab-local notification state. It is the Workspace Agent's durable prioritized set of things that may require the user's foreground participation while the Agent orchestrates Workspace Goals.

Priority is ordered:
1. severity;
2. time-sensitive answer;
3. blocks the user's current action;
4. queued questions that may be deferred;
5. follow-up suggestions that may be deferred;
6. proactive suggestions, which enter Waiting by default.

Deferred items may rise into popup or blocking Attention when deadlines, consequence, dependency position, changed context or other evidence warrants it. Age alone does not force escalation. Every automatic escalation retains an inspectable reason.

Blocking items stay foreground-blocking until resolved or the underlying blocker disappears. Popup items may be deferred. Waiting must expose an indication of the quality/importance of what is accumulating, not only a raw count.

Attention may navigate the user to another surface. The prior surface retains its presentation/work state so returning is like coming back to a desk with the papers still where they were left.

### 11. Dreaming and idle compute may support bounded proactive curiosity

Dreaming is both memory maintenance and a source of better future relevance: consolidate evidence, resolve/flag contradictions, identify useful information gaps and produce a stronger durable user model.

Separately, while the user is away, MAIstro may perform bounded proactive discovery. Cheap/local CPU models may do broad high-recall scanning/classification/dedupe; stronger local or hosted models may curate a much smaller candidate set. Final selection uses Persona + user model + current Workspace/Goals/recent activity.

All physical work is canonical Run -> NodeRun -> Attempt. Network/model/provider actions use governed Invocations and applicable M2 Warden/Sentinel/SSRF/credential rules. Ordinary proactive findings go to Waiting/unpinned Home, not interruption.

This is usefulness-oriented curation, not an engagement feed or unbounded crawler.

## Consequences

### Positive

- Workspaces compound knowledge about one user instead of repeatedly starting from zero.
- Different Personas can know the same durable facts while selectively caring about different subsets.
- Cross-domain "how did it know that?" moments become an intentional product capability.
- Ladybug keeps its clean role as fast disposable working memory.
- Privacy semantics become clearer: same-user canonical user memory is not the same as sharing private memory to another owner.
- UI, Agent and API remain semantically aligned.
- Workspace Home can serve users who want an adaptive Mission Control and users who want a fully fixed dashboard.
- Idle compute can improve the next session without granting a background system new authority.

### Trade-offs

- User-model consolidation/retrieval is a new correctness and privacy surface: over-promotion feels invasive; under-promotion loses the product benefit.
- Relevance quality must be measured; access permission alone cannot justify injecting a fact into context.
- Durable preference/adaptation state needs transparent correction and deletion behavior.
- Proactive discovery needs strict cost/network/source budgets to avoid becoming noisy or expensive.

## Clarification of ADR-080 part C

This ADR **does not repeal** ADR-080/SPEC-242 consent for widening memory to another principal/owner/team/org.

It supersedes only the interpretation that *every different Agent identity constitutes a different memory owner*. An authorized Workspace Agent acting for the same canonical user may read that user's canonical user-scope memories without a separate share flag, subject to scope, policy and relevance filtering.

A private Agent/Workspace memory does not become user-scope merely because the same user owns the Workspace; promotion/consolidation is an explicit canonical memory operation with provenance.

## Acceptance criteria

- [ ] Durable same-user memory can be learned in Workspace A and contextually reused in Workspace B without B reading A's Ladybug graph.
- [ ] The same fact is excluded from an unrelated task, proving relevance filtering rather than blanket injection.
- [ ] Memory owned by another principal/team/org remains unavailable without the existing explicit sharing/authorization contract.
- [ ] Persona changes relevance/learning behavior but never authorization.
- [ ] Workspace Home can be 0–100% Agent-composed depending on pinning and is not required for Agent/API use.
- [ ] Recent-session restoration and explicit/learned default behavior share one durable preference contract.
- [ ] Workspace Agent can modify an ordinary user preference through the same backend service used by UI/API.
- [ ] Attention priority/escalation follows the ordered model above and persists across restart.
- [ ] Proactive discovery is budgeted, governed and normally non-interrupting.

## Implementation ownership

- M3-E epic: #1046
- per-Workspace Ladybug floor: #776
- durable user model: #1047
- adaptive Workspace Home: #1048
- Attention/Waiting: #1049
- adaptive landing/settings: #1050
- bounded proactive curation: #1051
- broader M4 Ladybug/retrieval/Dreaming optimization: #301/#105
