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

## Re-proven at the merged head `f2133735b1` (2026-11-16, base `f8a2df966`)

Two develop merges (`981a804a`, `f8a2df966`) landed after the round above,
so every claim was re-executed on the current tree against the current base
(`f8a2df966a1d0db82be5fc08a571ed4750902c88` == `origin/develop`, verified by
`git rev-parse`). Host note: the profile needed restoring — `/dev/kvm` was
`root:kvm 0660` after a WSL restart and this process lost access
(`chmod 666 /dev/kvm`, resets at reboot; kata-runtime 3.32.0 and the docker
`kata` runtime were still in place). Placement proof re-run:
`build_selector().available_tiers == ['vm']` via `KataSandboxBackend`, all
four standard policies select it.

- Combined live rerun, same two suites on the same host in one round:
  `test_kata_live_conformance.py` → **10 passed / 0 skipped** (26.3s);
  `test_sigterm_shutdown.py` → **3 passed / 0 skipped** (23.5s) including
  `TestStopRestartLeavesNoOrphanedSandboxes` through the canonical
  `maistro.tools.sandbox.canonical.create_sandbox`.
- Real-backend conformance on the selected production backend
  (`test_sandbox_conformance.py`, fixture wires `build_selector()`): first
  run 9 passed / 1 failed — `TestFilesystemBoundary::
  test_writes_land_in_the_sandboxes_own_workspace` died at Kata guest startup
  ("failed to start Kata sandbox: unknown error", kata.py:127). It passed
  alone, and the full file re-ran **10 passed / 0 skipped** (184.9s, rlimits
  readback inside the guest: `nproc == profile.max_processes`), so the first
  result is recorded as transient guest-startup contention, matching the
  2026-10-23 transient above. `docker ps -a --filter name=kata-` → 0
  containers after the run (no orphans).
- Named CI gate (Coverage gate, publish-set floor + diff coverage) replayed
  with CI's exact producer invocations (REQUIRE_AUTH=false, MAISTRO_DRY_RUN=1,
  five per-package `coverage run --append --branch` legs; python:3.12-slim
  pre-pulled as the workflow does): core 17256 passed / 1236 skipped /
  7 xfailed (884s), canvas 584 passed / 75 skipped, evolve 1000 passed /
  6 skipped, bootstrap 276 passed / 1 skipped, rsi 1795 passed / 1 skipped /
  1 failed — the failure is the recorded operator-image finding
  (`maistro-builders:latest` lacks `git`, so the in-container
  `git rev-parse` rerun in the contained-fitness probe fails; CI skips this
  test because runners have no such image). `.coverage` still recorded the
  rsi leg. `coverage report --fail-under=87` → exit 0, TOTAL 93% over 93,902
  statements (conservative: unit producer data only — MinIO/PostgreSQL
  producers append hits). `coverage xml` + `scripts/check-diff-coverage.py
  coverage.xml --base f8a2df966...` → exit 0: all 29 changed source files ≥90%
  lines / ≥80% branch arcs, measured locally even with the bubblewrap-tier
  skips CI's producer does not have (its job installs bwrap and flips the
  userns sysctl).
- Ledger and repo gates on the merged head: vulture CI-exact argv → exit 0
  (1238 reviewed → 1236 findings, 0 unbanked, no amendment);
  `check-suite-inventory.py` full → 21 suites match (35,389 unique IDs);
  mypy (AGENTS-exact, 7 package trees) → Success, 955 files; ruff check and
  `ruff format --check` → pass (3568 files). The #76 sandbox named-gate test
  union ran green in this round's driver checks: 445 passed / 28 skipped
  (bwrap-tier and Kata-mock environment skips), including
  `test_single_authority.py`, `test_import_layering.py`, and the evolve/RSI
  fail-closed consumption suites.
- No test counts changed in this round: this is re-executed evidence at a
  new head, not an inventory delta.
