---
inventory-delta:
  packages/maistro-core/tests: 0
---

# auto-966 — sync to origin/develop 82097f6b7 and revalidate the #966 lane

Salvage round at exact starting head `f710627537e5` (develop base at capture
`82097f6b7acc`). Three things happened, in this order:

## 1. The prior session's uncommitted work was validated and committed

The worktree carried four modified files (rubric snapshot provenance, pack-id
publisher-grammar widening, CHANGELOG, contract tests). They were reviewed
against HEAD, the two new/extended tests were proven failing against the
parent commit's exact grammar and model, one `ruff format` nit from the prior
session's final write was applied, and the work was committed as `5f1f5a743`
with its own note (`966-rubric-pack-snapshot-provenance.md`, +1 node ID).

## 2. The develop sync was completed

`origin/develop` had advanced 9 commits past the previously merged
`e46ad6708`, tip `82097f6b7acc`. Merged cleanly as `fe70a74cb` — **zero
conflicts** (the earlier rounds' sync-conflict block is resolved; branch is
0 behind, 36 ahead). Post-merge ledger hygiene: `git diff --numstat
origin/develop -- quality/` shows exactly two rows, both additive and
intentional — `quality/ac-state-notes/auto-966.json` (this lane's AC note)
and `quality/workflow-inventory.json` (+7). No `quality/*.json` ledger lost
rows in the merge.

## 3. Worktree-local artifact: ignored `quality/ac-state.json`

The first root-suite run failed
`tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
with `unclassified quality state: quality/ac-state.json`. Root cause is not
the branch: `quality/ac-state.json` is **gitignored** (`.gitignore:81`) and
untracked — develop deleted the file in `db442b5d1` (folded into per-branch
notes), but this long-lived worktree still held the physical leftover, which
`discover_quality_json` finds and CI checkouts never see (the same root suite
is green in the f71062753 coverage-gate job, run 37850172848). The file was
**preserved, not deleted**: moved out of the repo to the job directory
(`salvage-backups/ac-state.moved-from-worktree.json`) — after which the test
passes and the tree is clean.

Two other root-suite failures are environmental, byte-identical on
`origin/develop`, and untouched by this lane:
`test_cli_certification.py::test_certify_refuses_a_malformed_signing_key` and
`test_cli_compat.py::test_compat_preflight_rejects_unreadable_input` assert
prose substrings (`not a hex Ed25519 private key`, `not valid JSON`) that the
CLI's 80-column wrapper splits across lines when the pytest tmp path length
shifts the wrap point — `test_compat_preflight` passes with `--basetemp=/tmp/pt`,
proving the geometry dependence. Develop tip's CI is green on identical bytes.

## Revalidation battery (all at fe70a74cb)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass (3199 files).
- `uv run pytest packages/maistro-core/tests` under the CI coverage producer
  env — 14867 passed, 1030 skipped, 2 failed (the environmental CLI wrap tests
  above; both files byte-identical to origin/develop).
- Root producer `pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py` — 4974 passed,
  1 failed (the ac-state.json artifact, resolved above).
- Suite inventory (`check-suite-inventory.py --suite
  packages/maistro-core/tests`) — ok, notes reconcile.
- Radon ratchet (the step the 8ffd06274 quality-gate run failed):
  `check-radon-baseline.py` — 137/137 blocks, 0 new, 0 regressed, base
  `82097f6b7acc`.
- Diff-coverage gate (the step the same run failed):
  `check-diff-coverage.py coverage.xml --base origin/develop` — ok, every
  measured changed file ≥ 90% lines / 80% branch arcs (packs.py was 76.7%
  there; the c790b4d64 repair plus this round's tested change hold the floor).
- Vulture ledger gate, CI-exact args — 1326 → 1326, no new identities.
- `uv run mypy packages/maistro-core/src` — clean (772 files).
- `check-doc-links.py` — pass.

No suite-count delta from this round itself; the merge's new suites arrived
with their own notes (885, 887, 929, 942, 966-family, 1077, …).
