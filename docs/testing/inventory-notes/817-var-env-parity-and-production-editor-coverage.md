---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-design/tests: +9
  packages/hive-conductor/tests/e2e: +0
---
# 817-var-env-parity-and-production-editor-coverage

Round-19 repair for the verified #817 findings. Nothing was removed or moved.

## Finding 1 — scanner/renderer parity for var()/env()/data: (AC-4)

`packages/maistro-core/src/maistro/security/warden/patterns.py`'s
`VISUAL_ARTIFACT_PATTERNS` css-network-or-code pattern now carries the
`var(`, `env(`, and `data:` families the browser boundary's
`NETWORK_OR_CODE_CSS` already blocked, so `scan_and_record` and the output
boundary can no longer recommend upgrading content the renderer blocks.

New tests:

- `test_renderer_css_families_are_all_recognized_by_the_shared_scanner`
  (test_visual_artifact_vocabulary.py): pattern-body lockstep, not just
  reason-name lockstep. It derives every function and scheme family from the
  TS regex literal at test time and requires the compiled Python pattern to
  recognize each one (scheme probes carry a `://` payload because the scanner
  deliberately value-anchors `behavior:`), so neither side can grow a family
  the other lacks without a red test.
- `test_renderer_blocked_var_env_data_styles_are_scanner_blocked`
  (test_visual_artifact_vocabulary.py): the exact round-19 probe
  (`<div style="color:var(--attacker-controlled)">`) must fail closed.
- 3 parametrized corpus entries in test_scan.py (output boundary) and 3 in
  test_trust_prescan.py's HOSTILE_CORPUS (pre-scan recommendation, which flows
  through the SKULL/never-upgraded and flags-parity machinery).

## Findings 2+3 — production reachability and hostile coverage (AC-5)

`DesignStudio.tsx` mounts the structured `FixedPageEditor`, not the hardened
`FixedPageArtifactEditor` the corpus previously exercised; the security doc
now says so truthfully (docs/security/design-studio-visual-artifact-rendering.md
Consumers section, including the doc-boundary filename fix `.ts` → `.tsx`).

- deck-sanitization.spec.ts's harness additionally mounts the production
  structured `FixedPageEditor`; the new test drives a hostile prompt through
  it and proves the payload survives only as escaped text in the canvas
  preview and the HTML export, with no hostile elements, no `__deckPwned`
  execution, and no attacker requests. Tagged payloads avoid URL schemes so
  the inert escaped text itself cannot trip the tag/attribute assertions
  (attributes are asserted against real tags only: `/<[a-z][^>]*\son...=/`).
- The corpus, scan probes, and trust-recommendation probes gain
  var()/env()/data: cases on the browser side of the same parity line.
- tests/Dockerfile.playwright copies the newly imported FixedPageEditor.tsx
  into the CI browser image.

Executed evidence: 9/9 deck-sanitization specs pass in the CI playwright
image (local direct runs are invalid for this spec: frontend/node_modules
gives the bundle a second React); focused pytest 284 passed; the suites above
carry the deltas listed in the front-matter. The e2e delta is +0 because that
suite's recorded count covers only its pytest files — the playwright spec
gain is documented here in prose, matching the +0 convention of the earlier
playwright notes (752, design-studio-keyboard-769).

test_trust_prescan's HOSTILE_CORPUS grew by 3 entries, which parametrize into
both corpus-consuming tests (+6 node IDs there); test_scan.py's blocking
corpus grew by 3 (+3 node IDs); the lockstep module gained 2 standalone
tests (+2).
