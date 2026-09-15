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
- Rich paste and drag/drop prevent the browser's default insertion/navigation behavior and sanitize before any untrusted HTML reaches the live DOM; dragover is canceled so URI drops cannot fall through to browser navigation.
- Editable preview blur sanitizes the live DOM before copying it into React state, so an edit cannot leave an unsafe transient DOM behind while the state update commits.
- Exported document titles are escaped as text before interpolation.
- No sanitizer dependency is required: the boundary uses the browser's DOM/CSS parsers plus a local reviewed allowlist, so there is no new package or license surface to pin.
- CSS escapes/comments are rejected before CSSOM normalization because the supported presentation templates do not need obfuscated declarations.
- The sanitizer reparses and scrubs serialized output a second time so parser mutation cannot introduce an unexamined executable construct.

## Adversarial browser evidence

`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` mounts the real Deck Builder component and sanitizer without exposing the still-contained `/decks` product route. The browser suite proves:

- hostile model-authored HTML/SVG cannot execute script, insert active elements, navigate, or emit attacker network requests in preview or presentation mode;
- rich clipboard/drop HTML is sanitized before insertion and remains safe through export;
- mutation, encoded-scheme, SVG, CSS/network, iframe/srcdoc, meta-refresh, and related payload families fail closed;
- safe representative presentation markup and built-in Deck templates remain renderable;
- exported HTML remains free of executable markup and raw-title injection.

The browser evidence above is the lane-local security proof; this document does not claim hosted CI status. The repository's normal frontend lint/build and required checks remain merge gates. The existing `/decks` route redirect and omitted shell navigation are intentionally unchanged; parent #311 owns their eventual removal.
