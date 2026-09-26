---
inventory-delta:
  packages/maistro-design/tests: +27
---
# 817-trust-prescan-shared-scanner

New `packages/maistro-design/tests/test_trust_prescan.py` (#817). Nothing was
removed or moved. It now adds 27 tests:

- 11 hostile-corpus cases (script, iframe, `javascript:`, prompt injection,
  U+200B, a base64 blob, plus the AC-3 active-markup families: MathML, an
  `onerror=` handler attribute, script-capable SVG, `data:text/html`, and a
  CSS `url()` primitive). Each must come back SKULL, with flags and a
  `banish` recommendation. The blocking portion of the recorded flags must be
  exactly the shared output-boundary verdict
  (`scan_blocking_patterns(..., visual_artifact=True)`), and any extra flags
  may only be Warden heuristic evidence.
- 1 clean-brief case that stays T3 with `upgrade`.
- 12 parity cases (the corpus plus the clean brief). `upgrade` must be
  recommended exactly when the shared output-boundary scan finds nothing AND
  Warden's heuristic layer has nothing to add.
- 2 banish-list cases. They check that `banish_list_match` is kept on its own,
  and that it comes first when the scanner also finds something.
- 1 shipped-path case. It runs `DesignEngine.generate()` with the builtin skills,
  the bundled design systems and a real review queue. The engine must raise
  `TrustBannedError`, and the queued record for that field must not be `upgrade`.

2026-09 repair update: the parity target moved from the bare
`scan_blocking_patterns("content", content, None)` call to the exact call the
final output boundary makes (`visual_artifact=True`, per AC-4), the corpus grew
from 6 to 11 entries (+5 params on two parametrized tests), and the recorded
flags contract now pins the blocking portion to the boundary verdict with
heuristic flags as the only permitted extras.
