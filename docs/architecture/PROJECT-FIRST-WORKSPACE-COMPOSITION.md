# Project-first Workspace composition

Status: proposed implementation contract for owner-confirmed product direction; review/merge required.
Owners: #1046, #2551; UAT #2549; integrated acceptance #1048; retirement #2274.
Milestone: M3 (#7). This is a presentation convergence correction, not a new execution spine.

## Product decision

Primary tabs/pages represent canonical Projects in the active Workspace. Workspace selection is separate; Home is Workspace-wide. The persistent Workspace Agent remains available throughout and understands the authorized current Project. Projects are domain-neutral, not fixed templates or subsystem page sets. Optional starter compositions may suggest modules but must never constrain a Project's future capabilities. No permanent Goals, Runs, Backlog, Approvals, Capabilities or Design Studio navigation destinations. Specialized editing environments are contextual hosts, not sibling products. Account/security utilities may be accessible outside a Project where scope requires it, not as a substitute subsystem rail.

Workspace → Project → composition → widget instance → governed action.
Canonical Workspace, Project, Goal, Agent, Graph, Run, artifact, capability and session authorities remain unchanged. A widget is a presentation instance, never a domain object. A module provides reusable functionality and one or more representations. A tool is a governed operation; UI, Agent and API use the same authority.

## Contract boundaries

- Host context: authenticated principal and authorized Workspace/Project; Home permits Workspace-wide authorized projections only. Module queries wait for context resolution. Scope is revalidated server-side on every action; stale client state cannot authorize.
- Module registry: stable module ID/version, typed configuration and resource references, supported host/representation IDs, capabilities/actions, required scopes, availability and provenance. Unknown/incompatible versions fail closed. First-party modules in M3; consume compatible #967/#968 contracts without requiring marketplace distribution. Registry is not a second capability registry.
- Composition: durable revisioned presentation state, owner/scope, instance ID, module/version/representation, resource reference, validated configuration, position/size, pin, and optional reason. Multiple distinct instances can reference the same canonical object; each retains its own configuration. Generalize existing Home layout authority rather than writing a competing store.
- User and Agent may add/remove/configure/move/resize through the same authorized service. Agent may only alter unpinned regions; a fully pinned layout is immutable to Agent composition. Revision conflicts are explicit, with no silent overwrite. Responsive rearrangements are ephemeral unless explicitly saved.
- Contextual hosting: compact widget, expanded widget, conversation component, inspector, dialog, full-screen editor. Maintain resource identity, authorized context, focus and drafts across transitions. Direct links resolve to canonical context and representation or refuse, not resurrect retired pages.
- Conversation: one persistent Workspace Agent; same canonical conversation/turn/Run identity across quick/full interaction, explicit Project scope where applicable. Ignore late responses after context changes. Restore authorized Workspace/Project, composition, focus and conversation under #1050/#1822; migrate path preferences with safe fallback.
- Security: declarative validated configuration only; no arbitrary endpoint/method/header/script. Named governed action resolves existing canonical capability or authorized service; preserve HITL, trust, sandbox, audit, quota and effect boundaries. Unknown/foreign/denied state is honest. No new external action capability from UI composition.
- A2UI protocol surfaces are distinct from durable Project compositions. Reconcile proposed ADR-070426-3a1f and SPEC-277; adopt/pin via normal review. AG-UI interaction transport does not establish execution or durable composition authority. Do not invent incompatible renderer/catalog or assume protocol implementation exists.
- Explicitly decide personal/shared layout ownership, lifecycle on deletion, config migration and editor draft scope in #2551 before production persistence changes. No permission widening via composition sharing.

## Migration and dependencies

| Work | Issue | Dependency |
| --- | --- | --- |
| Architectural contract | #2551 | Existing ontology/security/design contracts |
| First-party module registry | #2552 | #2551 |
| Canonical Project navigation | #2553 | #2551, #38 |
| Persistent composition runtime | #2554 | #2552, #2553 |
| Contextual module extraction | #2555 | #2554 |
| Agent composition | #2556 | #2554, #804 |
| Integrated Home/Project | #1048 | #2554, #2555, #2556 |
| Owner UAT and onboarding | #2549 | shared shell and integrated journeys |
| Per-route retirement | #2274 | merged equivalent module behavior; not final conformance closure |
| Production conformance | #2557 | all required delivery and retirement |

Inventory existing route/function, module, representation, resource and action, authorization, release disposition, migration owner, and replacement proof. Existing Goals/Run #65, backlog #99, approvals #2278, capabilities #2273, creative #773 and conversation #1822 are sources of functionality, not a reason to maintain permanent routes. Reuse existing components and services. Keep staged Evolve/RSI and Deck security boundaries. Delete old route/nav only after replacement behavior lands; honor shrink-only retirement ledger and update route inventory. #2274 may retire each proven replacement without waiting for final UAT closure. No route-per-module fallback.

## Acceptance and release

Original owner [Rooted Craft Co HTML](../product/reference/rooted-craft-co.html) is the visual and interaction reference. Preserved byte-for-byte from the supplied file (Git blob `edf8f77d2ae44e96f8fb4611ac2eac7be1bdfad3`, SHA-256 `c619b13fe28ae87b65fc87d7078391501d3d254161b18abaaf7a0385498bf05b`). Reference only: do not serve as production UI or trust its simulated actions/external font references. Distinguish sample data and simulated JS from actual product behavior; deterministic production browser fixture remains required (#2551/#2557). Design direction: contextual greeting/resume, Needs you inline actions, Goal expansion, suggestions/relevance feedback, persistent Agent status and conversation, unified actor-attributed timeline, contextual artifact inspection. Production uses canonical data/evidence, not fake timer success or demo persona assumptions.

Required browser evidence: create generic Project, compose widgets through user and Agent, pin/resize/configure/remove, same resource in two instances, switch two Projects in same Workspace, restart/restore, quick/full conversation continuity, expand editor and return, approval→canonical Run, artifact provenance, denied/revoked/foreign context, late frames, conflict, offline/unavailable states, desktop/mobile and light/dark visual/accessibility checks. Negative controls must reject arbitrary action/network payloads and subsystem navigation regression.

No closed issue, token integration, component-only test, mock-only/skip/unavailable required scenario or screenshot alone is integrated exit proof. Map AC to merged commit and executable test path. #2557 owns production gate; #1046 cannot close before required children and integrated UAT. Preserve M1/M2 and scope gates. No new backend authority.
