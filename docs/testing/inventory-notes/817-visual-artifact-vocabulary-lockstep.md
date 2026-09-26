---
inventory-delta:
  packages/maistro-core/tests: +3
---
# 817-visual-artifact-vocabulary-lockstep

New
`packages/maistro-core/tests/security/warden/test_visual_artifact_vocabulary.py`
(#817, #768). Nothing was removed or moved. It adds 2 tests:

- 1 structural lockstep case: `VISUAL_ARTIFACT_PATTERNS`' reasons must equal
  `VISUAL_ARTIFACT_BLOCK_REASONS` (same names, same order, no duplicates).
  The pattern table now derives its reasons from the declared tuple, so a
  failure here means the derivation was bypassed.
- 1 scanner-emission case: one hostile probe per declared reason family
  (active-element, event-handler, dangerous-url, css-network-or-code) run
  through `scan_blocking_patterns(..., visual_artifact=True)` — the exact
  call the Design output boundary and the trust pre-scan make. Each probe
  must be classified with its declared reason, and the visual layer may only
  ever emit declared reasons, so an admin-facing trust recommendation cannot
  contradict what the renderer blocks (AC-4).
- 1 cross-language mirror case: `test_typescript_renderer_mirror_equals_declared_vocabulary`
  parses the browser boundary's `VISUAL_ARTIFACT_BLOCK_REASONS` `as const`
  array in `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx`
  and asserts equality (same names, same order) with Warden's declared
  tuple. Previously that mirror was anchored only by a source comment;
  the equality is now enforced by test, so neither side can drift without
  a red run (AC-4/AC-5 residual from round-16 review).
