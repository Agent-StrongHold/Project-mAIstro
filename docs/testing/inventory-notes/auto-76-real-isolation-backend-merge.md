---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-bootstrap/tests: -1
---

# Issue 76 merge reconciliation — inventory delta

This note records the net test-count delta introduced by resolving the
develop-sync merge for #76 ("Ship a real supported unattended-isolation
backend"). The merge combined the #76 selector cutover (ours) with the
downstream OpenClaw/Pi harness nodes, the #614 separated-streams contract, and
the container-hardening work (develop). The counts below are the *residual*
drift between the resolved worktree and the pre-resolution expected ledger
(`baseline.json + Σ` every other note's `inventory-delta`), measured with
`scripts/check-suite-inventory.py --show` against per-suite
`pytest --collect-only -q` node-ID counts.

## `packages/maistro-core/tests: +2`

Two new node IDs in `tests/capabilities/test_foreign_harness_providers.py`, one
each in `TestOpenClawMicroVMWiring` and `TestPiMicroVMWiring`:

* `test_a_policy_the_substrate_cannot_honour_refuses` — asserts that when a
  caller asks for a workload policy the microVM substrate cannot honour (an
  egress grant the deny-only backend refuses), the factory fails closed with
  `LauncherVMUnavailableError` rather than silently launching an under-isolated
  sandbox. This mirrors the existing OpenCode wiring test.

These back the migration that moves OpenClaw and Pi off direct `MicroVMSandbox`
construction and through the canonical `SandboxSelector` (the same seam OpenCode
already uses), which is what lets `test_single_authority.py`'s convergence gate
pass: the only remaining `MicroVMSandbox(` construction lives inside the
allow-listed `sandbox/backends/launcher_vm.py` backend, and every provider
factory routes through the selector.

## `packages/maistro-bootstrap/tests: -1`

A net removal of one node ID across the two container-sandbox test files touched
by the merge:

* `test_container_sandbox_hardening.py` drops develop's docker-direct cases
  (`test_container_env_is_home_and_nothing_else` and
  `test_run_argv_streams_keeps_the_hardened_exec_and_separated_streams`). They
  asserted the pre-#76 docker argv shape (`_docker_calls`, `_AGENT_UID_GID`,
  `_AGENT_HOME`) that the #76 cutover deleted in favour of the selector backend
  exec, so they no longer describe reachable behaviour and would fail against
  the selector-only adapter. What remains are the four cases that still hold —
  the adapter never builds a docker command, the seed archive is built host-side
  with the denylist, the sync extract filters git host-side, and failure paths
  never fall back to direct execution.
* The #614 separated-streams contract develop added is **preserved**, not
  dropped: it was adapted into a hermetic `test_run_argv_streams_returns_separated_streams_and_the_status`
  in `test_container_sandbox.py` that injects a stub VM sandbox through the
  selector instead of driving a real container, so it exercises
  `run_argv_streams`'s `(exit_code, stdout, stderr)` contract with no Docker
  dependency.

The net lands one below the pre-resolution expected count. `packages/maistro-evolve/tests`
moved zero: develop's `test_sandbox_exec.py` union cases were carried through
the conflict resolution unchanged and were already accounted for by an existing
note.
