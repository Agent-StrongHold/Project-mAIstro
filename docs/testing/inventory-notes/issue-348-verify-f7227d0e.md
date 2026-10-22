---
inventory-delta:
  tests/: +0
---
# issue-348-verify-f7227d0e

Verification round for #348 in worktree `auto-348` at head `f7227d0e078e`
(the merge that carried the M1-C1/M2/M9-G4 WIP commits onto the lane). No
pytest tests were added or removed — `tests/:` is +0. The round is
re-executed acceptance evidence: the previous merge-ready determination
(6bbf343ef) predates this head, and the merge touched
`packages/maistro-core/pyproject.toml` + `uv.lock` (aiosqlite added to the
`builders` extra), so the earlier green did not cover this tree.

## Why no test delta

The acceptance surface is unchanged and already gated:
`tests/test_image_lock_contract.py` (30 cases), `tests/test_distribution_contract.py`,
`tests/test_dependency_namespaces.py`, `tests/test_engine_canvas_packaging.py`
(3 image-build cases skip locally by design — they need a built image; the
built-image half was exercised directly this round, see Evidence). This round
added no code and no tests; it rebuilt and reconciled the real engine image.

## Evidence (all executed first-hand at this head)

- `uv lock --check` clean (468 packages) — the merged builders-extra lock bump
  is consistent; `uv export --locked` succeeds for all four image contracts:
  engine 130 pins, hive 67, research 315, rsi 220 (the exact security.yml
  reconciliation exports).
- `uv run pytest tests/test_image_lock_contract.py` → 30 passed;
  `tests/test_distribution_contract.py tests/test_dependency_namespaces.py
  tests/test_engine_canvas_packaging.py` → 77 passed, 3 skipped (the three
  built-image cases; covered below by a real build).
- **AC-1/AC-3 end-to-end**: `docker build -f Dockerfile -t
  maistro-engine:l348-verify .` → exit 0 (builder ran `uv export --locked
  --package maistro-server --extra image --no-dev --no-emit-workspace` +
  `uv pip install --no-config --require-hashes --no-cache` + members
  `--no-deps`, `uv pip check`, builder smoke OK). Then
  `python scripts/check-image-lock-reconciliation.py --image
  maistro-engine:l348-verify --expected-file <engine export> --member
  maistro-core==0.9.0 --member maistro-server==0.9.0 --member
  maistro-canvas==0.9.0` → `OK: ships exactly the locked set (128
  distributions)`, exit 0. Negative controls against the same image: version
  skew (pyjwt 2.15.2) → exit 1; missing pin (websockets) → exit 1.
- **AC-2 red directions**: (a) drift — workspace metadata copy with one extra
  dependency in `packages/maistro-server/pyproject.toml` (no re-lock) →
  `uv export --locked` exit 1, while the untouched copy exports cleanly;
  (b) unresolvable locked artifact — `uv pip install --require-hashes` with
  an all-corrupted hash set for a pinned package → exit 1 "Hash mismatch",
  while the true hash set installs (positive control).
- **AC-4**: contract tests assert `--no-config` on every hashed install and
  `--no-deps` on member installs across all six Dockerfiles (30 cases green);
  the build log shows no resolver ran except through the hashed export.
- **AC-5**: second independent `docker build --no-cache` of the engine image
  → the two images' `importlib.metadata` dumps are byte-identical (128
  distributions) — the `docker-rebuild-compare` procedure re-executed locally;
  the job is registered in `.github/branch-protection.json` and
  `docs/ci/REQUIRED-CHECKS.md`.
- **AC-6**: both hash-verified builds downloaded every locked artifact for
  linux/amd64 × cp313 — a missing wheel fails under `--require-hashes`, so
  success is the availability proof; `tests/test_distribution_contract.py::test_image_pins_supported_python_and_installs_identity`
  green; `scripts/check-image-pins.py` OK (8 pins).
- `uv run ruff check .` → all checks passed; `uv run ruff format --check .` →
  3419 files already formatted. `scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1320/1320 banked (no amendment due). `scripts/check-image-inventory.py` OK.

## Residual

- The syft/trivy/grype executions against built images remain CI-side
  (security.yml `containers`); this round proved the reconciliation half of
  AC-3 on a real built image and re-read the workflow wiring first-hand.
- `deploy/sbx/template` remains operator-built under the owned #346
  coverage_exception (unsupported cp314 base), unchanged from the prior
  rounds' determination.
