---
inventory-delta:
  packages/maistro-core/tests: +26
---
# claude-m2-76-real-isolation-backend

The sandbox subsystem had a selector, a five-rung policy ladder and one fake
backend, and nothing assembled them (#76, ADR-093). Every property the ladder
promises was therefore unfalsifiable in a shipped configuration: no caller
built a selector, so no caller could be refused by one.

**`tests/sandbox/test_real_backend.py` (+26)**, in three groups that are
deliberately not the same kind of test:

*The fail-open the selector permitted.* `register("vm", FakeSandboxBackend())`
was legal, and it made in-process `subprocess.run` satisfy `UNTRUSTED_CODE` —
a policy whose entire stated reason is that model-generated code must run
behind a VM boundary. Everything downstream trusts the tier, so nothing else
would have caught it. A backend now declares its own tier and a mismatch is
refused; a caller may register something weaker than it hoped for and can never
relabel one as stronger.

*Detection, and the fail-closed rule.* Every absent tier carries a reason, since
an absent tier without one is indistinguishable from an unasked question. KVM
present-but-unopenable is not Tier 1 — the common container case, where
reporting Tier 1 on the strength of a visible device node fails at spawn, after
the policy check meant to prevent it. KVM without a VMM is not Tier 1 either. A
host with nothing refuses everything, the fake is never registered
automatically, and a bubblewrap-only host still refuses `UNTRUSTED_CODE`,
because ADR-093 is explicit that Tier 3 is a guardrail against accidents rather
than a boundary against hostile code.

*The backend's flags, then the kernel.* Which flags `bwrap` gets is this
repository's security content, so those are asserted on every host — a test
needing bubblewrap installed would leave them unverified on most machines.
Whether `bwrap` isolates is the kernel's job, and is asserted where bubblewrap
exists: real execution, the host filesystem invisible, a timeout that kills,
and a network namespace with nothing but loopback in it.

Detection is a **functional probe**, not a `which` check, and CI is what
taught us the difference. `bwrap` installed cleanly on the runner and then
failed at `loopback: Failed RTM_NEWADDR: Operation not permitted` — Ubuntu
24.04 ships `kernel.apparmor_restrict_unprivileged_userns=1`, so the binary
exists and cannot build the namespace. Reporting Tier 3 from the binary's
existence puts a workload on a boundary that cannot be built, and the failure
lands at spawn: after the policy check that existed to prevent it. Two tests
cover it — a probe that fails, and a probe that cannot run at all — and the
integration group now skips on *capability* rather than on binary presence.

CI installs `bubblewrap` in `ci.yml`'s `test` job and `quality.yml`'s
`coverage (no services)` job. Without that the six integration tests skip
everywhere and the diff-coverage gate measures a backend whose execution paths
nothing ran — the exact gap that gate exists to find.

Two vulture entries were pruned rather than banked, because both became live
code: `SandboxConfig.writable_paths` is now honoured by the bubblewrap backend,
and `FakeSandboxBackend` now has a caller in `build_selector`.
