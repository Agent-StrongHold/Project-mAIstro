# Repair #859 — develop sync (fe733ae4) + container-gate timeout evidence (branch auto-859, head 0c8b5bfa → merge 275e01735)

Starting head `0c8b5bfa5f70ad6fc977de3be0baf4a30b23c23b` (worktree clean). The board's
open items this round: the cancelled `security.yml` / `containers` job ("Container scan +
SBOM + cosign", run job 120286436113) and the PR sitting behind `origin/develop`.

## 1. The container job was cancelled, not red: a 30-minute runner timeout

The check-run data for `0c8b5bfa` shows `Container scan + SBOM + cosign` ran
2026-10-23T07:00:22Z → 07:30:54Z (30m32s) against `timeout-minutes: 30`, concluding
`cancelled` with "The operation was canceled." The PR's last push was 07:00:13Z and no
newer push exists, so the workflow's `concurrency.cancel-in-progress` cannot be the
canceller — the job hit its own 30-minute cap. The job builds five images (each with a
cold `--no-cache-filter` apt stage), runs four Trivy + four Grype scans, two SBOM/license
legs and the new (#348) four-way lock reconciliation; a cold-cache runner can overrun
30 minutes. No scanner finding is recorded anywhere in the cancellation.

## 2. Every locally executable leg of that job passes on the merged tree

Executed on the merged tree (`275e01735`), trivy 0.73.0 (the action's pinned version),
fresh DB 2026-10-23 (the CI run's day), `DOCKER_HOST` mirrored-socket Docker:

- Builds (CI's exact flags): `maistro-engine:pr-2209`, `hive-conductor:pr-2209`
  (`VITE_POC_MODE=pm --build-arg VITE_BASE_PATH=/pm/`),
  `hive-conductor-observability:pr-2209` (`INSTALL_OBSERVABILITY=1`),
  `maistro-engine-research:pr-2209` (`--no-cache-filter production-apt`),
  `maistro-rsi-runner:pr-2209` — all exit 0, apt stage re-ran.
- Trivy `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml` on all four scanned images: rc=0, zero HIGH/CRITICAL. The earlier
  real finding (CVE-2026-111943) stays fixed by the `golang:1.27.3-alpine` toolchain
  refresh already on the branch.
- Grype `--fail-on high --only-fixed` on all four: rc=0 (worst findings Medium).
- In-image identity contracts (ordinary + observability, CI's exact python -c):
  `identity=operational python=3.13.16 bip-utils=2.12.2 coincurve=21.0.0 pynacl=1.6.2`,
  observability imports pass.
- `scripts/check-image-lock-reconciliation.py` with CI's exact export + `--member` args
  for engine/hive/research/rsi-runner: all four "ships exactly the locked set"
  (128/72/148/220 distributions).
- Not locally reproduced: the frontend `npm ci` + syft SBOM + license-inventory leg (no
  frontend/npm changes exist anywhere in the branch's unique diff vs develop; the leg's
  inputs are byte-identical to develop's) and the artifact upload (CI-only).

## 3. Develop sync: `fe733ae4` merged clean, ledgers verified

`git merge origin/develop` (fe733ae4, "Build production images from the resolved
lockfile (#2243)") produced no textual conflicts → merge commit `275e01735`. Per the
quality-ledger rule, `git diff --numstat origin/develop -- quality/` shows only
`quality/ac-state-notes/auto-859.json` (+17, our branch's own rows); `git diff HEAD^2
HEAD -- quality/image-pins.json` is empty (merged file equals develop's, no row loss on
either side).

## 4. The post-merge `check-ac-state` red was a local-environment artifact — gate green under CI parity

After the sync, `check-ac-state.py --run-tests --ratchet` failed locally with
`design_coverage: 39.641 falls below the floor of 44.2377`. Root cause (from the
workflow, not guessed): CI's `quality-acceptance` job runs against a `pgvector/pg18`
service with `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set, `uv sync --locked --all-extras`,
maistro-evolve, age/age-keygen and pytest-timeout installed. Without the postgres
service the DB-backed `@pytest.mark.ac` tests fail, their criteria measure not-passing,
and the measured coverage sinks to 39.641. Reproducing CI's environment exactly (pg18
container, same DSN env, `uv pip install -e packages/maistro-evolve pytest-timeout`,
`alembic upgrade head`, all extras) the same command returns rc=0: measured coverage
44.2377 over the same 166 taken decisions, floors authorized (the `#166` grant at
39.641 leaves margin). The 44.2377 floor was identical at both the old base (2ac960614)
and the new one (fe733ae4), and CI's acceptance-state job passed at `0c8b5bfa` against
that same floor — consistent with the DB-artifact explanation, and there is no
docs/adr or docs/specs delta anywhere in the merge.

## 5. Issue-acceptance re-verification on the merged tree (independent, not inherited)

- `packages/maistro-turing/backend/tests` + `packages/maistro-turing/tests`: 350 passed.
- Scope-isolation suite (23 tests) collected and passing: two-user HTTP isolation,
  guessed-session-id collapse, scope-less refusal, write-seam boundaries,
  restart/replica semantics, deterministic uuid5 workspace resolution.
- Mutation sensitivity re-proven at this head: collapsing `scope_for` to a constant
  makes `test_two_users_have_isolated_self_model_snapshots` and
  `test_admin_facet_patch_cannot_reach_another_users_scope` FAIL; neutralizing
  `clamp_weight` makes `test_store_episode_clamps_out_of_range_weight_at_the_write_seam`
  and `test_ac_2_3_clamp_weight_respects_bounds` FAIL. Both mutations reverted
  byte-exact (git diff empty).
- Gates with CI's exact arguments: ruff check/format clean; mypy 10-package CI list
  (1096 files) clean; vulture `packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` 1309=1309; full-repo `check-suite-inventory.py` 21 suites ok;
  `tests/test_image_lock_contract.py`, `tests/test_check_image_lock_reconciliation.py`,
  `tests/test_backup_restore_oracle.py` 78 passed.

## 6. Not done / residual risk

- The containers job's 30-minute cap is CI infrastructure; nothing in this branch's
  unique diff (turing state scoping, restore-oracle drill, docs) touches image content,
  and every locally executable scan/reconciliation leg is green. Whether the next CI run
  fits 30 minutes depends on runner cache warmth, not on branch content.
- No tests added or removed this round → no suite-inventory delta note required; the
  full-repo inventory passes as recorded.
