# Design Studio product boundary

Issue: #286  
Canonical convergence parent: #52  
Premier finished-product outcome: #773

Design Studio is MAIstro's parent **AI-assisted creative-production environment**. It is larger than Canvas and larger than any one artifact editor. The user and the Workspace Master Orchestrator use Design Studio to turn Goals into coherent, versioned artifacts by composing canonical MAIstro tools and execution primitives.

Design Studio must not establish a second execution, Persona, memory, Goal, artifact, authorization, security, or provenance universe. It composes the canonical owners.

## Product model

The intended product relationship is:

- **Workspace Master Orchestrator** — persistent goal-driven coordinating Agent for one Workspace.
- **Persona** — persistent guiding flavor: voice, taste, behavioral style, preferences, creative instincts, and purpose. Persona never grants authorization.
- **Goal** — canonical Project-scoped desired outcome. One accountable Agent owns a Goal at a time; ownership/delegation is not Design Studio state.
- **CreativeBrief** — versioned Design Studio creative projection of one canonical Goal revision, adding creative-production context such as audience, constraints, source truth, acceptance interpretation, requested deliverables, and creative guidance without replacing Goal identity.
- **Workspace memory** — scoped context. PostgreSQL + pgvector remain authoritative durable memory; the accepted per-Workspace Ladybug graph is a disposable working projection.
- **Design System** — shared visual/brand language for applicable artifacts.
- **Design Studio** — the creative-production environment/toolbox used by both user and Workspace Master Orchestrator.
- **DAG / Graph** — orchestration and dependency engine. DAG/workflow describes a Graph shape rather than a separate execution identity.
- **Canvas** — fixed-page/visual composition and rendering tool/substrate.
- **Deck Builder** — presentation-specialized editing/presentation tool.
- **Builders** — code/web implementation tool when a Goal requires software or site artifacts.
- **Media and external tools** — specialized capabilities reached through the governed Capability → Provider → Binding → Invocation path.

A specialized tool may own its editing UX and product-local state, but it must return to the same Workspace/Project, canonical Goal revision, CreativeBrief version, Persona, artifact lineage, and canonical Run provenance.

## One goal, many coordinated artifacts

The finished Design Studio is expected to coordinate artifact families such as:

- copy, messaging, and articles;
- scripts;
- code and websites / landing pages;
- presentations / decks;
- posters;
- infographics;
- flyers;
- social graphics and copy;
- cards and covers;
- store / Etsy coupons and promotional assets;
- diagrams and composed visuals;
- images / illustrations;
- video/audio plans, scripts, and provider-backed rendered media;
- custom fixed-size visual artifacts;
- other artifact types exposed by governed Design Studio tools and skills.

These outputs are not independent prompt islands. They are projections of one canonical Goal revision and versioned CreativeBrief, one Persona-guided creative identity, shared Workspace context, and one canonical execution/provenance universe.

## Canvas-native visual modes

The current visual product surface establishes these initial Design Studio modes:

- Presentation / Deck
- Poster
- Infographic
- Flyer
- Social graphic
- Card
- Cover
- Diagram / visual
- Custom fixed-size canvas

This matches the existing renderer contract: `renderer.fixed-page` is the Canvas-native floor for slides, flyers, posters, cards, and covers; `renderer.deck` adds multi-page presentation behavior.

These visual modes are an initial subset of Design Studio, not the definition of Design Studio itself.

## Deck specialization

Deck is a specialized Design Studio tool/mode. It may add ordered pages, slide navigation, presentation mode, deck templates, PPTX/deck export, and later speaker notes. It must reuse the same project/artifact/render/security/provenance foundation rather than establishing a sibling product universe.

The existing `/decks` containment remains authoritative until #752 closes its browser-rendering security boundary. Product composition must not expose Deck early merely to make the information architecture look complete.

## Human ↔ agent control continuum

Design Studio must use the same project and artifact representations whether work is:

