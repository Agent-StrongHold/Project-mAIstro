---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# Auto 291 Conductor identity contract

Adds backend test nodes for the Conductor deployment contract: the health
probe distinguishes a supported no-crypto profile, operational provisioned
identity, selected-but-unprovisioned identity, and missing identity runtime.
The operational case decrypts and derives the persisted root; malformed roots,
DID-mismatched roots, missing records, and unavailable vaults are all
misconfigured. The existing API health tests also assert that identity status is
exposed on both liveness and readiness without making optional identity an
outage before setup. Setup still refuses to create accounts when identity
persistence fails. Browser coverage now verifies that unavailable and
misconfigured health responses disable the Crypto Identity action, executed
locally with Playwright against a live backend (8/8 passing, including the
full five-step setup completion).

Merge reconciliation: develop's font-size normalization (8/11 -> 12) was
carried into the identity-gated module card copy, and develop's conditional
`bip-utils` marker ("avoid the Python 3.14 path") was superseded by the
pinned cp312/cp313 wheel set this contract ships on Python 3.13.15. The
e2e spec was repaired for drift that predates this branch: the wizard grew
an Accounts step (five steps, not four), the header copy is "🐝 Hive
Conductor", and module/step selectors were tightened to role and exact-text
locators; security CI covers both image profiles with in-image import
assertions.

Independent verification addendum (head c932f42b, post-develop-merge):

- Re-executed at this exact head: driver gates (ruff check/format clean;
  extra_guard 6 passed; targeted conductor files 55 passed; suite inventories
  match) plus engine identity tests 69 passed, full conductor backend suite
  2663 passed (matches recorded inventory), prepull/wheel-import tests 43
  passed. The real-vault provisioning test executed (host age present), not
  skipped.
- Both Docker profiles rebuilt from this tree: default and
  INSTALL_OBSERVABILITY=1. The in-build smoke test (exact CPython 3.13.15,
  pinned bip-utils/coincurve/pynacl versions, ConductorSeed derive) passed in
  both builds; the security.yml in-image verification commands were replicated
  verbatim against both fresh images and printed
  identity=operational/observability=importable.
- Live Playwright run of frontend/e2e/setup.spec.ts against the freshly built
  default image: 8/8 passed, including unavailable- and misconfigured-health
  gating (toggle disabled, "no action offered") and full five-step setup
  completion. Fresh /health shows identity=misconfigured/setup_incomplete,
  identity_required=false pre-setup, as specified.
- Residuals: frontend/e2e still has no CI owner (compose e2e runs tests/e2e
  only); GitHub Actions execution of the security container job remains
  UNVERIFIED, and that job is scoped to PR-to-main/main pushes/nightly, so it
  will not fire on this develop PR — local replication above is the evidence
  of record.

Re-verification pass at final head 3c5688acd (independent re-execution, not
inherited from the addendum above):

- Driver-equivalent gates re-run green: ruff check/format, engine identity 69,
  full conductor backend suite 2663, prepull/wheel tests, image/cross-import/
  deployment-claims/doc-links/build-context/suite-inventory/workflow-write-
  safety/shell-execution/security-inventory/secret-field-labels/shipped-
  surface-truth/retired-guidance/radon/vulture (vulture with the CI argv
  `packages/*/src`; a bare invocation locally also sweeps node_modules and is
  not the CI contract), and full-package mypy (712 files clean).
- Both image profiles rebuilt from this exact tree (default and
  INSTALL_OBSERVABILITY=1); the security.yml in-image verification commands
  were re-executed verbatim against both and printed identity=operational
  (python 3.13.15, bip-utils 2.12.1, coincurve 21.0.0, pynacl 1.6.2) and
  observability=importable. `python:3.13.15-slim-bookworm` confirmed present
  in the registry.
- Live Playwright setup.spec.ts against the fresh default image: 8/8 passed,
  including unavailable- and misconfigured-health gating with a real disabled
  toggle. Live /health transitions recorded: fresh boot -> misconfigured/
  setup_incomplete with identity_required=false; after five-step setup with
  crypto_identity deselected -> disabled, readiness identity=true. The
  documented support-matrix states were each observed on a running image.

