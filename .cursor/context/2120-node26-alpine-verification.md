# #2120 node 26-alpine bump — verification evidence (head 26ad95ed8; re-verified at a3d7830d8; repaired at 6a5a57079; lock-scan round below; develop-syncs at e5ed12174 and 641d5422e8; gates-ran repair below)

## Gates-ran repair round 2026-11-17 (heads 641d5422e8/fc525a8d86 verified + repaired; base f927334a2e)

CI DID run on fc525a8d86 (dispatch-context check-runs, captured 2026-11-17T06:01Z): **all 78 check-runs
success** except two legitimately skipped service jobs (strike-ladder, object storage (MinIO);
durable-events skipped) — including every previously-RED context: Coverage gate (publish-set floor +
diff coverage), Quality gate (Pillars 1–4,7,8), Quality / Image pins, Container scan + SBOM + cosign,
test, exact-debt-ledger, block. The only blocker: the `gates-ran` commit status stuck `pending` (created
05:42:28Z, never updated) — the merge-queue admission's "commit status not successful".

Root cause (CI-exact local evaluation with the live check-run payload and the measured PR changed-file
envelope): `check-gates-ran.py --check-runs <live> --require-complete --base-branch develop
--event-name pull_request --changed-files <envelope>` → PENDING, "not present yet (1): Mutation gate
(changed critical lines)". develop commit af2e36e242 (#2270, 2026-10-25 — inside base f927334a2e) made
mutation.yml a PR-triggered workflow with a `paths:` filter (packages/**/*.py + mutation governance
files) while check-required-checks.collect() still derives its check name into the required-evidence
set (72 required on PRs, verified locally). GitHub's paths filter does not create check-runs for
out-of-scope PRs, and evaluate() can only excuse checks that are in PATH_SCOPED_CHECKS AND present as
`skipped` — so every PR touching no `.py` file can never produce the run and gates-ran pends forever.
PR #1775's gates-ran success (no mutation run in its 31 check-runs) predates #2270, which is why the
class worked before.

