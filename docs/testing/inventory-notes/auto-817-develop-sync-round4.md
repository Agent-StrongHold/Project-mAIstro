---
inventory-delta:
  packages/maistro-design/tests: -28
---

# auto-817 develop sync round 4 — merge resolution of origin/develop (0d8a90fbc)

The lane synced `origin/develop` (0d8a90fbc, containing efb1e3a77 "Make
sanitized structured rendering the shared visual-artifact bound" and the
Coverage-gate timeout) into `auto-817` and resolved every conflict in place.

## Why this note exists

The merge brought in five develop-side inventory notes that recorded pytest
deltas for develop's own variant of the maistro-design tests:

- 768-css-comment-prescan-parity.md (+3)
- 768-output-scan-format-gate.md (+6)
- 768-parser-prescan-parity.md (+15)
- 768-prescan-visual-vocabulary-merge.md (+3)
- 768-self-closing-dispatch-regression.md (+1)

The conflict resolution kept the `auto-817` branch's test files
(`test_scan.py`, `test_trust_prescan.py`, `test_design.py`) because they are
the reviewed, verified variants: they import the shared Warden vocabulary
(`maistro.security.warden.patterns`) instead of duplicating a local scanner,
keep the Warden heuristic layer in the trust pre-scan (AC-1), and carry the
superset hostile corpus (parser parity, CSS comment/escape families,
var()/env()/data: declarations, unknown-tag catch-all — the same families the
develop-side notes describe). Develop's variant of those tests is therefore
not part of the resolved tree, and its +28 delta must not stay banked against
nodes that do not exist. The notes themselves are retained as historical
evidence of the develop-side rounds; only their banked delta is reverted by
this note.

`docs/testing/inventory-notes/design-studio-visual-artifact-768.md` (the
sixth overlapping note, develop's copy claimed +5) was resolved to the
auto-817 version, which carries no inventory-delta key — it adds no collected
pytest nodes (Playwright-only coverage), consistent with the round-3 note.

## Resolved conflict files

- packages/maistro-design/src/maistro_design/scan.py (ours: shared Warden
  vocabulary; develop duplicated a local scanner, violating the #817 stop
  condition)
- packages/maistro-design/src/maistro_design/trust.py (ours: blocking +
  heuristic pre-scan, visual_artifact=True)
- packages/maistro-design/tests/{test_scan,test_trust_prescan,test_design}.py
  (ours: superset hostile corpus, 347 collected nodes)
- packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx (ours:
  4-reason vocabulary in lockstep with Warden's
  VISUAL_ARTIFACT_BLOCK_REASONS) plus develop's
  `writeSanitizedVisualArtifact` reviewed sink (moved into the shared
  renderer so the one-sink contract holds)
- packages/hive-conductor/frontend/src/lib/deckSanitizer.ts (ours: fail-closed
  deprecated wrapper) plus the `writeSanitizedVisualArtifact` re-export
- packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx (theirs: every
  sink routed through the shared renderer, required by the boundary contract
  spec)
- packages/hive-conductor/frontend/src/pages/FixedPageArtifactEditor.tsx
  (theirs: two-arg onMarkupChange + initialTrustRecommendation contract the
  merged DesignStudio.tsx consumes)
- packages/hive-conductor/tests/Dockerfile.playwright (union: DesignStudio,
  FixedPageArtifactEditor, and FixedPageEditor copies)
- packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts (ours: superset
  hostile corpus) plus develop's production-path
  `data-trust-recommendation` assertions
- docs/security/design-studio-visual-artifact-rendering.md (theirs'
  consumer section, corrected to .tsx and re-extended for both editors)

No collected node moved in any other suite (verified with
check-suite-inventory.py across all suites after this note).
