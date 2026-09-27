# L80 round 24 — independent verifier re-proof at head fe6cc89

Branch `auto-80`, head `fe6cc89ca851f205572bb70a316ada58850fffe2` (the
uid-map root-range repair commit), issue #80, 2026-09-27. Read-only verify
round plus this note; no source or test changes, inventory delta +0.

## Both daemon branches re-executed by this verifier at this exact head

- Rootless daemon (`DOCKER_HOST=unix:///run/user/1000/docker.sock`,
  `docker info` reports `SecurityOptions: rootless`, server 29.7.2, image
  `maistro-builders:latest` = `sha256:205c40a9f0b3...`, probe container
  uid_map `0 1000 1 / 1 100000 65536`):
  `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v`
  = **16 passed, 1 skipped** — the skip is the inverted
  `test_sandbox_refuses_a_rootful_unmapped_daemon`. The full escape suite ran
  live: 7-class network default-deny + DNS, credential default-deny env,
  seed hygiene (indexed `.env`/`.env.production`/`.envrc`, untracked host
  secrets, key material at depth, nested `.git`, gitlink recursion),
  unprivileged uid execs, read-only rootfs with `/proc/mounts` write-scope
  enumeration, pid/mount/chroot/mknod/docker-sock/CapEff/NNP probes, timeout
  kill of detached descendants, cleanup, 3 GiB containment, live uid_map
  non-identity, nested-userns non-reopening, no block devices, no host
  sockets/ports.
- Rootful daemon (`/var/run/docker.sock`, rootdir `/var/lib/docker`,
  uid_map `0 0 4294967295`): same command = **1 passed, 16 skipped** — the
  fail-closed ADR-093 Decision 2 refusal, live, container removed behind it.

## Repair-specific re-proof (round-23 findings closure)

- `test_uid_map_root_mapping_detection` parametrized table now includes the
  partial map `0 0 1 / 1 100000 65536 -> refused` that round 23 flagged as
  missing; passed in the suite runs above.
- Direct classifier sanity at this head:
  `partial 0->0: refused=True`, `identity: refused=True`,
  `rootless: refused=False`, `remap: refused=False`,
  `no-uid0: refused=True`, `garbage: refused=True` — the exact
  round-23 admission vector is closed and unproven maps still fail closed.

## Gates re-executed at this head

- `packages/maistro-bootstrap/tests` full suite: 249 passed, 17 skipped.
- Lane pytest (`test_container_sandbox.py` + hardening + 15 rsi files,
  driver manifest argv): 193 passed, 16 skipped (driver check-3 log).
- `uv run ruff check .` / `ruff format --check .`: green (driver logs).
- Documented mypy gate (six packages incl. `maistro-bootstrap/src`):
  Success, no issues in 724 source files.
- `scripts/check-suite-inventory.py` for `maistro-bootstrap/tests` (266) and
  `maistro-rsi/tests` (801): ok (driver logs); `scripts/check-ac-state.py`:
  clean, worktree stayed clean afterward.

## Remote CI evidence (updated, still the open handoff item)

`gh pr view 1450` at this head: `formal-conformance` SUCCESS, `lint-and-type-
check` SUCCESS, but the CI **`test` job — which IS the designated conformance
lane — is FAILURE**, and it has failed at the same step on seven consecutive
heads (b272b42, 3eaafb9, 8f714f2, 881fdad, c12bae5, 90ab5b6, fe6cc89; the last
green ci.yml run d8c0d95 predates the rootless lane step, which was added in
bb24ae825/66fb808b1). Failure point: "Start a rootless Docker daemon for the
conformance lane" — `dockerd` never ready in 120s with
`failed to create NAT chain DOCKER: iptables ... Permission denied (you must
be root)` (run 36347745778, job 108700304682; same step failed in runs
36347224805, 36336385671, 36346506400). The runner-side rootless provisioning
therefore still needs repair before the "CI runs the suite" acceptance
criterion is met remotely; local both-branch execution above is the current
executable evidence.

## Claim/behavior drift checks

- SECURITY.md §8 (~326-352) and `docs/security/SANDBOX-SUPPORT-MATRIX.md`
  describe the enforced uid-0-to-host-root refusal (partial maps included)
  and both-branch CI proof — consistent with the code at this head.
- Conformance instantiates the production
  `maistro_bootstrap.builders.container_sandbox.ContainerBuilderSandbox`
  directly; no hardened fixture.
- Closure-keyword review: PR body uses "Refs #80" only; zero
  fixes/closes/resolves matches in any commit subject on
  0c8370a8..fe6cc89.
- Salvage review of the incoming handoff: worktree arrived clean at
  fe6cc89; the previous block's uncommitted work was already committed as
  fe6cc89 itself in the prior round; no develop-sync conflict remained
  (develop base 0c8370a8 is merged in 881fdad).
