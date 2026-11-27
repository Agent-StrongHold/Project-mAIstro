---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — repair round at 839ab09f4d (independent re-proof + cross-lane contract finding)

Repair-round verification record for issue #89 (M3-A7, parent epic #19) at the
assigned head `839ab09f4da4fce5b9f97c086c166866e8bee6b6` (branch `auto-89`,
worktree clean, base `3be6b6650caaf5e59c1b15ad3096a2631865f6b9`). The job
manifest carried `checks: []` and the job directory contained no `check-*.log`
files, so every check below was executed by this round at the exact head.
Prior rounds' claims were not assumed true; the battery, gates, sync state,
and two mutation probes were re-executed here.

## Battery (all executed at 839ab09f4d)

- `uv run ruff check .` — exit 0 ("All checks passed!").
- `uv run ruff format --check .` — exit 0 (3682 files already formatted).
- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **163 passed** (1.84 s).
- `uv run pytest tests/test_check_required_checks.py
  tests/test_mutation_targets.py -q` — **123 passed** (3.22 s).
- `uv run pytest tests/release -q` — **308 passed** (32.96 s).
- `uv run python scripts/check-release-consistency.py` — exit 0 ("released
  none, shipping 0.9.0, working toward 1.0.0").
- `uv run python scripts/check-image-inventory.py` — exit 0.
- `uv run python scripts/check-image-pins.py` — exit 0 (11 pins registered).
- `uv run python scripts/check-suite-inventory.py` — exit 0 (21 suites match).
- `uv run python scripts/check-doc-links.py` — exit 0.
- `uv run python scripts/check-workflow-inventory.py` — exit 0 (33
  workflows dispositioned).
- `uv run python scripts/check-workflow-write-safety.py` — exit 0.
- Ledger integrity: `git diff --numstat <base>..HEAD -- quality/` empty; and
  a fresh `git fetch origin develop` confirms `origin/develop` is still
  `3be6b6650c` — an ancestor of HEAD, so no sync merge is owed.

## Mutation probes (save-mutate-restore at this head, reverted via exact
edit reversal; `git status`/`git diff` clean after each)

1. Removed `"multi_replica_soak",` from `REQUIRED_SOAK_CHECKS`
   (`scripts/promote_release.py:139-145`) →
   `test_required_soak_checks_are_pinned_not_adaptive` **FAILED**; the
   adaptive per-check test alone stayed green, confirming the pin test is
   load-bearing. Restored byte-exact.
2. Removed `images` from the pypi job's `needs`
   (`.github/workflows/release.yml`, pypi job) →
   `test_pypi_waits_for_the_soak_gate_before_irreversible_publication`
   **FAILED**. Restored byte-exact.

## New evidence this round: cross-lane soak-evidence schema seam

From the frozen PR #1672 capture (`scripts/soak/run_soak.py` patch): the
#860 harness writes `m3a-soak-evidence.json`
(`thresholds.checks.<name>.ok` booleans; checks named
`exact_rc_artifact`, `sustain_duration`, …). Its patch contains **zero**
occurrences of this gate's contract vocabulary (`artifact_binding`,
`multi_replica_soak`, `clean_install`, `security_hot_path`,
`backup_restore`, `real_model`, `wheels_sha256`, `image_digests`,
`config_digest`, `routed_issue`, `promote_release`). Consequence: even once
#860's own gates go green, the soak lane must still publish an Actions
artifact named exactly `soak-evidence` on the RC release run in this lane's
schema-1 shape before any final promotion can pass `adopt-digests`. Until
then the promotion gate fails closed — correct posture, but the
requirement is now recorded explicitly instead of being discovered at
release time: `scripts/promote_release.py` module docstring gained a
"Cross-lane contract (#860 / PR #1672)" paragraph this round (doc-only
change; no behavior or gate weakening).

## Acceptance disposition

In-lane engineering surface (candidate evidence record, byte-verified wheel
adoption, soak-bound digest adoption, routed-findings gate, PyPI gated
behind the soak gate, finals-only evidence attachment, evidence shipped as
release assets): complete, tested, mutation-proven, gate-clean at this head.
Promotion-scale criteria (cutting an actual RC, the sustained exact-RC
multi-replica soak via unmerged child lane #860 / PR #1672 — itself still
red on `sustain_duration` and `exact_rc_artifact` per
`verify-89-m3a7-c5e070d9.md` —, the final promotion, external
PyPI/GHCR/cosign/install verification) require release operations and the
child lane, both outside lane authority; `git tag -l 'v*'` remains empty.
They stay UNVERIFIED at issue level and program-owned.
