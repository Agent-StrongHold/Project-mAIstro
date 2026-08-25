---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# pr-242-m0-closeout-adapter-test

Not this branch's delta. PR #242 (M0 closeout, merged as part of `6845aa9`)
added `packages/hive-conductor/backend/tests/test_maistro_core_adapter.py`,
whose single test is
`test_start_passes_container_prompt_manager_to_agent_factory`, and did not
record a note for it. `develop` has been failing `check-suite-inventory.py`
ever since — measured on a worktree at `origin/develop`:

```
DRIFT  packages/hive-conductor/backend/tests: expected 1285, collected 1286
```

Recorded here, under a slug naming the change that caused it rather than the
branch that noticed it, because the ledger's whole point is that a delta is
attributable. Filing it under this branch's own note would have made #132's
formal model look like it added a hive-conductor test, which is exactly the
misattribution the per-change ledger exists to prevent.

The test itself is legitimate and stays; only its accounting was missing. This
note is a candidate for folding into the baseline the next time it moves.
