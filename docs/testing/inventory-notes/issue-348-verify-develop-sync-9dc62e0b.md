# issue-348-verify-develop-sync-9dc62e0b

Verification round for #348 in worktree `auto-348` on top of the develop-sync
repair `2c7648ef2`, at the merged tip `9dc62e0b` (which carries the #2223
Conductor CLI page contract on top). The prior repair-phase attempt at this
same tip (job `49c85b989f404230904d45d6949fbf52`) was blocked by an exhausted
provider budget before it could execute any verification, and the two
verify-phase attempts at `2c7648ef2` (`53245f68`, `7d5440033d8c4ea3868ca9d8f4c15416`,
`f2948c4cb6d54416ae4d707572ab4a0b`) failed on provider error at the first LLM
call. This round performs and records the verification they could not.

No pytest tests were added or removed — `tests/` is unchanged this round. The
#348 acceptance surface is already gated by
`tests/test_image_lock_contract.py` (23 parametrized cases) and
`tests/test_dependency_namespaces.py`, both green at this tip. A verification
note with no test delta therefore records none.

## What moved at the merged tip

The #2223 develop merge refreshed `uv.lock` (aiohttp 3.14.3→3.14.5, yarl
1.24.2→1.25.1, plus new transitive pins flowing through maistro-server's
`image`/`browser`/`observability` extras). The package set stayed at 468
resolved packages, but several versions drifted, so the *reconciled*
distribution counts from the prior round's evidence are stale at this tip:

- `issue-348-lock-enforced-images.md` recorded the engine image at **118**
  distributions reconciled to the `2c7648ef2` lock. At `9dc62e0b` the engine
  image reconciles to **127** — the +9 is the new deps #2223's feature
  surfaces pull through the `image` extra. The contract is unchanged
  (image == lock, `--require-hashes`); only the absolute count moved.
- The rsi-runner reconciled count is unchanged at **220** — the `rsi-fitness`
  extra did not gain pins across #2223, so the develop-sync repair's proof
  number is still current.

## Evidence (all executed locally this round, docker 29.1.3)

- `uv lock --check` clean (468 packages) — the committed lock is consistent
  with every workspace member's pyproject.toml after #2223.
