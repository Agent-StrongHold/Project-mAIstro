---
inventory-delta:
  packages/maistro-design/tests: +15
---

# 768-parser-prescan-parity

Repair follow-up for #768/#817: `scan_visual_artifact_markup` in
`packages/maistro-design/src/maistro_design/scan.py` was rewritten from four
whole-content regexes to an `html.parser.HTMLParser` walk that enforces the
same allowlists as the frontend boundary
(`frontend/src/lib/visualArtifactRenderer.tsx`): HTML/SVG tag sets,
namespace-scoped attribute sets, the presentation-only CSS property list, and
the network/code value patterns — the same reason vocabulary
(`VISUAL_ARTIFACT_BLOCK_REASONS`).

## Why the regexes were not enough

The lexical regexes decided "active element" from a fixed tag alternation, so
tags outside it (`<html>`, `<head>`, `<body>`, `<style>` was present but
arbitrary others were not) and allowlist drift between the Python pre-scan and
the browser renderer went unnoticed. #817 requires the admin pre-scan to
classify content with the words the renderer blocks in; a tag list that only
overlaps the renderer's allowlist cannot do that.

## Conservative-superset contract

The pre-scan deliberately never sees less than the renderer:

- attributes the renderer strips without inspecting (unknown/disallowed,
  XML-namespaced) still contribute `dangerous-url` when their value carries a
  `javascript:`/`vbscript:`/`data:`/network scheme — corpus evidence, not a
  pass;
- a parser failure fails closed and returns every reason, so no
  recommendation can call unparseable content upgradeable;
- reasons are reported in the shared `VISUAL_ARTIFACT_BLOCK_REASONS` order so
  recorded `warden_flags` are deterministic.

## New tests (+14 collected in test_scan.py)

`TestScanVisualArtifactMarkupVocabulary`:

- 4 parametrized safe-presentation cases (fixed-page poster template with
  layout CSS + SVG, layout-only CSS, escaped script **text**, bare
  `title` attribute) assert no
  reasons — safe templates stay upgradeable and literal text is not
  misclassified as active markup (matching the browser's DOM pass).
- 9 parametrized hostile cases assert the specific renderer reason carried:
  `<html>`/`<style>` wrappers → `active-element`; SVG-only attribute on an
  HTML element and never-allowlisted attribute → `unsupported-attribute`;
  `xlink:href` → `unsupported-attribute`; `data:text/html` src and
  entity-encoded `jav&#x61;script:` in dropped attributes → `dangerous-url`;
  `behavior:`/`column-rule:` CSS → `unsupported-css-property`.
- 1 test asserts reasons come back in the shared vocabulary order (stable
  `warden_flags`).
- 1 test drives `scan_and_record` with renderer-hostile content and proves
  SKULL/banish with `active-element`, `dangerous-url`, and
  `css-network-or-code` flags — the #817 "never recommend upgrade for content
  the boundary blocks" guarantee exercised through the new parser path.

## Fixture alignment (+0 net)

`test_design.py` fixtures `test_multi_format_content_produces_container_root`
and `test_persist_blobs_calls_store_blob_for_each_blob_leaf` used incidental
`<html></html>` markup — a full-document wrapper the shared boundary (and now
the pre-scan) rejects as `active-element`. Their documented intent is output
structure and blob persistence, so the fixtures were switched to
boundary-safe `<article></article>`; no assertion intent changed.
