---
inventory-delta:
  tests/: +0
  scripts/: +1 (scripts/check-image-lock-reconciliation.py)
  workflows/: +1 job (ci.yml docker-rebuild-compare), +1 gate step (security.yml containers)
---

# issue-348-lock-enforced-images

Repair round for #348 in worktree auto-348 on top of the prior attempt's
commit 144286fc. No pytest tests were added — the new gate is a script whose
correctness is proven by execution against real built images, recorded below.
`tests/: +0` is deliberate: a unit test for `parse_expected`/`parse_actual`
would re-state what the three live reconciliations already demonstrate, and
the negative control (a deliberately-wrong expected manifest) fails with exit
1.

## What this round changed

- `pyproject.toml`: the `rsi-fitness` extra regained `radon` and `vulture`.
  The prior commit's extra listed four of the six tools
  `maistro_evolve.code_quality.py` shells out to; `radon`/`vulture` are
  load-bearing for fitness scoring and were silently dropped.
- `packages/hive-conductor/Dockerfile`: the PUBLISHED Conductor image's
  pybuild stage now installs from `uv export --locked --package
  hive-conductor` + `--require-hashes` (members `--no-deps`), replacing the
  pip resolution over requirements.txt floors. The identity wheel contract
  moved to the lock's `bip-utils==2.12.2` (was ARG-pinned 2.12.1 while the
  lock resolved 2.12.2 — exactly the shipped≠locked divergence this issue
  exists to close); ARG, security.yml assertions, requirements.txt and the
  support-matrix doc moved together.
- `packages/hive-conductor/pyproject.toml`: `msgpack>=1.2.1,<2` declared so
  the Trivy-driven security floor enters the locked closure the image
  actually installs (nobody in the lock required msgpack; security.yml
  asserts it inside the image).
- `deploy/sbx/template/Dockerfile(.tests)`: lock-enforced installs, uv pinned
  to 0.12.20.
- `scripts/check-image-lock-reconciliation.py` + the workflow wiring: the
  SBOM/audit scans and the lock are now forced to describe the same set.

## Evidence (all executed locally, docker 29.1.3, uv 0.12.20)

- `uv lock --check` clean; images built: `maistro-engine:l348`,
  `maistro-rsi-runner:l348`, `hive-conductor-pybuild:l348` (pybuild target,
  in-stage identity contract test green: CPython 3.13.15, bip-utils 2.12.2,
  coincurve 21.0.0, pynacl 1.6.2, ConductorSeed derivation OK).
- Reconciliation: engine 118 dists == locked set; hive pybuild 71 dists ==
  locked set; rsi-runner 213 dists == locked set (radon 6.0.1 + vulture 2.16
  back). Negative control: skewed expected manifest → exit 1.
- Rebuild determinism (#348 AC-5): two independent `--no-cache` builds of the
  engine image produced byte-identical 118-distribution manifests.
- sbx-template install path proven on a clean Python 3.12 venv with
  `--require-hashes` (200 packages, `uv pip check` clean, member imports OK);
  the image itself still cannot be built by CI (owned #346 exception) — the
  conversion is validated at the export/install layer the same way the
  Dockerfile executes it.

## Known residual

`Dockerfile.research` was converted by the prior commit and is exercised by
ci.yml `docker-build` and security.yml `containers`; its full image build was
not rerun locally in this round (chromium/apt-heavy), but its export command
was validated and its builder smoke runs in CI. `deploy/sbx/template` builds
remain operator-side per the owned inventory exception.
