---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-design/tests: +0
  packages/hive-conductor/backend/tests: +0
---
# 817 repair: finish the ee98fab driver merge (conflict markers) and union the
# Deck/Design sanitization hardening

Nothing was removed or moved. The lane's #817 production boundary
(`trust.py`, `scan.py`, `patterns.py`, `normalize.py`) was already green at
`d39b0de` (rounds 1-4 in `issue-817-design-trust-active-markup.md`), but the
driver merge `ee98fab47` (lane `dac3aecc0` + develop `60862b6c5`) committed
four files with unresolved conflict markers, so `scripts/check-merge-markers.py`
exited 1, the browser corpus could not parse, and the frontend boundary could
not build. This repair resolves those conflicts as a reviewed union and adds
no new tests (no pytest delta; the e2e spec keeps its 8 test functions — the
three incoming-side tests arrived with `60862b6c5`, not with this repair).

## Conflict resolutions

- `packages/hive-conductor/frontend/src/lib/deckSanitizer.ts`: keep the lane's
  single-boundary architecture (compatibility re-exports of
  `visualArtifactRenderer`; no second sanitizer per the #817 stop condition)
  and take the incoming side's public contract only: `sanitizeDeckMarkup(markup:
  unknown)` fails closed to `""` for non-string/empty stored JSON before
  delegating to `sanitizeVisualArtifactMarkup`. The incoming standalone
  attribute/tag-allowlist sanitizer (and the `HTML_TAGS`/`SVG_TAGS` definitions
  the merge had already dropped from the file top) is not resurrected; its two
  genuine hardening ideas move into the shared boundary instead (below).
- `packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx`: keep the
  `SanitizedVisualArtifact markup={...}` render path (no second
  `dangerouslySetInnerHTML` sink in Deck Builder — the only reviewed sink stays
  the annotated one in `visualArtifactRenderer.tsx`) and take the incoming
  sanitizing `onBlur={handlePreviewBlur}`. The merge had dropped the incoming
  `sanitizeDeckMarkup` import, leaving `handlePreviewBlur` calling an undefined
  identifier (silent ReferenceError at blur, DOM left dirty); it now calls the
  already-imported `sanitizeVisualArtifactMarkup`, matching the file's other
  state-mutation paths (`safeSlide`, `exportHTML`).
- `packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts`: union the
  hostile corpus — keep both the `<image href="data:text/html,...">` and the
  `<circle fill="blob:..." stroke="ftp://...">` payloads in the payload-family
  test. No test function added or removed.
- `docs/security/deck-builder-sanitization.md`: keep the single-allowlist
  architecture description and fold in the incoming non-HTTP scheme list.

## Shared-boundary hardening (both sides, one place)

`packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx`, the one
#768 boundary:

- `NETWORK_OR_CODE_ATTRIBUTE` now rejects every non-presentation scheme
  (`blob|file|filesystem|ftp|ws|wss|about|mailto|tel|cid` in addition to
  `javascript|vbscript|data|http(s)` and `//`) in the SVG paint/transform
  attribute values it guards.
- `sanitizeStyle` fails closed on the whole declaration block when the raw
  style text contains a CSS escape or `/*` comment (`\75rl(` decodes to `url(`
  only in a CSS parser), recording the existing `css-network-or-code` reason —
  no new block reason, so `VISUAL_ARTIFACT_BLOCK_REASONS` and the Warden
  vocabulary stay in lockstep and no Python/Warden change is needed.

## Executed evidence at the repair tree

- `scripts/check-merge-markers.py` → rc 0 (was rc 1 at `ee98fab47`).
- Chromium browser corpus (`auto817-playwright-r4` image, worktree sources
  bind-mounted over the baked copies): `deck-sanitization.spec.ts` 8/8 passed,
  including the union payloads, malformed stored values failing closed, the
  blur-sanitized edited-DOM case, MathML `active-element` scan reason,
  `recommendVisualArtifactTrust` parity (MathML → `review`), and the `\75rl(`
  fail-closed assertions.
- CI-exact semgrep (4 configs, `--error packages/ tests/`) → rc 0, 364 rules
  over 1889 files, 0 findings (Deck Builder gained no unannotated sink).
- CI-exact vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → rc 0, 1415 reviewed identities → 1415 findings.
- `uv run pytest packages/maistro-design/tests
  packages/maistro-core/tests/security/warden -q` → 386 passed;
  `packages/hive-conductor/backend/tests/test_design_renderers.py
  test_design_scope.py -q` → 28 passed (no Python file changed by this repair;
  runs predate it only in the sense that Python is untouched).
- `uv run ruff check .` / `ruff format --check .` → pass; mypy (CI nine-src
  scope) → 832 files, 0 issues.
- Independent 24-case hostile corpus through `scan_and_record` (MathML,
  handlers, script SVG, foreignObject, `data:text/html`, CSS `url()`,
  `\75rl(`/`\000075rl(` escapes, `@import`, meta refresh, form action,
  `javascript:`, animate href, `expression(`, `-moz-binding`, `behavior:`,
  `<body onload>`, use/data, poster, link stylesheet, prompt injection,
  entity script) → all SKULL/`banish` with the exact shared output-boundary
  flags; clean brief stays T3/`upgrade` with `()` flags; `scan_design_text`
  blocks every case; `build_multimodal_output` raises `TrustBannedError`.
