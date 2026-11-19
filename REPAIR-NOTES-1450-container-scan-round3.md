# Repair notes — issue #1450 round 3 (container-scan gate repair)

Branch `auto-80`, head `5065aa984e57` (develop tip `f8a2df966a1d` already merged
in 58138f673; merge-base HEAD..origin/develop equals `origin/develop`).

## What was actually failing at this head

Read-only CI inspection (`gh api .../commits/5065aa98.../check-runs`) shows the
**only** failing check run at this head is `Container scan + SBOM + cosign`
(run 43789821209, job 133045463155). The prompt's named failure
"Supply chain (pip-audit)" does **not** fail at this head — commit 5065aa98
(upgrade dnspython/graphql-core/joserfc/opentelemetry-api) already resolved it,
and the live CI-exact reproduction below re-proves it:

- `uv sync --locked --all-extras` + `uv pip install pip-audit`, then
  `uv pip freeze --exclude-editable` → `pip-audit --strict --format=json -r`
  → `scripts/pip_audit_gate.py`: **exit 0**, sole advisory the reviewed
  `ecdsa PYSEC-2026-1325` ALLOWED pair (printed twice by the report, both hit
  the same allowlist pair), direct-dependency usage ratchet OK
  (11 packages, 66 runtime deps, 4 reviewed dispositions).
- ci.yml `security` job's other leg `check-dependency-namespaces.py`: exit 0.

The real blocker, from the job log itself:

```
Trivy scan maistro-engine (HIGH/CRITICAL only)
Total: 2 (HIGH: 2, CRITICAL: 0)
│ github.com/go-jose/go-jose/v4 │ CVE-2026-116587 │ HIGH │ fixed │ v4.1.5 │ 4.1.6 │
│ golang.org/x/net              │ CVE-2026-78661  │ HIGH │ fixed │ v0.60.0 │ 0.62.0 │
##[error] Process completed with exit code 1.
```

Both findings are read by trivy straight out of the `docker` binary's Go
buildinfo: the docker/cli v29.9.1 vendor tree pins go-jose v4.1.5 and
x/net v0.60.0. Neither is in `.trivyignore.yaml`, and the gate's policy is to
upgrade when a fix exists rather than ignore.

## Fix (salvage from the prior attempt, completed and proven here)

The `dockerclibuild` stage in **both** `Dockerfile` and `Dockerfile.research`
now runs, on the same immutable v29.9.1 tag (commit verified by the existing
`test "$(git rev-parse --short=7 HEAD)" = dfc520d` guard):

```
go get github.com/go-jose/go-jose/v4@v4.1.6 golang.org/x/net@v0.62.0
go mod vendor
```

before the existing `CGO_ENABLED=0 go build`. `go get` edits only go.mod/go.sum;
`go mod vendor` rewrites `vendor/` from them, so the build stays in vendor mode
with content-hash-pinned module replacements (module proxy versions are
immutable). The stage is digest-pinned `golang:1.27.3-alpine` (toolchain already
past CVE-2026-111943).

## Evidence (all executed locally this round)

- **Stage builds**: `docker build` of the extracted `dockerclibuild` stage
  succeeds; `/out/docker` buildinfo reads
  `dep github.com/go-jose/go-jose/v4 v4.1.6` and `dep golang.org/x/net v0.62.0`,
  with **zero** occurrences of `v4.1.5` / `golang.org/x/net v0.60.0`
  (`go version -m`).
