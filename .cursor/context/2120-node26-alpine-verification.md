# #2120 node 26-alpine bump — verification evidence (head 26ad95ed8; re-verified at a3d7830d8)

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
