---
inventory-delta:
  packages/maistro-bootstrap/tests: +11
---

# 80-sandbox-rootless-userns-conformance

#80 reopened (D-04): `ContainerBuilderSandbox` claimed ADR-093 Tier-3-style
containment while launching on whatever daemon `docker` reached — including a
rootful, user-namespace-unmapped one, where container uid 0 *is* host uid 0 and
even the auditable one-shot bootstrap `chown` runs as host root. ADR-093
Decision 2 requires a retained container runtime to be rootless and socket-less;
nothing enforced or tested that.

Eleven node IDs added to `maistro-bootstrap`, nothing removed or renamed.

`packages/maistro-bootstrap/src/.../container_sandbox.py` now refuses to enter
on an identity `/proc/self/uid_map` (rootless daemons and `--userns-remap`
daemons both map container uids onto unallocated subuids; unproven output fails
closed). The suite proves both halves of that conformance split:

`test_container_sandbox_hardening.py` (+9): the boundary probe is issued as the
agent uid before the harness lookup, bootstrap chown, and seed; an identity map
(or an unreadable one) refuses entry, runs no root exec, builds no seed, and
removes the created container; `_uid_map_is_identity` is pinned to the
documented real-world shapes of `/proc/self/uid_map` (rootful identity, remap,
rootless two-line map, multi-line identity, garbage/empty fail closed) — 6
parametrized cases.

`test_container_sandbox.py` (+2, Docker-gated on the *actual* backend):
- `test_container_user_namespace_maps_container_uids_off_the_host` — on a
  rootless/userns-remapped daemon, the live container's uid_map is non-identity
  and container uid 0 does not map to host uid 0.
- `test_sandbox_refuses_a_rootful_unmapped_daemon` — on a rootful unmapped
  daemon (this repository's CI-default and the D-04 regression host), the
  production sandbox refuses to start, cites ADR-093 Decision 2, and leaves no
  container behind. The 12-test escape suite skips there with a reason pointing
  at this test; the two branches are complementary conformance evidence for the
  same requirement.

Verified locally both ways: against the shared rootful daemon
(`DOCKER_HOST=unix:///var/run/docker.sock`) — 1 refusal test passed, 12 skipped;
and against a user-local rootless dockerd 29.7.2 (`dockerd-rootless-setuptool.sh
install`, `SecurityOptions=[...,"name=rootless"]`, container uid_map
`0 1000 1 / 1 100000 65536`) — all 12 escape tests passed, including the
network-deny, seed-hygiene, writable-scope, capability, timeout-kill,
resource-budget and new userns probes.
