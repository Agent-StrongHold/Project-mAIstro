# Deck Builder sanitization boundary

Issue: #752 (child of #311)

This document records the implementation boundary for the Deck Builder HTML/SVG sanitization work before application code changes begin.

## Security objective

Model-authored and previously stored Deck markup is untrusted. No raw Deck HTML/SVG string may reach a browser HTML rendering sink. The implementation must use one explicit, reviewed sanitization boundary and prove the actual render path rejects executable or exfiltrating markup while preserving the presentation subset the product supports.

## Collision boundary

This lane may change Deck Builder implementation, a Deck-specific sanitizer/helper, Deck-specific tests, and the frontend dependency manifest/lockfile only if a sanitizer dependency is required.

It must not change `frontend/src/App.tsx`, `frontend/src/components/AppShell.tsx`, global navigation, backend authentication/session code, M1 execution authorities, workflows, or shared quality/ratchet machinery.

The existing `/decks` route/navigation containment remains in place until parent #311 completes after this child.

## Status

Claimed from `develop@fdb6bcbb83b6e362f8fbf922bb41f737355a71bd`. Implementation and adversarial evidence are pending on the draft PR for #752.
