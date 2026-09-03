---
id: SPEC-090326-8b64
title: "Adaptive Workspace Home, Attention/Waiting, session restoration, and Agent-editable preferences"
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
supersedes: []
blocks: []
blocked-by: []
contracts:
  - product
  - behavioral
  - boundary
tests: []
layer: Workspace
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-090326-8b64: Adaptive Workspace Home, Attention/Waiting, session restoration, and Agent-editable preferences

## Purpose

Specify the M3 product contract for three coupled presentation/control behaviors:

1. Workspace Home as a fully pinnable adaptive Mission-Control composition;
2. Workspace-Agent-owned Attention/Waiting across every surface;
3. adaptive return/session restoration and user preferences editable through UI, API, or natural language with the Workspace Agent.

This SPEC owns no Goal, Run, chat, artifact, memory, settings, or approval truth. It defines projections/control state over canonical owners.

Issue owners:
- #1048 Workspace Home;
- #1049 Attention/Waiting;
- #1050 landing/session/settings.

## Invariant: UI is optional

Every substantive operation exposed here MUST have a canonical backend/API operation that the Workspace Agent can use without browser/UI automation.

Supported users include:
- Agent-first users who rarely open specialized UI;
- Workspace-Home/Mission-Control users;
- users who pin a fixed dashboard;
- users who mostly work in specialized persistent surfaces;
- users who always resume where they left off;
- API/headless users who never use the UI.

No mode creates a different underlying MAIstro architecture.

# Part A — Workspace Home

## A1. Baseline composition

When no stronger return/default preference applies, Workspace Home is the default surface.

Home SHOULD support compact projections of at least:
- canonical Goals and reconciliation state;
- tasks / BacklogItems / campaigns;
- recent artifacts;
- Workspace-Agent chat;
- micro Design / recent creative work;
- recent chat sessions;
- current Runs/blockers when relevant;
- adaptive content selected by the Workspace Agent for remaining unpinned space.

A compact projection is not a copied domain object. It references canonical identities and current canonical state.

## A2. Presentation-instance identity

A presentation instance has its own identity/location/layout metadata while referencing a canonical resource.

Conceptually:

```python
@dataclass(frozen=True)
class SurfaceInstance:
    instance_id: str
    workspace_id: str
    surface_kind: str
    resource_ref: CanonicalResourceRef | None
    placement: Placement
    pinned: bool
    presentation_state: dict[str, object]
```

Two instances may reference the same Goal/chat/artifact. They remain two views, one canonical resource.

Duplicating a card/window must never duplicate the Goal/chat/artifact/Run itself.

## A3. Pinning and adaptive space

Every Home region may be:
- pinned/unpinned;
- moved;
- resized;
- removed/closed according to the surface's restore contract.

The user may pin 0–100% of available Home space.

- 0% pinned: Agent can compose the whole surface.
- partial: Agent composes only unpinned regions.
- 100% pinned: Agent must honor the fixed layout and has no adaptive placement area.

Pinning is a durable user presentation preference, not domain ownership.

## A4. Adaptive content

The Workspace Agent may fill unpinned space from:
- current/recent canonical Workspace work;
- dormant or newly relevant Goals;
- artifacts/recent conversations;
- user-model relevance from SPEC-090326-5f21;
- governed external discoveries supplied by the proactive-curation contract;
- Attention/Waiting state;
- explicit user preferences.

Selection optimizes for likely usefulness, not time-on-screen or engagement.

Surfaced items retain an inspectable explanation/evidence trail sufficient to answer "why are you showing me this?" without exposing private chain-of-thought.

## A5. Quick/open behavior

Selecting a compact projection may:
- open the full specialized surface;
- open a transient popup/quick view;
- execute a canonical backend control action.

For chat, a quick-chat presentation and full chat surface must reference the same conversation/session authority where they represent the same conversation.

## A6. Responsive layout

The saved layout is canonical presentation preference. A smaller/different viewport may temporarily adapt placement so it remains usable, but temporary adaptation must not silently overwrite the saved layout.

The user/Agent may explicitly save an adapted arrangement as a new/updated preference.

