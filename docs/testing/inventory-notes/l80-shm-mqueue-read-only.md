---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---
# L80 round 10 — pin the runtime's implicit /dev/shm and /dev/mqueue read-only

Prior verification (round 9, NEEDS-REPAIR) proved by live probe that
`ContainerBuilderSandbox` accepted agent writes to `/dev/shm` and
`/dev/mqueue`: those mounts are created by the container runtime *outside* the
image layers, so `--read-only` does not touch them, and
`test_container_sandbox.py`'s writable-scope case did not enumerate them.

## Behavior change

`container_sandbox.py` now passes two extra create-time tmpfs mounts —
`/dev/shm` and `/dev/mqueue`, each `size=64k,ro,nosuid,nodev,noexec` — so the
runtime's implicit writable scratch is replaced by read-only stubs and the
declared contract ("only the workspace and `/tmp` tmpfs are writable") matches
reachable behavior. Nothing else in the create argv changed; the mqueue path
becomes a plain tmpfs, so POSIX message queues are default-deny inside the
sandbox.

## Test delta

- `test_container_sandbox_hardening.py` (+1): new
  `test_container_creation_pins_implicit_runtime_tmpfs_read_only` — offline
  argv-shape proof that every `--tmpfs` outside `{/workspace, /tmp}` carries
  `ro`/`noexec`/`nosuid`/`nodev` and that `/dev/shm` + `/dev/mqueue` are both
  pinned.
- `test_container_sandbox.py` (modified, no count change):
  `test_rootfs_and_writable_scope_are_explicit` now probes writes to
  `/dev/shm`, `/dev/mqueue`, `/dev` and `/proc`, and additionally enumerates
  the live `/proc/mounts` and asserts every `rw` mount outside
  `{/tmp, /workspace}` refuses an agent probe write — so a future implicit
  Docker default cannot reopen scratch without failing this suite.

## Live evidence (this round, Docker 29.7.2, image maistro-builders:latest)

- Pre-fix reproduction: raw `docker run` with the old flags accepted
  `touch /dev/shm/p` (rc=0) and `touch /dev/mqueue/p` (rc=0); `mount` showed
  `shm ... rw` and `mqueue ... rw`.
- Post-fix: both writes fail with `Read-only file system`; `grep shm\|mqueue
  /proc/mounts` shows both `ro,nosuid,nodev,noexec`.
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py`
  = 11 passed (Docker-gated, real backend).
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  test_container_sandbox_argv_status.py` = 19 passed.
- `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py`
  = 7 passed.

SECURITY.md limitation #8's conformance citation now states the pinned
`/dev/shm`/`/dev/mqueue` evidence explicitly.
