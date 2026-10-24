# Repair round for #1820 — develop sync completion + gate revalidation

Candidate: `auto-1820` @ `3e7bf31b9` (merge of `origin/develop` @ `c29e0ea70`
into the branch after completing the blocked `7f8683be2` sync as `6d4bd96e9`).
Base: `origin/develop` @ `c29e0ea70`.

## What this round did

1. **Completed the previously blocked develop sync.** The worktree held an
   in-progress merge of `7f8683be2` with one unmerged path
   (`deploy/scripts/verify-restore.sh`, diff3 base `9cc5d1aca`). Resolved by
   keeping the union of both sides' readiness properties (180-probe budget
   from this branch's #1820 repair; develop #2185's inline DB-answering loop
   condition; liveness fail-fast with a log form that preserves the engine's
   stderr on both failure paths). Committed as `6d4bd96e9`.
2. **Merged develop's tip** `c29e0ea70` (auto-merge, no conflicts) as
   `3e7bf31b9`. `quality/` ledgers byte-identical to develop after the merge
   (`git diff --numstat origin/develop -- quality/` empty); no conflict
   markers in any tracked file.
3. **Reconciled two stale/conflicting test literals** in
   `tests/test_backup_restore_oracle.py` (no node-ID changes): develop's
   diagnosable-failure test now pins the merged 180-probe budget; the shared
   `test_scratch_ready_means_the_target_database_answers` split marker now
   matches the real loop header, so its loop-body assertions are no longer
   vacuous. Full rationale in
   `docs/testing/inventory-notes/auto-1820-develop-sync-7f8683b2-resolution.md`.

## Gate evidence at HEAD `3e7bf31b9` (CI's exact shapes)

| Gate | Result |
|---|---|
| `uv sync --locked --extra dev` / `--all-extras` | `Resolved 260 packages` |
| ci.yml `security` (namespaces → freeze → pip-audit → gate) | **exit 0** — `ecdsa` finding triaged in ALLOWED |
| security.yml `Supply chain (pip-audit)` | **exit 0** — same single triaged finding |
| `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **exit 0** — 1315/1315 banked, unclassified 0, no ledger edit |
| `uv run ruff check .` / `ruff format --check .` | clean / 3438 files formatted |
| `uv run mypy` (CI's ten-package invocation) | `Success: no issues found in 991 source files` |
| `check-suite-inventory.py` | `ok: 21 suite(s) match the recorded inventory` |
| `check-merge-markers.py` | `ok: no conflict markers in any tracked file` |

## #1820 acceptance re-validation at HEAD `3e7bf31b9`

- `tests/test_install_runtime_selection.py` +
  `tests/test_install_compose_floor.py` + `tests/test_install_engine_floor.py`
  + `tests/test_backup_restore_oracle.py` → **85 passed** (both-CLIs-present,
  selected-podman-never-probes-inaccessible-docker, docker-only/podman-only,
  unavailable-selected-runtime-fails-without-switching, documented `auto`
  policy, persisted-plan precedence, manifest runtime recording,
  recovery/upgrade commands naming the selected runtime, podman-safe
  healthchecks, elevation-denial/missing-sudo → recoverable prerequisite,
  interrupted-install retry keeping selection and ownership).
- Restore-oracle suites + `test_upgrade.py` → **94 passed**.
- `packages/maistro-bootstrap/tests` → **252 passed, 7 skipped**.
- Docs intact: `docs/install/default-installer.md` § "Container runtime
  selection and host privilege (#1820)";
  `docs/install/runtime-selection-evidence-1820.md` (clean-account
  transcripts recorded in an earlier round; not re-executed on a pristine
  host in this round — no CI failure alleges regressions there).

## Residual risks

- The clean-account install transcripts
  (`docs/install/runtime-selection-evidence-1820.md`) are recorded evidence
  from a prior round on dedicated hosts; this round verified the doc and the
  hermetic installer tests, not a fresh clean-account install.
- `pip-audit` advisories are a moving target; verdict is as of this run's
  advisory DB (single triaged `ecdsa` finding, allow-listed).
