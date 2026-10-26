---
inventory-delta:
    packages/maistro-core/tests: 3
---

# Issue 76 live-Kata repair inventory delta

This repair round stood up the real Kata deployment profile on the
development host (`/dev/kvm` access, kata-containers 3.32.0 static bundle,
docker `kata` runtime via `runtimeType: io.containerd.kata.v2`) and fixed the
three production defects the live conformance then exposed:

1. `KataSandboxBackend.exec` now re-asserts the spawn-time
   no-new-privileges promise per exec (`setpriv --no-new-privs`), because
   Kata's guest agent applies NNP to the container init process but not to
   `docker exec` processes (`test_kata_backend.py` +1: the mocked argv pin).
2. Kata's virtiofs share enforces host mode bits against the guest's id
   mapping, so the 0700/0600 transfer defaults were unreadable in-guest.
   `make_beneath_guest_readable` widens the written chain through the same
   no-follow walk, and the bind root gets /tmp semantics
   (`test_host_path_boundary.py` +2: chain widening incl. fd-root caller,
   swapped-symlink refusal).
3. `_probe_vm` now absorbs a launcher `RuntimeError` as tier-absent instead
   of aborting detection — the same #1328 contract the bubblewrap probe
   already honored. No test-count change: the existing
   `test_an_unsupported_preexec_hook_reads_as_absent_not_an_abort` previously
   passed vacuously on hosts without the Kata profile and now exercises the
   real docker-info call path.

Net +3 tests across `packages/maistro-core/tests` (13→14 in
`test_kata_backend.py`, 25→27 in `test_host_path_boundary.py`).
`test_kata_live_conformance.py` keeps its 10 tests; on the originating
configured host they ran and passed against real Kata VMs instead of skipping.

## Independent repair-lane verification (2026-10-23)

At `5e1c0835d7df3e2591b57d156e6552b766d90dcc`, the assigned worktree's
current environment did not reproduce that configured deployment profile:

- `uv run pytest packages/maistro-core/tests/sandbox packages/maistro-core/tests/tools/test_canonical_sandbox.py packages/maistro-core/tests/tools/test_sandbox_paths.py -x -q`
  -> 238 passed, 38 skipped. Live Kata conformance cases were among the
  environment-dependent skips; this run is not live-VM acceptance evidence.
- `uv run pytest packages/maistro-server/tests/test_sigterm_shutdown.py -x -q`
  -> 2 passed, then the orphan-cleanup test failed because the restart phase
  observed `kata-289be30c9fc3`. Immediate `docker ps -a --filter name=kata-`
  showed no remaining containers. The exact orphan-cleanup test then passed
  alone (`1 passed in 9.01s`). Treat the first result as a transient
  integration failure, not a proven code fix; repeat on the supported profile.
- `uv run python scripts/check-suite-inventory.py` -> all suites match,
  including core at 16860. `uv run python scripts/check-convergence-matrix.py`,
  `uv run ruff check .`, and `uv run ruff format --check .` passed.

These results are a fresh verification record, not a substitute for rerunning
live Kata conformance and the server orphan-cleanup/restart behavior together
on the documented deployment profile.

## Combined live rerun on the Kata profile (2026-10-26, head `9ef2204c`)

That substitute has now been executed: both suites ran together on the same
host in the same round, on the documented deployment profile (KVM usable,
kata-runtime on PATH, docker daemon answering with the `kata` runtime):

- Placement proof: `build_selector().available_tiers == ['vm']` via
  `KataSandboxBackend`, and all four standard policies — UNTRUSTED_CODE,
  BENCHMARK_EVAL, TRUSTED_TOOL, BROWSER_AUTOMATION — select the Kata backend
  through the canonical selector on this host. This also makes the server
  suite's `_canonical_sandbox_placeable()` gate true, so the orphan-cleanup
  class no longer skips here.
- `uv run pytest packages/maistro-core/tests/sandbox/test_kata_live_conformance.py
  -v --timeout=600` → **10 passed in 30.45s, 0 skipped**: all four policies
  launch real work through the selected backend, and the host boundary, file
  transfer, file budget, output overflow, timeout and cancellation cases each
  verified guest removal on real Kata VMs.
- `uv run pytest packages/maistro-server/tests/test_sigterm_shutdown.py -v
  --timeout=600` → **3 passed, 0 skipped in 20.57s**, including
  `TestStopRestartLeavesNoOrphanedSandboxes::
  test_stop_destroys_seeded_sandbox_and_restart_is_clean` — the previously
  skipped server cleanup path executed against the canonical
  `maistro.tools.sandbox.canonical.create_sandbox` with no orphaned
  `kata-*` containers after stop and restart.
- Idempotent destroy and the cancelled-destroy window are covered by
  executed unit tests in `test_kata_backend.py` (double `destroy()` and the
  destroyed-between-lock-and-instance case), which ran inside this round's
  core producer leg (17,164 passed).
- The bubblewrap-tier cases in `test_real_backend.py` still skip here, with
  the probe's own reason ("bwrap: Creating new namespace failed: Resource
  temporarily unavailable") — explicit unsupported-host skips, not counted
  as proof; the selected backend carries the executed evidence.
