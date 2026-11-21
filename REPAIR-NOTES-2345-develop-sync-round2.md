# Repair notes — #2345 develop sync round 2 (dlint >=0.17.0)

## State found

- Branch `dependabot/uv/dlint-gte-0.17.0` was at `92a43ad0b3` — a merge of
  develop **as of `d521240c6b`**, which is no longer develop tip. `origin/develop`
  had advanced to `a3efc93c92` (the PR's recorded conflict base), so the PR was
  still conflicting against develop tip.

## Action

- Fetched origin; merged `origin/develop` (`a3efc93c92`) into the branch.
- Single conflict: `requirements-dev-tools.txt` — two-sided edit of adjacent lines.
  - HEAD: `dlint>=0.17.0` (PR intent) + `semgrep>=1.181.0`
  - develop: `dlint>=0.16` + `semgrep>=1.185.0` (#2385)
  - Resolution preserves both: `dlint>=0.17.0` + `semgrep>=1.185.0`. Merged file
    differs from develop tip by exactly the dlint hunk.
- `quality/*.json`: merged tree is row-identical to `origin/develop`
  (`git diff --numstat origin/develop -- quality/` prints nothing). No ledger
  amendment needed; no test additions, so no inventory-note delta.

## Validation evidence (all local, exit codes checked)

- `uv sync --locked --extra dev` — venv matches merged `uv.lock`.
- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 3598 files already formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` —
  rc=0, 1229 reviewed identities == 1229 findings (base `a3efc93` = merge base).
- `uv run python scripts/check-suite-inventory.py` — ok: 21 suites match inventory.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -x -q` — 85 passed
  (develop's new suite, smoke of merged tree).
- dlint acceptance: isolated venv, CI's extraction pattern
  (`grep -E '^dlint' requirements-dev-tools.txt | sed 's/[[:space:]]*#.*//'`)
  yields `dlint>=0.17.0`; installs dlint **0.17.0** with flake8 7.5.0;
  `flake8 --version` registers `dlint: 0.17.0`; functionally detects
  DUO109/DUO104 on a seeded bad file (rc=1) and passes a clean file (rc=0).

## Result

Merge commit `89ff3bc738`; HEAD contains `origin/develop` tip; PR intent
(dlint >=0.17.0) intact at `requirements-dev-tools.txt:18`. Not pushed
(campaign prohibition: no GitHub mutations from worker).
