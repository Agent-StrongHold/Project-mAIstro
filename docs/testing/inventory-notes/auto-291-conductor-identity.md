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

Writer-lane re-verification at head bae8919df (independent re-execution; the
only delta from 67be62413 is this note itself, so code provenance carries):

- Gates: ruff check + format --check clean; extra_guard 6, conductor
  api+identity_health+setup_guard 55, engine identity 69, prepull 25 passed;
  both suite inventories match (2670 / 10776); nine check-*.py gates PASS
  (build-context, deployment-claims, doc-links, image-inventory,
  shell-execution, workflow-write-safety, security-inventory,
  shipped-surface-truth, cross-package-imports).
- Image provenance re-proven at this head: hive-conductor:l291-final's
  services/identity_health.py, routes/health.py, routes/setup.py and
  requirements.txt byte-identical to the worktree; both profiles re-verified
  in-image with the verbatim security.yml commands (identity=operational
  python=3.13.15 with exact wheel pins; observability=importable).
- Live arc re-observed against a fresh l291-final container: boot ->
  misconfigured/setup_incomplete (required=false); setup without
  crypto_identity -> disabled with readiness identity=true; fresh container
  with crypto_identity -> did persisted, identity=operational/provisioned.
- Live Playwright setup.spec.ts re-run against a fresh l291-final container
  (host port 18294): 8/8 passed, including both gating tests asserting the
  Crypto Identity toggle is disabled with unavailable and misconfigured
  health responses, and full five-step completion to Live Operations.

Independent verifier pass at head e7b318b2f (delta from bae8919df is this note
only, so all prior image provenance carries to this head):

- Re-executed: ruff check clean; extra_guard 6, conductor
  api+identity_health+setup_guard 55, full conductor backend 2670 (matches
  inventory), distribution+prepull 30, engine identity 69 — all passed. Ten
  check gates rc=0 (build-context, deployment-claims, doc-links,
  image-inventory, shell-execution, workflow-write-safety,
  security-inventory, shipped-surface-truth, cross-package-imports,
  suite-inventory).
- Image provenance re-proven: hive-conductor:l291-final's
  services/identity_health.py, routes/health.py, routes/setup.py and
  requirements.txt byte-identical to this worktree. Both verbatim security.yml
  in-image commands re-executed: default → identity=operational (python
  3.13.15, bip-utils 2.12.1, coincurve 21.0.0, pynacl 1.6.2, msgpack/setuptools
  floors held); observability → observability=importable identity=operational.
- Live support-matrix arc re-observed on fresh l291-final containers: boot →
  misconfigured/setup_incomplete with identity_required=false; setup without
  crypto_identity → disabled (readiness identity=true); setup with
  crypto_identity → DID persisted, one-time mnemonic returned,
  identity=operational/provisioned.
- Live Playwright frontend/e2e/setup.spec.ts against a fresh l291-final
  container (host port 18303): 8/8 passed, including the unavailable- and
  misconfigured-health gating tests asserting the Crypto Identity toggle is
  disabled ("no action offered").
- Residuals unchanged: GitHub Actions execution of the security containers job
  remains UNVERIFIED from this read-only lane (job fires on PR-to-main/main
  pushes/nightly, not develop PRs); the verbatim local in-image replication is
  the evidence of record. frontend/e2e still has no CI owner (compose e2e runs
  tests/e2e only); no #291 criterion requires it and the spec was executed
  live here. No premature closure keywords in the PR body or commit messages.

Repair-lane re-verification at final head 183ac8fb (delta from e7b318b2f is
this note only; all independent execution below is from this pass, not
inherited):

- Gates: ruff check + ruff format --check clean (2535 files); conductor
  test_identity_health + test_setup_guard + test_api 55 passed; engine identity
  69 passed; extra_guard 6 passed; tests/test_prepull_base_images.py 25
  passed; check gates build-context/deployment-claims/doc-links/
  image-inventory/workflow-write-safety/shipped-surface-truth/
  security-inventory/cross-package-imports/shell-execution all PASS;
  check-suite-inventory: 13 suites match (conductor backend 2670).
