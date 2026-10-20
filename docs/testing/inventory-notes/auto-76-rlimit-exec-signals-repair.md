---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Issue 76 repair — execing helper must not leak ignored signals

This repair round follows independent verification of `auto-76` at
`48cf1e57dd`. The verifier's `check-3` failure was one test
(`test_sandbox_exec.py::TestRunFunctionChecksDocker::test_correct_implementation_passes`)
on a host whose canonical selector correctly refuses every workload: the
bubblewrap probe cannot build a namespace under the enforced `RLIMIT_NPROC`
budget, `runsc` is absent, and `/dev/kvm` is unreadable. The test asserted a
passing sandbox check the host could never provide. It is now gated on the same
`_selector_satisfies_trusted_tool()` measurement its sibling
`test_swebench.py` already used, so a correct refusal skips instead of failing.

Two further, independent defects surfaced when the whole
`packages/maistro-core/tests/sandbox` and `.../extensions` suites were run — the
verify battery had not included the extensions suite:

* **`_rlimit_exec` leaked the interpreter's ignored signals into the sandbox.**
  The helper introduced by the #76/#80 cutover `execvp`s in place, so
  `SIGPIPE`/`SIGXFSZ` — which CPython sets to `SIG_IGN` at startup — stayed
  ignored in `bwrap` and in every workload process. With `SIGXFSZ` ignored a
  write past `RLIMIT_FSIZE` returns `EFBIG` and `dd` exits 1 instead of being
  killed by the kernel, so
  `test_sandbox_conformance.py::TestWorkspaceStorageRule::test_the_file_size_ceiling_stops_a_runaway_write`
  failed (`assert 1 == 153`). The helper now restores the same dispositions
  `subprocess` restores in a forked child, immediately before `execvp`.
* **`test_isolation_profiles.py` still asserted the retired `network` field.**
  The develop-sync merge dropped the legacy `network=` argument from
  `build_sandbox_config` (egress is the sole authority, #76/#77) but left
  `assert config.network is True`; the assertion now pins
  `config.network is False` beside the authoritative
  `config.egress.mode is EgressMode.SCOPED`.

Also updated: `docs/security/SANDBOX-SUPPORT-MATRIX.md` still described network
as reachable through a `network_allowed` policy field, which this round removes
from `WorkloadPolicy`. It now names `EgressMode.HOST` and the mechanical
rejection of `SandboxConfig.network`.

The +1 is one hermetic test in
`packages/maistro-core/tests/sandbox/test_real_backend.py`:

* `test_the_execing_helper_hands_default_signal_dispositions_to_the_sandbox` —
  runs `limited_argv` with `/bin/sh` reading `/proc/self/status` and asserts the
  inherited `SigIgn` mask clears the `SIGPIPE`/`SIGXFSZ` bits. It fails against
  the pre-repair helper (`SIGPIPE stayed ignored across the execing helper`) and
  passes after it; no bubblewrap namespace is needed, so it runs everywhere
  `/proc` is readable.