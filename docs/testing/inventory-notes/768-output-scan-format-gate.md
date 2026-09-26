---
inventory-delta:
  packages/maistro-design/tests: +6
---

# 768-output-scan-format-gate

Repair for the branch regression at `1be76a498`: REQUIRED CI `test` (and the
coverage-gate combine step) ran 2 failed / 2717 passed because
`packages/hive-conductor/backend/tests/test_design_service_startup.py`
`test_a_generation_against_each_bundled_slug_succeeds[workspace]` and
`test_different_systems_produce_different_prompts` raised
`maistro_design.types.TrustBannedError: ... prompt-stack: visual artifact
active-element`. Both pass at the develop base `84402748`, so the branch
regressed them.

## Root cause

`scan_design_output()` (packages/maistro-design/src/maistro_design/scan.py)
routed *every* string leaf through `scan_visual_artifact_markup()` — the
HTML/SVG tag/attribute/CSS allowlist parser that mirrors the frontend
`visualArtifactRenderer` boundary. `DesignEngine.generate()` emits a single
`OutputFormat.MARKDOWN` leaf (`prompt-stack`) whose prose embeds the design
system's component examples (`<a>`, `<input>`, `<label>`, `<nav>`, `<style>`)
as documentation for the model. The allowlist parser banned that prose as
`active-element`, so generation failed for a built-in first-party system.

## Fix

`scan_design_output()` now gates the visual-markup scan on the leaf's format:
it runs for `OutputFormat.HTML` and `OutputFormat.SVG` (the formats that reach
a browser markup sink) and, fail-closed, for untagged FILE leaves.
`scan_blocking_patterns()` (scripts, prompt injection, base64, suspicious
Unicode, banish list) and external-URL collection still cover *every* string
leaf, so a `<script>` smuggled into prose still blocks. The #817 trust
pre-scan (`trust.scan_and_record`) is unchanged: stored visual content keeps
being classified with the full renderer vocabulary.

## New tests (+6, in packages/maistro-design/tests/test_scan.py)

- `test_markdown_prompt_stack_with_documented_tags_passes`: the regression —
  a MARKDOWN prompt-stack carrying `<a>/<input>/<label>/<nav>/<style>`
  examples passes with no `visual artifact` flag.
- `test_text_patterns_still_cover_prose_leaves`: format-gating opens no text
  hole — `<script>` inside markdown still blocks via the shared text scanner.
- `test_visual_formats_keep_the_full_boundary[html]` /
  `[svg]`: handler attributes and `foreignObject` + `img data:text/html` in
  HTML/SVG-format leaves still block, proving the boundary survived the gate.
- `test_untagged_file_leaf_fails_closed`: a FILE leaf with `format=None` and
  hostile markup is still scanned (fail-closed).
- `test_bundled_workspace_prompt_stack_passes_the_output_scan` (integration):
  the exact first-party content that regressed — the bundled workspace
  system's DESIGN.md inside a MARKDOWN prompt-stack — passes `scan_design_output`.

The conductor-side regression is pinned by the pre-existing
`test_design_service_startup.py::TestEveryBundledSystemResolves` /
`TestTheStubIsGone` suites, green again after the fix (26 passed).
