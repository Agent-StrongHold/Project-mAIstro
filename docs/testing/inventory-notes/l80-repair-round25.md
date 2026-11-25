---
note: l80-repair-round25
issue: "#80"
head: 21c1ceea29b79320fb34b33654e09ef228c42dc7 (base for this round's commit)
date: 2026-09-27
---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---

# L80 round 25 — CI conformance-lane rootless provisioning repaired (root cause reproduced locally)

The single blocking finding carried since the lane was added was that the
"Start a rootless Docker daemon for the conformance lane" step in
`.github/workflows/ci.yml` failed on every remote run (8 consecutive heads,
last checked at run 36349000939 / head 21c1ceea) with:

```
failed to start daemon: Error initializing network controller: error
obtaining controller instance: failed to register "bridge" driver: failed to
create NAT chain DOCKER: iptables failed: iptables --wait -t nat -N DOCKER:
iptables v1.8.11 (nf_tables): Could not fetch rule set generation id:
Permission denied (you must be root)
```

so the escape suite never executed remotely and SECURITY.md's "CI proves both
branches" sentence was drift.

## Root cause: reproduced locally, not guessed

This round reproduced the exact runner failure locally instead of treating it
as an opaque runner quirk:

- Downloaded the same pinned `docker-rootless-extras-29.8.1.tgz` bundle ci.yml
  uses, plus the static `docker-28.5.2.tgz` dockerd (the GitHub-hosted
  ubuntu-24.04 runner preinstalls a 28.x dockerd), and started the daemon with
  the exact ci.yml recipe (vfs, custom data-root/exec-root/pidfile/host,
  rootlesskit slirp4netns, AppArmor userns knob relaxed).
- The daemon failed with the byte-identical NAT-chain error above.
- Cause: dockerd 28.x default-initializes the iptables firewall inside the
  rootlesskit netns even though that netns is owned by an unprivileged user
  namespace — the operation needs privileges the netns cannot grant. moby
  29.x (the local daemon that masked this for rounds 19–24's local proofs)
  no longer firewall-initializes in rootless mode, which is why every local
  lane run was green while every remote run was red.

## Fix (all in `.github/workflows/ci.yml`, no production code changed)

1. The daemon is now started with `--iptables=false --ip6tables=false
   --userland-proxy=false --bridge=none`. This is safe by construction for the
   conformance contract: the sandbox's network default-deny is enforced
   per-container (`--network=none`; no bridge/NAT/publish path is ever
   exercised by the suite), and removing the plane removes exactly the
   privilege the rootless netns cannot grant. Two follow-on requirements of
   disabling iptables on dockerd 28.x were hit and fixed empirically
   (`userland-proxy is enabled, but userland-proxy-path is not set` →
   `--userland-proxy=false`; `error creating default "bridge" network:
   operation not permitted` → `--bridge=none`).
2. `sudo loginctl enable-linger "$uid"` added before daemon start: rootless
   dockerd can only enforce `--memory`/`--pids-limit` through a delegated
   cgroup v2 subtree, which systemd grants to a user manager; hosted runners
   have no logind session for the runner user. Without this,
   `test_memory_exhaustion_is_contained_by_the_container_limit` would fail
   opaquely on its first remote run.
3. The image-load step now proves enforcement before the suite runs: it reads
   `memory.max` back from inside a 64 MiB-limited `--network=none` container
   and fails with a named error if the limit is not byte-exact (67108864).
   Resource-exhaustion coverage therefore cannot become vacuous remotely.

## Live re-proof at this round (dockerd 28.5.2, the fixed recipe)

- Repro daemon: `SecurityOptions` includes `rootless`; `CgroupVersion=2`,
  `CgroupDriver=systemd`, `Driver=vfs`; probe container uid_map non-identity.
- Full escape suite against that daemon:
  `DOCKER_HOST=<repro socket> uv run pytest
  packages/maistro-bootstrap/tests/test_container_sandbox.py -q` = **16
  passed, 1 skipped** (the skip is the inverted refusal test, correct on a
  qualifying daemon).
- Refusal branch against the rootful system daemon:
  `test_sandbox_refuses_a_rootful_unmapped_daemon` = **1 passed**.
- Memory probes on the repro daemon: `memory.max=67108864` under a 64m limit;
  48 MiB allocation succeeds; 3 GiB allocation is killed (rc != 0).

## SECURITY.md

The drifted "CI proves both branches" sentence is replaced with a precise
description of what the lane runs (both branches) and how it provisions the
daemon (firewall/bridge-free flags with the dockerd 28.x root cause noted).
No claim of a remote green run is made — that is what the next CI run on this
branch establishes.

## CI-gate repair (designated vulture per-identity ledger round)

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` = rc 0: 1403 reviewed
identities, 1403 findings, `unclassified: 0`, ratchet base
0c8370a8eaa4 → candidate 21c1ceea29b7 clean. No unbanked identities; this
round touches no Python, so nothing was eliminated and no ledger amendment
was required.

## Salvage resolution

The assigned previous block said a worker left uncommitted work. The worktree
at 21c1ceea is clean; the round-24 verifier report at this same head records
that the salvage was already committed in prior rounds (fe6cc89ca repair +
21c1ceea2 note). Nothing was discarded.

## Validation battery (this round, at the commit below)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 2601 files
  formatted.
- actionlint 1.7.7 + shellcheck 0.10.0 over `.github/workflows/ci.yml` (the
  same command the workflow-lint job runs) — clean.
- `uv run python scripts/check-required-checks.py` — 33 PR checks match
  docs/ci/REQUIRED-CHECKS.md.
- `uv run python scripts/check-security-inventory.py` — OK (SECURITY.md edit
  covered).
- `uv run python scripts/check-doc-links.py`, `scripts/check-ac-state.py` — pass.
- `uv run pytest packages/maistro-bootstrap/tests packages/maistro-rsi/tests
  -q` — **1050 passed, 17 skipped**.
- `scripts/check-suite-inventory.py` for bootstrap (266) and rsi (801) — match.
- Vulture baseline gate as above — rc 0, no amendment needed.

Residual risk: the runner's exact dockerd minor (28.x) may differ from the
reproduction's 28.5.2; the fix is flag-level (works on both 28.x and 29.x
daemons — the local 29.7.2 daemon runs the same flags), and the new in-lane
memory-enforcement probe converts any residual cgroup-delegation gap into a
named step failure rather than a distant red test.
