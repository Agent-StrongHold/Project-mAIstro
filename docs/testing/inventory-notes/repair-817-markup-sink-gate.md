---
inventory-delta:
  packages/maistro-design/tests: +4
---

# repair-817-markup-sink-gate

CI-repair round for #817 (exact-debt-ledger / Quality gate, both failing at
`187792523`): the vulture per-identity ledger flagged one NEW identity —
`packages/maistro-design/src/maistro_design/types.py:32: unused variable 'SVG'`
(pydantic-declarative-field). The finding was real: the branch's #817/#768
consolidation removed `scan.py`'s last src read of `OutputFormat.SVG`
(`visual_markup_formats`), and a ledger grant cannot authorize new debt from a
candidate branch (authorizations are read from the base revision, two-merge
rule), so the identity had to be eliminated in code.

## What changed

`packages/maistro-design/src/maistro_design/scan.py` restores the reviewed
markup-sink gate from the deliberate lineage (37fced681, efb1e3a77) that a
merge resolution silently dropped:

- `scan_design_output()` applies the visual-artifact (markup-sink) families of
  the shared vocabulary only to leaves whose format reaches a browser markup
  sink — `OutputFormat.HTML`, `OutputFormat.SVG`, and untagged FILE leaves,
  failing closed. Prose leaves (MARKDOWN prompt stack) keep every
  unconditional arm (script, prompt-injection, active-markup, base64,
  suspicious Unicode) but not the sink families.
- `scan_design_text()` gains a `visual_artifact: bool = True` parameter; the
  default keeps the renderer boundary (hive-conductor `design_render.py`)
  fail-closed exactly as before.

Unchanged: `scan_and_record` (trust pre-scan, AC-1/AC-2/AC-4),
`scan_blocking_patterns(visual_artifact=True)` as the AC-4 parity target, and
the final render boundary — so no acceptance path of #817 is scanned more
narrowly than before; the trust pre-scan stays at least as strict as the
renderer at every sink.

## Tests (+4, `TestVisualMarkupFormatGate` in `packages/maistro-design/tests/test_scan.py`)

- prose (MARKDOWN) leaf carrying a sink-only payload (`var()` CSS value) passes
  the artifact-tree walk while `scan_design_text` still blocks it;
- HTML and untagged leaves fail closed on the same payload;
- an `OutputFormat.SVG` leaf with `<svg><script>` still blocks (the pin that
  keeps `OutputFormat.SVG` on the reviewed src surface).
