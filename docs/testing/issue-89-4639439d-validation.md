# Issue #89 validation round at assigned head `4639439d00`

Job `4d7bd718b7fa44e59bf506cb6c534961` (repair phase, branch `auto-89`, base
`618954f052` == `origin/develop`). Frozen scope: issue #89's named CI gates
only — the one remotely RED check (`Coverage gate (publish-set floor + diff
coverage)`, PR #2536 head `5f6bff7d458f`), the dispatched-but-unconfirmed
`Validate ADR/spec front-matter` state, and the `exact-debt-ledger` repair
brief. Worktree entered clean at the exact starting head (`git status` empty);
no driver `check-*.log` files were supplied in this job's directory (third
round in a row), so every log cited here is a fresh worker execution under
`/home/dev/maistro/jobs/4d7bd718b7fa44e59bf506cb6c534961/`.

## Fresh execution this round (all exit 0)

- **Coverage gate, diff half** (`check-release-producer-local.log`,
  `check-release-diffcoverage-local.log`, `check-release-perfile-local.log`):
  CI's exact `scripts` producer — `coverage run --branch --source=scripts -m
  pytest tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q` — **6589 passed, 140 skipped, exit 0** (16m35s). Then
  `coverage xml` + `scripts/check-diff-coverage.py --base
  618954f0528090144683c308a18e19c6068d63f1`: **ok** — 2 changed measured
  production files (`scripts/promote_release.py`, `scripts/release_guard.py`)
  at/above the 90% lines / 80% branch floors; 3 test files exempt by
  declaration. Per-file: promote_release.py 327 stmts / 0 missed / 99%
  (3 partial arcs); release_guard.py 94%. This is the exact check that is RED
  on the pushed PR head; it passes at this head because repair `87ce1ab3de`
  ("cover the fail-closed promotion seams the diff-coverage gate named") is
  an ancestor of this head and a **non**-ancestor of `5f6bff7d458f`
  (`git merge-base --is-ancestor` both directions verified this round).
  The combined hosted publish-set floor (87%) still needs CI's six producers
  and stays UNVERIFIED locally, as every prior round recorded — but it was
  not the failing half: the captured run failed on per-file diff coverage.
- **Front-matter gate, all 7 `registry.yml` steps**
  (`check-registry-part1-local.log`, `check-registry-part2-local.log`):
  registry/lifecycle unit tests **194 passed**; lifecycle lint baseline 0;
  `maistro_registry.cli lint . --strict` **447 files, 0 errors / 0 warnings**
  (199 pre-existing test-evidence debts); citation provenance with
  `RATCHET_BASE_REV=origin/develop` 0 exceptions; ADR-INDEX consistent;
  AC-Defined index regenerated with `git diff --exit-code docs/specs/README.md`
  clean; body-status language 0 contradictions. The dispatch's `queued` state
  for this check corresponds to no failure: the captured check-run at
  `5f6bff7d458f` is `completed/success` (dispatch-context.json source 41),
  and all 7 steps re-pass fresh here.
- **exact-debt-ledger / vulture, CI args** (`check-vulture-local.log`):
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — **1217 reviewed identities / 1217 findings**,
  unclassified 0, never_allowlist 0, exit 0. Ledger byte-identical to
  `origin/develop`: `git diff --numstat origin/develop -- quality/
  docs/testing/inventory/` prints nothing. No amendment made; none warranted.
- **Static battery** (`check-static-local.log`): `ruff check .` exit 0;
  `ruff format --check .` **3717 files already formatted**; suite inventory
  **21/21 suites match**, 0 duplicates.
- **Gate-consistency tests** (`check-policy-local.log`):
  `tests/test_check_required_checks.py tests/test_mutation_targets.py
  tests/test_check_diff_coverage.py` — **141 passed**.
- Not re-run this round (supplementary, not a CI gate): the byte-verification
  mutation probe, last re-killed from scratch in round `f168d59c86`; and the
  focused release battery, superseded here by the full producer above.

## Disposition

- **No repair is warranted in the tree.** The only reproduced remote failure
  (Coverage gate at `5f6bff7d458f`) is already repaired in this branch's
  history by `87ce1ab3de`; the branch tip is 38 commits ahead of the pushed
  head. Advancing `origin/auto-89` is a push — prohibited to this worker —
  so the remote re-run is the driver's/integrator's action. No source, test,
  workflow, gate, grant, or ledger change was made this round; the only tree
  change is this note.
- **Operational acceptance stays blocked on owner execution**, re-read from
  source rather than prior notes: `scripts/promote_release.py:40-57` (the
  soak harness must upload an Actions artifact named exactly `soak-evidence`
  on the RC run; the #860 native boolean record does not satisfy the gate and
  adapting would weaken it), `:144` `SOAK_ARTIFACT`, `:150`
  `REQUIRED_SOAK_CHECKS`, `:259` `_validate_binding`, `:333` `validate_soak`,
  `:351` `verify_dist`; `.github/workflows/release.yml:952-953,1005-1006,1033-1034`
  (soak-evidence upload wiring). Hosted RC build, sustained multi-replica
  soak (#860 / PR #1672), finding routing, replacement-soak on change, the
  actual RC/final byte pair, external verification, and evidence binding are
  UNVERIFIED here and reserved to the release/soak owners and the protected,
  tag-triggered pipeline (ADR-073126-c4e1, ADR-095). Local green tests inject
  the download seam; they do not create the producer/transport or run a soak.

Progress: checked 1 issue, done 1 focused validation/handoff round, skipped 0,
unexpected errors 0. No push, tag, merge, or GitHub mutation. Writer handoff
only; not integration approval or issue completion.
