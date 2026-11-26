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
- `FixedPageArtifactEditor` is the hardened raw-markup fixed-page editor built
  on this boundary. DesignStudio.tsx mounts it for Poster, Infographic, Flyer,
  Social, Card, Cover, Diagram, and Custom Canvas modes; it sanitizes its
  initial persisted value, edit/paste/drop updates, preview, and export, and
  records the pre-scan verdict (`data-trust-recommendation`) beside the
  sanitized markup so a hostile artifact is never re-read as trusted content
  across remounts.
- The structured `FixedPageEditor` (`pages/FixedPageEditor.tsx`) remains the
  brief-driven editor DesignStudio.tsx opens from the catalog. It never parses
  raw markup: layer text renders as escaped React children and is re-escaped
  by `escapeHtml` in the HTML export, colors come from color inputs, and
  geometry is numeric — hostile prompt text stays inert by construction. The
  deck-sanitization browser proof mounts it and asserts that inertness
  directly.

The browser proof in
`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` mounts the real
DeckBuilder, the hardened `FixedPageArtifactEditor`, and the production
structured `FixedPageEditor`. It covers hostile model markup, SVG and CSS
payloads (including `var()`/`env()`/`data:` declaration values, whose block
reasons are lockstep-enforced against Warden's shared scanner), rich editing,
export, hostile-prompt inertness, and safe representative templates across
Deck, Poster, Infographic, and Flyer.
