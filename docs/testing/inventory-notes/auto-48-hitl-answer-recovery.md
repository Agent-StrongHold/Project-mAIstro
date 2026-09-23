---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-48-hitl-answer-recovery

Adds a canonical durable HITL regression for a crash after the accepted answer continuation is persisted and the canonical Run mirror has not yet transitioned. The test verifies targeted restart repair, successful resume, and preservation of physical Attempt history while a new Attempt completes.

## Independent verification at f35b1bd9edbfb2740a5f6f79e5ba4251f17181c3 (2026-09-23)

Executed in the lane worktree; no code edits. All issue #48 acceptance
criteria were re-derived and exercised against this tree:

- `uv run pytest packages/maistro-core/tests/graph/durable_runs/ -q` — 473
  passed, 21 skipped (incl. the settlement and continuation-conformance
  suites this note's delta names).
- `uv run pytest packages/hive-conductor/backend/tests -q` — 2656 passed,
  1 skipped. The four isolated lane suites also pass alone.
- `uv run ruff check .` and `uv run ruff format --check .` — clean;
  `uv run mypy packages/*/src` (six packages) — clean.
- Quality-gate scripts re-run locally: radon baseline, vulture ledger
  (1415 -> 1414), reachability + dispositions, convergence matrix,
  enumerations, doc links, contract markers, security inventory, image
  inventory, agent-store writes, durable-table inventory, wiring reads
  (base 750edd84), version consistency — all green.
- Diff-coverage gate re-run from locally produced coverage data (full
  maistro-core tests + full hive-conductor backend tests, branch arcs):
  `check-diff-coverage --base 750edd84` — all 4 changed production files at
  or above 90% lines / 80% branches.
- CI at this head: Quality gate and Coverage gate both SUCCESS (the
  7adbf77 failures are repaired). One failure remains — `Supply chain
  (pip-audit)` — with a network fault, not a finding: pip-audit could not
  reach the PyPI advisory API, left `pip-audit.json` empty, and the gate
  crashed parsing it (JSONDecodeError char 0). The same workflow passed on
  the base SHA 750edd84 thirteen minutes earlier, and this branch touches
  no dependency manifests. Recorded as environmental; a re-run is the
  remedy, not a code change.
