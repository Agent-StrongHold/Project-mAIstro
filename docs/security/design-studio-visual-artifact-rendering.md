# Design Studio visual-artifact rendering boundary

Issue: #768 (Design Studio; parent #17)

All model-authored, loaded/stored, or user-edited HTML/SVG for Design Studio
fixed-page modes crosses one frontend boundary before it is parsed into a live
DOM, presented, or exported. The boundary is
`packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx`.

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
  grant. Inert unsupported attributes/properties are dropped during
  sanitization rather than treated as security blocks, so ordinary presentation
  markup such as `class` remains eligible.

The allowlist retains typography, layout, gradients, inert SVG geometry, and
presentation attributes such as `class` and `id`. It rejects scripts, handlers,
forms, links/navigation, images and other active HTML, `foreignObject`, external
SVG references, dangerous URLs including `data:text/html`, and CSS/network/code
primitives such as `url()`, `@import`, `var()`, `expression()`, and `image-set()`.
Unknown inert attributes and unsupported presentation properties are removed
without being added to the shared blocking vocabulary.

## Consumers

- Deck Builder imports the shared renderer directly for model generation,
  persisted slide state, content-editable preview, presentation mode, rich
  paste/drop, and HTML export. `deckSanitizer.ts` remains compatibility exports
  only and contains no second policy.
- The structured `FixedPageEditor` (`pages/FixedPageEditor.tsx`) is the
  fixed-page editor DesignStudio.tsx actually mounts for Poster, Infographic,
  Flyer, Social, Card, Cover, Diagram, and Custom Canvas modes. It never
  parses raw markup: layer text renders as escaped React children and is
  re-escaped by `escapeHtml` in the HTML export, colors come from color
  inputs, and geometry is numeric — hostile prompt text stays inert by
  construction. The deck-sanitization browser proof mounts it and asserts that
  inertness directly.
- `FixedPageArtifactEditor` is the hardened raw-markup fixed-page editor built
  on this boundary (it sanitizes its initial persisted value, edit/paste/drop
  updates, preview, and export). It is exercised by the deck-sanitization
  browser proof; DesignStudio.tsx does not currently mount it.
- Server-side Design renderers call `maistro_design.scan_design_text` before
  dispatching content to PDF/PPTX/DOCX/PNG backends, reusing the returned-output
  boundary rather than maintaining a renderer-specific scanner.

The browser proof in
`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` mounts the real
DeckBuilder, the hardened `FixedPageArtifactEditor`, and the production
structured `FixedPageEditor`. It covers hostile model markup, SVG and CSS
payloads (including `var()`/`env()`/`data:` declaration values, whose block
reasons are lockstep-enforced against Warden's shared scanner), rich editing,
export, hostile-prompt inertness, and safe representative templates across
Deck, Poster, Infographic, and Flyer.
