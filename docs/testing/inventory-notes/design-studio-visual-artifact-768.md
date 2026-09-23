---
inventory-delta:
  packages/hive-conductor/tests/e2e: +1
---

Issue #768 adds one serial browser journey that mounts the real fixed-page
editor for Poster, Infographic, and Flyer modes. The journey checks the shared
sanitized preview after hostile initial content, sanitized rich editing, HTML
export, safe fixed-page template rendering, and the absence of attacker
requests. Existing Deck browser cases stay in the same suite and continue to
exercise the shared renderer.
