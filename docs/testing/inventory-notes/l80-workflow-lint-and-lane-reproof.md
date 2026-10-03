---
inventory-delta:
  packages/maistro-bootstrap/tests: 0
---

# Issue #80 round 28 — workflow-lint non-reproduction proven, securityfs-mask fix mechanism re-proven live

Branch `auto-80`, starting HEAD `ce743da9c92162874cfcb28d2201e11ab39eae2b`
(no source changes this round; evidence round), issue #80, 2026-09-27.

## Named gate: workflow-lint "failure" does not reproduce in any reachable configuration

The lane brief reported `workflow-lint: failure` from the last merge-queue
evaluation. Every reachable check says the gate is green:

1. **Local, exact pinned tool versions** at `ce743da9`: the full CI
   `workflow-lint` job battery was executed step by step —
   `scripts/ci_merge_group_scope.py` (ok),
   `actionlint 1.7.7 -no-color -oneline -shellcheck shellcheck 0.10.0`
   (exit 0), `shellcheck --severity=warning tools/*.sh` (exit 0),
   `scripts/check-required-checks.py` (33 PR checks ok),
   `scripts/check-uv-setup.py` (22 steps ok),
   `scripts/check-workflow-write-safety.py` (23 workflows ok),
   `scripts/check-branch-protection.py` (18/30 ok). Local
   actionlint/shellcheck binaries were verified to be exactly the CI-pinned
   `ACTIONLINT_VERSION=1.7.7` / `SHELLCHECK_VERSION=0.10.0`.
2. **Hosted, at the PR #1450 head `d4b3c7919c5e`** (the only hosted
   evaluation of this branch that exists): the `workflow-lint` check run
   (`108713321926`, CI run `36352351901`, `pull_request` event) concluded
   **success**. So does `exact-debt-ledger` at that head.
3. **Merge-queue semantics**: `origin/develop` advanced to `bc1182f9c`
   (3 commits past the lane base). `git merge-tree --write-tree HEAD
   origin/develop` is **clean** (no conflict), and those 3 develop commits
   touch **no** `.github/` or `scripts/` paths, so a queue merge would lint
   byte-identical workflow content to what passed locally. No
   `gh-readonly-queue/develop/pr-1450-*` run exists on the remote at all.

The one hosted red at `d4b3c791` is the `test` job (`108713321959`): step 10
"Load the Builder sandbox image into the rootless daemon" failed **after**
`docker load` succeeded, on the enforcement probe:

    docker: Error response from daemon: Could not check if docker-default
    AppArmor profile was loaded: open /sys/kernel/security/apparmor/profiles:
    permission denied
    ##[error]Process completed with exit code 126.

Job-log trace proves that head started `dockerd-rootless.sh` **directly** —
`nohup dockerd-rootless.sh --iptables=false ...` — i.e. without the
securityfs mask. The fix commit `e4903977f` (mountns wrapper) is a local
commit **after** `d4b3c791`; it has never executed on CI.

## This round's live re-proof of the e4903977f fix mechanism (local rootless lane, moby/rootlesskit 29.8.1/3.1.0 = the CI-pinned extras bundle)

The exact CI recipe was executed locally at this head against a scratch
rootless daemon (`/tmp/l80r`), started through
`scripts/ci-rootless-mountns.sh` with the CI flag set (`--iptables=false
--ip6tables=false --userland-proxy=false --bridge=none
--storage-driver=vfs`):

- **Mask survives rootlesskit**: the dockerd pid's `mountinfo` contains
  `0:699 / /sys/kernel/security ro,nosuid,nodev,noexec,relatime - tmpfs
  maistro-ci-securityfs ro,size=4k`, and its bundled containerd child shows
  the same mount. `dockerd`'s view of `/sys/kernel/security/` is an **empty
  tmpfs** — the `apparmor` directory that the hosted error names does not
  exist for the daemon plane, so moby's AppArmor discovery treats AppArmor
  as absent (the same state as any host without securityfs, where the suite
  is green) instead of taking the visible-but-unreadable EACCES path.