- Image provenance re-proven at this head: hive-conductor:l291-final's
  services/identity_health.py, routes/health.py, routes/setup.py and
  requirements.txt md5-identical to the worktree.
- Both verbatim security.yml in-image verification commands re-executed:
  default -> identity=operational python=3.13.15 bip-utils=2.12.1
  coincurve=21.0.0 pynacl=1.6.2 (msgpack/setuptools floors held);
  observability -> observability=importable identity=operational.
- Live Playwright frontend/e2e/setup.spec.ts against a fresh l291-final
  container (host port 18311): 8/8 passed, including the unavailable- and
  misconfigured-health gating tests ("no action offered", toggle disabled).
- Full support-matrix arc observed live on the shipped image: fresh boot ->
  misconfigured/setup_incomplete (required=false); setup without
  crypto_identity (via the e2e wizard completion) -> disabled with readiness
  identity=true; POST /v1/setup/complete with crypto_identity on two fresh
  containers (ports 18312/18313) -> 24-word one-time mnemonic returned,
  identity=operational/provisioned, readiness identity=true.
- Prior findings confirmed fixed at this head: security.yml builds BOTH
  Conductor profiles and verifies each in-image (observability build +
  verification steps present under the `containers` job); e2e setup.spec.ts
  asserts the disabled action under unavailable and misconfigured health
  responses, executed live above.

Repair-writer re-verification at final head 4759c9f83 (merge of develop
60862b6c5 into auto-291; delta from 183ac8fb is that merge plus this note —
no identity surface changed: Dockerfile, identity_health, routes/health+setup,
requirements.txt, security.yml, support-matrix docs, Setup.tsx and
setup.spec.ts are all absent from the 183ac8fb..HEAD diff):

- Gates re-run green at this head: ruff check + ruff format --check (2535
  files); conductor test_api + test_identity_health + test_setup_guard 55
  passed; engine identity 69 passed; extra_guard + prepull 31 passed;
  canonical mypy clean (713 files); check-suite-inventory 13 suites match
  (conductor backend 2677 — grew coherently with the merge's HITL/workspace
  tests); check gates build-context/deployment-claims/doc-links/
  image-inventory/cross-package-imports/workflow-write-safety/
  shell-execution/security-inventory/shipped-surface-truth all PASS.
- Image provenance re-proven at this head: hive-conductor:l291-final's
  services/identity_health.py, routes/health.py, routes/setup.py and
  requirements.txt md5-identical to the worktree, so the earlier in-build and
  in-image evidence carries to this tree.
- Both verbatim security.yml in-image verification commands re-executed
  against those images: default -> identity=operational python=3.13.15
  bip-utils=2.12.1 coincurve=21.0.0 pynacl=1.6.2 (msgpack/setuptools floors
  held); observability -> observability=importable identity=operational.
- Live support-matrix arc re-observed on fresh l291-final containers at this
  head: fresh boot -> identity=misconfigured/setup_incomplete with
  identity_required=false; POST /v1/setup/complete with crypto_identity ->
  24-word one-time mnemonic returned, identity_persisted=true, liveness
  identity=operational/provisioned, /health/ready checks.identity=true; fresh
  container with setup sans crypto_identity -> no mnemonic,
  identity=disabled/crypto_identity_not_enabled, identity_required=false,
  readiness identity=true. The unavailable state remains unit-tested only
  (test_identity_health_distinguishes_missing_runtime) because the shipped
  image structurally cannot reach it: the build fails if the extra does not
  import.
- Both prior findings re-confirmed fixed in-tree at this head: security.yml
  builds both profiles (default + INSTALL_OBSERVABILITY=1) under the
  `containers` job with per-image in-image verification steps;
  frontend/e2e/setup.spec.ts asserts the Crypto Identity toggle is DISABLED
  (`toBeDisabled()`, not copy-only) under unavailable and misconfigured
  health responses.
- Residuals unchanged: GitHub Actions execution of the security containers
  job remains UNVERIFIED from this read-only lane (job fires on
  PR-to-main/main pushes/nightly, not develop PRs; no GitHub mutations
  permitted) — the verbatim local in-image replication is the evidence of
  record. frontend/e2e still has no CI owner (compose e2e runs tests/e2e
  only); no #291 criterion requires it, and the spec was executed live at
  183ac8fb with the frontend byte-identical since.

