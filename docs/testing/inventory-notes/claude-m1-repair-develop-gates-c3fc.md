---
inventory-delta:
  tests/: +1
---
# claude-m1-repair-develop-gates-c3fc

Records the +1 that commit `067ad55` ("Classify the canonical container
boundary as high risk", #318) added to `tests/test_check_autonomous_merge.py`
without an inventory note — the drift that turned the `test` job red on every
open PR. This repair PR adds no tests of its own; it re-aligns the
branch-protection tests with ADR-095 as amended (integration retired, main
exempt from linear history) and adds the Autonomous Merge Safety workflow to
gates-ran's triggers, none of which changes collection counts.
