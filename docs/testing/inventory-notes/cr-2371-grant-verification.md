# cr-2371 — grant-only PR verification (#1629 debt authorization)

No test inventory change (no tests added, removed, or modified), so this note
carries no `inventory-delta` front matter — per `docs/testing/inventory-notes/README.md`,
a note without the block records no delta, which is the normal case for a
change that moved no count. (An earlier draft of this note wrote a
nested `added/removed/modified` block instead; `check-suite-inventory.py`
read those keys as suite names and failed the CI `test` job with
"recorded suites with no collection recipe: added, modified, removed" — the
block is therefore removed rather than re-indented.)

This PR is a two-merge ratchet grant only: one entry `@tool/plan_delivery`
under `reachability` in `quality/ratchet-authorizations.json` (+5 lines vs
merge-base), so #1640 can bank the matching baseline/disposition row from a
base that already carries the grant.

## Round 2 evidence (local, CI-exact arguments, head after develop sync)

This round (1) synced `origin/develop` (`fdf545a6175`) into the branch and
(2) fixed the note front matter described above. The sync picks up the
already-landed prune of the superseded `ac-state` grant
`design_coverage@39.641` (removed on develop by #2361/#2363), which is what
makes `Quality / Acceptance state` pass here: `check_ac_state_impl.py`
computes `superseded_by_present` from the candidate tree's own grant file, so
the only run that passes is the one that no longer carries the row.

- Branch diff vs merge-base `origin/develop` (`fdf545a6175`) touches exactly
  two files: `quality/ratchet-authorizations.json` +5 (the one grant, with
  owner/issue/reason) and this note. No product code, no baseline or
  disposition edits.
- Post-merge row audit of `quality/ratchet-authorizations.json`: all 13
  develop `reachability` rows retained + this branch's `@tool/plan_delivery`
  (14 total); `ac-state` is `{}` (develop's prune, not re-added); every other
  section count matches `origin/develop` exactly; `quality/vulture-baseline.json`,
  `quality/reachability-baseline.json`, `quality/reachability-dispositions.json`
  and `docs/testing/inventory/baseline.json` are byte-identical to develop.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
  (the exact-debt-ledger job's invocation, vulture-ratchet.yml) → exit 0;
  resolves base `ba7d378ef7d3` → candidate `21986b8b92e8` pre-sync and
  "no candidate-approved expansion", "55 quality JSON consumer(s) have
  explicit provenance".
- `uv run python scripts/check-reachability.py` (quality.yml Quality /
  Reachability) → exit 0; 88 unreachable of 1489 modules, unchanged from
  develop.
- `uv run python scripts/check-reachability-dispositions.py` (quality.yml
  Quality / Reachability dispositions) → exit 0; 30 groups cover all 88
  unreachable modules (67 CONNECT, 20 LIBRARY, 1 RETIRE).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exact CI args) → exit 0;
  1236 reviewed identities, 1236 findings, unclassified 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
- `uv run python scripts/check-compliance.py` → exit 0.
- `uv run pytest tests/test_ratchet_provenance.py
  tests/test_check_ratchet_provenance.py tests/test_reachability_baseline_identity.py
  tests/test_check_reachability.py tests/test_check_reachability_dispositions.py`
  → 133 passed.
- Driver battery at the pre-sync head: `uv sync --locked --extra dev` ok,
  `ruff check .` all passed, `ruff format --check .` all formatted.

## Why the earlier RED CI picture is not a content failure of the grant

On head `272fd3aade` (and its develop-merge `21986b8b92e8`) every check run
was mass-cancelled twice (2026-10-26T11:07:32–39Z and ~11:17–11:18Z); the
`failure` conclusions were aggregate/waiter jobs reporting cancelled
dependencies ("dependency did not succeed", "docker-build … concluded
cancelled"), not scanner findings. On the re-run at `21986b8b92e8` (2026-11-18),
two real content failures appeared — both repaired by this round:

- `test` job → `scripts/check-suite-inventory.py` exit 2: this note's
  malformed `inventory-delta` block (see above). Repaired here; reproduced
  locally with `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-suite-inventory.py` → exit 2 before the fix.
- `Quality / Acceptance state` → `scripts/check-ac-state.py` FAIL
  "authorized floor(s) independent landings have superseded":
  `design_coverage@39.641` was already pruned on develop
  (`ac4a7667ba`, `fdf545a617`), but this branch's develop merge predated the
  prune. Resolved by syncing `origin/develop` (`fdf545a6175`); the candidate
  file no longer carries the superseded row, which is the run the gate
  accepts ("by_present is correctly empty, because there is nothing left in
  the file to report on").
- `Quality gate (Pillars 1–4, 7, 8)` was a waiter on the above
  ("quality-acceptance: dependency did not succeed"), not an independent
  finding.

## Residuals (recorded, not repaired here)

- #1640's current head places the planner at `tools/plan_delivery.py`, while
  `scripts/check-reachability.py` collects tooling from `TOOLING_DIR = "scripts"`
  only — so `@tool/plan_delivery` may never enter the baseline and the grant
  may go unexercised. Unused authorizations are harmless (the provenance gate
  passes with this grant present and unused). The grant reason's reference to
  the LIBRARY disposition describes the state #1640 is expected to bank, not a
  row that exists today.
- "CI green on the new tip" cannot be proven from this lane (push prohibited);
  the content-relevant gates are re-run locally with CI's exact arguments and
  recorded above.
