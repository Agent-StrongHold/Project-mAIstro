# Repair #859 — container-gate red X: age/docker-CLI Go toolchain carried CVE-2026-111943 (branch auto-859, head be75dd8c7)

Starting head `be75dd8c7f39ed4669ef4f0b982f4ab13a900228` (unchanged by this
round's work until the repair commit). Worktree arrived clean. Prior verify job
(6989a7dd) had judged this exact head MERGE-READY on the issue acceptance; the
only red was the `security.yml` / `containers` job ("Container scan + SBOM +
cosign") on PR #2209, run 39708149532, job 119592929257. No develop drift:
branch base c29e0ea70 is still origin/develop's tip.

## 1. Root cause (from the CI log, not guessed)

The failing step is `Trivy scan (HIGH/CRITICAL only)` on
`hive-conductor:pr-2209`. The one finding:

```
usr/bin/age-keygen (gobinary)
Total: 1 (HIGH: 1, CRITICAL: 0)
stdlib  CVE-2026-111943  HIGH  fixed  v1.27.2  fixed: 1.26.10, 1.27.3
        crypto/x509: Man-in-the-middle attacks via untrusted intermediate certificates
```

The `agebuild` stage in `packages/hive-conductor/Dockerfile` builds age v1.3.1
from the immutable release tag on the digest-pinned `golang:1.27.2-alpine`
toolchain (the #363 policy for keeping 2026 stdlib fixes out of shipped Go
binaries). A *new* stdlib advisory (CVE-2026-111943, fixed in go1.27.3)
postdates that pin, so every Go binary the 1.27.2 toolchain emits — age,
age-keygen, and the docker CLI built by the identical `dockerclibuild` stages
in `Dockerfile` and `Dockerfile.research` — now carries a HIGH+fixed finding.
The hive-conductor scan runs first, so the engine/research scans never got a
chance to report the same root cause from the docker CLI.

## 2. Fix (same policy as #363: rebuild on the patched toolchain, no suppression)

`.trivyignore.yaml` keeps `vulnerabilities: []` on purpose; the fix is the
toolchain refresh, not an ignore entry:

- `golang:1.27.2-alpine@sha256:f92b6ef8…` →
  `golang:1.27.3-alpine@sha256:d530cf60723abf1ffae0cd16bb546b379ec0550d2f3815e5b16ed69dbc00fba4`
  in `packages/hive-conductor/Dockerfile` (agebuild), `Dockerfile`
  (dockerclibuild), `Dockerfile.research` (dockerclibuild). Digest is the
  manifest-list index digest of the tag (verified via
  `docker buildx imagetools inspect`).
- `quality/image-pins.json` golang row refreshed (tag, digest, recorded
  2026-10-22, recorded_in #2209, note names CVE-2026-111943).
- Stage comments state the refresh and the CVE; `.claude/skills/security-scan/SKILL.md`
  base-image list updated to 1.27.3.

## 3. Evidence (executed locally, fresh trivy DB 2026-10-22 = CI's DB day)

- Negative control: trivy on the go1.27.2-built age binaries
  (`age-old-bins-891:test`, left by an earlier round) reproduces exactly the CI
  finding — 1 HIGH, CVE-2026-111943, fixed, v1.27.2.
- Rebuilt age v1.3.1 @ b8564ad on go1.27.3 (`go version` in-image:
  go1.27.3): `usr/bin/age`, `usr/bin/age-keygen` → 0 HIGH/CRITICAL
  (trivy, HIGH/CRITICAL, ignore-unfixed, repo ignorefile).
- Rebuilt docker CLI v29.9.1 @ dfc520d on go1.27.3: `usr/local/bin/docker` →
  0 HIGH/CRITICAL (trivy, same flags).
- grype cross-check leg (`--only-fixed --fail-on high`) on both rebuilt-binary
  images: "No vulnerabilities found", rc 0.

## 4. Gates run after the edit (all green)

- `uv run python scripts/check-image-pins.py` → 8 pins across 10 Dockerfiles,
  all registered (this gate enforces Dockerfile↔ledger equality, so the pin
  bump cannot drift from the ledger).
- `uv run python scripts/check-image-inventory.py` → OK.
- `uv run python scripts/check-build-context.py` → ok.
- `uv run pytest tests/test_prepull_base_images.py tests/test_prepull_copy_sources.py
  tests/test_check_image_pins.py` → 68 passed.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- Issue-acceptance re-execution at this head: 8-file turing gate → 221 passed;
  full `packages/maistro-turing/{backend/,}tests` → 350 passed;
  suite-inventory for both turing suites → ok.

## 5. Not done / not needed

- No Python source changed, so no vulture/radon/reachability ledger delta; the
  prior verifier's green Python gates stand. The vulture-ledger repair clause
  of the lane brief does not apply — the red gate is the container scan.
- `docs/testing/inventory-notes/issue-363-license-inventory.md` is the
  historical #363 record and was left as-is; this note is the #2209 round's
  record. No tests were added or removed this round, so no inventory delta note
  is required.
- The full four-image container job (builds + SBOM + license inventory) still
  runs in CI; locally only the failing surface (Go-binary findings) was
  reproduced and cleared, plus the adjacent Go stage that would have failed
  next.
