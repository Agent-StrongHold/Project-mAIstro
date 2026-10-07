---
inventory-delta:
  tests/: +16
---

# #1610 retained Ruff owner review

Refs #1357 and #160. The independent review found three ways the regression
contract could stay green after the remaining Ruff owner lost source scope,
push coverage or failure propagation. This follow-up changes tests only; the
workflow's two deduplication conditions are unchanged.

The ownership contract now checks that one unconditional checkout precedes each
Ruff owner, with no alternate repository/ref/path or sparse/filter override.
Quality push filters cannot contain negative patterns, and workflow/job/step
shell overrides cannot mask the retained command's exit status. Future changes
to these contracts require an explicit equivalence review, not a silent fallback.

Sixteen added cases cover sparse and substituted checkout scopes on both owners,
negative topic/protected branch patterns, and shell masking at all three levels
on both owners. All sixteen failed against the previous guard. After the fixes,
35 focused tests pass (the original 19 are retained). The published test blob
matches the tested local file: 9070b5b7b11321cdbf980c9fd6b8a694308f5e42.

Local testing used Python 3.13.5, the complete hash-verified CI file and relevant
source-derived Quality/protection fixtures including the real checkout fields.
It does not replace repository CI using the complete actual files. New-head
formatting, full tests, inventory, review and candidate validation remain required.
The preceding PR run showed CI omitting the duplicate Ruff steps as intended;
that is not approval of this updated head or a measured whole-CI compute saving.
