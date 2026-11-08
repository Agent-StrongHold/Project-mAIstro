---
inventory-delta:
  packages/maistro-rsi/tests: +0
  packages/maistro-bootstrap/tests: +0
---

# L80 round 23 — independent verifier re-proof at repair head c12bae51

Branch `auto-80`, head `c12bae51c00e4f525b756920c740690e09390f59` (the
round-22 unstated-isolation fail-closed commit), issue #80, 2026-09-27.
Documentation-only round: no source or test changes, inventory delta +0.

## Both daemon branches live-proven by this verifier at this exact head

The prior verify round only had the rootful daemon and could not see the
rootless escape assertions pass; this round executed both branches:

- Rootless daemon (`DOCKER_HOST=unix:///run/user/1000/docker.sock`,
  `docker info` reports `rootless`, data-root `/home/dev/.local/share/docker`):
  `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py`
  = **16 passed, 1 skipped** — the skip is the inverted
  `test_sandbox_refuses_a_rootful_unmapped_daemon` (this daemon qualifies, so
  the sandbox starts). Every escape assertion ran live: network default-deny
  (7 target classes + DNS, with per-target DENIED proof), credential
  default-deny env (blanked proxies), seed exclusion of indexed
  `.env`/`.env.production`/`.envrc`, untracked host secrets, key material at
  depth, nested `.git` (config/hooks/credential.helper) and gitlink
  recursion, unprivileged uid 65532 execs (`/etc` write and `chown` refused),
  read-only rootfs with the whole `/proc/mounts` write-scope enumeration
  (only `/workspace` and `/tmp` accept writes; `/dev/shm`, `/dev/mqueue`,
  `/dev`, `/proc` refuse), pid/mount/chroot/mknod/docker-socket/CapEff/NNP
  probes, timeout kill of detached descendants, context cleanup, 3 GiB
  allocation containment, live uid_map non-identity (container root ≠ host
  root), nested-userns non-reopening, no block devices, no host unix sockets
  or listening ports.
- Rootful daemon (`/var/run/docker.sock`, rootdir `/var/lib/docker`, no
  rootless marker): same command = **1 passed** (`test_sandbox_refuses_a_
  rootful_unmapped_daemon` — fail-closed entry naming ADR-093 Decision 2,
  container removed behind it), 16 skipped.

## Gates re-executed at this head

- `packages/maistro-bootstrap/tests` full suite: 247 passed, 17 skipped
  (matches recorded inventory 264).
- `packages/maistro-rsi/tests` full suite: 801 passed (matches inventory;
  includes the 15 autonomous-isolation-tier tests pinning the round-22
  unstated-isolation refusal at CLI, config and factory, plus the
  mirror-vs-canonical `maistro.sandbox.policy` parity pin).
- `test_container_sandbox_hardening.py` + `test_autonomous_isolation_tier.py`:
  39 passed (argv-shape create-time policy, split-index seed allowlist,
  only-root-exec-is-the-pre-seed-chown, seed failure cleanup at every
  transfer stage, uid_map classifier table).
- `uv run ruff check .`: all checks passed. `ruff format --check` per driver
  log (2601 files already formatted).
- Documented mypy gate (six packages incl. `maistro-bootstrap/src`): Success,
  no issues in 724 source files.
- `scripts/check-suite-inventory.py` for both touched suites: ok.
- `scripts/check-ac-state.py`: clean; worktree stayed clean afterward.

## Claim/behavior drift checks

- ADR-093 re-read: Decision 2 (retained runtime MUST be rootless/socket-less)
  ↔ `_verify_userns_boundary` live gate; Decision 5 ladder ("no bare-subprocess
  tier") ↔ unstated-isolation refusal; Decision 6 (autonomous floor Tier 2) ↔
  `autonomous_isolation_refusal` container refusal — all match implemented
  behavior, no drift found.
- SECURITY.md §8 (lines ~326-352) cites the conformance suites, the both-daemon
  CI proof, and the RSI floor posture — consistent with the code at this head.
- Conformance instantiates the production class
  (`maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`)
  directly; no hardened fixture.
- Closure-keyword review: PR body uses "Refs #80" only; no
  fixes/closes/resolves + issue ref in any commit body on this branch.

## Residual handoff

Remote CI green at this exact head remains unproven by this lane (push
prohibited); the designated conformance lane (`.github/workflows/ci.yml`,
rootless-daemon provisioning + live suite) is the executable evidence path and
its exact commands were proven locally on both daemon branches above.