# Part B — Attention and Waiting

## B1. Ownership

Attention belongs to the persistent Workspace Agent and is Workspace-wide. It does not belong to the tab/surface that discovered the issue.

An Attention item is a durable orchestration projection/reference to canonical underlying state or an Agent-originated question/suggestion.

## B2. Priority classes

The ordering is:

1. **severity**;
2. **time-sensitive answer**;
3. **blocks current user action**;
4. **queued question**;
5. **follow-up suggestion**;
6. **proactive suggestion**.

A concrete schema may separate `class`, `severity`, `deadline`, `interrupt_mode`, etc., but the resulting ordering must preserve this policy.

Conceptually:

```python
class AttentionClass(StrEnum):
    SEVERITY = "severity"
    TIME_SENSITIVE = "time_sensitive"
    CURRENT_ACTION_BLOCKER = "current_action_blocker"
    QUEUED_QUESTION = "queued_question"
    FOLLOW_UP = "follow_up"
    PROACTIVE = "proactive"

class InterruptMode(StrEnum):
    BLOCKING = "blocking"
    POPUP = "popup"
    WAITING = "waiting"
```

Proactive suggestions default to `WAITING`.

## B3. Dynamic escalation

Priority is recomputable from current evidence. An item can move upward when:
- consequence/severity changes;
- a deadline approaches;
- an opportunity is expiring;
- a Goal/Run reaches a dependency blocked on the answer;
- the user's current activity now depends on it;
- new security/safety evidence appears;
- relevant context makes a previously optional question necessary.

Elapsed age may contribute, but **age alone cannot force eventual interruption**.

Every automatic escalation stores:
- old/new class or interrupt mode;
- reason code/text suitable for user explanation;
- timestamp;
- source evidence references / related canonical ids;
- policy/version that made the decision where applicable.

## B4. Interruption behavior

- `BLOCKING`: remains in foreground until resolved or its blocking condition canonically disappears.
- `POPUP`: can be answered now or deferred back to Waiting.
- `WAITING`: does not interrupt ordinary work.

Urgent items may pop over any active surface because the Workspace Agent owns the queue.

## B5. Waiting quality indicator

Waiting MUST expose more than a raw count.

The backend/service should provide enough metadata for a compact UI/Agent summary to indicate, for example:
- number waiting;
- highest current class/importance among waiting items;
- number rising/nearing escalation;
- aggregate expected value/relevance bucket if used;
- oldest/nearest deadline when useful.

The exact visual representation is not specified. Importance must not be invented solely in the client.

## B6. Underlying authority

Attention may reference:
- Goal reconciliation blockers/waits;
- HITL;
- approvals/elevation/security decisions;
- Run failures requiring user action;
- deadlines/opportunities;
- Backlog/campaign decisions;
- user-model gap questions;
- Design Studio/mixed-control questions;
- follow-up/proactive suggestions.

Resolving an Attention item calls the canonical owning service. Attention cannot independently mark a Goal/Run/HITL/approval completed.

# Part C — Surface continuity

## C1. Desk metaphor

When the user leaves a surface to answer Attention or navigate elsewhere, the previous surface state remains resumable "like papers left on a desk."

Presentation state may include:
- active tab/surface/component instances;
- layout/location/size;
- selected canonical resource ids;
- scroll/cursor/editor presentation state where safe/useful;
- transient popup/panel state;
- draft/unsaved editor state only according to that editor's durability/recovery contract.

## C2. Never restore stale canonical truth

Restoration state contains presentation context, not cached execution/domain truth.

On restore, Goal/Run/HITL/approval/task/artifact metadata that may have changed is re-read from canonical services.

A presentation snapshot must never resurrect `running`, `approved`, `failed`, `completed`, `waiting`, etc. over newer canonical state.

# Part D — Workspace landing and return

## D1. Precedence

Landing behavior follows:

1. sufficiently recent return -> restore exact prior working surface/state;
2. otherwise explicit user preferred/default surface;
3. otherwise learned/preferred surface if accepted/applicable;
4. otherwise Workspace Home.

Explicit user preference outranks learned preference.

