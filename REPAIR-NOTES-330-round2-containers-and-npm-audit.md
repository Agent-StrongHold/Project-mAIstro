# REPAIR-NOTES — #330 round 2: the two red checks at head `7e468400e64b`

Job `58116981c67249208f9083cff878188f`, branch `auto-330`, base `4de7e906d9dc`.
Scope: the two failing merge-queue checks at the round's starting head —
`test` and `Container scan + SBOM + cosign`. Everything else was green at
`7e468400e64b` (74 check-runs inspected in the dispatch context: 72 success).

## Root causes, from local reproduction (not from the truncated CI excerpts)

### `Container scan + SBOM + cosign` — the reconcile step's marker-fork collapse

The lane's own repair commit `687b3830e` ran `uv lock --upgrade-package
fastmcp setuptools pypdf`. That re-resolution forked **beartype** across
`python_full_version` markers in `uv.lock`:

- `beartype==0.22.9` for `python_full_version < '3.15'` (develop has only
  this, unforked — verified against `origin/develop:uv.lock`)
- `beartype==0.23.1` for `python_full_version >= '3.15'`

`uv export --locked --package maistro-server --extra image` therefore lists
BOTH pins (conditional on their markers). The engine image is py3.13, so
`uv pip install --require-hashes` correctly installs **0.22.9**. But
`scripts/check-image-lock-reconciliation.py` — the `Reconcile installed
packages to uv.lock` step that closes the containers job — collapsed the
variants twice:

1. `parse_expected` keyed pins by bare name, so the LAST variant
   (0.23.1) overwrote 0.22.9 and the image's correct version was disowned.
2. the comparison's `expected_by_name` dict gave a forked name a single
   arbitrary-winner slot.

Result: `image maistro-engine:pr-<tag> does NOT reconcile to the lock:
version mismatch : beartype==0.22.9 (image) != beartype==0.23.1` → exit 1 →
red job. **Reproduced locally** against the engine image built from this
tree, then fixed in the script (`parse_expected` keeps every variant per
name; new `reconcile_variance` allows a name any of its locked variants and
still reports a version no variant names as a single skew). All four
reconcile contracts now exit 0 against the locally built images.

Also aligned the setuptools exact pins the same commit left stale after its
own lock bump (the Dockerfile's comment requires the pin to BE the lock's
version): `packages/hive-conductor/Dockerfile` `setuptools==84.0.0` →
`84.2.1`, and the matching `--member setuptools==84.0.0` in
`.github/workflows/security.yml`. (Note: the trivy finding for the old
setuptools is LOW, not HIGH — this pin drift alone would not have failed the
gate; the reconcile beartype failure is the proven red.)

### `test` — canvas frontend npm audit

`npm audit --audit-level=high` in `packages/maistro-canvas/frontend` exits 1
on 3 HIGH advisories: body-parser (GHSA-27r3-jxmh-p828), undici
(GHSA-4qv8-2p9j-2685 / -f72v-6w45-q472 / -xjj6-f33q-929c), zod
(GHSA-mrhx-c7xc-m3w5) — plus 3 moderate. `npm audit fix` (lockfile-only,
semver-compatible) bumps them all to fixed versions: body-parser 2.4.0,
undici 7.30.1, zod 4.6.7, vitest/@vitest/mocker 5.0.5, ip-address 10.7.4.

The `RuntimeError: Event loop is closed` lines in the CI log are annotations
from a pytest step that PASSED (the job proceeded past it to npm audit, so
that step exited 0); the full root suite passes locally (below), so no code
change is warranted for them.

## Local proof, CI's commands where defined

- Full containers-job replication on locally built images (cold buildx, the
  four Dockerfiles with security.yml's build args): builds exit 0; identity
  smokes `identity=operational` / `observability=importable` exit 0;
  **trivy v0.73.0** (`--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml`) exit 0 on all four; **grype v0.116.0**
  (checksum-verified, `--fail-on high --only-fixed`) exit 0 on all four;
  frontend license surfaces `npm ci && npm run build` both trees exit 0;
  **syft v1.49.0** (checksum-verified) SBOMs + `check-license-inventory.py`
  → `OK: inventoried 8 surface(s), 25300 component(s)` exit 0;
  **all four `check-image-lock-reconciliation.py` contracts exit 0** (engine,
  hive-conductor, research, rsi-runner) with CI's exact `uv export` inputs.
- Coverage producer: `uv run coverage run --branch --source=scripts -m pytest
  tests/ tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q` → **5860 passed, 139 skipped**.
- Diff coverage: `check-diff-coverage.py coverage.xml --base 4de7e906…` →
  **ok: every measured file ≥ 90% lines / 80% branch arcs**.
- `check-suite-inventory.py --update --note
  330-image-lock-recon-marker-fork` (+5 tests, prose in the note) → ok.
- `uv run vulture packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → 1302 findings = 1302 baselined identities,
  `check-vulture-baseline.py` (same args) → exit 0, **no ledger amendment**.
- `npm audit --audit-level=high` (canvas) → `found 0 vulnerabilities`, exit 0;
  canvas `npm run test:ci` 79/79, `npm run lint` 0 errors, `npm run build` ok.
- actionlint 1.7.7 + shellcheck over all workflows → clean;
  `check-workflow-inventory.py` → clean (32 workflows);
  `check-workflow-write-safety.py` → ok; ruff check/format → clean.

## Not touched / residuals

- `quality/vulture-baseline.json`: unchanged (no new debt).
- hive-conductor frontend's own npm tree carries a zod HIGH
  (GHSA-mrhx-c7xc-m3w5); no gate reads that lockfile (the image ships only
  `dist/`, trivy finds no npm manifests in the final filesystem — verified),
  so it is not a current red. Recorded here as a follow-up, not fixed in
  this gate-repair round.
- Grype reports Medium/Negligible python-binary findings on all four images;
  `--fail-on high` does not fail on them and trivy (HIGH/CRITICAL,
  ignore-unfixed) is clean. No action.
- Mutation-gate work itself is untouched this round; the red checks were
  supply-chain surfaces, not the mutation machinery.
