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

---

# CI-repair round 3 — `gates-ran` pending forever (head `720aaa2500`)

## State found

Develop-sync round 2 landed as merge `720aaa2500` (develop tip `971e536838`
absorbed; three-dot diff = exactly this repair note + the dlint hunk). All
~80 check-runs on that head are success/skipped, but the required `gates-ran`
commit status stayed **pending** ("Required execution evidence is still
arriving", publisher run 44908701689) — the merge-queue blocker ("commit
status not successful").

## Diagnosis (evaluator reproduced locally with CI's exact arguments)

`python3 scripts/check-gates-ran.py --check-runs <captured> --require-complete
--base-branch develop --event-name pull_request --changed-files <envelope>` →
exit 2, one absent row: **"Mutation gate (changed critical lines)"** (71/72
present). Cause: the PR's changed paths (`REPAIR-NOTES-2345-*.md`,
`requirements-dev-tools.txt`) match none of `mutation.yml`'s
`pull_request.paths` triggers, so the workflow never ran on this PR and its
required check-run can never appear — the same permanent-pending failure mode
previously measured and fixed for `quality/image-pins.json` (#2120) and for
`quality/ratchet-authorizations.json` + `docs/testing/inventory-notes/**`
(#2371). Every producer had completed, so no later publisher run could ever
flip the verdict.

## Fix (evidence plumbing, not gate weakening — the job still fails closed)

- `.github/workflows/mutation.yml`: added `'requirements-dev-tools.txt'` and
  `'REPAIR-NOTES-*.md'` to the `pull_request.paths` triggers (documented
  in-file, same style as the #2120/#2371 precedents). This PR's own diff now
  matches the filter (both the new paths and the edited workflow itself), so
  the mutation gate executes and publishes real zero-overlap evidence
  instead of being permanently absent. Root `REPAIR-NOTES-*.md` is a
  recurring campaign evidence class (#1450/#1837/#2267/#2345/#2375/#2406).
- `tests/test_mutation_targets.py`: `TestEvidenceOnlyPrSurfacesStillTrigger`
  (+4 node IDs; both trigger assertions shown failing against the pre-fix
  workflow from `origin/develop`) pins the surfaces, the prior pins, and a
  `README.md` negative control.
- `docs/testing/inventory-notes/cr2345-mutation-trigger-evidence-surfaces.md`:
  `inventory-delta: tests/: +4`.

## Validation evidence (this round, all local)

- CI-exact evaluator, pre-fix captured snapshot: exit 2 — only the mutation
  gate absent. Post-fix synthetic snapshot (same capture + a completed
  mutation run): `ok: all 74 required check(s) ran on this head`, exit 0 —
  the absent mutation run was the only gap.
- Mutation job steps replayed for this PR's diff:
  `git diff --name-only origin/develop...HEAD -- packages --diff-filter=ACMR`
  → empty; `mutation_critical.py --changed-from` → "no mutation-critical
  files in the changed set", exit 0; `mutation_critical.py --validate` →
  exit 0. The job publishes zero-overlap evidence, not failure.
- `uv run pytest tests/test_mutation_targets.py tests/test_check_gates_ran.py
  tests/test_gates_ran_publisher_contract.py -q` — 127 passed.
- `uv run ruff check .` / `uv run ruff format --check .` — clean (3605 files).
- `uv run python scripts/check-suite-inventory.py --suite tests/` — ok,
  6130 node IDs match baseline + recorded delta.
- `uv run python scripts/check-required-checks.py` — ok: 79 PR checks match
  `docs/ci/REQUIRED-CHECKS.md`; queue SQUASH; merge_group coverage intact.
- `uv run python scripts/check-workflow-inventory.py` — clean (33 workflows;
  triggers recorded as event names only, unaffected by a `paths:` filter).
- PR intent unchanged: `grep -E '^dlint' requirements-dev-tools.txt` →
  `dlint>=0.17.0`; three-dot diff vs `origin/develop` is still exactly the
  repair note + the dlint hunk + this round's workflow/test/note edits.

## Result

The `gates-ran` pending verdict is repairable: once this commit is on the PR
head, the mutation workflow triggers, its check-run appears, and the
publisher can flip `gates-ran` to success. Not pushed (campaign prohibition:
no GitHub mutations from worker).
