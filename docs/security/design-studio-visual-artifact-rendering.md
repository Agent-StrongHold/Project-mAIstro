# Design Studio visual-artifact rendering boundary

Issue: #768 (Design Studio; parent #17)

All model-authored, loaded/stored, or user-edited HTML/SVG for Design Studio
fixed-page modes crosses one frontend boundary before it is parsed into a live
DOM, presented, or exported. The boundary is
`packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.ts`.

## Contract

- `sanitizeVisualArtifactMarkup` is the only allowlisted HTML/SVG sanitizer;
  it is applied on read and again at every render/export edge.
- `SanitizedVisualArtifact` is the reviewed React HTML sink. Feature
  components pass markup as data and do not own `dangerouslySetInnerHTML`.
- `createSanitizedVisualArtifactFragment` handles rich paste/drop before
  insertion, so browser default insertion cannot load an active element first.
- `scanVisualArtifactMarkup` returns the sanitized value and the shared
  `VISUAL_ARTIFACT_BLOCK_REASONS` vocabulary for trust/pre-scan consumers.
  `recommendVisualArtifactTrust` applies that result and returns `review` for
  blocked content, never `upgrade`; it is advisory and not an authorization
  grant. The `maistro-design` pre-scan uses the same four visual blocking
  reason names when creating trust-review records, so the admin recommendation
  cannot upgrade markup the browser boundary blocks.

The allowlist retains typography, layout, gradients, and inert SVG geometry.
It rejects scripts, handlers, forms, links/navigation, images and other active
HTML, `foreignObject`, external SVG references, dangerous URLs including
`data:text/html`, and CSS/network/code primitives such as `url()`, `@import`,
`var()`, `expression()`, and `image-set()`.

## Consumers

- Deck Builder imports the shared renderer directly for model generation,
  persisted slide state, content-editable preview, presentation mode, rich
  paste/drop, and HTML export. `deckSanitizer.ts` remains compatibility exports
  only and contains no second policy.
- `FixedPageArtifactEditor` is the shared fixed-page editor used by Poster,
  Infographic, Flyer, Social, Card, Cover, Diagram, and Custom Canvas modes.
  It sanitizes its initial persisted value, edit/paste/drop updates, preview,
  and export.

The browser proof in
`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` mounts the real
Deck and fixed-page components. It covers hostile model markup, SVG and CSS
payloads, rich editing, export, and safe representative templates across Deck,
Poster, Infographic, and Flyer.