- **CI step 10 verbatim passed**: rootful-daemon `docker save` piped into
  lane-daemon `docker load` ("Loaded image: maistro-builders:latest"),
  then `docker run --rm --network=none --memory=64m --memory-swap=64m
  maistro-builders:latest cat /sys/fs/cgroup/memory.max` printed
  `67108864` — the create-time AppArmor check that kills the hosted probe
  did not occur, and cgroup memory enforcement is active.
- **Negative control**: a daemon started with a writable
  `apparmor/profiles` (chmod 000) fixture visible in its mountns from the
  start behaves differently, confirming the decision latches on
  `/sys/kernel/security/apparmor` visibility at daemon start — exactly the
  state the wrapper removes. (Fixture-injected-after-start does not affect
  the daemon; the check is a start-time decision.)

Round 26 already re-proved the escape suite green (16 passed / 1
daemon-posture inverted skip), rootful-refusal 1 passed, and hardening 26
passed at this head's code (the only code delta since,
`c121f9140` seed-path refusal, is covered by its own tests and the
verifier's driver gates at `ce743da9`: 199 passed/19 skipped check-3,
bootstrap inventory 269, rsi inventory 801, ruff/format green). The mask is
behaviorally inert on a host without securityfs, so those local suite
results carry over to the masked lane unchanged.

## Conclusion / handoff

- `workflow-lint: failure` is a stale or externally-artifacted claim: green
  locally at HEAD with pinned tools, green hosted at the PR head, and the
  merged-with-develop tree is workflow-identical and conflict-free. No
  branch change is warranted; none was made.
- The only real hosted red (rootless conformance lane, 10 consecutive red
  runs) fails at heads **preceding** `e4903977f`; this round's mountinfo +
  probe evidence demonstrates the fix's mechanism end-to-end with the
  pinned toolchain. The remaining step is hosted execution of a head
  ≥ `e4903977f` — push/CI-trigger authority sits outside this lane, so
  remote confirmation stays explicitly UNVERIFIED from this seat.
- No test files added or modified this round; inventory delta +0.

## Round 29 (this file was round 28's uncommitted salvage; preserved, reviewed, re-proven, committed)

The round-28 note above was left uncommitted and is preserved verbatim with
this addendum. Independent re-verification at the same HEAD `ce743da9`:

1. **workflow-lint battery re-run, all 7 steps exit 0** with the CI-pinned
   tools (`/tmp/actionlint` 1.7.7, `/tmp/shellcheck-bin` 0.10.0):
   `ci_merge_group_scope.py` ok; `actionlint -no-color -oneline -shellcheck`
   ok; `shellcheck --severity=warning tools/*.sh` ok;
   `check-required-checks.py` (33 PR checks ok);
   `check-uv-setup.py` (22 steps ok); `check-workflow-write-safety.py`
   (23 workflows ok); `check-branch-protection.py` (18/30 ok). The named
   gate failure still does not reproduce at this head.
2. **Vulture per-identity ledger**: `check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` exit 0 — 1403 findings
   all banked, 0 unclassified, 0 never_allowlist. No amendment needed.
3. **Sandbox suites re-run**: bootstrap container suites 85 passed / 20
   skipped (skips are the documented rootful-daemon posture; the refusal
   itself is `test_sandbox_refuses_a_rootful_unmapped_daemon`, passing),
   rsi `test_ambient_credentials` + `test_autonomous_isolation_tier` +
   `test_no_host_shell_execution` 46 passed.
4. Acceptance-to-test mapping confirmed at this head:
   `test_container_sandbox.py` covers filesystem/path escape, network
   default-deny, credential default-deny, non-root exec, process/
   namespace/device/host-socket isolation, timeout kill + detached
   descendants, cleanup, memory exhaustion, userns mapping, rootful
   refusal; `test_container_sandbox_hardening.py` covers seed allowlist/
   denylist (`.env`/`.git`/ambient secrets), unprivileged user pinning,
   read-only rootfs + explicit writable scope, fail-closed uid-map checks,
   and seed-failure cleanup. No branch change made or needed; the only
   residual remains hosted execution of the conformance lane at a head
   >= `e4903977f`, which sits outside lane authority.
