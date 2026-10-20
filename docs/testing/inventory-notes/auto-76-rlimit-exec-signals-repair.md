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
## Round evidence — CI-repair round at `b61d652dcc` (job 14003c29200a45e69a9cc52bfabafeaf)

Dispatch carried one prior finding (`check-3.log` from job
`70dc946dddce4ac0965a391016ee33df`) and a vulture-ledger instruction. Both were
re-derived here rather than assumed, and one new ledger defect was found by
running the gates the verify battery did not include.

* **The carried `check-3` finding is already fixed and does not reproduce.** It
  was captured at `48cf1e57dd`, where the class was still
  `TestRunFunctionChecksDocker` gated on `_DOCKER_AVAILABLE`; `b61d652dc`
  renamed it `TestRunFunctionChecksSandbox` behind
  `_selector_satisfies_trusted_tool()`. Re-run at HEAD:
  `pytest packages/maistro-evolve/tests/benchmarks/test_sandbox_exec.py` →
  30 passed, 3 skipped; `test_swebench.py` → 12 passed, 3 skipped.
* **`exact-debt-ledger` (vulture) is green, unchanged.**
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → 1326 reviewed identities / 1325 findings, no unbanked
  identity. No vulture ledger edit was warranted this round.
* **New defect: `maistro.sandbox.backends._rlimit_exec` was a graph-invisible
  `-m` target.** The backend named it in a string
  (`sys.executable -m "maistro.sandbox.backends._rlimit_exec"`), so the module
  was load-bearing on every bubblewrap spawn yet reported unreachable. It was
  banked as a `reachability-baseline.json` row plus a CONNECT disposition, and
  that bank is exactly what `check-reachability-provenance.py` refuses: a
  candidate baseline may only grow behind an authorization read from the merge
  base (two-merge rule), and no grant exists from the base. Repair: the module
  is now a static import in `backends/bubblewrap.py` and the argv takes its
  name from the object (`_rlimit_exec.__name__`), so the edge is real and the
  gate can see it. `quality/reachability-baseline.json` drops the row (170 →
  169) and `quality/reachability-dispositions.json` drops the
  `sandbox-rlimit-exec-helper` group (49 groups / 169 modules); both ledgers
  shrink toward trusted state, so no grant is involved.
* **Consequential doc fix:** `docs/architecture/CONVERGENCE-MATRIX.md`'s
  `Sandbox isolation` row said `few` unreachable; the census recomputes `none`
  (0 of 18). `check-convergence-matrix.py` now passes (169 attributed).

Verification at this head (all re-executed): `ruff check .` / `ruff format
--check .` clean; `mypy packages/maistro-core/src/maistro/sandbox` clean;
`pytest packages/maistro-core/tests` → 15669 passed, 1131 skipped;
`packages/maistro-bootstrap/tests` → 240 passed; `packages/maistro-evolve/tests`
+ `packages/maistro-rsi/tests` → 2713 passed; `packages/maistro-core/tests/
{capabilities,extensions}` → 1835 passed; `check-suite-inventory.py` → all 21
suites ok (no delta this round: no test added or removed).

Two reachability reds remain and neither is repairable inside this lane:

* `maistro.runs.admission_identity` — **pre-existing on develop**, not caused by
  #76. Proven by scanning the base in a throwaway detached worktree: at
  `e20e9f52ea` `check-reachability.py` returns 1 naming the same module, and
  `tests/test_check_reachability.py::test_baseline_matches_the_tree` fails
  identically there. The module has no production importer at either rev
  (`git grep admission_identity origin/develop -- '*.py'` finds only its own
  test), and the #1851 lane already records this exact failure in
  `docs/testing/inventory-notes/task-admission-identity-types.md:176`.
* `maistro.tools.sandbox.docker` — the intended new row (the #76 cutover moved
  `tools/sandbox/server.py` onto `canonical.py`, so the retired Docker sandbox
  has no product caller; `test_single_authority.py` and the matrix both pin
  that). It needs a reachability authorization landed on develop first
  (two-merge rule); deleting the module instead would require rewriting
  `packages/maistro-server/tests/test_sigterm_shutdown.py`,
  `packages/maistro-evolve/tests/test_e2e_sandbox_loop.py`,
  `packages/maistro-core/tests/tools/test_sandbox_paths.py` and deleting
  `test_docker.py` — a retirement PR of its own (#35), and unverifiable on a
  host with no sandbox backend.

### AC1 probe on this host: a real workload does run behind the real backend

The verify battery reported AC1 as unverifiable here because every standard
policy refuses. That refusal is the fail-closed contract, not the whole story:
`bubblewrap` *can* build a namespace on this machine. The probe said otherwise
only because `SandboxConfig.max_processes` defaults to `128` and uid 1000 is
running ~538 threads, so the budgeted clone fails `EAGAIN` — the deliberate
`#1235`/`#1328` rule that the probe must answer for the config spawn will use.
Raise the budget explicitly and the real path works end to end:

```
build_selector(sandbox_config=SandboxConfig(max_processes=1024))
  -> tiers ['bubblewrap']
policy = WorkloadPolicy(min_tier="bubblewrap", mode=INTERACTIVE, ...)
  -> select() == ('bubblewrap', BubblewrapSandboxBackend)
spawn()/exec(['/usr/bin/python3','-c','print(pid,uid); sys.exit(7)'])
  -> exit 7, stdout "pid 2 / uid 1000"       # fresh PID namespace
exec(['/usr/bin/sh','-c','ls /home ...; ip a | grep -c 172.'])
  -> "home_hidden", "0"                      # host home and network absent
```

So AC1 is verified for the Tier-3 backend through the canonical selector, and
`pid 2`/`exit 7` show the workload really executed inside the boundary with its
status propagated. The VM tier stays unverified: `/dev/kvm` is unreadable and no
`runsc`/Kata runtime is installed, so `UNTRUSTED_CODE`, `BENCHMARK_EVAL` and
`BUILDER_AGENT` correctly refuse here and cannot be exercised on this host.

Residual gap found while probing (reported, not repaired here): the raised
budget is unreachable through `SandboxSelector.build_config()`. It accepts
`**overrides` but only forwards `memory_mb`/`timeout_s`/`egress`, so it always
returns the default `max_processes=128` — while `build_selector(sandbox_config=…)`
probes with whatever budget the caller passed. A caller that configures a
non-default budget therefore gets a probe answer spawn cannot reproduce. Giving
`max_processes` a policy ceiling is a `WorkloadPolicy` change with ADR weight,
so it belongs in its own lane.
