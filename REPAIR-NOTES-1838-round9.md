# REPAIR-NOTES-1838 round 9 — develop sync conflict resolution + CI-gate re-validation

Lane L1838, branch `auto-1838`. Starting head `475f4256256fb7c0ada60dfea1a5de2ebce29f09`
(round 8), develop base `f956a814275cbc22185c8f622074de71350b7289`.

## State found

The worktree held an **in-progress merge of `origin/develop` (`f956a8142`)** with
one unmerged path: `scripts/check-image-lock-reconciliation.py` (conflict
markers at lines 79–98, 100–109, 115–134, 139–164, 255–274). The driver's
`check-2.log` failed on exactly that (`Failed to parse
scripts/check-image-lock-reconciliation.py:100:1: Expected a statement` — ruff
cannot parse conflict markers), so every tree-dependent gate was unrunnable.

## Why the conflict existed: the same fix landed twice

Since merge-base `4de7e906d`, exactly one commit on each side touched each of
the two conflicted files, and both implement the **same defect fix**
independently:

| | auto-1838 round 8 (`475f42562`) | origin/develop (`f956a8142`, PR #2285 / issue #1182) |
|---|---|---|
| `parse_expected` | keeps conditional pins grouped **by name** (`dict[str, set[str]]`) | keeps **every version of every name** (`by_name` dict, returns flat sets) |
| split-name reconcile | shipped pin accepted against any locked alternative | same |
| mismatch report | `!= a or b` | `!= one of a, b` (`_expected_clause` helper) |
| extra coverage | — | `test_split_resolution_leaves_single_pin_skews_and_requirements_alone` (single-pin format pinned) |

The defect: the fastmcp re-lock split `beartype` across interpreter markers
(`0.22.9 ; python_full_version < '3.15'`, `0.23.1 ; >= '3.15'`); the old
name-keyed parser let the last export line win, so a correct py3.13 image
shipping `0.22.9` red-exited the `Container scan + SBOM + cosign` job's
"Reconcile installed packages to uv.lock" step (CI run `40097563262`, job
`120882902208`) — the named gate failure this lane is repairing.

## Resolution (merge commit `e504776f7`)

- `scripts/check-image-lock-reconciliation.py` and
  `tests/test_check_image_lock_reconciliation.py` — **took `origin/develop`'s
  versions verbatim** (upstream canonical; behavior equivalent; the PR diff vs
  develop on these files shrinks to zero). The round-8 implementation remains
  reviewable at `475f42562` — nothing discarded.
- `docs/testing/inventory-notes/1838-image-lock-reconciliation-beartype-split.md`
  — delta `tests/: +3` → `tests/: +0`, with the supersession recorded
  round-test-by-round-test: the round-8 tests are the same three regressions
  as develop's five (`1182-image-lock-split-resolution.md`, `tests/: +5`),
  and keeping both would double-count one regression in the suite inventory.
- No other path conflicted; `uv.lock`, the maistro-core/server develop
  changes, and develop's notes/ac-state files auto-merged.

## Validation at the merged head (all executed this round)

- `uv lock --check` → `Resolved 469 packages`; `uv sync --locked --extra dev` ok.
- `uv run pytest tests/test_check_image_lock_reconciliation.py -q` → **32 passed**.
- **Fail-before** (structural): pre-fix parser (`fe733ae4e`) copied to an
  isolated tree with the merged test file → **4 failed, 28 passed**; the 4
  failures are exactly the split-regression guards
  (`test_parse_expected_keeps_every_version_of_a_split_resolution`,
  `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved[0.22.9|0.23.1]`,
  `test_split_resolution_still_fails_on_a_version_neither_branch_pins`).
- **Real-image reconcile, CI-exact argv** (security.yml rsi leg) with the
  merged tree's script and `uv export --locked --extra rsi-fitness
  --no-emit-workspace` (byte-identical to the pre-merge export apart from the
  comment header — the sync did not move the rsi dep set):
  `uv run python scripts/check-image-lock-reconciliation.py --image
  maistro-rsi-runner:pr-2269-r7 --python /workspace/.venv/bin/python
  --expected-file … --member maistro-workspace==0.9.0 …` → **exit 0**,
  `ships exactly the locked set (220 distributions …; 14 marker-conditional
  pin(s) evaluated leniently)`. The export carries both beartype lines, so
  the split path is exercised for real.
- `uv run ruff check .` → clean; `uv run ruff format --check .` → clean.
- `uv run python scripts/check-merge-markers.py` → `ok: no conflict markers`.
- `uv run python scripts/check-suite-inventory.py` (CI-exact, ci.yml:719, no
  args) → `ok: 21 suite(s) match the recorded inventory` (with the +0 note).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact) → **exit 0**,
  `1302 reviewed identities -> 1302 findings` — no ledger amendment owed
  (`scripts/` is outside the `packages/*/src` scan).
- `git diff --numstat origin/develop -- quality/` → empty (all ledgers
  byte-identical to develop; no rows lost in the merge).
- `git diff --check` → clean.
- Full CI top-level suite: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  tests/ -q --timeout=60` → **5736 passed, 143 skipped** (6m04s).
- Merge-brought package tests:
  `uv run pytest packages/maistro-core/tests/runs/test_run_concurrency_limits.py
  packages/maistro-server/tests/api/test_resource_policy_health.py -q` →
  **71 passed, 19 skipped**.
- Canonical mypy (AGENTS.md full target list, 7 package src trees) →
  `Success: no issues found in 937 source files`. (A subset run without
  `packages/maistro-canvas/src` reports one import-untyped note for
  `maistro_canvas.canvas.store` — an artifact of the partial path list, not a
  defect; the canonical command includes canvas sources.)
- Issue hygiene command: `uv run python scripts/check-adr-status-language.py`
  → `ok: 0 baselined body-status contradiction(s)`.

## Acceptance framing

Issue #1838 is a **decision gate** ("Select Biscuit verification adapter"):
its deterministic acceptance requires the named ADR owner's explicit review
(`@BlakeMatthews-dev`) of the adapter contract and vectors — the issue text
itself states a hygiene command "cannot resolve the decision". This lane's
contract is the CI-gate repair + develop sync; the owner-acceptance decision
remains open and is not claimed here.

## Residual risks

- The engine / hive-conductor / research reconcile legs were not re-run
  against locally built images (no locally built image matches the merged
  lock for them). The parser fix is name-generic, the rsi leg is proven on
  the real round-7 image with the identical export, and develop's
  `1182-image-lock-split-resolution.md` carries real-gate/real-Docker
  fail-before/pass-after evidence for the engine leg.
- Trivy/SBOM/cosign legs run against CI's fresh image builds of the merge
  commit; a scanner catch-up advisory (the round-7 mirror-race class) is
  inherent to the gate design and not addressable from this tree.
