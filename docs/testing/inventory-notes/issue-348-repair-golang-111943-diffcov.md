---
inventory-delta:
  tests/: +27
---
# issue-348 repair — golang builder CVE + the reconciliation gate's coverage

Repair round (job `99fd96499df84a16bbb45e8e93c7bd9d`) for #348 in worktree
`auto-348` at `0edf496f1ece` (base `a9fdec4cb40a`). Addresses the two red
required checks from the merge-queue evaluation at that head:

- `Container scan + SBOM + cosign` — job 119987083525, failing step
  `Trivy scan (HIGH/CRITICAL only)`: `usr/bin/age` and `usr/bin/age-keygen`
  (gobinary) each carried `CVE-2026-111943` (HIGH, crypto/x509 MITM via
  untrusted intermediate certificates, fixed in go1.26.10/1.27.3; installed
  stdlib v1.27.2).
- `Coverage gate (publish-set floor + diff coverage)` — job 119994841456,
  failing step `Diff coverage gate (per file, lines 90% / branches 80%)`:
  `scripts/check-image-lock-reconciliation.py: 0.0% of 75 changed lines
  (need 90%)`. The "Event loop is closed" lines in that job's log are a
  `PytestUnhandledThreadExceptionWarning` from an aiosqlite worker thread;
  5714 passed — they are not the failure.

No package source changed; both fixes live in the image/tooling surface this
issue owns, so vulture/radon per-identity ledgers are untouched
(`check-vulture-baseline.py packages/*/src --min-confidence 60` green at this
head).

## 1. golang builder 1.27.2-alpine -> 1.27.3-alpine

The `agebuild` stage (`packages/hive-conductor/Dockerfile`) and both
`dockerclibuild` stages (`Dockerfile`, `Dockerfile.research`) build the shipped
static Go binaries from pinned upstream tags on a digest-pinned toolchain —
that policy exists because no released upstream binary embeds a fixed stdlib.
go1.27.2 itself now carries CVE-2026-111943, so every shipped age/docker binary
inherited it. Bumped all three `FROM golang:1.27.2-alpine@sha256:f92b6ef8…`
lines to `golang:1.27.3-alpine@sha256:b8c9b82a…` (index digest, verified via
`docker buildx imagetools inspect` and `go version` inside the image) and
updated the one `quality/image-pins.json` row the pins gate requires to move in
lockstep (`recorded_in: "#2243"`). Engine/research moved too although CI died
before scanning them: they ship the docker CLI from the same toolchain, so the
same finding would have surfaced one scan later.

Proof, executed locally (docker via mirrored socket, trivy v0.73.0 — the
version CI runs):

- rebuilt the `agebuild` stage on the new digest: `go version -m /out/age`
  reports `go1.27.3`;
- `trivy rootfs --severity HIGH,CRITICAL --ignore-unfixed --scanners vuln` on
  the rebuilt binaries: `age`/`age-keygen` 0 findings;
- negative control on a go1.27.2-built age from the same source tag: the scan
  reports exactly `CVE-2026-111943 HIGH (fixed 1.26.10, 1.27.3)` — the CI
  finding, reproduced. The green scan is not green because the DB lacks the
  CVE.

## 2. tests/test_check_image_lock_reconciliation.py (+27 to `tests/`)

The reconciliation gate existed only in security.yml text — no suite imported
it, so its changed lines measured 0%. Following the `tests/test_check_*.py`
convention (import the script, drive its pure logic), the new battery covers
PEP 503 canonicalization, export parsing (conditional vs unconditional pins,
hash continuations, empty-export red exit), dump parsing (docker/uv noise
lines, empty-dump red exit), and every reconcile verdict through a faked
`docker run` (exact match, missing, extra, version skew, member pins,
malformed member, docker failure passthrough, stdin path, argparse mutual
exclusion), plus the `__main__` guard via runpy.

Writing them surfaced a real defect, fixed in the script: the original
`skewed` comprehension compared each pin against itself
(`for pin in actual & everything_expected … .pop() != pin` — both operands of
the filter are the same string for every member of that intersection), so it
could never fire and a version skew was misreported as a missing+extra pair.
Skew detection is now name-keyed; `test_version_skew_*` pins the
"version mismatch" behaviour the script's own output heading documents.
`missing`/`extra` exclude skewed names so a skew reports once.

Coverage of the script under the gate's own producer shape
(`coverage run --branch --source=scripts` over the new file): **78 stmts, 0
miss; 32 branches, 0 partial — 100%**. Full gate reproduced: root producer
(`pytest tests/ …` → 5741 passed, 140 skipped), `coverage xml`, then
`scripts/check-diff-coverage.py coverage.xml --base a9fdec4cb40a` →
`ok: every measured file this change touches is at or above 90% lines / 80%
branch arcs` (exit 0) — the exact step that failed in CI.