Repair-phase re-verification at final head f682c4f16 (independent execution;
previous verify job 8b5d3ef6 failed on worker exit, all 7 driver checks green):

- Branch hygiene: base 750edd84d is not an ancestor of HEAD; the #1192 test/
  CHANGELOG deltas in the base..HEAD diff are unmerged upstream work, not
  deletions by this branch. Branch's 9 commits touch only #291 surfaces.
- Gates re-run green at this head: ruff check, ruff format --check (2529
  files), engine identity 69 passed, conductor test_api/test_identity_health/
  test_setup_guard 55 passed, tests/test_prepull_base_images.py 25 passed,
  suite inventories match (conductor 2663, core 10737), security.yml parses
  with both image builds and both in-image verification steps under the
  `containers` job.
- In-image verification re-executed verbatim against the existing l291-final
  builds of both profiles: default printed identity=operational (python
  3.13.15, bip-utils 2.12.1, coincurve 21.0.0, pynacl 1.6.2, msgpack/setuptools
  floors held); observability printed observability=importable
  identity=operational. The image's /app/backend diffed byte-identical against
  the worktree's packages/hive-conductor/backend, proving image provenance.
- Live Playwright setup.spec.ts 8/8 against a fresh default-profile container
  (host port 18291): unavailable- and misconfigured-health gating disabled the
  Crypto Identity toggle; full five-step completion reached Live Operations.
  Observed /health arc on one boot: fresh -> misconfigured/setup_incomplete
  (required=false), post-setup -> disabled with readiness identity=true.
- Residuals unchanged: GitHub Actions execution of the security container job
  remains UNVERIFIED (no GitHub mutations permitted from this lane; job fires
  on PR-to-main/main pushes/nightly, not develop PRs) — the verbatim local
  replication above is the evidence of record; frontend/e2e still has no CI
  owner (compose e2e runs tests/e2e only), which no #291 acceptance criterion
  requires.

Final-head verification at merge commit 67be62413 (develop 1dea30dfe merged in;
independent re-execution, not inherited from earlier addenda):

- The develop merge touched none of the identity surfaces (Dockerfile,
  identity_health, routes/health+setup, security.yml, support-matrix docs);
  it brought unrelated credential/design/security test deltas, and the suite
  inventories grew coherently (conductor 2670, core 10776).
- Driver gates green at this head (uv sync, ruff check, ruff format --check,
  extra_guard 6, conductor api+identity_health+setup_guard 55, both suite
  inventories match). Independently re-executed: extra_guard 6 passed,
  test_identity_health+test_setup_guard 25 passed, test_api 30 passed,
  tests/test_prepull_base_images.py 25 passed, engine identity suite 69
  passed, and check gates build-context/deployment-claims/doc-links/
  image-inventory/shell-execution/workflow-write-safety/security-inventory/
  shipped-surface-truth/cross-package-imports all PASS. security.yml parses
  with both image builds and both in-image verification steps in the
  `containers` job.
- Both l291-final image profiles re-verified in-image verbatim (CI commands):
  default printed identity=operational (python 3.13.15, bip-utils 2.12.1,
  coincurve 21.0.0, pynacl 1.6.2, msgpack/setuptools floors held);
  observability printed observability=importable identity=operational. Image
  provenance proven at this head: the image's services/identity_health.py,
  routes/health.py, routes/setup.py and requirements.txt are byte-identical
  to the worktree.
- Live deployment contract observed against the shipped default image: fresh
  boot -> /health identity=misconfigured/setup_incomplete,
  identity_required=false, /health/ready identity=false; five-step setup
  without crypto_identity -> disabled, readiness identity=true; setup with
  crypto_identity (POST /v1/setup/complete, did persisted, one-time mnemonic
  returned) -> identity=operational/provisioned. Live Playwright
  setup.spec.ts against the same image: 8/8 passed, including unavailable-
  and misconfigured-health gating with the Crypto Identity toggle disabled.
- Residuals unchanged: GitHub Actions execution of the security containers
  job remains UNVERIFIED (read-only lane; job fires on PR-to-main/main
  pushes/nightly, not develop PRs) — the verbatim local in-image replication
  is the evidence of record. frontend/e2e still has no CI owner (compose e2e
  runs tests/e2e only); no #291 criterion requires it, and the spec was
  executed live here.
