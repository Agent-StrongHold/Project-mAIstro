---
inventory-delta:
  packages/maistro-core/tests: 0
---
# Issue #1893 CI repair: active-extension collision diagnostic

Source: `973772507c94428dba24fad7d9530490688d59e2`, base:
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Frozen input: job
`88e144df073146a3b862fef1d0b06457`, `check-3.log`.

The branch-added pack collision regression expected `already active as an
extension`; the merged production registry says `already an active extension`.
Reproduced at the exact starting head with:

```text
uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py::TestCompatibilityThroughM9Machinery::test_pack_install_cannot_shadow_an_active_extension_id -q
1 failed: Regex pattern did not match
```

Update that assertion to the production diagnostic, retaining the typed
`PackIdentityConflict` and empty-registry checks. Extend the same test to install
a dependent requiring the original extension's ^1.0.0 version after the rejected
2.0.0 pack collision. This exercises real manifest inspection, installation and
compatibility evaluation without mocked returns, proving that the refusal
preserves dependency resolution as well as pack records. No test node is added
or removed. No production code, ledger, grant, workflow or gate changes.

## Executed validation

All commands ran in the assigned worktree against the source above plus this
repair. Logs are in the supplied job directory, not historical assertions.

- `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -q -x -rs`:
  **346 passed, 3 skipped**, 349 collected nodes. The three skipped cases require
  PostgreSQL DSNs, which are unset; they provide no durability evidence.
- `uv run pytest packages/maistro-core/tests/extensions -x -q`:
  **1092 passed**.
- Mutation check (`uv run python -`, calling `pytest.main` on the single repaired
  node): wrap the real `InstallablePackRegistry.install` in memory so that on
  `PackIdentityConflict` it changes the active extension to 2.0.0 before
  re-raising. **1 failed**, at the added dependent install with
  `PackIncompatible: ... 2.0.0 ... does not satisfy ^1.0.0`. The typed error and
  empty-record checks still pass; the new check detects identity corruption.
  No tracked production file was modified for this experiment.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 identities,
  zero unclassified. No ledger amendment is justified.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16567 collected nodes, zero duplicates.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger,
  1403 production modules, 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate ledger, 50 groups covering 171 modules.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-promotion-surface.py`: PASS.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python
  scripts/check-ratchet-provenance.py`: **FAIL**, both admission modules remain
  unauthorized new unreachable identities and dispositions. Candidate-ledger
  checks above do not override the trusted-base failure.
- `git diff --check`: PASS.

PostgreSQL, authorization, Run JSONB materialization and production admission
reachability are not proven by this pack test. Full integration CI was not run.
The supplied failing regression is repaired, but #1893 remains blocked on the
unchanged trusted-base provenance gate and unverified integration acceptance.
