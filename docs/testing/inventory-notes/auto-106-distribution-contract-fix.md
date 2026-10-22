---
inventory-delta:
  tests/: +0
---
# auto-106-distribution-contract-fix

Fixes `tests/test_distribution_contract.py` to match the actual Dockerfile content.

## Change

The test was asserting that the Dockerfile contains `maistro-core[identity,llm,sandbox,observability]`, but the Dockerfile actually contains `maistro-core[identity,llm,sandbox,observability,sqlite]` (with the `sqlite` extra added in commit `2dfd3b97a`).

## Fix

Updated `tests/test_distribution_contract.py` line 72 to expect the actual Dockerfile content.

## Evidence

- The Dockerfile at `home/dev/Git/wt/auto-106/Dockerfile` line 57 contains:
  ```
  "./packages/maistro-core[identity,llm,sandbox,observability,sqlite]" \
  ```
- The test `test_image_pins_supported_python_and_installs_identity` was failing because it expected the old content without `sqlite`
- After the fix, all distribution_contract tests pass

## Impact

This fix resolves a red gate that was inherited by this branch but was actually caused by a develop-side change (commit `2dfd3b97a`).

The `sqlite` extra was intentionally added in commit `2dfd3b97a` with the message "fix(engine): install maistro-core[sqlite] extra so aiosqlite ships in the image", indicating this was a deliberate fix for the engine functionality.