- Deterministic driver checks (`uv sync --locked --extra dev`,
  `uv run ruff check .`, `uv run ruff format --check .`): all exit 0
  (mirror of the verifier's check-0/1/2).
- Per-image `uv export --locked ...` (the exact commands the Dockerfiles run)
  succeeds for all four contracts with non-empty `--hash=` sets:
  engine `maistro-server --extra image` (129 pins), research
  `maistro-server --extra observability --extra browser` (315 pins),
  hive-conductor (67 pins), sbx `maistro-workspace -package ... -package`
  (208 pins). A lock/pyproject drift would make `--locked` red here first.
- `maistro-engine:test` built green from `Dockerfile` at `9dc62e0b` (uv
  export `--require-hashes` install + `uv pip check` + builder smoke
  `import maistro_server.main` green → the `image` extra, identity included,
  is installed).
- `check-image-lock-reconciliation.py` against the built engine image:
  `OK: maistro-engine:test ships exactly the locked set (127 distributions,
  incl. 3 workspace member(s))`.
- `check-image-lock-reconciliation.py` against the built
  `maistro-rsi-runner:test` (the image the develop-sync repair targeted):
  `OK: maistro-rsi-runner:test ships exactly the locked set (220 distributions,
  incl. 4 workspace member(s))` — proving the `COPY extensions/` repair holds
  post-#2223: `uv sync --locked --python 3.12 --extra rsi-fitness` resolves the
  whole workspace (reference-gallery packages + reference-greeter) in the
  build context.
- Shipped-image namespace assertion (#406), run on both built images:
  `find_spec('examples') is None` → exit 0; the build-layer prune removed 8
  `examples` RECORD rows (pytoniq-core-fork) + 1 `doc` row (crosshair-tool),
  reported `verified: 2 pruned namespace(s) no longer importable`.
- AC-2 hash enforcement proven both directions at this tip (one-package
  `uv pip install --require-hashes --no-deps` against a `sniffio==1.3.1`
  lock-export block): both hashes corrupted → exit 1
  (`Computed: sha256:2f6da…` ∉ expected); locked hashes intact → exit 0.
  The positive direction is also the green engine/rsi-runner builds above.
- `scripts/check-suite-inventory.py`: 21 suites match (32487 node IDs);
  `tests/` = 5651, matching the corrected baseline after `2c7648ef2`'s +23
  delta.
- `scripts/check-build-context.py`: ok (60 rules, 27 secret patterns, no
  tracked exclusion — `extensions/` is carried into every production context).
- `scripts/check-image-inventory.py`: ok (9 Dockerfiles inventoried).
- pytest `tests/test_image_lock_contract.py tests/test_distribution_contract.py
  tests/test_engine_canvas_packaging.py` with `MAISTRO_ENGINE_IMAGE=maistro-engine:test`:
  6 passed, 1 skipped (the skip is the opt-in full `pg18`+pgvector boot smoke
  behind `MAISTRO_ENGINE_IMAGE_SMOKE`); the skipped tests are `maistro-engine`
  image-dependent and were active here. The artifact-level #1825 proof — the
  built image alone imports `maistro_canvas.canvas.store.PgCanvasStore` with
  no network/mounts/PYTHONPATH, and the Canvas-less control fails the probe —
  passes against `maistro-engine:test`.

## Residual

`Dockerfile.research`, `packages/hive-conductor/Dockerfile`, and
`deploy/sbx/template/Dockerfile(.tests)` were not rebuilt at this tip. Their
#348 mechanism is identical to the engine/rsi-runner images proved above
(same `uv export --locked ... --require-hashes` + `--no-deps` member install +
`uv pip check`), their `uv export --locked` commands succeed with hashes, and
`tests/test_image_lock_contract.py` gated every shared defect (bare pip
install, missing `--locked`, missing `--package`/`--extra`, missing
extension copy) on all of them. A lock refresh that only changed versions —
as #2223's did — cannot reintroduce a build-time resolution without also
changing a Dockerfile's export command, which no --2223 diff touched; the
regression classes the tests name are unchanged here.

## Round 2 (this round) — driver-checks-independent verification + CI-contract repair

The driver's deterministic check-*.log files were absent from the job
directory, so every check below was executed locally at `9dc62e0b8`.

### Repair: `docker-rebuild-compare` was not registered in the merge contract

The branch's own commit `afc450f51` added the `docker-rebuild-compare` job
(AC-5's implementation) but never registered it, and both workflow-shape gates
failed at this tip:

- `scripts/check-required-checks.py` → exit 1
  ("docs/ci/REQUIRED-CHECKS.md does not match .github/workflows/")
- `scripts/check-branch-protection.py` → exit 1
  ("PR check 'docker-rebuild-compare' is neither required on any branch nor
  listed under advisory … docs/ci/BRANCH-PROTECTION.md disagrees with
  .github/branch-protection.json")

Registered it required-on-`main` (mirroring `docker-build`, the job it
complements): `.github/branch-protection.json` main contexts, plus the
generated rows in `docs/ci/REQUIRED-CHECKS.md` (`--update`) and
`docs/ci/BRANCH-PROTECTION.md` (`--update-doc`). Both gates now exit 0
("75 PR checks match …; develop queue is SQUASH" / "19 on develop, 32 on
main; every PR check is required or explicitly advisory"), and
`pytest tests/test_check_required_checks.py tests/test_branch_policy.py
tests/test_ci_quality_split.py` → 171 passed. No test was added or removed;
`scripts/check-suite-inventory.py` → ok (21 suites), no inventory delta.

### Fresh-build acceptance evidence (docker 29.1.3)

- `docker build --no-cache -f Dockerfile -t maistro-engine:verify-r .` → exit 0.
- `uv export --locked --package maistro-server --extra image --no-dev
  --no-emit-workspace` (1446 hashed pins) and
  `check-image-lock-reconciliation.py` → `OK: maistro-engine:verify-r ships
  exactly the locked set (127 distributions, incl. 3 workspace member(s))`.
- `docker build --no-cache -f Dockerfile.rsi-runner -t
  maistro-rsi-runner:verify-r .` → exit 0; reconciliation against
  `uv export --locked --extra rsi-fitness --no-emit-workspace` → `OK:
  maistro-rsi-runner:verify-r ships exactly the locked set (220 distributions,
  incl. 4 workspace member(s))` — the extension-COPY repair still holds.
- AC-2 red directions, in /tmp copies: a pyproject drift makes
  `uv export --locked` exit 1 (unsatisfiable); zeroing ALL of sniffio's
  hashes makes `uv pip install --require-hashes` exit 1
  ("Computed: sha256:2f6da… ∉ expected"). (Corrupting one of two hashes
  correctly still installs — the other platform hash matches; both must go.)
- AC-5 locally emulated: dependency manifests dumped from the prior round's
  `maistro-engine:test` and the fresh `maistro-engine:verify-r` (two
  independent builds of the same commit) are byte-identical (127 lines).
- AC-6: all 12 workspace member wheels built to /tmp/348-dist and
  `verify-wheel-imports.py --python 3.12 --mode bare` → "All wheels import
  from a clean venv (Python 3.12)", exit 0; the `wheel-imports` CI job is a
  required check on `main` (.github/branch-protection.json).
- Deterministic battery at this tip: `uv lock --check` ok (468 packages),
  `ruff check .` ok, `ruff format --check .` ok (3371 files), targeted pytest
  (test_image_lock_contract / test_dependency_namespaces /
  test_distribution_contract / test_engine_canvas_packaging) → 100 passed,
  3 skipped (opt-in image smoke), check-build-context / check-image-inventory
  / check-image-pins all ok.

Residual unchanged from round 1: Dockerfile.research,
packages/hive-conductor/Dockerfile, and deploy/sbx/template Dockerfiles were
not rebuilt this round (same shared mechanism, shape-gated by
test_image_lock_contract.py; their `uv export --locked` commands succeed with
hashes).
