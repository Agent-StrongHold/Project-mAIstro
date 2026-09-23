---
inventory-delta:
  packages/hive-conductor/tests/e2e: +1
---

Issue #768 repair adds a Node-level Playwright spec that freezes the Design
Studio visual-artifact contract in source: `dangerouslySetInnerHTML` may appear
only inside `frontend/src/lib/visualArtifactRenderer.tsx`, the shared renderer
module must exist, and Deck, Design Studio, and the fixed-page editor must
consume it. Adding a new HTML/SVG-capable mode that renders model markup
through any other sink now fails this spec, giving the "one boundary, not one
per artifact type" acceptance criterion deterministic failure evidence without
needing a full browser run.