Repair-writer re-verification at final head 8bfef0c8f (this round; driver
produced no check-*.log files, all evidence below is independently executed in
this worktree):

- Prior CI findings at this head root-caused (read-only `gh run view`):
  "object storage (MinIO)" (run 36066572512) and "coverage (MinIO)" (run
  36066572584) both died in their "Start MinIO" step with "could not pull
  quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z after 4 attempts" — a
  transient registry pull failure, not a code or contract regression; every
  other job in both workflows was green (test, postgres pg17/pg18,
  docker-build, hive-conductor-e2e, wheel-imports, security, lint/type,
  quality gate, coverage PostgreSQL/no-services). integration-scope (run
  36066572640) failed solely as its aggregator ("object storage (MinIO) is
  required by integration scope but concluded failure"), and gates-ran (run
  36068515405) failed solely as the evidence aggregator over the same MinIO
  pull ("Required execution evidence is missing or non-executed"). All four
  findings share one infra root cause; no #291 surface is implicated.
- Vulture per-identity ledger (CI argv): `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` ->
  1415 reviewed identities = 1415 findings, unclassified 0, never_allowlist 0;
  ratchet balanced against base 60862b6c5. No ledger amendment required.
- Gates re-run green at this head: ruff check + ruff format --check (2535
  files); engine identity 69 passed; conductor test_identity_health +
  test_setup_guard + test_api 55 passed; extra_guard + prepull 31 passed;
  check-deployment-claims, check-image-inventory, check-doc-links,
  check-suite-inventory (13 suites match) all PASS.
- All issue-#291 acceptance surfaces re-inspected in-tree at this head:
  pinned CPython 3.13.15 + wheel pins (bip-utils 2.12.1 / coincurve 21.0.0 /
  pynacl 1.6.2) with in-build import+derive smoke test (Dockerfile);
  in-image verification steps for both profiles in security.yml `containers`
  job; identity_health distinguishes unavailable/misconfigured/operational/
  disabled; setup returns 503 before account creation on missing runtime or
  failed persistence; Setup.tsx disables the Crypto Identity toggle under
  checking/unavailable/misconfigured(except setup_incomplete); e2e asserts
  toBeDisabled() for unavailable and misconfigured health.
- Documentation consistency repair this round: the conditional-marker comment
  in backend/requirements.txt still claimed "the shipped Python 3.14 image
  intentionally omits it" — contradicting the support matrix (shipped image
  is 3.13.15 *with* the pinned wheel set). Comment rewritten to state the
  shipped contract and the enforced Python-3.14 boundary; no behavioral
  change (marker itself unchanged).

Independent verifier pass at merged head 78325c061 (auto-291 = branch merged
with develop 2c8022fe8; driver checks all green: uv sync --locked --extra dev,
ruff check, ruff format --check 2547 files, engine extra_guard 6 passed,
conductor test_api+test_identity_health+test_setup_guard 55 passed, suite
inventories ok for hive-conductor/backend/tests and maistro-core/tests):

- The develop merge touched image inputs (maistro-core source, conductor
  backend main.py/routes/services, Dockerfile, requirements.txt), so prior
  image provenance was stale for this head. Rebuilt BOTH profiles in this
  worktree at 78325c061: hive-conductor:l291-verify2 and
  hive-conductor-obs:l291-verify2. The Dockerfile in-build smoke test step
  (identity import + ConductorSeed.generate/did_key derivation + version
  assertions; opentelemetry imports under INSTALL_OBSERVABILITY=1) executed
  and passed in both builds.
- Both security.yml in-image verification commands executed verbatim against
  the fresh images: default profile printed
  `identity=operational python=3.13.15 bip-utils=2.12.1 coincurve=21.0.0
  pynacl=1.6.2` (msgpack>=1.2.1 and setuptools>=78.1.1 asserted); observability
  profile printed `observability=importable identity=operational
  python=3.13.15`.
- Merge survived identity wiring re-verified in-tree: routes/health.py wires
  identity_health into /health (identity, identity_required, degraded) and
  /health/ready checks; requirements.txt pins bip-utils==2.12.1 /
  coincurve==21.0.0 / pynacl==1.6.2 with the corrected 3.13-contract comment;
  security.yml retains both profile builds and both in-image verify steps.
