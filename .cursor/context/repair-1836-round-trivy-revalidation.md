# Repair #1836 round — rsi-runner trivy failure independently re-validated (branch auto-1836, head 73fd7bf3e9c3)

Starting head `73fd7bf3e9c346032d558db41ca29cdbed2d8d80` (assigned, clean),
base `4de7e906d9dc9f74ed47f240abc94221db102a66`. This round re-derived every
claim from primary evidence; no prior verification was trusted unverified.

## The named CI gate failure, from the actual job log

Job `120830352564` ("Container scan + SBOM + cosign", run 40079655352, head
`73fd7bf3e9c3`, failed 2026-10-24T09:08:19Z) — fetched read-only via
`gh api .../actions/jobs/120830352564/logs` this round. The failing step is
the **`Trivy scan maistro-rsi-runner`** step: `maistro-rsi-runner:pr-2264
(debian 13.7)` — `libbrotli1 CVE-2026-111497 HIGH, installed 1.1.0-2+b7,
fixed 1.1.0-2+deb13u1`. The `npm audit fix` lines in the log digest are the
hive frontend `npm ci` advisory footer inside a build step that exited 0;
the hive-conductor, maistro-engine and maistro-engine-research trivy scans
in the same job all reported clean.

## The scan contradicted its own build

Inside that same job, the rsi-runner build's `--no-cache-filter runtime-apt`
stage installed the FIXED package (`Get:54 ... libbrotli1 amd64
1.1.0-2+deb13u1` → `Unpacking` → `Setting up`, 09:01:35–09:01:41Z), exported
manifest `sha256:95841ce4...`, loaded to the daemon — and the 09:07:37Z scan
of the same tag still reported installed `1.1.0-2+b7`. `Dockerfile.rsi-runner`
has exactly one apt stage (`runtime-apt`) and the final stage is
`FROM runtime-apt`, so there is no second apt path that could carry b7. The
scanned image content cannot have been b7; the finding is a scanner-side
artifact (stale trivy artifact/scan cache restored via actions/cache or a DB
snapshot race), not a tree defect.

## Local CI-exact reproduction this round (proof, not assumption)

- `docker buildx build --no-cache-filter runtime-apt -f Dockerfile.rsi-runner
  -t maistro-rsi-runner:pr-2264 --load .` → rc 0 (build succeeded).
- `dpkg -s libbrotli1` inside that image → `Version: 1.1.0-2+deb13u1`.
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml maistro-rsi-runner:pr-2264` with trivy
  **0.73.0** (CI's pinned version), DB updated 2026-10-24 → **rc 0, zero
  HIGH/CRITICAL**.

No Dockerfile, workflow, lock, or ignore-file change was made: the finding is
scanner-side and self-heals on re-run; suppression would violate
`.trivyignore.yaml`'s own policy and weaken the gate.

## Every other gate re-validated at this head

- Fetched check-runs for `73fd7bf3e9c3`: **72 success / 1 failure** — the
  failure is only the containers job above. Includes green: test (canvas
  `npm audit --audit-level=high`, ci.yml:698), Supply chain (pip-audit),
  SAST/Gitleaks, exact-debt-ledger, Validate ADR/spec front-matter,
  Quality / Acceptance state, docker-build, integration-scope.
- Re-run locally this round: `check-adr-status-language.py` rc 0;
  `git diff --check` rc 0 (the issue's deterministic acceptance command);
  CI-exact `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` rc 0 (1302 reviewed == 1302 findings, 0
  unclassified, 0 never-allowlist → the CI-repair ledger clause is vacuous,
  no `quality/` ledger edit needed); canvas `npm audit --audit-level=high`
  rc 0; `pip_audit_gate.py` rc 0 (ecdsa PYSEC-2026-1325 remains the sole
  triaged advisory); `check-suite-inventory.py` rc 0 (21 suites match — no
  test added/moved, no inventory note owed); ruff check + format --check rc 0.
- Develop sync: `origin/develop` fetched == merge-base ==
  `4de7e906d9dc`; branch = base + exactly the 6 in-scope files; no conflict.
- Diff audit: `uv.lock` bumps are the pip-audit-gate repairs (fastmcp
  4.0.11→4.1.3 for GHSA-7xgj-8392-5q4r/GHSA-vqqp-x5qm-5qp4, pypdf→6.21.2,
  setuptools→84.2.1); canvas `package-lock.json` is the `npm audit fix
  --package-lock-only` repair for ci.yml:698 (3 HIGH: body-parser, undici,
  zod); `.gitleaks.toml` adds a content-scoped `generic-api-key`-only
  allowlist for the W3C did:key spec's published example DID
  (`z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK`), quoted verbatim at
  SPEC-101826-1836 line 307 as a byte-pinned golden-vector input — a public
  test vector that authenticates to nothing; any other credential-shaped
  value in the document still fails closed.

## Decision-gate posture (unchanged, by design)

SPEC-101826-1836 revision 5 declares `status: Proposed`, `contracts: []`,
gate open, downstream blocked-by-gate. Per the issue text, a hygiene command
cannot prove the owner decision: ADR-owner acceptance of the payload contract
remains **open by design** and stays visibly open. No code, test, or gate
change claims it.

## Residual

- Hosted re-run of the containers job is outside writer power (no GitHub
  mutations); the gate self-heals via `--no-cache-filter` on the next
  merge-queue evaluation.
- Owner acceptance of SPEC-101826-1836 is the issue's actual completion
  condition and remains with the ADR owner.

Note-only round: this file is the only change; no tree, gate, or inventory
delta.
