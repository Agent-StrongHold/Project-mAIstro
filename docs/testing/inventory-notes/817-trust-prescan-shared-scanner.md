---
inventory-delta:
  packages/maistro-design/tests: +14
---
# 817-trust-prescan-shared-scanner

New `packages/maistro-design/tests/test_trust_prescan.py` (#817). Nothing was
removed or moved. It adds 14 tests:

- 5 hostile-corpus cases (script, iframe, `javascript:`, prompt injection,
  U+200B). Each must come back SKULL, with flags and a `banish` recommendation.
- 1 clean-brief case that stays T3 with `upgrade`.
- 6 parity cases (the corpus plus the clean brief). `upgrade` must be recommended
  exactly when `scan_blocking_patterns` finds nothing.
- 1 banish-list case that checks `banish_list_match` is kept.
- 1 shipped-path case. It runs `DesignEngine.generate()` with the builtin skills,
  the bundled design systems and a real review queue. The engine must raise
  `TrustBannedError`, and the queued record for that field must not be `upgrade`.
