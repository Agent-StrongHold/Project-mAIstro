# Issue 76 container-gate repair (CI-repair round, 2026-11-16)

No inventory delta: no test counts moved. The only test edit updates the asserted interpreter
tag in `tests/test_distribution_contract.py` (3.13.16 -> 3.13.18) to match the
refreshed base-image pin. This note records the CI-repair evidence for the
"Container scan + SBOM + cosign" gate.

## Failing gate (GitHub run 43822789023, job 133149494061, head ca35d2d7)

Step outline (fetched via `gh run view`): every "Build ..." step and the first
Trivy scan (hive-conductor) passed; **"Trivy scan maistro-engine
(HIGH/CRITICAL only)" failed** with exactly two findings in
`usr/local/bin/docker` (gobinary):

- CVE-2026-116587 — github.com/go-jose/go-jose/v4 v4.1.5, fixed v4.1.6 (HIGH,
  DoS via crafted RSA parameters in JWKs)
- CVE-2026-78661 — golang.org/x/net v0.60.0, fixed v0.62.0 (HIGH, DoS via
  crafted HTML input)

(The `npm audit` lines in earlier findings were tail noise from the successful
hive-conductor frontend build, not the failure.)

## Fix under review (uncommitted salvage, re-validated locally)

1. `Dockerfile` + `Dockerfile.research` dockerclibuild stage: patch the
   v29.9.1 release tag's vendored tree with
   `go get github.com/go-jose/go-jose/v4@v4.1.6 golang.org/x/net@v0.62.0
   github.com/klauspost/compress@v1.20.2 && go mod vendor` (same
   patch-the-release-tag policy the file already applies to the Go toolchain).
2. Base-image digest refreshes recorded in `quality/image-pins.json`:
   python:3.13.16-slim-bookworm -> 3.13.18 (grype Critical CVE-2026-115557 in
   the CPython binary, fixed 3.13.18) and python:3.12-slim -> 3.12.16 (same
   Critical, fixed 3.12.16), propagated to the version assertions in
   `packages/hive-conductor/Dockerfile`, `.github/workflows/security.yml`, and
   `scripts/smoke-engine-canvas.sh`.
3. `uv.lock` transitive bumps (none imported by `packages/*/src` — verified by
   grep) resolving fresh PyPI advisories.

## Local re-execution evidence (this host, 2026-11-16)

- `docker build --no-cache -f Dockerfile --target dockerclibuild` — exit 0:
  the patched vendored tree builds (`go get` + `go mod vendor` + `go build`),
  binary reports `Docker version v29.9.1, build dfc520d`.
- `docker build -f Dockerfile -t maistro-engine:pr-2241` — exit 0; runtime
  python reports 3.13.18.
- trivy v0.73.0, fresh DB (2026-11-16), CI flags `--severity HIGH,CRITICAL
  --ignore-unfixed --exit-code 1 --ignorefile .trivyignore.yaml` — all four
  gate images, all exit 0: **maistro-engine** (`usr/local/bin/docker
  gobinary  0` findings), **hive-conductor**,
  **maistro-engine-research**, **maistro-rsi-runner**.
- grype v0.116.0 (checksum-verified), `--fail-on high --only-fixed` — all
  four gate images, all exit 0: maistro-engine, hive-conductor (built exit 0
  with the in-image `(3, 13, 18)` identity assert; the workflow's
  identity-contract step was re-run verbatim and printed
  `identity=operational python=3.13.18 ...`), maistro-engine-research,
  maistro-rsi-runner.
- `scripts/check-image-lock-reconciliation.py` re-run verbatim against the
  locally built maistro-engine (new uv.lock export vs image contents):
  `OK: maistro-engine:pr-2241 ships exactly the locked set (126
  distributions, incl. 3 workspace member(s))`, exit 0.
- Old python:3.12-slim digest vs new: grype flags CPython 3.12.15
  CVE-2026-115557 **Critical** (fixed *3.12.16); the new digest resolves
  Python 3.12.16 and no longer carries it. zlib1g Highs (CVE-2026-76844 /
  CVE-2026-85091, fixed only in trixie deb13u1) pre-exist on BOTH base digests
  and are resolved by the images' `apt-get upgrade` stages (same
  trixie-security doctrine already documented in `.trivyignore.yaml` for
  libbrotli1).
- `uv sync --locked --all-extras` + pip-audit `--strict` +
  `scripts/pip_audit_gate.py`: gate exit 0 (only the already-triaged
  `ecdsa==0.19.2 PYSEC-2026-1325`).
