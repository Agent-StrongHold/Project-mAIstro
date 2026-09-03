---
id: SPEC-090326-d3c2
title: "Bounded proactive Workspace discovery and overnight curation"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-09-03
substrate:
  - maistro-engine#ADR-090326-a91c
implements:
  - maistro-engine#ADR-090326-a91c
related:
  - maistro-engine#SPEC-090326-5f21
  - maistro-engine#SPEC-090326-8b64
supersedes: []
blocks: []
blocked-by: []
contracts:
  - product
  - behavioral
  - security
tests: []
layer: Workspace
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-090326-d3c2: Bounded proactive Workspace discovery and overnight curation

## Purpose

Specify #1051: the Workspace Agent may use idle/overnight time and heterogeneous compute tiers to discover and curate a small amount of unusually relevant external/internal context for the user.

This is a governed Workspace-Agent workload, not a recommendation-feed subsystem, private crawler, alternate scheduler, or separate knowledge/memory authority.

## Product objective

The user should be able to leave MAIstro and return to a Workspace that is more useful because the persistent Agent spent bounded cheap compute looking for things that plausibly matter to this user **in this Persona/Workspace/Goal context**.

Examples:
- a restaurant article or upcoming special relevant to a food-blogging Workspace;
- a tripod review matching a known photography need;
- a lens deal that fills a previously discussed focal-range gap;
- a sale on a frequently used ingredient;
- a relevant video, paper, repository, event or news item;
- yesterday's unfinished work resurfaced because it is now useful;
- a question that fills a meaningful user-model gap.

The output should be a tiny curated set relative to the candidate set discovered.

## Architecture

```text
Persona + durable user model + Workspace/Projects/Goals + recent activity + preferences
        ↓
discovery intents / gaps / watch topics
        ↓
bounded cheap/local scout Runs
        ↓
candidate source items with provenance/freshness
        ↓
trust / dedupe / policy / freshness filtering
        ↓
mid-tier relevance extraction (optional)
        ↓
stronger curator/judge on a small candidate set (optional)
        ↓
ranked discovery candidates with relevance explanation
        ↓
Waiting / unpinned Workspace Home
        ↓
#1049 escalation only when current evidence warrants popup/blocking
```

All execution remains canonical Graph -> Run -> NodeRun -> Attempt.

Every network/model/provider/tool operation uses Capability -> Provider -> Binding -> Invocation and applicable M2 Warden/Sentinel/SSRF/credential/tenant policy.

## Discovery intent

A `DiscoveryIntent` describes something worth scanning for without becoming a self-expanding subscription graph.

Conceptually:

```python
@dataclass(frozen=True)
class DiscoveryIntent:
    intent_id: str
    user_id: str
    workspace_id: str
    persona_id: str | None
    goal_ids: tuple[str, ...]
    query_or_topic: str
    rationale_refs: tuple[str, ...]
    source_policy: SourcePolicy
    expires_at: datetime | None
    budget: DiscoveryBudget
    priority: float
```

Intents may originate from:
- explicit user request ("watch for...", "show me more...");
- Persona-guided curiosity;
- durable user-model facts/interests/plans;
- Goal dependencies;
- Dreaming-identified gaps;
- prior surfaced-item feedback;
- scheduled/known time windows.

An intent does not grant network/source access beyond canonical policy.

## Heterogeneous compute tiers

### Tier 1 — scout

Prefer cheap/local CPU-capable models or deterministic tools for tasks such as:
- source discovery/search-query generation;
- classification;
- title/metadata extraction;
- dedupe/fingerprinting;
- keyword/entity matching;
- initial freshness filtering;
- broad relevance screening.

The system must not require a frontier model for every source/candidate.

### Tier 2 — intermediate curator

Optional inexpensive local/hosted models may:
- summarize candidates;
- link source content to known user facts/Goals;
- identify novelty/redundancy;
- estimate whether stronger judgment is warranted.

### Tier 3 — strong curator/judge

A stronger model/provider may operate on the reduced candidate set when nuanced judgment materially improves value.

Model identity is Provider/configuration, not product identity. Deployments may use different tiers or skip tiers.

## Source candidate record

A candidate surfaced from external discovery must preserve at least:
- canonical discovery Run/Invocation provenance;
- source URL/resource identity;
- fetched/observed time;
- source/publisher when available;
- freshness/expiry metadata when applicable;
- content digest or stable dedupe key where feasible;
- trust/security classification;
- concise source-derived summary;
- relevance evidence references;
- novelty/dedupe decision;
- final surfacing disposition.

External content remains untrusted input under M2 security.

## Budget and bounded autonomy

Every proactive discovery campaign/run is constrained by explicit durable policy. Supported dimensions SHOULD include:
- wall-clock budget;
- local compute/CPU budget or work-unit ceiling;
- hosted-model token/spend budget;
- network request/source count budget;
- maximum candidates discovered;
- maximum candidates fetched/read;
- maximum candidates reaching stronger curation;
- maximum items surfaced;
- recrawl/backoff/freshness interval;
- source/category allow/deny controls;
- quiet/idle windows;
- Workspace/user enable/disable state.

Budget exhaustion is a truthful stop condition, not a failure that triggers unlimited retry.

No discovery process may recursively create unbounded new discovery intents merely because a source contains more links/topics.

## Trust and network boundaries

