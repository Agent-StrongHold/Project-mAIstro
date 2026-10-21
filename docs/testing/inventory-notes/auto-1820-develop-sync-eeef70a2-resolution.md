---
inventory-delta:
  tests/: +0
  packages/maistro-bootstrap/tests: +0
---

# auto-1820-develop-sync-eeef70a2-resolution

Repair round for #1820 (Honor the selected container runtime and define
non-elevated host installation). The round resolved the preserved
`origin/develop` sync conflict in the worktree and re-validated the security
gates on the merged head. **No test was added or removed by this round** — the
merge brought develop's own tests together with develop's own
`docs/testing/inventory/baseline.json` rows, and
`scripts/check-suite-inventory.py` reports all 21 suites matching the recorded
inventory at the merged head (`ok: 21 suite(s) match the recorded inventory`).

## Merge state found and completed

The worktree held an **in-progress** merge of `780f1d340` ("WIP: M3 — Build
Workspace-centric Goal and Run inspection in Conductor (#2181)", an ancestor
of `origin/develop`) with three unmerged paths. The driver's check logs
(`check-*.log`) all failed on the conflict markers left in
`packages/maistro-canvas/pyproject.toml` (TOML parse error at the
`<<<<<<<` line), so every `uv`-based gate was unrunnable.

Resolution, committed as `acb0a286f`:

- `packages/maistro-canvas/pyproject.toml` + `uv.lock` — pillow specifier
  `>=13.0.0,<14`: the intersection of this branch's security ceiling `<14`
  (round-2 repair `71b34e46f`, which unlocked the fix version 13.0.0 for the
  CVE-2026-11239x/11240x/11289x set) and develop's independently raised floor
  `>=13.0.0,<14`. Locked versions are unchanged on both sides of the merge
  (`pillow 13.0.0`, `certifi 2026.10.19`), so the lock body needed no
  re-resolution; `uv lock --check` → `Resolved 260 packages`.
- `deploy/scripts/verify-restore.sh` — kept this branch's readiness budget
  and structure (180-probe `scratch_ready()` helper = `pg_isready` **AND** a
  real `SELECT 1` query) and folded develop's rationale (the entrypoint's
  temporary bootstrap server answers `pg_isready` before `${PG_DB}` exists —
  the `test_restore_oracle_characterization.py` finding) into the comment.
  Net diff vs the pre-merge branch head is comment-only;
  `bash -n` passes and the three restore-oracle suites pass (26 passed).

A second `git merge origin/develop` then brought the branch to develop's tip
`eeef70a2a` (17 commits beyond `780f1d340`); it auto-merged with no conflicts
(`f0ace1961`). Post-merge checks per `AGENTS.md`:

- `git diff --numstat origin/develop -- quality/` → empty (all ledgers
  byte-identical to develop; no rows lost in the auto-merge).
- `scripts/check-merge-markers.py` → `ok: no conflict markers in any tracked
  file`.

## Security gate re-validation at the merged head (CI's exact sequences)

The round's named gate failure was `security: failure` (with the pip-audit
supply-chain job). Both were re-run locally at `f0ace1961`:

ci.yml `security` job:

```
uv sync --locked --extra dev                          -> ok (223 frozen dists)
uv run python scripts/check-dependency-namespaces.py  -> exit 0 (233 distributions)
uv pip freeze --exclude-editable > /tmp/deps.txt      -> 223 rows
uv run pip-audit --strict --format=json -r /tmp/deps.txt
    -> "Found 2 known vulnerabilities in 1 package" (ecdsa only)
python scripts/pip_audit_gate.py /tmp/pip-audit.json  -> exit 0
    ("pip-audit OK (1 known, all triaged in ALLOWED)")
```

security.yml `Supply chain (pip-audit)` job (`uv sync --locked --all-extras`,
225 frozen dists): same audit → same single triaged `ecdsa` finding → gate
exit 0.

`certifi 2026.10.19` and `pillow 13.0.0` (the round-2 fixes) survive the sync
and are clean under the current advisory database; the vulture per-identity
ledger also passes with CI's exact arguments
(`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → `1321 reviewed identities -> 1321 findings`,
`unclassified: 0`).

## Issue-contract re-validation (focused)

- `uv run pytest tests/test_install_runtime_selection.py
  tests/test_install_compose_floor.py packages/maistro-bootstrap/tests/test_plan.py
  packages/maistro-bootstrap/tests/test_delivery.py -q` → 86 passed
  (both-CLIs-present, selected-podman-never-probes-inaccessible-docker,
  unavailable-selected-runtime-fails-without-switching, `auto` policy,
  elevation-denial → recoverable prerequisite, interruption/retry ownership).
- `packages/maistro-bootstrap/tests` full package → 245 passed, 7 skipped.
- Restore-oracle suites (`test_restore_oracle_readiness_gate.py`,
  `test_restore_oracle_characterization.py`, `test_backup_restore_oracle.py`)
  → 26 passed.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- CI's exact ten-package `mypy` invocation → `Success: no issues found in
  1078 source files`.
- The documented support matrix
  (`docs/install/default-installer.md` § "Container runtime selection and
  host privilege (#1820)") and the clean-account evidence transcript
  (`docs/install/runtime-selection-evidence-1820.md`) are intact at the
  merged head.
