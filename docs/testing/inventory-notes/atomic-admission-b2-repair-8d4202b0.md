---
inventory-delta: {}
---

# Issue #1893 B2 — CI-repair validation at 8d4202b0

Validation round (no code or test change; worktree clean at start).

- `uv run ruff check .` -> All checks passed.
- `uv run ruff format --check .` -> 3364 files already formatted.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q` -> 128 passed, 3 skipped.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -q` -> 201 passed, 3 skipped.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` -> Success, no issues in 2 source files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` -> exit 0, 1321 reviewed identities = 1321 findings, unclassified 0, never_allowlist 0.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` -> ok, 16918 collected node IDs.
- `uv run python scripts/check-reachability-provenance.py` -> exit 1 on exactly `maistro.runs.admission_identity` + `maistro.tasks.admission_codec` (NEW unreachable / NEW dispositions, not covered by an already-landed reachability authorization). All other sub-ratchets OK.
- `uv run python scripts/check-reachability-dispositions-provenance.py` -> exit 1, same two identities.

Blocker: reachability provenance two-merge wall. The prepared grant `3235229f5fed` is not an ancestor of `origin/develop` (`c2d7209f`); `ratchet_provenance.load_authorizations` reads grants from the merge base, so in-branch edits cannot authorize these two intentionally unwired modules. Campaign-level action required: land the grant on develop, then merge origin/develop here. No in-branch change to code, tests, or ledgers was made.
