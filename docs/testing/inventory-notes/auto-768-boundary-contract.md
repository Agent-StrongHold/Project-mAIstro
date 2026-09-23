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

2026-09-23 repair strengthening (same file, +1 collected test, 2 -> 3): the
offender scan originally knew only `dangerouslySetInnerHTML`, so the prior
session's "no other innerHTML/srcdoc in frontend/src" evidence lived in a
throwaway /tmp scan rather than in the suite — a new mode using
`el.innerHTML = modelMarkup`, `srcdoc={markup}`, `insertAdjacentHTML`,
`document.write`, an `.outerHTML` assignment, or
`createContextualFragment` would have shipped green. The spec now scans for
that full executable-sink vocabulary (still excluding the shared renderer,
whose one `template.innerHTML =` sits behind the sanitize call), and a new
self-test feeds synthetic hostile and benign source lines through the pattern
table so a future regex typo cannot silently neuter the contract.