- `uv lock --check`: consistent. `uv run ruff check .` /
  `ruff format --check .`: clean. `uv run pytest
  tests/test_distribution_contract.py`: 6 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 0 (1238 reviewed
  identities -> 1236 findings, no unbanked rows).

## Repair round re-validation (2026-11-16, head 005e98d58 + this fix)

This note originally opened with an `inventory-delta: {}` front-matter block.
`check-suite-inventory.py` rejects that shape (a value on the key's own line
is unreadable, and an empty block would be "records nothing"), so the block
is removed: no front matter records no delta, the documented convention for a
change that moved no count (see the directory README and the precedent in
`859-container-gate-base-pin-refresh.md`). Fresh re-execution at this head:

- `scripts/check-suite-inventory.py`: full run exit 0 (21 suites match the
  recorded inventory; 35,389 collected node IDs, 0 duplicate identities) and
  all five `--suite` per-suite invocations exit 0.
- targeted sandbox/harness pytest (the 26-file verifier battery): 465 passed,
  8 skipped.
- `ruff check` / `ruff format --check`: clean. `uv lock --check`: consistent.
- vulture gate, CI arguments: exit 0 (1238 reviewed identities -> 1236
  findings).
- pip-audit gate (`pip_audit_gate.py` over `pip-audit --strict`): exit 0
  (only the triaged `ecdsa==0.19.2 PYSEC-2026-1325`).
- image-lock reconciliation (`check-image-lock-reconciliation.py` vs
  `maistro-engine:pr-2241`, CI's exact export): exit 0 — ships exactly the
  locked set (126 distributions, 3 workspace members).
- Trivy v0.73.0 with the gate's flags (`--severity HIGH,CRITICAL
  --ignore-unfixed --exit-code 1 --ignorefile .trivyignore.yaml`) on all four
  gate images, all exit 0; maistro-engine's `usr/local/bin/docker` gobinary
  reports 0 findings.

## Independent verification round (2026-11-16, head f27177c38e45b8be946f3d554a2b978f24dea1af)

Re-executed at the head SHA by the verifier lane; all commands run locally with
CI's exact arguments unless noted. No test counts moved; still no inventory delta.

- Base-pin resolution (decisive): `docker run --entrypoint python` on the two
  digest-pinned bases — `python:3.13.18-slim-bookworm@sha256:a5a7017efc59…`
  reports **Python 3.13.18**, `python:3.12-slim@sha256:5e2bdb1b0d5425…` reports
  **Python 3.12.16**. The Dockerfile in Docker wins over the tag, so this
  proves the branch's pins resolve to the fixed CPython builds, matching the
  `(3, 13, 18)` interpreter assertion in `security.yml` (lines 325, 331).
- Trivy v0.73.0, CI flags (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed --ignorefile .trivyignore.yaml`): exit 0 on
  `maistro-engine:pr-2241` (the CI-named artifact; `usr/local/bin/docker`
  gobinary: 0 findings — the CVE-2026-116587 go-jose / CVE-2026-78661 x/net
  findings that failed run 43822789023 are gone) and on
  `maistro-engine:pr-localrepair`, `hive-conductor:pr-localrepair`,
  `maistro-engine-research:pr-localrepair`, `maistro-rsi-runner:pr-localrepair`.