- outbound HTTP/browser/source access uses the actual governed M2 network boundary;
- redirects/DNS/private-address rules and browser-specific egress remain enforced;
- no ambient credentials are supplied to a scout merely because it is unattended;
- untrusted content is scanned/treated as untrusted before it re-enters trusted model context according to Warden policy;
- a source cannot issue instructions that expand the discovery campaign, write memory, change Goals, or invoke effects outside the host-owned Graph/policy.

## Relevance / ranking

Final selection should consider:
- Persona relevance;
- current Workspace/Project/Goal relevance;
- durable user-model relevance;
- novelty vs what the user already knows/saw;
- temporal usefulness;
- source trust/confidence;
- explicit positive/negative preferences;
- prior dismissals/accepted discoveries;
- expected usefulness vs cost/noise.

The ranking objective is usefulness, not engagement/time-on-screen/click-through.

The exact scoring model is tunable and may later be improved under M4. M3 requires the input/evidence contract and bounded behavior, not one hard-coded formula.

## Surfacing contract

Ordinary proactive discoveries default to:
- `WAITING`; and/or
- unpinned adaptive Home regions.

They do not become popup Attention merely because they score highly.

A candidate may be promoted under #1049 only when evidence changes its Attention class, for example:
- an expiring deal/opportunity becomes time-sensitive;
- a discovered security problem becomes severe;
- new information becomes a blocker for an active Goal.

Any promotion retains the #1049 escalation reason/evidence.

## Relevance explanation

The product should be able to explain why an item was surfaced using inspectable evidence, not hidden chain-of-thought.

Example:

> This lens is compatible with your known camera, fills the focal-range gap recorded in your photography plan, and is currently below the price range you previously discussed.

The explanation must not fabricate or expose private facts outside the current user's authorized context.

## Feedback

User actions such as:
- dismiss;
- "not relevant";
- "show me less news";
- "watch this more closely";
- save/pin/open;
- explicitly reject a category/source;

must update canonical preferences and/or eligible user-model evidence rather than only hiding a client card.

A click alone should not necessarily be interpreted as durable positive preference; the feedback policy should distinguish explicit from inferred signals.

## Relationship to Dreaming and memory

Dreaming may:
- improve the user model;
- identify information gaps;
- propose bounded discovery intents;
- consolidate user feedback from discoveries.

Discovery may return source evidence useful to later conversations/Goals.

But arbitrary external content **cannot directly create a trusted durable belief about the user**. SPEC-090326-5f21's promotion/consolidation rules remain authoritative.

Likewise, discovered facts about the world remain sourced knowledge/evidence; they do not become unsourced user memory merely because the Agent found them.

## Scheduling / unattended operation

A proactive run may be scheduled/triggered by canonical scheduler/event/idle policy. It must not create a private forever-loop.

The cadence can be configured (overnight, idle, periodic, explicit "while I'm away", etc.). Failure/restart semantics use canonical Runs/recovery.

Blocked security/network/provider state produces truthful degraded/blocked evidence; the system does not bypass policy to fill Home.

## Required behavioral proofs

### Cheap-to-strong funnel

A fixture with many candidate items proves:
- Tier 1 can eliminate/dedupe most candidates without frontier-model calls;
- only bounded reduced candidates reach strong curation;
- surfacing count is below configured maximum.

### Cost/budget stop

A campaign that reaches token/network/work budget stops admitting new discovery work and records the budget reason without unlimited retry.

### Non-interruption default

A high-relevance but non-urgent article/deal appears in Waiting/Home, not popup Attention.

### Legitimate escalation

The same candidate, when an objective deadline/expiry makes it time-sensitive, can be promoted through #1049 with a stored reason.

### Prompt-injection/non-authority proof

A malicious source instructing the scout to ignore policy, crawl more domains, change memory, or execute an effect cannot expand the host-owned campaign/authority.

### User feedback proof

An explicit "stop showing me news" preference changes later discovery/surfacing across Agent/API/UI without client-only suppression.

## Acceptance criteria

- [ ] Proactive discovery runs as canonical Runs/NodeRuns/Attempts, not a private crawler lifecycle.
- [ ] Network/model/provider work uses governed Invocations and M2 boundaries.
- [ ] Cheap/local scout work can materially reduce candidate volume before stronger curation.
- [ ] Durable budgets bound wall-clock/compute/tokens/network/candidates/surfaced items as configured.
- [ ] Budget exhaustion stops new work truthfully and restart does not reset spent budget unexpectedly.
- [ ] Candidates retain source provenance/freshness/trust/dedupe evidence.
- [ ] External content remains untrusted and cannot expand host policy or directly create user-model truth.
- [ ] Ranking uses Persona + user model + Workspace/Goal + novelty/time/trust/preferences.
- [ ] Ordinary proactive content goes to Waiting/unpinned Home by default.
- [ ] #1049 escalation is required for popup/blocking promotion and stores an evidence-based reason.
- [ ] Surfaced items can explain relevance from inspectable evidence.
- [ ] Explicit negative/positive preferences affect later discovery through canonical settings/user-model services.
- [ ] User may disable/constrain discovery through Agent/API/settings.
- [ ] No engagement/click-through objective or self-expanding crawler graph is introduced.

## Non-goals

- Building a general-purpose web crawler/search engine.
- Replacing M8 research #910; M8 may test improved techniques, while this SPEC owns accepted M3 product behavior.
- Making all discovery local-only; local compute is a cost tier, not an architectural requirement.
- Defining an advertising or affiliate system.
- Allowing external content to directly write user beliefs.
