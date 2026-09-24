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

## 2026-09-24 re-validation evidence (head 5cfdf6afd)

Executed locally against the real frontend sources (no harness mocks),
Chromium via the repo Playwright 1.60.0, `E2E_SRC_ROOT` pointed at the
shipped `frontend/src`:

- `e2e/visual-artifact-boundary.spec.ts` — 3/3 passed (single executable sink;
  sink-pattern self-test; all three visual surfaces consume the shared
  renderer).
- `e2e/deck-sanitization.spec.ts` — 5/5 passed (deck preview/presentation,
  paste/drop/export, mutation/encoded/SVG/CSS payload families fail closed,
  safe Deck template survives, poster + infographic + flyer preview/edit/export
  through the shared boundary with zero attacker requests; trust verdict read
  from the production component's `data-trust-recommendation`).
- Negative contract check: a scratch `frontend/src/pages/__sink_probe__.tsx`
  holding a second `dangerouslySetInnerHTML` sink made the boundary spec fail
  (`1 failed`); removing it restored `3 passed` — "new mode without the shared
  renderer fails test evidence" is proven, not assumed.
- `uv run pytest packages/maistro-design/tests -q` — 286 passed (pre-scan
  vocabulary parity, #817 never-upgrade union, engine integration).
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
