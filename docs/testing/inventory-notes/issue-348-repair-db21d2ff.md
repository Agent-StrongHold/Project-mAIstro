---
inventory-delta:
  tests/: +0
---
# issue-348-repair-db21d2ff

CI-repair round for #348 in worktree `auto-348` at the branch head (docs-only
verification rounds on top of the validated merge `000f08f0e`). No pytest
tests were added or removed — `tests/:` is +0 and the suite-inventory gate
re-ran green at 21 suites; the four modified files change assertions inside
two existing suites, not suite membership. The round addresses the real,
tree-level failures in the merge-queue CI run at `ada02defb`, separating them
from the runner-infrastructure failures in the same run.

## CI failures at `ada02defb`: classification

Real (fixed here):

1. `tests/test_bump_version.py::TestTheRegisteredCorpus::test_every_registered_site_resolves_to_exactly_one_occurrence`
   — `SystemExit: inter-package dep:packages/hive-conductor/pyproject.toml:maistro-core[bcrypt]:
   expected exactly 1 match ... found 0`. The lane's own lock-enforcement
   commit `144286fcf` changed the conductor dependency to
   `maistro-core[bcrypt,identity]>=0.9.0,<2` (the `identity` extra carries
   the bip-utils/coincurve/pynacl stack the auth wiring imports) but left the
   registered corpus row naming `maistro-core[bcrypt]`. Reproduced locally:
   `uv run python scripts/bump_version.py --check` → exit 1, "1 of 42 sites
   disagree" — the same root cause as the Quality / Version-consistency job
   failure in the same CI run.
2. `packages/maistro-rsi/tests/test_gate_evidence.py::TestRunnerImageParity::test_runner_image_declares_every_required_analyzer`
   — `AssertionError: runner image lost its analyzer install line; assert []`.
   Reproduced locally. The develop-side test required an explicit
   `RUN uv pip install ...` line in `Dockerfile.rsi-runner`; #348 replaced
   that unpinned install with `RUN uv sync --locked --python 3.12
   --extra rsi-fitness` (the six fitness tools are locked in the extra).
   Re-adding an explicit `uv pip install` layer would reintroduce the
   implicit build-time resolution #348 removes, so the test was re-bound to
   the locked install surface (below).
3. Container-scan job `ModuleNotFoundError: No module named 'packaging'` —
   the "Verify live Python packages and Conductor identity contract" smoke
   (security.yml) imports `packaging.version` inside the built
   hive-conductor image. `packaging` previously rode in transitively with
   the test toolchain (pytest/hypothesis via `backend/requirements.txt`)
   that #348's lock-enforced image deliberately stopped shipping, and the
   reconciliation gate (`scripts/check-image-lock-reconciliation.py`)
   requires shipped == locked export exactly, so the dist cannot be re-added
   ad hoc. `uv export --locked --package hive-conductor --no-dev
   --no-emit-workspace` (67 pins) confirmed `packaging` is not in the locked
   set. Fixed by asserting the same floors (msgpack >= 1.2.1, setuptools >=
   78.1.1) with a stdlib version-tuple parse; the exact-pin assertions
   (bip-utils 2.12.2, coincurve 21.0.0, pynacl 1.6.2, python 3.13.16) are
   unchanged.

Infrastructure (not fixable in-tree; documented, not "repaired"):

- coverage job: `could not pull python:3.12-slim after 3 attempts` — runner
  registry outage. (The same job's parity-test failure is fixed above.)
- security / Supply-chain jobs: `pip-audit produced no usable report after 3
  attempts` — the workflow itself classifies this as a registry/network
  outage and says to retry the job.
- `gates-ran` and `Quality gate (Pillars 1–4, 7, 8)`: aggregator jobs whose
  components include the version-consistency step and the test jobs above.

## What changed

- `scripts/bump_version.py` — the conductor corpus row now names
  `maistro-core[bcrypt,identity]`, with the why in a comment (the row must
  name the expression the file actually holds, or the bound silently stops
  being checked).
- `tests/test_bump_version.py` — the registered-label fragment updated to
  the same expression (exact-equality assertion).
- `packages/maistro-rsi/tests/test_gate_evidence.py` —
  `TestRunnerImageParity` re-bound to the #348 mechanism: the RUN sync line
  must be lock-pinned (`--locked`/`--frozen`), must request
  `--extra rsi-fitness`, must keep the dev group (no `--no-dev`), and every
  `REQUIRED_LINT_TOOL_SPEC` analyzer plus coverage must be named by the
  locked dev group or the locked rsi-fitness extra in the root pyproject.
- `.github/workflows/security.yml` — the hive-conductor image smoke asserts
  its floors without `packaging` (stdlib tuples); a comment records why.

## Evidence (executed first-hand this round)

- `uv run python scripts/bump_version.py --check` → exit 0, "42 sites agree
  on '0.9.0'" (was exit 1).
- `uv run pytest tests/test_bump_version.py` → 18 passed (was: 1 failed).
- `uv run pytest packages/maistro-rsi/tests/test_gate_evidence.py` → 34
  passed (was: TestRunnerImageParity failed).
- Full #348 contract battery:
  `uv run pytest packages/maistro-rsi/tests/test_gate_evidence.py
  tests/test_bump_version.py tests/test_image_lock_contract.py
  tests/test_distribution_contract.py tests/test_dependency_namespaces.py
  tests/test_engine_canvas_packaging.py` → 159 passed, 3 skipped (the skips
  are the MAISTRO_ENGINE_IMAGE-gated artifact tests).
- Red controls against the rewritten parity test (mirrored assertion logic
  on mutated copies; the tree itself was not dirtied): dropping
  `--extra rsi-fitness`, un-pinning the sync, adding `--no-dev`, and
  removing bandit or coverage from every locked source are each caught.
- Smoke-floor equivalence: the stdlib tuple parse matches `packaging.Version`
  semantics below/at/above the floors, and the locked versions (msgpack
  1.2.3, setuptools 84.0.0, bip-utils 2.12.2, coincurve 21.0.0, pynacl
  1.6.2) satisfy every assertion the updated smoke makes — the image ships
  exactly this locked set per the prior rounds' reconciliation (engine 128,
  research 148, hive 72, rsi 220 dists).
- Gates: `uv run ruff check .` OK; `uv run ruff format --check .` OK (3439
  files); `scripts/check-suite-inventory.py` OK (21 suites, counts
  unchanged); `scripts/check-image-pins.py` OK (8 pins / 10 Dockerfiles);
  `uv lock --check` clean (468 packages); security.yml re-parsed as valid
  YAML.

## Residual / risks carried

- The runner-infrastructure failures (docker pull, pip-audit registry) need
  a CI retry, not a code change; this round cannot execute them.
- The smoke now parses versions with a stdlib tuple instead of
  `packaging.Version`; for the exact-pin dists the equality assertions are
  unchanged, and the floor comparisons are equivalent on the locked pins
  (proven above). If a future pin introduces a PEP 440 pre/post-release
  spelling, the floor comparisons must move to a real specifier engine.
- Everything else documented by the prior rounds holds: sbx-template base
  interpreter is the owned #346 gap; the trivy `gobinary` finding is a
  develop-side base-image item; no ledger rows were touched (`git diff
  --numstat <develop base> -- quality/` unchanged from the prior round's
  record: only `quality/image-pins.json`).