## D2. Adaptive recency

Recency must consider both:
- absolute elapsed absence;
- elapsed absence relative to prior session length.

There is no product-law constant such as "35 visits" or one global fixed recency threshold.

Conceptually:

```python
@dataclass(frozen=True)
class SessionReturnPolicy:
    absolute_window: timedelta
    session_fraction: float
    user_tuning: float


def should_restore(previous: SessionSummary, returned_at: datetime, policy: SessionReturnPolicy) -> bool: ...
```

The concrete algorithm may evolve, but tests must prove both absolute time and session proportion affect the result.

## D3. Natural-language policy changes

Requests such as:
- "hold onto my sessions longer and take me back when I come back";
- "always open this Workspace to Goals";
- "stop showing me news";
- "make this view the default";
- "go back to Home by default";

must write durable preferences via the canonical settings service.

"Hold onto sessions longer" must materially increase the actual restoration policy, not merely store a cosmetic phrase.

## D4. Learned preference suggestions

The product may observe repeated immediate navigation after entering a Workspace and propose a default change.

The trigger can consider frequency, consistency, recency, confidence, previous refusal/acceptance and other behavior. There is intentionally no universal fixed count.

Unless the user has explicitly enabled automatic adaptation for the preference family, learning results in a **suggestion**, not a silent permanent change.

Repeated refusal/ignoring must suppress nagging.

# Part E — Canonical settings authority

The Workspace Agent may change ordinary user settings/preferences when:
- the user asks;
- an applicable policy explicitly permits adaptive change;
- the mutation is within the user's existing authority.

Every mutation:
- uses the same canonical settings backend/API as UI controls;
- records actor/provenance/reason where settings auditing supports it;
- is reversible/correctable;
- preserves explicit overrides over learned defaults;
- cannot grant permissions/capabilities, waive approvals, widen memory scope, or weaken security.

# Part F — UI / Agent / API parity

For at least one representative preference/control in each family, integration proof must show equivalent end state through:
- direct API;
- Workspace Agent instruction;
- UI control.

Recommended proof examples:
- set default surface;
- pin/unpin a Home region;
- defer an eligible popup Attention item;
- increase session-restore aggressiveness.

The resulting canonical record/id/value must be identical in meaning regardless of entry surface.

## Acceptance criteria

- [ ] Workspace Home renders compact canonical projections without duplicating domain identity.
- [ ] Home supports 0%, partial, and 100% pinning; Agent composition is limited to unpinned regions.
- [ ] Saved layout survives reconnect/restart and is not silently rewritten by responsive adaptation.
- [ ] Core Workspace operations remain usable via Agent/API without opening Home.
- [ ] Attention is Workspace-Agent-owned and survives closing the source surface/restart.
- [ ] Priority respects severity > time-sensitive > current-action blocker > queued question > follow-up > proactive.
- [ ] Proactive items default to Waiting.
- [ ] Context/age may promote to popup/blocking only with inspectable evidence; age alone is insufficient.
- [ ] Waiting exposes a quality/importance/rising indicator contract beyond raw count.
- [ ] Blocking items remain foreground-required until resolved/condition disappears; popup items may defer.
- [ ] Attention navigation preserves resumable prior presentation state.
- [ ] Restoring a surface re-reads live canonical domain/execution state.
- [ ] Landing follows recent restore -> explicit default -> accepted learned default -> Home.
- [ ] Recency considers both absolute time and prior-session proportion.
- [ ] Repeated immediate navigation may produce a non-blocking default suggestion without a magic threshold.
- [ ] Explicit default outranks learned preference and repeated refusals reduce future prompting.
- [ ] Workspace Agent can materially alter restoration/default/preferences via canonical settings service.
- [ ] UI/Agent/API parity is behaviorally proven against the same canonical state.

## Non-goals

- Fixing exact visual design/token styling.
- Creating a generic operating-system notification framework.
- Creating a second Goal/HITL/approval lifecycle.
- Defining collaboration/multi-user surface synchronization beyond preserving future compatibility.
- Using engagement/time-on-screen as the adaptive Home objective.
