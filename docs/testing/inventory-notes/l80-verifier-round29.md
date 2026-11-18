---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 29 — repair round: real conformance re-executed on both daemon postures; swebench `test` gate failure proven to be hosted pull-infra flake

Branch `auto-80`, head `b5a932c94896861c5f0ef968d817707e4942ebc9` (unchanged;
evidence-only round), issue #80, 2026-09-28. Driver checks (job
`fc84daa293944042a479191b38d52a64`) were all green before this round:
uv sync ok, ruff check ok, ruff format ok, bootstrap+rsi pytest
199 passed / 19 skipped, both suite inventories ok.

## Previous block resolved: no uncommitted work remains

The lane brief reported "worker left uncommitted work; preserved for salvage
review". `git status` at `b5a932c9` is clean and `git stash list` contains
only stashes belonging to other lanes' branches (`repair-1396`,
`repair-1321`) — untouched. The round-28 uncommitted note was already
committed verbatim by `4a3825b76` ("round-28 salvage commit"), which is an
ancestor of the current head. Nothing to salvage; nothing discarded.

## Named gate `test: failure` — root cause and local proof

Hosted run 36440932829 job 108990898155 failed the `test` job on
`packages/maistro-evolve/tests/benchmarks/test_swebench.py:117,152`
(image pull of `python:3.12-slim`; Docker Hub DNS refused on the runner).
This branch contributes **zero diff** to `packages/maistro-evolve` and
`packages/maistro-core` (`git diff 55be1459..HEAD -- packages/maistro-evolve
packages/maistro-core` is empty), and the same tests pass locally at this
head: `uv run pytest packages/maistro-evolve/tests/benchmarks/test_swebench.py`
→ **15 passed in 12.29s**. The failure is hosted pull infrastructure, not
reachable branch behavior.

## Real conformance suite re-executed live (not assumed from prior claims)

Both daemon postures, same production class
(`maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`;
production use at `packages/maistro-rsi/src/maistro_rsi/local_loop.py:864-866`):

- Rootless daemon (`unix:///run/user/1000/docker.sock`,
  `docker info` SecurityOptions include `name=rootless`):
  `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py`
  → **18 passed, 1 skipped in 131.93s**. The skip is
  `test_sandbox_refuses_a_rootful_unmapped_daemon` ("this daemon provides the
  rootless/userns boundary, so the sandbox starts on it") — the correct
  posture split. The suite covers filesystem escape, path escape, network
  default-deny (live `NetworkMode == "none"` plus public v4/v6/DNS/metadata/
  RFC1918 probes all DENIED), credential default-deny (env and Docker proxy
  sentinels absent), unprivileged exec (uid 65532; `/etc` write and chown
  refused), ambient-credential-free seed (`.env*`, `.git`, nested gitlinks,
  key material absent; tracked files present), read-only rootfs with implicit
  `/dev/shm` + `/dev/mqueue` pinned read-only and full `/proc/mounts`
  writable-scope enumeration, process/namespace/device/host-socket surfaces
  (CapEff empty, NoNewPrivs=1, no docker.sock, mknod/mount/chroot refused),
  uid_map non-identity mapping, nested userns, timeout kill of detached
  descendants, context cleanup, and memory-exhaustion containment.
- Rootful daemon (`unix:///var/run/docker.sock`): the same suite's
  `test_sandbox_refuses_a_rootful_unmapped_daemon` → **passed in 70.28s**
  (sandbox refuses to start where container uid 0 maps to host uid 0).
- Non-Docker-gated hardening + lane suites:
  `test_container_sandbox_hardening.py` + `test_container_lane.py` →
  **32 passed, 1 skipped in 0.20s** (seed allowlist/denylist, default-deny
  create config, unprivileged pin, uid-map fail-closed branches, sole root
  exec = pre-seed chown, per-stage seed-failure cleanup, lane mask).

## CI lane present for both postures

`.github/workflows/ci.yml` (Builder conformance job): builds the real image
from `packages/maistro-bootstrap/tests/Dockerfile.sandbox` (never the repo as
build context), runs the rootful-refusal proof, provisions a rootless daemon
(pinned static rootless-extras 29.8.1, linger + cgroup v2 delegation,
`memory.max` enforcement probe, `scripts/ci-rootless-mountns.sh` securityfs
mask, NAT plane disabled), then runs the full escape suite on it.

## Ledger and hygiene

- Vulture per-identity ledger:
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1402/1402
  banked; no amendment needed.
- Environment hygiene: removed leaked sandbox container `36c97bf30a24`
  (`maistro-builders:latest`, `sleep infinity`, up ~10h) left on the shared
  rootful daemon by an earlier round of this lane.

## Verdict

No source changes were needed this round: the reopened-regression claims are
refuted by the executed suite (network none, credential blanking, read-only
rootfs, unprivileged uid, userns gate, minimal seed), the `test` gate failure
does not reproduce locally, and every acceptance criterion has current,
executed evidence.
