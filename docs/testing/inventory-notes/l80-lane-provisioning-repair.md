---
inventory-delta:
  packages/maistro-bootstrap/tests: +4
---
# L80 round 19 — repair the CI conformance lane's provisioning and land the four remaining escape probes

Round 18's verdict was NEEDS-REPAIR on two concrete remote-CI defects at the
then-head `b272b424e`; both persisted at the merge head `3eaafb958`:

1. `CI / workflow-lint` red: actionlint+shellcheck flagged the lane's own run
   blocks — SC2155 at `ci.yml:489` (`export XDG_RUNTIME_DIR="/run/user/$(id -u)"`
   masks the substitution's status) and SC2046 at `ci.yml:508` (unquoted
   `$(id -u)` word-splitting in the image `save | load` pipe).
2. `CI / test` red: the lane's rootless bootstrap died with apt exit 100 —
   `docker-ce-rootless-extras` has no installation candidate on the runner
   image (the Docker apt repo is not in its sources) — so the escape suite
   never ran remotely. `integration-scope` and `gates-ran` were downstream
   casualties of the same two.

## Lane repair (ci.yml)

The rootless toolchain is now provisioned from Docker's **pinned static
bundle** (`docker-rootless-extras-29.8.1.tgz` from download.docker.com —
reachable from the runner, same host the workflow already curls actionlint
and shellcheck from) and the daemon is started directly with
`dockerd-rootless.sh --storage-driver=vfs` on a dedicated socket under
`$RUNNER_TEMP`, replacing the `docker-ce-rootless-extras` apt install and the
setuptool/`systemctl --user` service dance. `dockerd` itself is preinstalled
on the runner; `uidmap`/`slirp4netns` come from Ubuntu's own universe repo,
not Docker's. The shellcheck findings are fixed by assigning `uid="$(id -u)"`
before exporting and quoting every expansion.

The exact recipe was proven locally end-to-end before landing: static bundles
downloaded to `/tmp`, rootless daemon started as uid 1000, image seeded via
`save | load`, `maistro-builders:latest` (`205c40a9f0b3`) present, and the
suite run against it — before the file was edited.

## Four new escape probes (+4 node IDs, `test_container_sandbox.py`)

These finish the per-attack-class coverage the reopened issue asks for
("namespace/kernel boundary, network, device, host socket" — the Docker
backend previously covered devices/host-socket only via `/dev/kvm` absence,
`mknod`, and `docker.sock` path checks, and had no nested-namespace or
netns-table probe). They are the previous round's unlanded worker intent
(recovered from its job report; its `.bak` was byte-identical to the committed
file, so nothing was lost), adapted to this image's reality — unlike the
Bubblewrap sandbox, the Builder image *has* `/etc/passwd`, so the host-isolation
assertions target reach rather than absence:

- `test_nested_user_namespace_does_not_reopen_the_host` — nesting a user
  namespace (the way to regain dropped capabilities) cannot write the image
  root or mount through the sandbox's mount namespace; host-agnostic
  semantics (refusal or success, same assertions), mirroring the Tier-3 twin.
- `test_no_block_devices_reachable` — no `/dev/sd*|nvme*|vd*|loop*` node
  exists (a visible disk is a filesystem escape needing no kernel bug).
- `test_no_host_unix_sockets_visible` — `/proc/net/unix` holds only its
  header (unix sockets are per-netns; a populated table is a reachable host
  socket, i.e. host root).
- `test_no_host_listening_ports_visible` — `/proc/net/tcp`+`tcp6` hold only
  headers (the netns is real, not shared with the host).

All four are `_needs_isolating_daemon`-gated like the rest of the escape
suite, instantiate the production `ContainerBuilderSandbox`, and skip on a
daemon the sandbox itself refuses.

## Evidence at this round's head

- Escape suite on the live rootless daemon (`unix:///run/user/1000/docker.sock`,
  SecurityOptions `rootless`, image `205c40a9f0b3`): **16 passed, 1 skipped**
  (only the qualifying-daemon refusal test skips) — including the four new
  probes. An independently provisioned static-bundle daemon (same recipe as
  the new lane) ran the pre-addition suite **12 passed, 1 skipped** earlier
  this round.
- Rootful branch on `unix:///var/run/docker.sock`:
  `test_container_sandbox.py` + hardening + argv suites → **29 passed,
  16 skipped** (refusal test passes against the real rootful daemon).
- `uv run pytest packages/maistro-bootstrap/tests -q` → **247 passed,
  17 skipped**; `uv run ruff check .` and `ruff format --check .` clean;
  actionlint 1.7.7 + shellcheck 0.10.0 over all workflows → no findings;
  `check-required-checks`, `check-uv-setup`, `check-workflow-write-safety`,
  `check-suite-inventory`, and the vulture ratchet (1403 == 1403) all green.