- Gates re-run and witnessed at this head: engine identity 69 passed;
  tests/test_prepull_base_images.py 25 passed; conductor 55 passed (above).
- Live deployment contract re-observed at this head against a fresh
  hive-conductor:l291-verify2 container: /health reports
  identity={status: misconfigured, reason: setup_incomplete},
  identity_required=false, degraded=true; /health/ready reports
  checks.identity=false with ready=true (pre-setup is not a failed capability).
- Playwright e2e executed LIVE against the shipped image (frontend bundle from
  the image, PLAYWRIGHT_BASE_URL -> published port): 8/8 passed, including
  "does not offer crypto identity when the runtime is unavailable" and
  "... when the deployment is misconfigured" (both assert the Crypto Identity
  toggle toBeDisabled) and full setup completion on the live deployment.
- Closure-keyword audit: PR #1465 body says "Refs #291" only; no
  fixes/closes/resolves in any commit message on the branch.
- Live CI refresh (read-only gh pr view) at this head: prior MinIO findings
  resolved — "object storage (MinIO)" and "coverage (MinIO)" now SUCCESS;
  hive-conductor-e2e / e2e-ui / wheel-imports / lint-and-type / SAST /
  postgres pg17+pg18 / coverage(no-services, MinIO, PostgreSQL) SUCCESS.
  Later refreshes: docker-build (ci.yml) and integration-scope completed
  SUCCESS; CI test and the coverage gate were still in progress; gates-ran
  PENDING. Correction of attribution: ci.yml's docker-build is NOT the
  security.yml containers job — the containers job owns the in-image identity
  verification and is gated to PRs targeting main, merge groups to main, or
  nightly (security.yml `if:` on the containers job), so it structurally does
  not run on this develop-targeted PR. GitHub-side execution of the identity
  contract therefore remains UNVERIFIED by design for this PR (it fires at
  merge-to-main/nightly); the verbatim local in-image replication above is
  the evidence of record.

Independent verifier pass at head d68cd1ceb (auto-291 = branch merged with
develop 55c5ad892; all driver checks green, re-executed locally this round):

- Input-identity check: `git diff 78325c061..d68cd1ceb` over every
  identity-relevant path (Dockerfile, requirements.txt, health.py, setup.py,
  identity_health.py, conductor identity/setup tests, maistro-core identity
  source+tests+pyproject, support matrix, security.yml, Setup.tsx, e2e spec)
  is EMPTY — the deep image verification recorded above at 78325c061 (both
  profiles built, security.yml verify commands executed verbatim in-image,
  live Playwright 8/8, live /health observation) carries over byte-for-byte
  to this head.
- Re-executed at d68cd1ceb: uv sync ok; ruff check + format --check clean;
  engine identity extra_guard 6 passed; conductor test_api +
  test_identity_health + test_setup_guard 55 passed; FULL conductor backend
  suite 2728 passed / 5 skipped (no regressions from the develop merge);
  suite inventory gates ok for hive-conductor/backend/tests and
  maistro-core/tests.
- Live CI at this exact head (read-only gh pr view): hive-conductor-e2e and
  e2e-ui SUCCESS (updated setup.spec.ts runs green in GitHub CI);
  coverage (MinIO) and object storage (MinIO) SUCCESS (prior findings
  resolved by the develop merge); wheel-imports, lint-and-type-check, SAST,
  postgres pg17/pg18, Gate C, formal-conformance, supply-chain SUCCESS;
  docker-build and integration-scope completed SUCCESS at a later poll —
  ci.yml docker-build at d68cd1ceb executed the Dockerfile build-time
  identity smoke test (import + derive + version assertions) in GitHub CI.
  security.yml containers job remains SKIPPED on this develop-targeted PR by
  its main/merge_group/nightly `if:` — the nightly cron is the
  update-testing loop; its last execution evidence for this content is the
  verbatim local in-image replication recorded at 78325c061.
- Closure-keyword audit repeated at this head: PR body says "Refs #291" only;
  no fixes/closes/resolves in any commit message on the branch.
