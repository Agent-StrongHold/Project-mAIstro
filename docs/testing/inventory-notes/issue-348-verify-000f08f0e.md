---
inventory-delta:
  tests/: +0
---
# issue-348-verify-000f08f0e

Independent verification round for #348 in worktree `auto-348` at head
`000f08f0e03f` (the merge of develop base `c29e0ea70` onto the lane). No
pytest tests were added or removed — `tests/:` is +0. The merge changed no
image-relevant surface (`git diff b4cac1522..000f08f0e` over the six
Dockerfiles, uv.lock, pyprojects, and the reconciliation script is empty),
but the develop side changed `maistro-core`/`maistro-server` sources that the
images COPY, so the builder smoke could have broken; this round re-ran the
builds to rule that out. All evidence below is first-hand at this head.

## Evidence (all executed first-hand at this head)

- `uv run pytest tests/test_image_lock_contract.py
  tests/test_distribution_contract.py tests/test_dependency_namespaces.py
  tests/test_engine_canvas_packaging.py` → 107 passed, 3 skipped (the skips
  are the MAISTRO_ENGINE_IMAGE-gated artifact tests).
- `uv lock --check` clean (468 packages); `uv export --locked` succeeds for
  all four image contracts with hashes on every pin.
- Four real image builds at this head, all green:
  `maistro-engine:verify-000f08f0e` (engine builder smoke `import
  maistro_server.main` passed post-merge), `maistro-research:verify-000f08f0e`
  (cp312 + browser extra, 146 hash-verified packages), `hive-conductor:
  verify-000f08f0e` (identity smoke: bip-utils=2.12.2, msgpack=1.2.3,
  setuptools=84.0.0), `maistro-rsi-runner:verify-000f08f0e` (`uv sync
  --locked --extra rsi-fitness`, 220 packages).
- `scripts/check-image-lock-reconciliation.py` green on all four built
  images with security.yml's exact exports/members: engine 128 dists,
  research 148, hive 72, rsi 220 — each "ships exactly the locked set".
- AC-5 double rebuild: second `docker build --no-cache` of the engine
  image produced a byte-identical 128-distribution manifest (`diff -u`
  clean), the exact `docker-rebuild-compare` CI procedure; the required
  context is registered in `.github/branch-protection.json` and
  `docs/ci/REQUIRED-CHECKS.md`.
- Red controls: mutated pyproject → `uv export --locked` exit 1 ("lockfile
  needs to be updated"); all-hashes-zeroed export → `uv pip install
  --require-hashes` exit 1 (hash mismatch) with the uncorrupted set
  installing fine; reconciliation skew and missing-pin controls both exit 1.
- Engine runtime has no pip (`/app/venv/bin` and site-packages pip-free) and
  every install in the image is the hashed export + `--no-deps` members.
- Gates: `scripts/check-suite-inventory.py` (21 suites match),
  `scripts/check-image-pins.py` (8 pins / 10 Dockerfiles registered),
  `uv run ruff check .` and `ruff format --check .` clean (driver logs),
  `quality/` diff vs develop base shows only the intended
  `quality/image-pins.json` rows — no ledger rows lost in the merge.
- PR #2243 body and every `#348` commit message: no fixes/closes/resolves
  keywords; the only "Closes #NNNN" strings in the range are inherited
  develop-side lane history for unrelated issues.

## Not executed here (CI-side, unchanged scope)

The trivy/grype/syft scan executions and the pip-audit gate run in GitHub
Actions (`security.yml`), not locally; their wiring was re-read this round
(the reconcile step runs after the SBOM steps, on the built PR images).
Integration of develop-side code changes is CI's lane, not this round's.