1. **Direct / interactive** — the user edits and invokes AI selectively.
2. **Collaborative / copilot** — user and Workspace Master Orchestrator iteratively plan, edit, critique, and refine together.
3. **Delegated / autonomous** — the Workspace Master Orchestrator may continue toward the authorized Goal without waiting for another prompt.

Autonomous never means exclusive control. While delegated work is active, the user must remain able to pause, inspect, edit, interrupt, redirect, guide, lock/freeze, cancel a branch, change delegation scope, stop, or take direct control. Different branches may be direct, collaborative, autonomous, paused, or locked at the same time.

User intervention is durable project state, not a reset. Human edits, guidance, locks, redirects, and forks must preserve lineage and be visible to subsequent agent work. An in-flight external effect must expose truthful requested/stopping/stopped semantics rather than pretending it disappeared instantly.

#777 and #780 own the downstream M3 realization of this mixed-control model.

## Goal, CreativeBrief, and Persona are different

Persona is persistent reusable identity/flavor: voice, taste, behavioral style, preferences, creative instincts, and purpose. Persona does not own the desired Project outcome and never grants authorization.

`Goal` is the canonical Project-scoped desired outcome under #458. One accountable Agent owns a Goal at a time. Normally that is the Workspace Master Orchestrator unless the Goal or a derived Subgoal has been explicitly delegated. Goal identity, revision history, ownership, and delegation remain canonical outside Design Studio.

`CreativeBrief` is Design Studio domain state under #774: a versioned creative projection/context for one exact canonical Goal revision. It may elaborate audience, creative acceptance interpretation, channel/artifact requirements, source truth, allowed claims, and creative constraints, but it cannot replace, silently fork, or mutate canonical Goal identity. Historical Runs and artifacts must be able to identify the Goal revision and CreativeBrief version they consumed.

Changing the desired Project outcome is a Goal change/new Goal revision. Changing only the creative interpretation or artifact/channel guidance may create a new CreativeBrief version against the same Goal revision. Design Studio must not create a product-local Goal owner for either case.

## Execution truth

Design Studio must never represent elapsed client time, fixture state, or local animation as completed work.

A visible execution state must come from a real persisted product fact or canonical Graph/Run/NodeRun/Attempt state. `DesignEngine.generate()` currently prepares, scans, and persists a DesignProject/prompt stack; that operation is not itself visual generation and the UI must not label it as such.

If canonical generation is unavailable, the product must report that state or disable the action. It must not fall back to simulated success.

The current M1 slice intentionally establishes truthful availability and the parent product boundary before the occupied Canvas execution seam is mounted.

## Memory boundary

The Workspace Master Orchestrator may eventually use a Ladybug graph for hot Workspace-local associative context, but Ladybug is not durable truth. PostgreSQL + pgvector remain authoritative. The working graph must be isolated per Workspace, rebuildable, provenance-bearing, and incapable of widening authorization.

#776 owns the minimum M3 product floor; #301 retains broader M4 Dreaming, retrieval experimentation, benchmarking, and adaptive working-memory work.

## Self-improvement boundary

Design Studio must be useful before self-improving workflows are enabled.

Later, creative DAGs, templates, skills, tool-routing policies, and harness components may improve through M4's governed candidate → independent evaluation → governed promotion mechanism. Production work must not directly rewrite and promote its own DAG/tool policy, and user taste must not silently become global policy.

## Current parallel ownership

The M1 implementation slices intentionally respect live ownership:

- #735 / PR #746 owns `packages/maistro-canvas/**` canonical execution.
- #752 / PR #757 owns Deck Builder sanitization and browser security.
- #750 owns global application-shell accessibility.
- #286 owns the Design Studio product/composition surface and consumes those seams after they land.

M1 establishes truthful canonical composition. M2 hardens shared rendering/security and accessibility. M3 completes the actual product through #93/#94/#95 and premier outcome #773 with children #774/#775/#776/#777/#779/#780.

The finished result should feel like one persistent creative team with tools, memory, and a consistent Persona working toward the user's Goals, not a menu of unrelated AI generators.