- **Control scan** (same stage minus the two `go get` lines, trivy v0.73.0 —
  CI's exact version — current DB 2026-11-16):
  `trivy rootfs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed`
  reports exactly the 2 CI HIGHs (CVE-2026-116587 v4.1.5→4.1.6,
  CVE-2026-78661 v0.60.0→0.62.0) — the CI failure reproduced locally.
- **Patched scan**: same trivy invocation on the patched binary: **0
  vulnerabilities** (gobinary target, clean).
- The stage's output is what both images ship:
  `COPY --from=dockerclibuild /out/docker /usr/local/bin/docker`
  (Dockerfile:218, Dockerfile.research:183). Python-side image content is the
  uv.lock set already fixed at 5065aa98; OS-layer triages are the existing
  `.trivyignore.yaml` entries. The job log shows hive-conductor's scan passed;
  maistro-engine was the only failing scan, on exactly these 2 findings.
- **pip-audit (named failure)**: CI-exact gate exit 0, only the reviewed ecdsa
  ALLOWED pair remains (see above).

## Issue #1450 acceptance re-verified live (sandbox conformance + escape)

The prior rounds' "live rootless leg UNVERIFIED" caveat is **resolved**: this
host exposes a rootless daemon on `unix:///run/user/1000/docker.sock`
(SecurityOptions include `name=rootless`) with working delegated cgroup v2 —
refuting the earlier "local daemon rootful, memory probe cannot run" note.

Full CI-exact lane sequence, executed:

1. `docker build -t maistro-builders:latest --file
   packages/maistro-bootstrap/tests/Dockerfile.sandbox
   packages/maistro-bootstrap/tests` (rootful, as CI) → ok
2. `docker save | docker --host unix:///run/user/1000/docker.sock load` → ok
3. Fail-closed proof, rootful daemon:
   `test_sandbox_refuses_a_rootful_unmapped_daemon` → **PASSED live**
4. `MAISTRO_TEST_ROOTLESS_LANE=1 uv run pytest
   packages/maistro-bootstrap/tests/test_container_lane.py` → **PASSED live**
   (securityfs masking + privilege-drop wrapper proof; sudo -n available)
5. CI's enforcement probe on the rootless daemon:
   `run --rm --network=none --memory=64m --memory-swap=64m
   maistro-builders:latest cat /sys/fs/cgroup/memory.max` → `67108864` =
   64 MiB — **enforced**, matching CI's hard assertion
6. `DOCKER_HOST=unix:///run/user/1000/docker.sock uv run pytest
   packages/maistro-bootstrap/tests -v --tb=short` → **306 passed, 3 skipped**

The 3 skips are structural: the Windows-only escape test (platform-gated), the
lane-provisioning test inside the full-suite run (opt-in env; run separately in
step 4 and PASSED), and the userns-refusal test whose precondition is "this
daemon does NOT provably provide the rootless boundary" — false for a proven
rootless daemon, and its refusal twin was proven live against the rootful
daemon in step 3. No untested production path remains.

Other gates at this tree: `ruff check .` all passed; `ruff format --check .`
3562 files; `check-suite-inventory.py --suite packages/maistro-bootstrap/tests`
ok (no test-count change → no inventory-note delta); CI-exact vulture gate
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` → RC 0, 1238 reviewed identities = 1238 findings.
`git diff --numstat origin/develop -- quality/`: only the intended additive
branch rows (ac-state-notes, image-inventory/image-pins for the test-only
sandbox image); no ledger row loss.

## Adversarial re-examination of prior findings

- **"container_sandbox.py:801 stale error message references removed API
  run_command" — REFUTED.** The message is model-facing: `_dispatch_tool`
  surfaces it as `[tool error] {exc}` (agent_loop.py:421) when `read_file`
  hits the sandbox read bound, and `run_command` is the live model tool
  (agent_loop.py:325) that dispatches to `sandbox.run_argv` (agent_loop.py:419)
  — exactly the chunked-read vehicle the advice names. Not a stale reference;
  no change made.
- **"live rootless escape suite leg UNVERIFIED" — RESOLVED** (steps 3-6 above;
  the environmental claim it rested on no longer holds on this host).
- **"hive-conductor backend/e2e inventory collection fails locally"** —
  environmental (PEP-668 system python 3.14 vs CI setup-python 3.12), not a
  branch property; unchanged, out of this round's scope.
- **"advisory mypy on maistro-bootstrap"** — advisory only; the mypy CI gate
  covers maistro-core. Out of scope for this gate-repair round.

## Residual risk

The container-scan job itself still needs GHA runners (buildx cache, cosign
key), so the end-to-end job is not re-run here; but the failing step's
decisive input — the binary trivy reads — is proven fixed with CI's exact
trivy version and a current DB, and the Python advisory surface the earlier
round fixed is re-proven green live. New advisories can still land in any
feed between this commit and CI's evaluation; the gate policy (upgrade when a
fix exists) applies unchanged.
