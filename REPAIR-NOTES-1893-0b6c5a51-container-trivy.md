# REPAIR NOTES — issue #1893 round at 0b6c5a513a11 (job 836fe33f) — Container gate

## Frozen scope

Only issue #1893, branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
Exact starting HEAD `0b6c5a513a11f861723236fa0881f012b67e06f1` (verified; tree
clean). Merge-queue named failure: **`Container scan + SBOM + cosign`:
failure** (job 119604530527, run 39711775923). Driver battery already green at
this head (check-0..4 logs: uv sync, ruff check, ruff format --check 3439
files, focused pytest 273 passed / 3 skipped, suite inventory ok: 17535 unique
identities). No GitHub mutations; no Python/test changes (suite inventory
delta 0); no gate, ledger, grant, or workflow edits.

## Root cause (from the CI log, then reproduced locally)

The failed job's failing step is the first Trivy scan (`hive-conductor`
image). Job log (`gh api .../actions/jobs/119604530527/logs`) shows exactly:

- `usr/bin/age (gobinary)` + `usr/bin/age-keygen (gobinary)`: **1 finding each
  — CVE-2026-111943, HIGH, status fixed, installed stdlib v1.27.2, fixed
  1.26.10/1.27.3** (crypto/x509 MITM via untrusted intermediate certificates).
  `Total: 1 (HIGH: 1, CRITICAL: 0)`; nothing else flagged.

Both binaries are built from the pinned age v1.3.1 release tag by the
`agebuild` stage on the digest-pinned `golang:1.27.2-alpine`
(`packages/hive-conductor/Dockerfile:44` before this round). The same pin also
builds the static docker CLI (`Dockerfile:92`, `Dockerfile.research:55`), so
the maistro-engine / research Trivy steps (never reached in the failed run)
would flag the same CVE in their `/usr/local/bin/docker`.

Timeline proof the failure is CVE-DB-driven, not branch-caused: run
39686526132 at `807dfacca` (2026-10-21T22:26) passed the **entire** containers
job with image inputs identical to this head (branch diff vs develop touches
no Dockerfile, `.trivyignore.yaml`, `quality/license-policy.json`,
`pyproject.toml`, `uv.lock`, or frontend tree); the next run (2026-10-22,
Trivy DB cache key `cache-trivy-2026-10-22`) flagged the newly published CVE
in the same binaries.

## Repair (root cause, not an ignore entry)

Rebuild both release-tag-pinned binaries with the fixed toolchain — the same
policy the tree already documents for the 2026-01... rounds (CVE-2026-78667 /
78669 / 97031 fixed in go1.26.9/1.27.2); 1.27.3 supersedes it:

- `packages/hive-conductor/Dockerfile`: `FROM
  golang:1.27.3-alpine@sha256:b8c9b82affbbb82a020bbcf998dad2ba9516944ac7e883524642a481a9505e9c`
  (index digest; `docker buildx imagetools inspect golang:1.27.3-alpine`),
  comment records the toolchain move; `docker run ... go version` →
  `go1.27.3 linux/amd64`.
- `Dockerfile` + `Dockerfile.research`: same builder bump for
  `dockerclibuild`, comments updated.
- `quality/image-pins.json`: golang row moved to tag `1.27.3-alpine`, digest
  `sha256:b8c9b82a…`, `recorded 2026-10-22`, `recorded_in #1945`, note states
  the previous recording (#363) and the reason (CVE-2026-111943). The registry
  and the Dockerfiles hold each other closed; no digest survives unregistered.
- `.claude/skills/security-scan/SKILL.md`: base-image list updated to the new
  pin. The historical note
  `docs/testing/inventory-notes/issue-363-license-inventory.md` is left
  untouched — it is a dated record of #363's state.

No `.trivyignore.yaml` entry was added — the gate's documented policy is that
ignores are for findings a rebuild cannot resolve, and this one is resolved by
a rebuild.

## Executed validation (long timeouts; read output, not just exit codes)

Before-state reproduction:

- `docker build -f packages/hive-conductor/Dockerfile --target agebuild -t
  1893-age-before .` → exit 0 (old toolchain). `trivy image --severity
  HIGH,CRITICAL --ignore-unfixed 1893-age-before` (trivy v0.73.0, DB
  2026-10-22 — the same DB the failed CI run used): CVE-2026-111943 HIGH in
  every go1.27.2 gobinary — byte-identical to the CI finding (installed
  v1.27.2, fixed 1.26.10/1.27.3).

After-state:

- `uv run python scripts/check-image-pins.py` → exit 0 ("8 pinned base/tool
  image(s) across 10 Dockerfile(s), all registered").
- `uv run python scripts/check-image-inventory.py` → exit 0 (9 Dockerfiles;
  PUBLISHED 2 / DISTRIBUTED 4 / INTERNAL 3) — CI-exact commands per
  quality.yml.
- Rebuild `agebuild` on go1.27.3 → trivy (same argv): **exit 0, zero
  HIGH/CRITICAL, no CVE-2026-111943**.
- Rebuild root `dockerclibuild` on go1.27.3 → trivy: **exit 0, zero
  findings**.
- Full hive-conductor image rebuild (`--build-arg VITE_POC_MODE=pm
  --build-arg VITE_BASE_PATH=/pm/`) → exit 0; CI-exact Trivy step (`--severity
  HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml`) → **exit 0**; Grype cross-check (grype 0.116.0, sha256
  verified, `--fail-on high --only-fixed`) → **exit 0** (only pre-existing
  Medium python-binary rows; the gate fails on high only).
- CI's "Verify live Python packages and Conductor identity contract" step
  re-run against the rebuilt image → `identity=operational python=3.13.16`,
  exit 0.
- `uv run ruff check .` → pass; `uv run ruff format --check .` → pass (3439
  files). No Python changed, so check-3/4 results stand for this head.

Residual risk: the four-image Trivy matrix, frontend license SBOM steps, and
release-time provenance attestation are not re-executed locally; their inputs
are unchanged by this repair (the Go toolchain swap strictly reduces gobinary
findings; the same binaries' licenses are unchanged), and the full job last
passed green at `807dfacca`. go1.27.3 ≥ every fixed version named by both
scanners for the 2026 stdlib CVE set (78667/78669/97031 fixed in
1.26.9/1.27.2; 111943 fixed in 1.26.10/1.27.3).

Issue-#1893 scope reconciliation: B2 (admission codec) code and tests are
untouched and remain validated by the driver battery plus prior rounds' PG
durability evidence; this round repairs only the lane-named container gate.
No execution, authorization, or Goal-store surface touched.
