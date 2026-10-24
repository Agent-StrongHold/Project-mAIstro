---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue #1893 CI repair: wrapped invalid-lock diagnostic

Starting source: `38b6c44e617dfd70d9f344da9d4236fe48b7f6a2`.

The existing real Typer invocation rejected invalid lock JSON with exit 1, but
its diagnostic assertion failed when Rich wrapped `not a valid extension lock`
across lines. Reproduced with `uv run pytest
packages/maistro-core/tests/extensions/test_cli_lock.py -x -q`: 1 failed, 6 passed.

Parameterize that existing test at 40, 80, and 120 columns (+2 collected nodes).
Use the real Rich Console and production CLI/load/parser path, not a mocked
return. Assert rejection and the full semantic diagnostic after normalizing
rendered whitespace. Terminal layout is not part of the rejection contract.
No gate, production implementation, or ledger is changed.

## Executed evidence

- With the new terminal-width parameters and the old contiguous assertion,
  `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py -q
  -k invalid_lock`: **2 failed (40/80 columns), 1 passed (120 columns)**.
- After whitespace normalization, `uv run pytest
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`:
  **324 passed, 3 skipped** (PostgreSQL DSNs unset).
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, **16543** nodes, zero duplicate evidence.

This does not establish admission reachability, authorized admission or
database durability. Trusted-base provenance remains blocked; details and
acceptance limits are in `docs/implementation/issue-1893-current-repair.md`.
