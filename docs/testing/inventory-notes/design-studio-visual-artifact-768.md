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

## 2026-09-24 repair evidence (merge of origin/develop resolved on auto-768)

The `git merge` of `origin/develop` (1dea30dfe) conflicted with the shared
boundary in `deckSanitizer.ts`, `DeckBuilder.tsx`, `deck-sanitization.spec.ts`,
and `deck-builder-sanitization.md`. Resolved as a union: the shared renderer
keeps single-boundary ownership while develop's #752-era hardening moved INTO
`visualArtifactRenderer.tsx` — extended non-HTTP scheme blocklist
(blob/file/filesystem/ftp/ws/wss/about/mailto/tel/cid), pre-CSSOM rejection of
css escapes/comments (`OBFUSCATED_CSS`), and unknown-input fail-closed
sanitization. The edited-DOM blur protection now writes back through the new
reviewed sink `writeSanitizedVisualArtifact`, keeping the one-sink contract
intact. Executed evidence on the resolved tree:

- Fresh `docker build` of `tests/Dockerfile.playwright` from this worktree;
  `npx playwright test deck-sanitization visual-artifact-boundary` — **11/11
  passed** (hostile corpus incl. `data:text/html` image, blob/ftp circle
  paint, CSS escape/comment families; preview/edit/present/export;
  poster/infographic/flyer shared boundary; zero attacker requests;
  malformed stored values fail closed).
- Sink contract held during repair: the first resolution (blur assigning
  `innerHTML` in DeckBuilder) FAILED the boundary spec ("uses .innerHTML
  assignment") and was moved into the shared renderer before committing.
- `uv run pytest packages/maistro-design/tests -x -q` — 287 passed;
  `uv run pytest packages/maistro-core/tests/security ... -q` — 1342 passed,
  19 skipped, 1 failed (`test_log_redaction.py::test_install_is_idempotent`,
  reproduces on the canonical clone at 57ddca502 → pre-existing environment
  issue, unrelated to this lane).
- Live `scan_and_record` probe: active markup / handler attrs /
  `data:text/html` / CSS network / foreignObject SVG → tier=skull with
  populated `warden_flags` (never `upgrade`); safe template → tier=t3,
  recommendation=upgrade.
- `npx tsc --noEmit` clean; `uv run ruff check .` and `ruff format --check .`
  clean.
