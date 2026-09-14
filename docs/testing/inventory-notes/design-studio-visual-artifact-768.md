---
inventory-delta:
  packages/maistro-design/tests: +5
---

Issue #768 adds serial browser coverage that mounts the real fixed-page editor
for Poster, Infographic, and Flyer modes and rehydrates a persisted Poster.
The journeys check the shared sanitized preview after hostile initial content,
sanitized rich editing, HTML export, safe fixed-page template rendering, trust
recommendations from the production component, persistence migration, and the
absence of attacker requests. Existing Deck browser cases stay in the same
suite and continue to exercise the shared renderer.
