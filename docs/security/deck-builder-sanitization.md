# Deck Builder sanitization boundary

Issue: #752 (child of #311)

This document records the implementation and evidence boundary for Deck Builder HTML/SVG sanitization.

## Security objective

Model-authored and previously stored Deck markup is untrusted. No raw Deck HTML/SVG string may reach a browser HTML rendering sink. The implementation uses one explicit reviewed sanitization boundary and proves the actual render path rejects executable or exfiltrating markup while preserving the presentation subset the product supports.

## Collision boundary

This lane may change Deck Builder implementation, a Deck-specific sanitizer/helper, Deck-specific tests, and the frontend dependency manifest/lockfile only if a sanitizer dependency is required.

It must not change `frontend/src/App.tsx`, `frontend/src/components/AppShell.tsx`, global navigation, backend authentication/session code, M1 execution authorities, workflows, or shared quality/ratchet machinery.

The existing `/decks` route/navigation containment remains in place until parent #311 completes after this child.

## Implemented boundary

- `frontend/src/lib/deckSanitizer.ts` defines the single Deck HTML/SVG allowlist. It strips executable elements/attributes, active or remote URL schemes, and CSS network/code primitives while retaining the supported presentation subset.
- Sanitization is applied to model-authored slide markup, slide-state updates, editable preview state, presentation rendering, built-in templates, and HTML export.
- Rich paste and drop prevent the browser's default insertion/navigation behavior and sanitize before any untrusted HTML reaches the live DOM.
- Exported document titles are escaped as text before interpolation.
- The sanitizer reparses and scrubs serialized output a second time so parser mutation cannot introduce an unexamined executable construct.

## Adversarial browser evidence

`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` mounts the real Deck Builder component and sanitizer without exposing the still-contained `/decks` product route. The browser suite proves:

- hostile model-authored HTML/SVG cannot execute script, insert active elements, navigate, or emit attacker network requests in preview or presentation mode;
- rich clipboard/drop HTML is sanitized before insertion and remains safe through export;
- mutation, encoded-scheme, SVG, CSS/network, iframe/srcdoc, meta-refresh, and related payload families fail closed;
- safe representative presentation markup and built-in Deck templates remain renderable;
- exported HTML remains free of executable markup and raw-title injection.

The repository CI frontend lint/build and frontend test steps pass on the branch after the branch-owned lint correction. Full required CI remains the merge gate for PR #757.
