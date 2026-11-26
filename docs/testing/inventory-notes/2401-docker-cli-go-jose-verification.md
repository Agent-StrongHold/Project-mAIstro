# Issue 2401 verification: docker CLI go-jose v4.1.5 (CVE-2026-116587) at develop head c87dd79acd

No inventory delta: no test counts moved (no tests added or changed; this note
records verification evidence only, per the directory README's no-front-matter
convention).

## The issue's acceptance criteria, mapped to this tree

Issue #2401 asks that both `Dockerfile` and `Dockerfile.research` bump
`DOCKER_CLI_VERSION` to the first docker/cli release whose vendored go-jose is
>= 4.1.6 (CVE-2026-116587, HIGH, fixed in go-jose 4.1.6), rebuild, re-run the
trivy/grype scan shape, confirm zero HIGH/CRITICAL on `usr/local/bin/docker`,
and prune nothing from the scan triage ledger (fix exists — upgrade, never
allowlist).

At this head **both Dockerfiles already carry the fix** (landed on develop via
#1373, 2026-11-16, after the issue was filed against the v29.9.1 pin; see
`76-container-gate-repair.md` and `cr1373-recovery-evidence-repair.md` for the
repair-round history). This note re-proves the fix against the issue's exact
criteria at the current develop head, without trusting the earlier claims:

| Criterion | Status at c87dd79acd |
|---|---|
| `DOCKER_CLI_VERSION` pins a release vendoring go-jose >= 4.1.6 | `Dockerfile:179` / `Dockerfile.research:157` pin **29.9.3**; upstream `vendor.mod`/`vendor.sum` at tag `v29.9.3` carry `github.com/go-jose/go-jose/v4 v4.1.7` (>= 4.1.6) |
| "check .../vendor/github.com/go-jose/go-jose/v4/go.mod after picking the tag" | docker/cli ships no per-vendor-path go.mod at that path (raw.githubusercontent 404); the authoritative manifests are the tag's `vendor.mod`/`vendor.sum`, fetched for both tags (see below) and agreeing at 4.1.7 |
| Tag/commit assertion | `DOCKER_CLI_COMMIT_SHORT=5457199` matches tag `v29.9.3` (annotated tag `5e262e04` -> commit `5457199aa57c45e990c59c89cab5f02b817238d7`); the Dockerfile `test "$(git rev-parse --short=7 HEAD)"` re-asserts it at build time |
| Rebuild + scan shape, zero HIGH/CRITICAL on the docker binary | Rebuilt locally with the exact stage recipe (below): trivy HIGH/CRITICAL **0**, grype `--only-fixed --fail-on high` exit 0 |
| Triage ledger untouched | `.trivyignore.yaml` contains **no** go-jose / CVE-2026-116587 entry (grep count 0) and no entry was added or removed by this lane |

Reconciliation note: the issue says "the first release carrying >= 4.1.6";
v29.9.2 plausibly also qualifies, but the canonical pin established by the
#1373/#2120 repair rounds is v29.9.3 (same builder digest, same commit-SHA
assertion, both Dockerfiles byte-identical in the stage). Moving the pin
downward would churn two digest-adjacent files for no CVE benefit; the >= 4.1.6
requirement is what the scanners gate on, and 4.1.7 satisfies it.

## Upstream vendor-manifest evidence (fetched 2026-11-22)

- `https://raw.githubusercontent.com/docker/cli/v29.9.1/vendor.sum`:
  `github.com/go-jose/go-jose/v4 v4.1.5` — the vulnerable version the issue
  names.
- `https://raw.githubusercontent.com/docker/cli/v29.9.3/vendor.sum` and
  `/vendor.mod`: `github.com/go-jose/go-jose/v4 v4.1.7` — both manifests agree.

## Local rebuild + scan evidence (this host, 2026-11-22, trivy 0.73.0 / grype 0.116.0 — CI's pinned scanner versions)

The `dockerclibuild` stages of the two Dockerfiles are byte-identical (diffed
`AS dockerclibuild`..`cmd/docker` blocks), so one faithful rebuild covers both
images' flagged surface (`COPY --from=dockerclibuild /out/docker
/usr/local/bin/docker`, `Dockerfile:251` / `Dockerfile.research:229`). The
stage recipe was re-executed step-by-step outside the daemon (an in-daemon
full-image build of this tree exceeded a 40-minute single-call window on this
host; the module-graph steps are identical either way, and for a
`CGO_ENABLED=0` static binary the OS does not enter the module graph):

- clone `docker/cli` `--branch v29.9.3 --depth 1`; commit-SHA assertion
  `5457199` passes (`COMMIT-MATCH-OK`).
- `cp vendor.mod go.mod && cp vendor.sum go.sum`;
  `go get golang.org/x/net@v0.62.0 github.com/klauspost/compress@v1.20.2` —
  resolves go-jose **v4.1.7** (matches upstream vendor.sum);
  `go mod vendor`.
- `GOTOOLCHAIN=go1.27.4 CGO_ENABLED=0 go build -trimpath -mod=mod -tags
  grpcnotrace -ldflags="-s -w -X ...version.Version=v29.9.3 -X
  ...version.GitCommit=5457199" -o docker-2993 ./cmd/docker` — same flags as
  the Dockerfile, same Go toolchain as the pinned `golang:1.27.4-alpine`
  builder.
- `go version -m docker-2993`: `go1.27.4`, `go-jose/v4 v4.1.7`,
  `golang.org/x/net v0.62.0`, `klauspost/compress v1.20.2`; the binary runs
  (`docker-2993 version` -> `v29.9.3`).
- trivy rootfs on the binary, fresh DB (2026-11-22):
  **Total 3 — MEDIUM 3, HIGH 0, CRITICAL 0**; no go-jose finding, no x/net
  finding (upstream otel/distribution MEDIUMs only, which the gate does not
  fail on).
- grype `file:docker-2993 --only-fixed --fail-on high`: exit 0 (2 MEDIUM otel
  rows only).

Positive controls (the same recipe at tag v29.9.1, the pin the issue was filed
against) — proves the scan shape has teeth on exactly this advisory:

- `go version -m`: go-jose **v4.1.5**, x/net v0.60.0.
- trivy: `CVE-2026-116587 github.com/go-jose/go-jose/v4 v4.1.5 fixed 4.1.6
  HIGH` plus `CVE-2026-78661 golang.org/x/net v0.60.0 fixed 0.62.0 HIGH` —
  identical to the failure that spawned this issue.
- grype (independent Anchore feed): go-jose v4.1.5 `GHSA-mgcc-cww5-fp2q High,
  fixed 4.1.6`.

## Residual risk

The full four-image rebuild + image-level scan was not re-run end-to-end on
this host in this round (single-call build window); the flagged surface — the
docker CLI gobinary, identical in both Dockerfiles — was verified directly, and
the last full-image verification is recorded in
`76-container-gate-repair.md` (2026-11-16 rounds) with security.yml re-running
the image scans on every candidate since. The inert
`CVE-2026-78661` `.trivyignore.yaml` entry (x/net, expired_at 2026-12-31) is
kept per the issue's "prune nothing" instruction; the rebuilt binary carries
x/net v0.62.0 so the finding no longer fires and the entry is dormant.
