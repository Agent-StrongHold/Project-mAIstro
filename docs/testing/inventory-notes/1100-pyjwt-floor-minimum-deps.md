---
inventory-delta:
  tests/: +38
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

## Follow-up round: the three review findings on the gate itself

Codex review of PR #2039 (head `c7846310`) raised three P2s against the gate as
first landed; this round closes them (+10 nodes, all still in `tests/`):

1. **Lazy verifier APIs were never probed at the floor.** `auth_jwt.py` and
   `auth_demo_cookie.py` import/use `jwt` only inside `_decode_token()` /
   `authenticate()`, and several `oauth.py` attributes are reached only during
   verification — importing the modules proves nothing about them. The gate now
   discovers every PyJWT API the three verifier sources reference statically
   (`jwt_api_inventory`: `pyjwt.X` attribute uses plus `from jwt...` imports
   wherever they appear) and asserts each one exists on the floor-resolved
   PyJWT inside the floor venv. An inventory that discovers nothing aborts the
   gate instead of gating nothing; a parenthesized multi-line jwt import is
   refused rather than half-parsed. Tests: discovery finds the lazy imports
   (`decode`, `PyJWK`, `get_unverified_header`, `PyJWKClient`,
   `MissingCryptographyError`), `VERSION_SENSITIVE_IMPORTS` stays a subset of
   the discovery (a lazy import cannot silently shrink the gate), the
   parenthesized refusal, and a floor-venv probe run that fails on an API the
   locked PyJWT has but the floor lacks (4 nodes).
2. **Only PyJWT's resolution was asserted; other stale floors were masked.**
   `uv pip install --resolution lowest-direct` picks the lowest COMPATIBLE
   version, so `pydantic-settings>=2.7` silently lifted pydantic above its
   declared `>=2.4.0` floor while the gate reported the minimum tested. The
   gate now derives and asserts a floor for EVERY declared dependency, failing
   on any resolution above its declaration — which exposed that maistro-core's
   `pydantic>=2.4.0` was untestable as written, so the declaration moves to
   `>=2.7.0` (the earliest release the floor set can actually install;
   `uv.lock` moves only the recorded specifier). Tests: a lifted floor is
   reported per-package, a corrected floor passes, a non-PyJWT mismatch fails
   the render even with PyJWT at its floor, every declaration has a derivable
   floor, and the pydantic floor never drops below what pydantic-settings
   installs (5 nodes).
3. **A merge-group change to the gate script skipped the gate.** The
   floor-install step lives in ci.yml's wheel-imports job, gated on
   `needs.workflow-lint.outputs.wheel_imports`, but the classifier set that
   flag only for package paths — a PR touching only
   `scripts/verify-minimum-dependencies.py` executed it on pull_request but
   not at the merge-queue SHA. `classify` now maps the gate script to
   `wheel_imports` (and `docker_build`, as before), with a classifier test
   (1 node).

Executed evidence for this round (all exit 0 unless stated):

- `uv run python scripts/verify-minimum-dependencies.py --python 3.12` — 24
  check(s) passed, pyjwt resolved 2.14.0, all 12 declared dependencies at
  their floors, PyJWT-removal refusal intact.
- Negative control: same gate against a copy of the package with the old
  `pydantic>=2.4.0` restored — exit 1, naming "pydantic 2.7.0, not the
  declared floor 2.4.0", i.e. the gate now catches the masking the review
  described.
- `uv run pytest tests/test_verify_minimum_dependencies.py
  tests/test_ci_merge_group_scope.py -q` — 56 passed (37 + 19).
- Mandatory-verification suites re-run green:
  `packages/maistro-core/tests/auth/test_mandatory_verification.py`,
  `.../auth/test_oauth.py`, `.../security/test_auth_jwt.py` — 83 passed.
- `uv run coverage run --branch --source=scripts -m pytest
  tests/test_verify_minimum_dependencies.py tests/test_ci_merge_group_scope.py`
  + `coverage xml` + `scripts/check-diff-coverage.py --base
  b78637f52be33c5` — ok at 90% lines / 80% arcs per file.
- `uv run python scripts/check-suite-inventory.py` — only this note's delta
  (+10 on `tests/`) after `--update`.
- `uv lock --check`, `uv run ruff check .`, `uv run ruff format --check .` —
  clean.
