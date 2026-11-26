---
inventory-delta:
  packages/maistro-design/tests: +3
---

# 768-prescan-visual-vocabulary-merge

Merge reconciliation for #768 (shared Design Studio visual-artifact boundary)
against develop's #817 pre-scan fix (#1546, commit `be46a228c`).

## What happened

Both sides fixed the same defect independently: `trust.scan_and_record`
recommended `upgrade` for content it never inspected. Develop classified with
`scan_blocking_patterns` only; this lane additionally applied the shared visual
vocabulary (`scan_visual_artifact_markup`) that the browser renderer enforces.
Merging develop into the lane conflicted in
`packages/maistro-design/src/maistro_design/trust.py`.

## Resolution

- `trust.scan_and_record` now unions both vocabularies: a record reaches SKULL
  and `banish` when either the shared text scanner (`scan_blocking_patterns`)
  or the shared visual scanner (`scan_visual_artifact_markup`) finds a blocking
  pattern. `banish_list_match` stays first when the banish list also hits.
- `packages/maistro-design/tests/test_trust_prescan.py` (develop's #817 suite)
  kept every assertion except two exact-tuple flag equalities, which became
  superset assertions so the union can add the renderer's visual reasons
  without dropping any shared-scanner finding. The intent — scanner-blocked
  content is never `upgrade` — is unchanged and still asserted dynamically.

## New tests (+3, parametrized body adds 3 cases)

- `test_renderer_blocked_markup_is_never_upgraded`: handler attribute,
  `foreignObject`/`img data:text/html`, and CSS `url(...)` primitives — two of
  which carry no `scan_blocking_patterns` finding, proving the visual
  vocabulary is load-bearing for the "never recommend upgrade" guarantee.

Existing lane coverage in `test_scan.py`
(`test_visual_trust_prescan_blocks_the_renderer_hostile_corpus`,
`test_visual_trust_prescan_keeps_safe_presentation_upgradeable`) continues to
assert the full visual reason set and that safe presentation markup stays
upgradeable.
