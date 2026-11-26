# #2413 develop sync (a3efc93) supersession resolution and gate revalidation

inventory-delta:
  suites_added: 0
  suites_removed: 0
  tests_added: 0
  tests_removed: 0
  notes: >
    No suite-count delta: this round added no test, removed no test and skipped
    no test. The round merged origin/develop (a3efc93c92) into the branch,
    which brought develop's own tests (root suite 5952 passed / 139 skipped,
    hive-conductor backend 4245 passed / 29 skipped under CI's exact
    invocations) into the branch tree; `scripts/check-suite-inventory.py`
    passes on the merged tree (21 suites match). Post-resolution the merged
    tree is byte-identical to origin/develop (`git diff origin/develop HEAD`
    empty), so every measured count equals develop's own.

## What this round did

The branch arrived at `03fa414cef` while the PR head had already moved to
`776d523d18` (a strict descendant: the develop catch-up merge `b8de969d67` of
2026-11-20 02:02:46 at develop `d521240c6b`, plus an empty retrigger commit).
This round fast-forwarded the worktree to `776d523d18`, diagnosed the CI red
at that head, merged origin/develop, and committed the resolution.

1. **CI red diagnosis at `776d523d18`** (dispatch check-runs, run set
   44667108263, 2026-11-20 03:20–03:54): 64 check-runs cancelled, 14
   succeeded (the fast SAST/CodeQL/security suites), and exactly one real
   failure — the aggregator `Quality gate (Pillars 1–4, 7, 8)`, which runs
   `scripts/check_ci_job_results.py` over 36 child jobs with `if: always()`.
   It failed in 9 s because its child jobs were **cancelled** by a run-wide
   cancel cascade (23 min after start), not because any child gate failed.
   No child quality job carries a `failure` conclusion at this head. The
   prior genuine failures (Quality / Image pins, vulture ledger) had already
   been repaired on-branch by `154f8f5c1d` + `126328ccf9` (consolidated
   fa3d596 row, retired b8c9b82 row).

2. **Develop sync conflict proven**: `git merge-tree --write-tree HEAD
   origin/develop` exits 1 with content conflicts in exactly the two files
   this PR touches — `packages/hive-conductor/Dockerfile` and
   `quality/image-pins.json`. The branch's last develop catch-up
   (`b8de969d67`, 02:02:46) pre-dates `cca1afb4ba` (#2375, 02:03:02) by 16
   seconds; #2375 re-pinned golang to `1.27.4-alpine@sha256:70bd7dde…` in all
   three builder Dockerfiles and retired **both** 1.27.3 indexes (b8c9b82 and
   this PR's fa3d596) because the Container scan flagged age-keygen's go1.27.3
   stdlib (CVE-2026-97054 HIGH; security.yml run 44477475371, job 135401410021).

3. **Resolution**: `git merge origin/develop` committed as `044cede564` with
   both conflicts resolved to develop's side. This PR's fa3d596 pin is the
   exact index #2375 retired; keeping it would regress a security fix, so the
   branch-side Dockerfile pin and its consolidated ledger row are dropped.
   After resolution no Dockerfile references fa3d596 or b8c9b82 (the only
   remaining mentions are prose provenance inside develop's own 1.27.4 row
   note and historical notes files). The merged tree is byte-identical to
   origin/develop.

## Gate revalidation at the merge head `044cede564` (all exit 0)

CI-exact invocations read from `.github/workflows/{quality,ci,release}.yml`:

- ruff: `check .` clean; `format --check .` 3598 files clean.
- Image pins: `check-image-pins.py` (11 pins / 11 Dockerfiles, all
  registered), `check-image-inventory.py`, and the release consumer
  `check-image-pins.py --base-digests Dockerfile
  packages/hive-conductor/Dockerfile`.
- Vulture ledger: `check-vulture-baseline.py packages/*/src --min-confidence
  60 --exclude '*/third_party/*'` → 1229 reviewed == 1229 findings, 0
  unclassified (develop's ledger; no Python touched by this round).
- Ratchets: `check-ratchet-provenance.py` (RATCHET_BASE_REV=origin/develop;
  0 lifecycle violations, 55 consumers have provenance),
  `check-shipped-surface-truth.py`, `check-promotion-surface.py`.
- Per-identity ledgers: radon 126 == 126; xenon blocks 126 == XENON_BASELINE
  126 (modules/averages clean); reachability 83 unreachable all disposed;
  dispositions 28 groups OK; wiring, agent-store writes, route permissions
  (42 declared), principal identity, frontend typed client, security
  inventory, workflow inventory (33 workflows), convergence (52 subsystems
  over 1494 modules), execution lifecycles (19 vocabularies), model egress +
  design model egress + foreign-harness egress, credential authority,
  contract markers, enumerations, retirement (89 entries), doc links,
  version (42 sites agree on 0.9.0), release consistency, backlog
  consistency (167 items) — all rc=0.
- Docstring floors: all 12 CI interrogate floors pass (`-f 63 …/projects`,
  `-f 38 graph/nodes`, `-f 45 graph/durable_runs`, `-f 46 maistro`,
  `-f 64 rsi`, `-f 59 server`, `-f 51 design`, `-f 38 evolve`,
  `-f 50 registry`, `-f 45 bootstrap`, `-f 36 canvas`, `-f 24 turing`,
  `-f 73 ext-sdk`).
- mypy: `mypy --strict packages/maistro-core/src` — no issues in 844 files.
- Tests: root `tests/` under CI's env (`REQUIRE_AUTH=false
  MAISTRO_DY_RUN=1`, `--timeout=60`; run alone rather than in CI's
  single-process combination with the conductor/design suites)
  `5952 passed, 139 skipped`; hive-conductor backend `4245 passed,
  29 skipped`; `tests/test_check_image_pins.py` +
  `tests/test_pinned_digest_references.py` `49 passed`; image
  lock/inventory/prepull suites `189 passed`;
  `packages/maistro-core/tests/fitness` `39 passed`.

## Coverage gate disposition

`Coverage gate (publish-set floor + diff coverage)` was never run to
completion at any head of this branch (infra cancel cascade:
`could not pull python:3.12-slim after 3 attempts`, then run-wide
cancellation). It is not re-run end-to-end here. Disposition instead:

- Diff coverage: post-merge, origin/develop is an ancestor of HEAD, so the
  CI diff is empty and `check-diff-coverage.py` has zero changed files to
  evaluate — trivially satisfied.
- Publish-set floor: the merged tree is byte-identical to origin/develop, so
  the five producers measure develop's exact tree and the floor outcome is
  develop's own CI outcome. An earlier round additionally measured all five
  producers and a 93% aggregate against the 87% floor at a tree whose only
  difference from develop was the two now-superseded non-Python files; that
  round's claim was not re-executed here and is not relied upon.

## Residual risks

- The cancel cascade itself is operational (runner-side), not in-tree; a
  clean CI re-run on the new merge head is required to convert the cancelled
  checks to green. This worktree cannot trigger CI.
- The PR's original content (bump golang b8c9b82→fa3d596) is fully
  superseded by develop's #2375 (golang 1.27.4). The branch can now only
  merge as a no-op sync; close-as-superseded vs merge-as-sync is an
  integration decision outside this lane's authority.
- Not run locally: `quality-pyright` (node toolchain download),
  `quality-acceptance`/`quality-hypothesis` (need alembic/Postgres),
  proof-envelope/model-proof blocks — all measured on develop's identical
  tree by develop's own CI.
