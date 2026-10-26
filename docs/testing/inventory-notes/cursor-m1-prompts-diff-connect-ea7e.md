---
inventory-delta:
  packages/maistro-core/tests: +3
---
# cursor-m1-prompts-diff-connect-ea7e

CONNECT proof for `maistro.prompts.diff` via `maistro.agents.factory`
`_upsert_agent_soul` (ADR-060-shaped prompt compare / disposition root).

Adds three tests in `test_factory_prompts_diff_connect.py`:

- first soul upsert has no prior content → no diff;
- changed soul returns structured `DiffLine` add/remove entries;
- identical re-upsert skips the diff.

Reachability baseline drops `maistro.prompts.diff`; the `prompts-diff`
CONNECT group is pruned. Vulture retires the `compute_diff` unused-function
row (caller is under `packages/*/src`). Convergence: Prompts and personas
unreachable `few` → `none`.
