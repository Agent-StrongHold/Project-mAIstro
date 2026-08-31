# Design Studio product boundary

Issue: #286  
Canonical convergence parent: #52

Design Studio is MAIstro's parent visual-authoring surface. Specialized editors project the same Design/Canvas substrate; they do not establish separate execution, artifact, security, or provenance authorities.

## Artifact modes

The product surface is expected to host:

- Presentation / Deck
- Poster
- Infographic
- Flyer
- Social graphic
- Card
- Cover
- Diagram / visual
- Custom fixed-size canvas

This matches the existing renderer contract: `renderer.fixed-page` is the canvas-native floor for slides, flyers, posters, cards, and covers; `renderer.deck` adds multi-page presentation behavior.

## Deck specialization

Deck is a Design Studio mode. It may add ordered pages, slide navigation, presentation mode, deck templates, PPTX/deck export, and later speaker notes. It must reuse the same DesignProject/artifact/render/security/provenance foundation as other Design Studio artifacts.

The existing `/decks` containment remains authoritative until #752 closes its browser-rendering security boundary. Product composition must not expose Deck early merely to make the information architecture look complete.

## Execution truth

Design Studio must never represent elapsed client time, fixture state, or local animation as completed work.

A visible execution state must come from a real persisted Design/Canvas fact or from canonical Graph/Run/NodeRun/Attempt state. `DesignEngine.generate()` currently prepares, scans, and persists a DesignProject/prompt stack; that operation is not itself visual generation and the UI must not label it as such.

If canonical visual generation is unavailable, the product must report that state or disable the action. It must not fall back to simulated success.

## Current parallel ownership

The M1 implementation slices intentionally respect live ownership:

- #735 / PR #746 owns `packages/maistro-canvas/**` canonical execution.
- #752 / PR #757 owns Deck Builder sanitization and browser security.
- #750 owns global application-shell accessibility.
- #286 owns the Design Studio product/composition surface and consumes those seams after they land.

Downstream M2/M3 work hardens and completes this same product rather than creating another visual-authoring product: secure rendering/asset boundaries, accessibility, background execution, publish/export, and the canonical Canvas API cutover.
