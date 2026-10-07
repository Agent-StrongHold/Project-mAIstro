---
inventory-delta:
  tests/: +28
---
# Issue #1100 — align the PyJWT dependency floor with the mandatory OIDC verifier imports

#1100's failure mode is invisible to every other gate in the repository: the
published `pyjwt[crypto]` floor advertises versions the mandatory OIDC verifier
(#856/#1073) may not import on, while the workspace lockfile — which a consumer
installing the published wheel never reads — resolves something newer and masks
the gap. The lane closed the remaining acceptance criteria rather than
re-litigating the floor itself:

- `packages/maistro-core/pyproject.toml` keeps `pyjwt[crypto]>=2.14,<3` (raised
  by #1685 for CVE-2026-102274; every allowed release is at or above the
  verified API minimum) and raises `pyyaml>=6.0` to `>=6.0.1` — 6.0 ships no
  CPython 3.12 wheels and its sdist does not build under Cython >=3.1, so the
  old floor was a release no clean minimum install could resolve. `uv.lock`
  moves only the recorded `requires-dist` specifier; the resolved pyyaml stays
  6.0.3.
- New gate `scripts/verify-minimum-dependencies.py`: installs the package's
  DECLARED floors (`uv pip install --resolution lowest-direct` against the
  source directory — a wheel's Requires-Dist resolve as transitive and the
  floors would be silently ignored), asserts PyJWT resolved exactly at the
  floor, imports the three OIDC/auth modules plus the two version-sensitive
  imports the issue names (`MissingCryptographyError`, `PyJWKClient`), and
  proves a PyJWT-removal still fails closed with the #856 actionable error.
  Wired into `release.yml` (wheels job) and `ci.yml` (wheel-imports job) —
  the "Release CI tests both the lockfile/current set and a
  minimum-supported-dependencies environment" criterion.

Net +28 node IDs, all in `tests/test_verify_minimum_dependencies.py`:

- floor derivation (`derive_floor`) and the resolved==floor prefix check
  (`floor_resolved`), including the degenerate inputs: a range with no `>=`
  clause, a wildcard lower bound, an unparsable resolution, and a resolved
  release shorter than the floor all refuse rather than gate nothing
  (10 nodes, one parametrized over four resolutions).
- the declarations themselves: maistro-core's PyJWT floor stays at or above
  the verified minimum (2, 14), and maistro-core's `pyproject.toml` and
  hive-conductor's no-lockfile `requirements.txt` agree on it — the
  "metadata and documentation agree" criterion (2 nodes).
- the JWT API inventory the three verifier modules import resolves on the
  installed PyJWT (parametrized over the three files, 3 nodes): the fast
  in-suite complement to the CI run at the floor.
- workflow wiring: both `release.yml` and `ci.yml` must reference the gate,
  and the gate must import the OIDC modules by name, so neither can silently
  shrink (2 nodes).
- the gate's reporting half, which needs no venv to prove: the probe
  environment cannot inherit the repo (PYTHONPATH/VIRTUAL_ENV scrubbed), the
  floor assertion reports a missing dist version and a resolution above the
  floor, and `render` fails on a probe failure or a floor mismatch even when
  every import passed (7 nodes).
- `check()`'s entry guard: a package that does not declare the gated
  dependency aborts loudly instead of gating some other range (1 node).
- the fail-closed probe (subprocess, fake `maistro.auth.oauth`): a module
  that refuses without PyJWT with the actionable message passes; one that
  imports anyway is reported as DOWNGRADED and fails the gate; an incidental
  `ImportError('boom')` does not count as refusal (3 nodes). The downgrade
  path is the one the probe exists to catch, so it is exercised, not assumed.

10 + 1 + 3 + 3 + 2 + 3 + 2 + 1 + 3 = 28 collected node IDs.

The gate script's environment-bound orchestration (`check()`/`main()`'s uv and
subprocess driving) is `# pragma: no cover` for the pytest producer with the
real producers named in the comment: the `ci.yml`/`release.yml` steps execute
it end to end, and every pure helper it calls is unit-covered (the file
measures 100% lines / 100% branch arcs outside the exclusions).

Executed evidence at this head (all exit 0):

- `uv run python scripts/verify-minimum-dependencies.py --python 3.12` —
  floors install, pyjwt resolves 2.14.0, 7 check(s) passed, PyJWT-removal
  refusal intact.
- `uv run pytest tests/test_verify_minimum_dependencies.py -q` — 28 passed.
- `uv run coverage run --branch --source=scripts -m pytest
  tests/test_verify_minimum_dependencies.py` then `coverage report` — 100%
  lines / 100% branch arcs on the script outside the named exclusions.
- `uv sync --locked --extra dev` — lock consistent with the moved specifier.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
