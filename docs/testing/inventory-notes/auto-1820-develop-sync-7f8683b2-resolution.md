---
inventory-delta:
  tests/: +0
  packages/maistro-bootstrap/tests: +0
---

# auto-1820-develop-sync-7f8683b2-resolution

Repair round for #1820 (Honor the selected container runtime and define
non-elevated host installation). The round completed the blocked develop sync
(the previous attempt died on `deploy/scripts/verify-restore.sh` mid-merge of
`7f8683be2`) and brought the branch to develop's tip, then re-validated the
#1820 acceptance battery and the named CI gates at the merged head.
**No test node was added or removed by this round** — the merged test file is
the union of both parents' node sets, which each parent's own inventory rows
already account for; `scripts/check-suite-inventory.py` reports all 21 suites
matching the recorded inventory at the merged head.

## Merge state found and completed

The worktree held an **in-progress** merge of `7f8683be2` (M1-C1 #49, builders
interactive turns on canonical Run/NodeRun/Attempt) with one unmerged path:
`deploy/scripts/verify-restore.sh` (diff3-style, base `9cc5d1aca`). Resolved
and committed as `6d4bd96e9`. A follow-up `git merge origin/develop` brought
develop's tip `c29e0ea70` (M4 eventual + M1-E1 durable event replay) in with
**no conflicts**, committed as `3e7bf31b9`. Post-merge checks per AGENTS.md:

- `scripts/check-merge-markers.py` → `ok: no conflict markers in any tracked file`.
- `git diff --numstat origin/develop -- quality/` → empty; all quality ledgers
  byte-identical to develop (no per-identity rows lost in the merge).

## `deploy/scripts/verify-restore.sh` — the scratch-postgres readiness loop

Three-way conflict between this branch (`HEAD`: 180-probe budget,
`scratch_ready()` helper = `pg_isready` **AND** a real `SELECT 1` query,
`{{.State.Running}}` fail-fast, `docker logs … | tail -40 >&2`), the base
`9cc5d1aca` (`seq 1 60`, inline query condition, bare failure), and develop
`7f8683be2` (#2185 rewrite: `seq 1 120`, same inline query condition, log
dump + `within 120s` message). Resolution (union, keeping the stronger half of
each independently-pinned property):

- **Budget 180 probes** — this branch's #1820 repair pinned 180 for the
  congested-runner failure class; develop independently raised 60→120 for the
  same class. The merged budget keeps the longer pin (180 ⊇ 120's intent),
  with the reconciliation noted in the script comment.
- **Inline `pg_isready` + `psql … -d "${PG_DB}" -c 'SELECT 1;'` loop
  condition** (develop's shape) — structurally pinned by
  `test_scratch_ready_means_the_target_database_answers`; the branch's
  equivalent helper is behaviorally identical, so the inline form was kept to
  satisfy the structural pin. Liveness fail-fast and the branch's
  `2>&1 | tail -40 >&2` log form are kept on **both** failure paths (the
  develop form `>&2 2>/dev/null` discards the engine's stderr, which
  `test_verify_drill_fails_fast_when_scratch_container_dies` proves must
  surface).
- Post-loop guard message carries the budget (`within 180s`) and dumps logs.

Two test literals were reconciled in `tests/test_backup_restore_oracle.py`
(same node IDs, no inventory delta):

- `test_verify_readiness_failure_is_diagnosable` (develop's): `seq 1 120` →
  `seq 1 180`, with a comment recording the budget reconciliation.
- `test_scratch_ready_means_the_target_database_answers` (shared, unchanged
  from the base on both sides): the split marker `for _ in $(seq 1 60); do`
  no longer occurs in the script on **either** side, so the split fell back to
  the whole file before the first `done` and the assertions passed without
  isolating the loop body. The marker now matches the actual loop header
  (`seq 1 180`); verified the isolated 11-line body genuinely contains
  `pg_isready`, `psql`, `-d "${PG_DB}"`, `SELECT 1` and the liveness check.

## Evidence at the merged head (`3e7bf31b9`)

- `uv run pytest tests/test_install_runtime_selection.py
  tests/test_install_compose_floor.py tests/test_install_engine_floor.py
  tests/test_backup_restore_oracle.py -q` → **85 passed**.
- `tests/test_restore_oracle_readiness_gate.py` +
  `test_restore_oracle_characterization.py` +
  `packages/maistro-core/tests/cli/test_upgrade.py` → **94 passed**.
- `packages/maistro-bootstrap/tests` full package → **252 passed, 7 skipped**.
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  3438 files already formatted.
- `uv run python scripts/check-suite-inventory.py` → `ok: 21 suite(s) match
  the recorded inventory`.
- ci.yml `security` job at CI's exact sequence: `uv sync --locked --extra dev`
  → `check-dependency-namespaces.py` (218 packages, no unreviewed namespaces)
  → `uv pip freeze` (208 dists) → `pip-audit --strict --format=json` →
  `pip_audit_gate.py` → **exit 0** (`ecdsa==0.19.2 PYSEC-2026-1325` triaged in
  ALLOWED).
- security.yml `Supply chain (pip-audit)` at CI's exact sequence
  (`uv sync --locked --all-extras`, 210 dists) → same single triaged finding →
  **exit 0**.
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact args) → **exit 0**: `1315 reviewed
  identities -> 1315 findings`, `unclassified: 0`, `never_allowlist: 0`; base
  `c29e0ea70`, candidate `3e7bf31b9`; no ledger amendment needed.
- CI's exact ten-package `mypy` invocation → `Success: no issues found in 991
  source files`.
- Doc surfaces intact: `docs/install/default-installer.md` § "Container
  runtime selection and host privilege (#1820)" (line 162) and
  `docs/install/runtime-selection-evidence-1820.md`.
