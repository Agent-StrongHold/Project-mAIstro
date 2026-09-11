---
inventory-delta:
  packages/maistro-core/tests/sandbox/test_real_backend.py: +3
---

# #1235 sandbox rlimit-aware capability probe coverage

Three new collected maistro-core cases, all in `test_real_backend.py`:

1. `test_the_probe_runs_bwrap_under_the_spawn_budgets` — the probe's `subprocess.run`
   receives a `preexec_fn`, and invoking it applies exactly `resource_limits(SandboxConfig())`
   (observed through a recording `setrlimit`, so nothing touches the test process).
2. `test_the_shared_preexec_hook_applies_exactly_the_limits_given` — `preexec_for` applies
   exactly the mapping it is given, one hook shared by `exec` and the probe so they cannot drift.
3. `test_an_eagain_namespace_failure_is_reported_as_an_absent_tier` — bwrap EAGAIN at
   namespace clone under the enforced budgets reads as Tier-3 absent with the probe stderr
   in `HostCapabilities.notes`, the unitized form of the #1235 reproduction.

Also updated: the `requires_bwrap` skip reason now carries the probe's own note, so a host
that fails under the enforced rlimits reports *why*.
