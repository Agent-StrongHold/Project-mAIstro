---
inventory-delta:
  packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts: +1 browser test
---

Issue #768 adds one serial browser journey that mounts the real fixed-page
editor for Poster, Infographic, and Flyer modes. The journey checks the shared
sanitized preview after hostile initial content, sanitized rich editing, HTML
export, and the absence of attacker requests. Existing Deck browser cases stay
in the same suite and continue to exercise the shared renderer.
