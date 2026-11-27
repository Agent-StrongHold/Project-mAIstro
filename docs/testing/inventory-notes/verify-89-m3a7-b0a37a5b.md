---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — repair round at b0a37a5b6f (post develop-sync)

Repair-round verification record for issue #89 (M3-A7, parent epic #19) at the
assigned head `b0a37a5b6f6f297f41885244d507f902c88d9508` (branch `auto-89`,
worktree clean, base `3be6b6650caaf5e59c1b15ad3096a2631865f6b9`). The job
manifest carried `checks: []` and the job directory contained no `check-*.log`
files, so every check below was executed by this round at the exact head.
This round changed no code: it re-proved the two repairs already committed by
the implement round (`684e9fa5ea` PyPI-gated-on-images, `232008c900`
finals-only soak-evidence download) plus the develop sync merge (`b0a37a5b6f`)
against the full battery, and re-ran mutation probes at this head.

## Battery (all executed at b0a37a5b6f)

- `uv run ruff check .` — exit 0 ("All checks passed!").
- `uv run ruff format --check .` — exit 0 (3682 files already formatted).
- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **163 passed** (1.94 s).
- `uv run pytest tests/test_check_required_checks.py
  tests/test_mutation_targets.py -q` — **123 passed** (3.00 s): the
  develop-side tests that ride the sync merge also pass with this branch's
  release changes.
- `uv run pytest tests/release -q` — **308 passed** (34.23 s): the new
  develop-side installed-workspace suite is green on this tree.
- `uv run python scripts/check-release-consistency.py` — exit 0 ("released
  none, shipping 0.9.0, working toward 1.0.0").
- `uv run python scripts/check-image-inventory.py` — exit 0 (every Dockerfile
  inventoried, every shipped image names live jobs).
- `uv run python scripts/check-image-pins.py` — exit 0 (11 pins registered).
- `uv run python scripts/check-suite-inventory.py` — exit 0 (21 suites match;
  37229 unique test identities, zero duplicated evidence).
- actionlint 1.7.7 (`/tmp/actionlint -no-color -shellcheck
  /usr/bin/shellcheck .github/workflows/release.yml`) — exit 0, no findings;
  release.yml also YAML-parses with `pypi.needs == [guard, wheels,
  m1-closeout, images]`.
- `uv run mypy scripts/promote_release.py scripts/release_guard.py` reports
  bare-generic `dict` type-args — **not a gate regression**: CI's mypy jobs
  (ci.yml `uv run mypy packages/*/src`, quality.yml `--strict
  packages/maistro-core/src`) do not scan `scripts/`, and pre-existing
  scripts (e.g. `bump_version.py`) carry the same class of findings.
- Ledger integrity after the sync merge: `git diff --numstat origin/develop
  -- quality/` is empty — no `quality/*.json` rows added, lost, or replaced
  relative to `origin/develop` (the vulture scan surface, `packages/*/src`,
  is untouched by this lane).

## Mutation proofs (save-mutate-restore at this head)

1. Removed `"multi_replica_soak",` from `REQUIRED_SOAK_CHECKS`
   (`scripts/promote_release.py`) → `test_required_soak_checks_are_pinned_not_adaptive`
   **FAILED** — the soak-coverage tuple is pinned against silent drift, and
   the adaptive per-check test alone cannot see an element removed from the
   tuple it parametrizes over. Restored byte-exact.
2. Removed `images` from `pypi.needs` (`.github/workflows/release.yml`) →
   `test_pypi_waits_for_the_soak_gate_before_irreversible_publication`
   **FAILED** — the dependency-graph regression test binds to the real
   workflow. Restored byte-exact.
3. Deleted the `final_tree != candidate_tree` rejection block
   (`scripts/release_guard.py verify_rc_tree`) →
   `test_final_cli_rejects_changes_after_the_rc[source|configuration|executable-bit]`
   **FAILED (3)** — the guard CLI tests bind to the real tree comparison.
   Restored byte-exact.

`git status` clean after all three probes; `git diff` empty.

## Sync status

The previous round's block ("PR 1672 head changed during collection") is a
dispatch-capture artifact; this round's `dispatch-context-receipt.json` reports
`complete_for_scope: true`, and the assigned develop base `3be6b6650` is the
merge parent of HEAD (`git show b0a37a5b6f`), so no further sync merge is
needed. `git diff 7926d9ab..3be6b6650` (old→new develop base) does not touch
any of this lane's surfaces, so the merge introduced no conflict or resolution
risk in them. Child soak lane #860 / PR #1672 remains open and unmerged
(frozen snapshot head `c5d4a6b38f77`); it is cross-lane and not touchable
here. `git tag -l 'v*'` remains empty — `release.yml` has never executed.

## Acceptance disposition

Unchanged in kind from the implement round's matrix
(`docs/testing/issue-89-71864dc4-validation.md`): the in-lane engineering
surface — candidate evidence record, byte-verified wheel adoption, soak-bound
digest adoption, routed-findings gate, PyPI gated behind the soak gate,
finals-only evidence attachment, evidence shipped as release assets — is
complete, tested, and gate-clean at this head. The promotion-scale criteria
(cutting an actual RC, the sustained exact-RC multi-replica soak, the final
promotion, external PyPI/GHCR/cosign/install verification) require release
operations and the unmerged child lane — both outside lane authority and
outside what any local run can produce. No code change was warranted this
round; none was made.
