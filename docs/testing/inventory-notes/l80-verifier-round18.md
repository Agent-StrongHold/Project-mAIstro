---
note: l80-verifier-round18
issue: "#80"
head: b272b424eb7f15be67f5c0f7d59f74af9d35c542
base: 341c900b0bca2bac5bf9ea0b60407417678f334a
date: 2026-09-27
kind: independent-verification
---

# L80 verifier round 18 — develop-merge head `b272b424e` (completes rate-limit-killed round)

Round 17's job (`4eec41f51fd4`) completed all six driver checks green (sync, ruff
check, ruff format, sandbox+rsi pytest 32 passed/12 skipped, both suite
inventories) but its agent died on a provider 429 before reporting. This round
completes that verification at the develop-merge head `b272b424e`.

`git diff 4e20c0151..HEAD` over `packages/maistro-bootstrap`,
`packages/maistro-rsi`, `SECURITY.md`, `docs/security/`, `.github/workflows/`
and `quality/` is empty: the merge changed none of the #80 surfaces.

## Both Decision-2 branches re-executed live at this head (by this reviewer)

- Rootful branch (`DOCKER_HOST=unix:///var/run/docker.sock`):
  `pytest test_container_sandbox.py test_container_sandbox_hardening.py
  test_container_sandbox_argv_status.py -v` -> **29 passed, 12 skipped**;
  `test_sandbox_refuses_a_rootful_unmapped_daemon` PASSED against the real
  rootful daemon (SecurityOptions without rootless, rootdir=/var/lib/docker).
- Rootless branch (`DOCKER_HOST=unix:///run/user/1000/docker.sock`, live
  user-rootless daemon, `maistro-builders:latest` id `205c40a9f0b3`
  byte-identical on both daemons): full escape suite -> **12 passed, 1 skipped**
  (only the qualifying-daemon-gated refusal test skips).

## Re-executed at this head

- `uv run pytest packages/maistro-bootstrap/tests -q` -> **247 passed,
  13 skipped**; `packages/maistro-rsi/tests -q` -> **793 passed**.
- `uv run ruff check .` -> all checks passed; suite inventories 260/793 ok.

## NEW at this head: remote CI at the reviewed SHA is RED on the lane itself

Read-only `gh pr view 1450` refresh at `b272b424e` (headRefOid matches) shows:

- **CI / test FAILURE** (run 36331154469): the rootless-daemon bootstrap step
  ("Start a rootless Docker daemon for the conformance lane") exits 100 —
  `E: Package 'docker-ce-rootless-extras' has no installation candidate` — so
  the step "Run the real Builder sandbox conformance lane" NEVER RAN remotely.
  The preceding fail-closed step did pass (`Rootful daemon is refused ...`
  -> `1 passed in 1.31s`).
- **CI / workflow-lint FAILURE**: actionlint+shellcheck report
  `.github/workflows/ci.yml:489` SC2155 and `ci.yml:508` SC2046 — both lines
  introduced by the lane itself in `4e20c0151` (verified via
  `git log -L488,510`; `d8c0d950:ci.yml` does not contain the lane, so round
  17's "remote CI green at d8c0d950" never covered it).
- **Integration Scope FAILURE** (`docker-build ... concluded skipped`, cascade
  of the test failure) and `gates-ran` FAILURE; quality "Coverage gate" still
  IN_PROGRESS at query time.

Consequence: the acceptance item "CI or a clearly designated hardware-capable
conformance lane runs the suite" is NOT satisfied at this head — the lane is
designated and locally proven both branches, but in remote CI its escape-suite
half failed to start (apt package absent on the runner image) and its workflow
additions fail the repo's own workflow-lint gate.

## Acceptance re-derivation at this head

- Escape-suite coverage (filesystem, process, namespace/kernel, network,
  device, host socket, credential, privilege): proven live on the rootless
  daemon (12/12), production class, no separate fixture.
- Network + credential default-deny: `--network=none` asserted on the live
  container config + per-host egress probes; env shows only HOME + blank
  proxies. Proven live.
- Seed hygiene: indexed `.env`/`.env.*`/`.envrc` under a split index,
  untracked host secrets, `server.pem`, `secrets/`, nested `.git`, gitlink
  contents — all absent inside; `.git` never seeded. Proven live.
- Non-root: uid 65532 everywhere, `/etc` write + `chown -R 0:0 /workspace`
  refused, uid_map non-identity, rootful daemon refused. Proven live both
  branches.
- Writable scope: ReadonlyRootfs=true, `/dev/shm`+`/dev/mqueue` pinned ro,
  full `/proc/mounts` enumeration admits only `/workspace` + `/tmp`. Proven
  live.
- Timeout/kill/cleanup/exhaustion: detached-session kill, container removal,
  3 GiB allocation contained, seed-failure cleanup. Proven live.
- SECURITY.md:326-342 and docs/security/SANDBOX-SUPPORT-MATRIX.md:166-185 cite
  the enforced boundary and both CI branches.
- Closure keywords: PR body says "Refs #80" (no fixes/closes/resolves);
  branch commit bodies' two "resolves" mentions refer to prior review blocks,
  not GitHub issues. No premature closure.

## Verdict

NEEDS-REPAIR — local conformance evidence complete, but two concrete CI
defects at the reviewed head: (1) ci.yml:489 SC2155 and ci.yml:508 SC2046
(workflow-lint red on the lane's own lines); (2) the rootless lane bootstrap
fails on GitHub runners because `docker-ce-rootless-extras` has no
installation candidate, so the escape suite never runs remotely. Repair must
provision the rootless toolchain from a source that exists on the runner (or a
pinned image) and fix the two shellcheck findings; then re-run the lane green
before merge.