Repair (additive, never weakens — the gate gains scope): mutation.yml `on.pull_request.paths` now lists
`quality/image-pins.json`, the recurring non-Python integrity surface this exact PR class changes (#93,
#1152, #1373, #2120). For such PRs the job now runs and reports real zero-overlap evidence ("No
mutation-critical file changed; nothing to mutate.") — all mutation-heavy steps are
`overlap == 'critical'`-gated, and `scripts/mutation_critical.py --validate` passes locally (rc=0).
For this PR the workflow also fires because the edit itself matches the existing
`.github/workflows/mutation.yml` filter path.

Repair validation at the edited tree: yaml parses; `check-required-checks.py` rc=0 ("77 PR checks match
docs/ci/REQUIRED-CHECKS.md; develop queue is SQUASH..."); actionlint 1.7.7 clean on mutation.yml;
tests/test_mutation_targets.py + tests/test_gates_ran_publisher_contract.py → 50 passed;
tests/test_check_gates_ran.py + test_check_required_checks.py + test_check_workflow_inventory.py +
test_check_workflow_write_safety.py + test_gates_ran_merge_group_scope.py → 211 passed. End-to-end
verdict proof: appending a synthetic successful "Mutation gate (changed critical lines)" run to the live
fc525a8d86 check-run set and re-running the evaluator CI-exact → `ok: all 72 required check(s) ran on
this head` (rc=0) — i.e. the new head's mutation success flips gates-ran to success and unblocks the
merge-queue admission.

Local re-validation carried out this round at fc525a8d86 (before the repair commit): check-image-pins
rc=0 (9 pins / 10 Dockerfiles), check-image-inventory rc=0, check-suite-inventory rc=0 (21 suites),
ruff check + format --check clean (3569 files), vulture ledger 1236=1236 (no Python changed; no
amendment), check-image-pins --base-digests Dockerfile packages/hive-conductor/Dockerfile rc=0 (lists
node:26-alpine@sha256:40cd011b…), uv lock --check rc=0, scoped battery tests/{test_check_image_pins,
test_pinned_digest_references,test_distribution_contract,test_check_image_inventory,
test_check_image_lock_reconciliation,test_image_lock_contract,test_prepull_base_images,
test_devskim_scan_scope}.py under coverage → 259 passed in 24.38s (incl. the devskim test that timed
out at 8b588456), check-diff-coverage.py coverage.xml --base f927334a2e3b → rc=0 "0 changed file(s)
measured". Docker proofs: `docker build --target frontend -f packages/hive-conductor/Dockerfile` rc=0;
in-image node v26.12.1 / npm 11.20.0 and dist/index.html present; the pinned digest pulls and runs
(v26.12.1); registry API confirms the pinned index manifest is live (200, amd64+arm64) — the mutable
26-alpine tag has since moved (6bd9ab43…) which is harmless: builds consume the immutable digest. The
develop-recipe × branch `-mod=mod` dockerclibuild combination (never CI-scanned at this shape) built
rc=0: `docker --version` = v29.9.3 build 5457199 and `go version -m` shows go-jose/v4 4.1.7,
klauspost/compress 1.20.2, golang.org/x/net 0.62.0 — the fixed module set the container scan requires.
No stale 22-alpine/0a7108bf references remain outside historical prose.

Residual (develop-side, out of this branch's scope): the merge-group required set (62 checks, verified
locally) also includes the mutation check, and mutation.yml has no `merge_group` trigger, so a queue
SHA's gates-ran evaluation would pend the same way; #2241 (post-#2270) nonetheless reached develop, so
queue-leg behavior needs develop-side evidence before touching trigger semantics. The PR-head fix here
is what the named admission failure requires.

## Develop-sync round 2026-11-17 (head 641d5422e8 = merge of origin/develop f927334a2e, M2-B1; PR-side head unchanged c4a49fb89f)

The PR went `mergeable_state: dirty` when develop advanced to f927334a2e (M2-B1, canonical Kata sandbox
backend); the merge-queue admission therefore saw no successful `gates-ran` status ("commit status not
successful"). Resolution: `git merge origin/develop` — zero conflicting files (branch touches 8 files vs
develop, none overlapping M2-B1's tree), committed as 641d5422e8. Merge-content audit:

- `git diff origin/develop HEAD -- '*.py'` is EMPTY and `git diff origin/develop HEAD -- uv.lock` is EMPTY:
  every Python-dependent gate (test, coverage floor, mypy/pyright, Python-side pillars) at this head consumes
  byte-identical inputs to develop's own CI-green run of f927334a2e. The branch's CVE lock bumps
  (playwright 1.65.2, patchright 1.64.4, temporalio 1.36.1, nexus-rpc 1.5.0, oauthlib 4.0.1, pyasn1 0.6.5)
  are all present in develop's lock (pypdf 7.1.0/soupsieve 4.1.1 moved further on develop); the merged lock
  delta vs the CI-green branch head c4a49fb89f is exactly pypdf, soupsieve and the macOS-only
  pyobjc-framework-pubsub row dropping out.
- Dockerfile / Dockerfile.research differ from develop ONLY in the #2120 comment blocks plus the branch's
  `-mod=mod` dockerclibuild flag (validated green in CI's container scan at c4a49fb89f); functional lines
  (DOCKER_CLI_VERSION=29.9.3, x/net v0.62.0, commit 5457199) are identical to develop's.
- packages/hive-conductor/Dockerfile is byte-identical to c4a49fb89f (node:26-alpine + digest pin — CI-green
  78/78 there); frontend package-locks unchanged since that run.
- quality/vulture-baseline.json multiset vs origin/develop: 12 identity rows, Counter-equal (AGENTS.md
  merge-loses-rows check); quality/ delta vs develop is image-pins.json only (the intended #2120 pin move).

Local re-validation at 641d5422e8 (uv.lock --check rc=0; uv sync --locked --all-extras OK; ruff check +
format --check clean): vulture ledger 1236=1236, radon 126=126, reachability rc=0 (88 modules, all
dispositioned), reachability-dispositions rc=0, promotion-surface ok, image-inventory rc=0,
check-image-pins rc=0 (9 pins / 10 Dockerfiles) + `--base-digests Dockerfile
packages/hive-conductor/Dockerfile` rc=0, workflow-inventory clean, backlog-consistency rc=0, pip-audit gate
CI-exact rc=0 (1 known = ecdsa, all triaged in ALLOWED). Scoped gate battery under coverage:
tests/{test_check_image_pins,test_pinned_digest_references,test_distribution_contract,
test_check_image_inventory,test_check_image_lock_reconciliation,test_image_lock_contract,
test_prepull_base_images,test_devskim_scan_scope}.py --timeout=120 -q → 259 passed in 31.61s (incl. the
devskim test that timed out at 8b588456). check-diff-coverage.py coverage.xml --base origin/develop → rc=0,
"0 changed file(s) measured". M2-B1 spot-check on merged state: test_single_authority.py +
test_canonical_sandbox.py + evolve test_sandbox_exec.py → 65 passed in 86.52s. Container subject proof:
`docker buildx build --target frontend` (node:26-alpine stage, CI build args) → npm ci + vite build rc=0,
in-stage `node --version` = v26.12.1 / npm 11.20.0; pinned digest sha256:40cd011b… pulls and matches
image-pins.json. Full-image build skipped deliberately: shared daemon at 18G free — every final-image input
(instructions, lock, package-locks) is byte-identical to a CI-green state on one side.

## Repair round 2026-11-16b (head 6a5a57079 + lock bumps; base f8a2df966): grype cross-check + rsi trivy surfaces

The 6a5a57079 fix for the research trivy scan was committed but never validated by CI (the following job died on a
provider 404 before running). This round re-validated it independently and, doing so, surfaced two scan surfaces
CI's job had never reached (both steps sit AFTER `Trivy scan maistro-engine-research`, which failed first at
262edeceb, so grype and the rsi trivy scan never executed on this branch):

- **grype 0.116.0 `--fail-on high --only-fixed` on maistro-engine-research** (rc=2): 5 findings, all node
  24.21.0 binaries — CVE-2026-111497 (Critical, kev), CVE-2026-105482/105483/106069 (High), fixed in
  24.22.1/26.12.1. Source: the driver `node` executables bundled inside the playwright and patchright wheels
  (`/app/venv/lib/python3.12/site-packages/{playwright,patchright}/driver/node`); trivy's node-pkg scan only reads
  package.json, so it never saw them.
- **`Trivy scan maistro-rsi-runner` at this head** (rc=1): 4 findings (1 Critical + 3 High), all in the `zip`
  crate 8.6.0 vendored inside `temporalio 1.34.0`'s `bridge/Cargo.lock` (CVE-2026-115905 fixed 9.0.5,
  CVE-2026-115907 fixed 9.0.0, +2). The wheel vendors the lock, so only a temporalio upgrade clears it.

Fixes (exact-and-only doctrine, upgrade-first — every finding had a published fix): uv.lock targeted bumps
playwright 1.64.0→1.65.2 (driver node v26.13.1), patchright 1.64.1→1.64.4 (driver node v24.22.1),
temporalio 1.34.0→1.36.1 (vendored zip crate 9.5.1), plus the forced transitive nexus-rpc 1.4.0→1.5.0.
Ship-surface isolation re-proven by CI-exact exports: playwright/patchright appear ONLY in the research contract
(`maistro-server --extra observability --extra browser`); temporalio ONLY in `--extra rsi-fitness`; engine
(`--extra image`), hive-conductor and rsi-python exports contain none of the browser packages, so those images'
dependency sets are unchanged. No Python source imports temporalio anywhere under packages/ (grep), so its bump
carries no call-site risk.

Local proof at the new head (docker 29.1.3, trivy 0.73.0 = CI's version, grype 0.116.0 = CI's version,
sha-verified): research image rebuilt via `scripts/buildx-build-retry.sh -- -f Dockerfile.research -t
maistro-engine-research:pr-2120 --no-cache-filter production-apt --load .` → rc=0; rsi image rebuilt with the
CI-exact `--no-cache-filter runtime-apt` → rc=0. Then, CI-exact arguments:

- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml` → rc=0 on
  BOTH maistro-engine-research:pr-2120 (was 15 HIGH) and maistro-rsi-runner:pr-2120 (was 4 HIGH/CRITICAL); 0
  findings on every scanned target.
- `grype <image> --fail-on high --only-fixed` → rc=0 on BOTH images (research was rc=2; only Unknown/Negligible
  rows remain, below the threshold).
- In-image proof: playwright driver node v26.13.1, patchright driver node v24.22.1, playwright 1.65.2,
  patchright 1.64.4 in the research image; temporalio 1.36.1 + nexus-rpc 1.5.0 in the rsi image.
- `check-image-lock-reconciliation.py` CI-exact per image (research: `--member maistro-core==0.9.0 --member
  maistro-server==0.9.0`; rsi: `--python /workspace/.venv/bin/python` + 4 members) → rc=0 both ("ships exactly
  the locked set").
- pip-audit gate CI-exact (`uv pip freeze --exclude-editable` → strict audit → pip_audit_gate.py) → rc=0, "1
  known, all triaged in ALLOWED" (ecdsa only; the bumped packages carry no advisories).
- `check-image-pins.py` (9 pins / 10 Dockerfiles), `check-image-inventory.py`, `check-image-pins.py
  --base-digests Dockerfile packages/hive-conductor/Dockerfile`, `check-suite-inventory.py` (21 suites) → all
  rc=0.
- Quality pillars CI-exact: vulture ledger 1238=1238, radon 126=126, reachability rc=0 (88 unreachable, all
  dispositioned), reachability-dispositions rc=0, promotion-surface rc=0; ruff check + format rc=0.
- Scoped pytest under `coverage run --branch --source=scripts`: tests/{test_check_image_pins,
  test_pinned_digest_references,test_distribution_contract,test_check_image_inventory,
  test_check_image_lock_reconciliation,test_image_lock_contract,test_prepull_base_images,
  test_devskim_scan_scope}.py --timeout=120 -q → 259 passed in 32.21s (includes the devskim test that timed out
  in the pre-sync CI run at 8b588456).
- Diff-coverage gate CI-exact (`check-diff-coverage.py coverage.xml --base f8a2df966`) → rc=0: 0 measured files,
  1 exempt — `tests/test_distribution_contract.py`, "test code is the evidence, not the thing evidenced"
  (check-diff-coverage.py EXEMPT declaration); the sole .py change vs base is its 1-line python-tag assertion
  update.

Environment notes for reproducers: trivy's first run died with `no space left on device` writing to the /tmp
tmpfs (32G, shared, near-full) while unpacking the chrome-headless-shell layer — not a scan finding; rerun with
`TMPDIR` on a large disk. Grype CLI installed to ~/.local/bin from the CI-pinned v0.116.0 tarball (sha256
40aff724… checked).

## Repair round 2026-11-16 (head 262edeceb; base f8a2df966): Trivy scan of maistro-engine-research

At head 262edeceb the only RED check is "Container scan + SBOM + cosign" (run 43843632088, job 133218221240;
all other 77 checks green, including the previously-RED Coverage, Quality and test contexts). The failing step
is `Trivy scan maistro-engine-research (HIGH/CRITICAL only)` — 15 HIGH findings, two surfaces:

- `usr/local/bin/docker` (gobinary): CVE-2026-116587 (go-jose/v4 4.1.5, fixed 4.1.6) and CVE-2026-78661
  (golang.org/x/net 0.60.0, fixed 0.62.0). Root cause: commit 8b5884567 added the `go get` module upgrades to
  the ROOT Dockerfile's dockerclibuild stage only — Dockerfile.research rebuilt the same pinned tag (v29.9.1,
  dfc520d) from the stock vendor.mod, so its CLI kept the vulnerable module set.
- python-pkg in the locked venv: oauthlib 4.0.0 (CVE-2026-49272), pyasn1 0.6.4 (CVE-2026-119194…119197),
  pypdf 6.21.2 (CVE-2026-119203…119209), soupsieve 3.0.3 (CVE-2026-126190) — all with published fixes
  (4.0.1 / 0.6.5 / 6.21.4 / 4.0.0), so per the gate's own policy (upgrade first, allowlist only when no fix
  exists) the lock moved, exactly and only, to the fix versions (`uv lock -P <pkg>==<fix>`), the same doctrine
  as 375232984. The four ship ONLY in the research image's dependency contract
  (`maistro-server --extra observability --extra browser`); the engine/rsi/hive-conductor exports are
  unchanged, matching CI's green scans of those images at the same head.

Fixes: Dockerfile.research dockerclibuild mirrors the root Dockerfile's `go get go-jose@v4.1.6
klauspost@v1.20.2 x/net@v0.62.0` + `-mod=mod` build (tag/commit assertion unchanged); uv.lock carries the four
version bumps. Local proof at the new head:

- `scripts/buildx-build-retry.sh -- -f Dockerfile.research -t maistro-engine-research:pr-2120
  --no-cache-filter production-apt --load .` → rc=0; in-image: oauthlib 4.0.1, pyasn1 0.6.5, pypdf 6.21.4,
  soupsieve 4.0, `docker --version` = v29.9.1, build dfc520d.
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml
  maistro-engine-research:pr-2120` (trivy v0.73.0, DB 2026-11-16) → **rc=0, 0 findings on every target**
  (debian 13.7: 0; usr/local/bin/docker gobinary: 0; all python-pkg: 0).
- `uv run python scripts/check-image-pins.py` / `check-image-inventory.py` / `--base-digests Dockerfile
  packages/hive-conductor/Dockerfile` → all rc=0; `check-suite-inventory.py` → 21 suites match; ruff
  check/format green; scoped pytest (image pins, pinned digests, distribution contract, inventory, lock
  reconciliation, image lock contract, prepull) → 238 passed.
- Supply chain (pip-audit): CI-exact freeze (`uv sync --locked --all-extras`) → `pip-audit --strict` report →
  `scripts/pip_audit_gate.py` → "pip-audit OK (1 known, all triaged in ALLOWED)" (ecdsa only; the four bumped
  packages are not in the workspace env — CI's pip-audit never covered them; they are image-scanned).
- Vulture ledger (CI-repair round check): `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1238 reviewed identities = 1238 findings; no amendment needed (no Python
  source changed).

Status of the dependabot bump branch `dependabot/docker/packages/hive-conductor/node-25-alpine`
at exact head `26ad95ed8aceafa7195e29b03f46b8b2d034ade9` (base `78133c093`), verified
2026-10-26 by an independent round (job `22c97181d0764991a9f7155fee7ff678`).

## Re-verification at head a3d7830d8 (develop-sync merge; base 10f872fa7) — 2026-10-26, job 00b4994fdb6e404c9b83c1f3b09de23b

Branch diff vs develop base `10f872fa7` is exactly 3 files, zero Python:
`packages/hive-conductor/Dockerfile`, `quality/image-pins.json`, this context doc.
All gates re-run at the new head with CI's exact arguments, all green:

- `uv run python scripts/check-image-pins.py` → rc=0, 9 pins / 10 Dockerfiles (quality.yml:2244)
- `uv run python scripts/check-image-inventory.py` → rc=0 (quality.yml:2201)
- `python3 scripts/check-image-pins.py --base-digests Dockerfile packages/hive-conductor/Dockerfile` → rc=0, `node:26-alpine@sha256:40cd011b…` listed (release.yml:797)
- `uv run python scripts/check-suite-inventory.py` → rc=0, 21 suites, 35149 IDs match baseline (ci.yml:723). Note: bare `python` (as CI names it, with deps preinstalled) fails locally with `ModuleNotFoundError: pydantic` — run under `uv run` per AGENTS.md.
- `uv run python scripts/check-diff-coverage.py coverage.xml --base 10f872fa7…` → rc=0, "0 changed file(s) measured" (coverage.xml generated from a scoped pytest run, then deleted)
- `uv run ruff check .` / `uv run ruff format --check .` → green (3557 files)
- `tests/test_check_image_pins.py` + `test_pinned_digest_references.py` + `test_distribution_contract.py`: 52 passed; adjacent `test_check_image_inventory.py` + `test_check_image_lock_reconciliation.py` + `test_image_lock_contract.py` + `test_prepull_base_images.py`: 177 passed
- Registry re-verified independently (auth.docker.io token + registry-1.docker.io): tag `library/node:26-alpine` → `docker-content-digest: sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797`, OCI index, platforms linux/amd64 + linux/arm64 (+2 attestation) — exact match to Dockerfile pin and image-pins.json row
- `docker pull` of the pinned digest → OK; `node --version` in the container → v26.12.1; the Dockerfile's frontend stage run verbatim in the pinned image (`npm ci` + `npm run build` = tsc×2 + vite) → ✓ built in 2.12s
- Residual re-checked: zero references to `22-alpine` under `scripts/` or `.github/workflows/`; the SKILL.md mention remains a doc example no gate reads.

The previously-named RED "test" and "Quality gate (Pillars)" contexts score Python this diff does not touch (0 `.py` files changed); the develop-sync merge `a3d7830d8` levels the branch with develop.

## The change

`git diff 4019249e8...HEAD` (merge-base diff, same as the PR's three-dot view) is exactly
two files: `packages/hive-conductor/Dockerfile` (FROM node:22-alpine@sha256:0a7108bf… →
node:26-alpine@sha256:40cd011b…, resolution comment updated) and `quality/image-pins.json`
(node row 22-alpine → 26-alpine, `recorded_in: #2120`). Zero Python lines. The repair
commit registering the pin is `72509bb38`; the develop-sync merge is `26ad95ed8`.

## Gate evidence (CI exact arguments)

| Gate | CI invocation (workflow:line) | Result |
|---|---|---|
| Quality / Image pins | `uv run python scripts/check-image-pins.py` (quality.yml:2240) | rc=0, 9 pins / 10 Dockerfiles |
| Image inventory | `uv run python scripts/check-image-inventory.py` (quality.yml:2197) | rc=0 |
| Release base digests | `check-image-pins.py --base-digests Dockerfile packages/hive-conductor/Dockerfile` (release.yml:797) | rc=0, node:26-alpine@sha256:40cd011b… listed |
| Diff coverage | `check-diff-coverage.py coverage.xml --base <base>` (quality.yml:759) | rc=0 with base `78133c093` and merge-base `4019249e8`: "0 changed file(s) measured" — non-.py files are `ignored` by classify() (check-diff-coverage.py:219), so the vacuous pass is structural |
| Suite inventory | `python scripts/check-suite-inventory.py` (ci.yml:723) | rc=0, 21 suites, 34691 IDs match baseline |
| Ruff check/format | driver job check-0/1/2.log | All checks passed; 3529 files formatted |

## Test evidence

- `tests/test_check_image_pins.py` (includes the previously RED
  `test_dunder_main_entrypoint_runs_the_real_gate`, which runs the real gate on the
  shipped tree): 38 passed.
- The other tests that read `quality/image-pins.json`, `tests/test_pinned_digest_references.py`
  and `tests/test_distribution_contract.py`: 14 passed.

## Digest and runtime evidence (re-verified 2026-10-26, not carried from prior rounds)

- Docker Hub registry API: tag `library/node:26-alpine` → index digest
  `sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797`
  (4 platform manifests, linux/amd64 present) — exact match to both the Dockerfile pin
  and the registry row.
- `docker pull` of the pinned digest: exit 0; `node --version` in the container → v26.12.1.
- Full frontend build inside the pinned image (bind-mounted repo,
  `packages/hive-conductor/frontend`): `npm ci` + `npm run build` (tsc + vite) succeeded,
  built in 2.00s.

## Residuals

- `.claude/skills/security-scan/SKILL.md` still shows a `22-alpine` string in a doc
  example; no gate or test reads it (grep over scripts/ and workflows is empty). Cosmetic,
  out of scope for this repair round.
- The four named RED gates from the prior attempt (Coverage, Quality / Image pins,
  Quality gate cascade, test) each trace to the single missing registry row fixed in
  `72509bb38`; the aggregator's other pillars (2, 3, 4, 7, 8) score Python the diff does
  not touch.
- The develop-sync merge commits (e5ed12174, 641d5422e8) are local-only; CI has not run
  on them. The merge-queue evaluation needs the pushed branch to re-run Gates Ran;
  the head is conflict-free against develop f927334a2e as of 2026-11-17.