- Image-lock reconciliation, CI's exact export (`uv export --locked --package
  maistro-server --extra image --no-dev --no-emit-workspace`): exit 0 —
  `maistro-engine:pr-2241` ships exactly the locked set (126 distributions,
  3 workspace members).
- `uv lock --check` consistent; `pip_audit_gate.py` over
  `pip-audit --strict` exit 0 (only triaged `ecdsa==0.19.2
  PYSEC-2026-1325`); `check-dependency-namespaces.py` exit 0.
- Vulture gate, CI arguments (`vulture packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` + `check-vulture-baseline.py`): both exit 0.
- Full `scripts/check-suite-inventory.py`: 21 suites match, 35,389 unique node
  IDs; targeted 26-file sandbox/harness pytest: 465 passed, 8 skipped (the 8
  skips are all bubblewrap host-capability skips; the server SIGTERM suite
  runs 3 passed / 0 skipped, including the orphan-cleanup stop/restart test).
- `ruff check .` / `ruff format --check .`: clean.

### Attribution caveat — stale local `pr-localrepair` images

The shared daemon's `hive-conductor:pr-localrepair`
(`maistro-engine-research:pr-localrepair`,
`maistro-rsi-runner:pr-localrepair`) images created 2026-11-16 08:29–08:44
local contain **CPython 3.13.16 / 3.12.15** (grype
`--only-fixed --fail-on high` flags Critical CVE-2026-115557 in them; trivy
does not detect the CPython binary version and passes). They predate the
base-pin refresh and were not built from this head — the digest resolution
above proves this head's Dockerfiles produce 3.13.18 / 3.12.16. Do not read
those local images as evidence about this branch; CI builds fresh images from
the branch Dockerfiles. Grype on freshly built research/hive/rsi images was
not re-executed locally (no correctly built images available on this daemon);
it remains corroborated by the pin resolution plus the earlier round's local
passes, and by GitHub CI as the final authority.

## Repair round: rebuild regression and recovery merge (2026-11-16, this round)

**Root cause of the renewed "Container scan + SBOM + cosign" failure at the
merge-queue evaluation of the rebuilt head `d1ce53600c`:** that rebuild commit
claimed to "re-apply orphaned lane history onto develop" but carried only the
final 152-line inventory note — the 89-file implementation diff (Kata backend,
`tools/sandbox/docker.py` retirement, the Dockerfile digest-pin refreshes, the
dockerclibuild go-jose/x/net patches, `quality/image-pins.json` rows) was
dropped. The gate then failed because the tree no longer contained the repair
it had previously passed with.

**Fix:** recovery merge `6c59a926aa` merging the orphaned chain tip
`a4ef00a066` into the rebuilt branch. Pre-verified with `git merge-tree
--write-tree` (`59052a9320…`, no conflicts) and confirmed post-merge:
`HEAD^{tree} == a4ef00a066^{tree} == 59052a9320…` — i.e. the working tree is
byte-identical to the state the prior verification battery passed on. No
history rewrite; `d1ce53600c` remains an ancestor.

**Re-executed evidence at merge head `6c59a926aa` (this host, this round):**

- `ruff check .` / `ruff format --check .`: clean (3568 files formatted).
- Targeted 26-file sandbox/harness/pytest battery: **465 passed, 8 skipped**
  (same 8 bubblewrap host-capability skips).
- `test_kata_live_conformance.py`: **10/10 PASSED live** (4 supported-policy
  real-workload launches; deny host-files/sockets/network/privilege; transfer,
  budget, overflow, timeout, cancellation).
- Suite inventory: bootstrap/core/evolve/rsi/server suites all `ok`.
- Vulture ledger gate, CI exact arguments
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): exit 0 (1238 reviewed identities → 1236 findings,
  base f8a2df966a1d).
- pip-audit gate per security.yml recipe (`uv sync --locked --all-extras`,
  `uv pip freeze --exclude-editable`, `pip-audit --strict`,
  `scripts/pip_audit_gate.py`): gate exit 0 (`ecdsa==0.19.2
  PYSEC-2026-1325` triaged).
- `scripts/check-image-pins.py`: exit 0 (9 pins / 10 Dockerfiles registered).
- **maistro-engine rebuilt locally from this tree** (`docker build -f
  Dockerfile -t maistro-engine:pr-2241 .`, warm-cache 4.6 s — layer cache from
  the prior round's build of the byte-identical tree):
  - Trivy 0.73.0, CI flags (`--severity HIGH,CRITICAL --exit-code 1
    --ignore-unfixed --ignorefile .trivyignore.yaml`): **exit 0**
    (docker gobinary: 0 findings — both CVE-2026-116587/CVE-2026-78661 gone).
  - Grype 0.116.0, CI flags (`--fail-on high --only-fixed`): **exit 0**
    (6 only-fixed matches, all Medium/Low/Unknown; the CPython Critical
    CVE-2026-115557 is gone at 3.13.18).
  - Lock reconciliation, CI exact args (`uv export --locked --package
    maistro-server --extra image --no-dev --no-emit-workspace` +
    `check-image-lock-reconciliation.py`): exit 0 — "ships exactly the locked
    set (126 distributions)".
  - In-image assertion: runtime python is **3.13.18**; base digest
    `sha256:a5a7017…` resolves to docker-library python
    `3.13/slim-bookworm`.

No inventory delta: no test counts moved in this round (merge only restores
previously counted tests; the battery total matches the recorded baseline).
