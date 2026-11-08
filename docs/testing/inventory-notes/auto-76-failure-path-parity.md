---
inventory-delta:
  packages/maistro-bootstrap/tests: +4
  packages/maistro-core/tests: +21
---

# auto-76-failure-path-parity — executed lifecycle/failure-path evidence that does not need a live VM

Repair/verification round for #76's acceptance clarification "Non-skipped
cleanup and retirement parity": lifecycle, cleanup and failure-path behavior on
the shipped backends must be *executed* evidence, not skipped on hosts where
Kata is not deployable. Every test below is stub-backed or monkeypatched, so it
runs in CI without docker/Kata and pins the production code paths the live
conformance suite exercises when it can run.

`packages/maistro-bootstrap/tests` +4 — new `TestLifecycleBoundary` in
`test_container_sandbox.py` (stub VM backend, so the contract holds on every
host): exit destroys through the bridge and removes the seed; adapters used
outside their context manager refuse; a second `__exit__` is a no-op (one
teardown, no double destroy/rmtree — the issue-76 idempotent-destroy parity
item); a backend that refuses at spawn leaves no seed directory and no
half-bound adapter.

`packages/maistro-core/tests` +21 across three files:

- `test_kata_backend.py` +11 — the Tier-1 backend's construction and spawn
  failure paths, unitized in-process: the constructor refuses to claim a VM tier
  without its toolchain (fail-closed, no weaker tier silently substituted);
  `_network_args` maps exactly the egress modes a grant can name; `_env_args`
  carries the attempt fence sorted after caller env; an explicit workspace bind
  is host-owned (spawn creates it, destroy leaves it); a failed no-follow open
  of the bind root reclaims the owned tempdir; a dead `docker run` or a
  non-zero/empty-id run reclaims the guest via `_remove_container`; a
  pipe-flooding child is reported as `OUTPUT_LIMIT_EXIT_CODE`; operations on an
  unknown instance (and on a lock-without-instance ghost) raise `KeyError`; a
  lost daemon during container removal escalates to `RuntimeError`, not a
  success report.
- `test_real_backend.py` +6 — selector assembly survives a VM probe/constructor
  disagreement (tier dropped, warning logged, no raise); `_probe_vm` reports a
  docker probe failure as tier-absent with a reason (#1328 contract) and
  refuses a docker whose runtimes do not include Kata; and the
  `_rlimit_exec` helper's argv contract is pinned in-process with an `execvp`
  stub (commandless rejection, triple-separator validation, setrlimit-then-exec
  happy path) so its argument handling is checked where CI can see it.
- `tools/test_canonical_sandbox.py` +4 — the facade surface product code
  actually calls: `exec` runs safe commands through `[/bin/bash, -lc]` with the
  configured timeout and blocks dangerous ones before the backend is touched;
  file transfers are confined to `/workspace`; `_safe_path` rejects foreign
  roots, absolute paths and traversal; the context manager destroys on exit and
  TTL expiry is observable without sleeping.

No production code changed in this round; the +0 on
`test_host_path_boundary.py` is an existing no-follow test extended to
`make_beneath_guest_readable` (same node ID).

Validation: `ruff check .` and `ruff format --check .` clean; the driver's
25-file sandbox battery re-run → 425 passed, 8 skipped (the skips are the
live-Kata/host-specific gates); `check-suite-inventory.py` green for
bootstrap and core after this note.
