# Sandbox support matrix

**Status:** enforced by `maistro.sandbox.detect` and
`packages/maistro-core/tests/sandbox/test_real_backend.py`.
**Governing decision:** [ADR-093](../adr/ADR-093-sandbox-isolation-model.md).

ADR-093 fixes the *required guarantee* and a fallback ladder. This page names
which rungs of that ladder this repository actually ships a backend for, what
each one needs from the host, and what happens when the host cannot provide it.

The distinction that matters throughout: **detection reports capability, policy
decides sufficiency.** A host that can only do Tier 3 is not a host that may run
untrusted code badly — it is a host on which untrusted code does not run.

## Tiers and their backends

| Tier | ADR-093 name | Backend shipped | Host requirements | Status |
|---|---|---|---|---|
| 1 | Hardware VM | `KataSandboxBackend` (`docker --runtime=kata`) | `/dev/kvm` readable/writable; `kata-runtime` and `docker` on `PATH`; Docker daemon reports a configured Kata runtime; a preloaded OCI image; guest image must ship util-linux `setpriv` | **Shipped**, selected by the canonical selector |
| 2 | User-space kernel | *none yet* | `runsc` on `PATH` | Detected, not implemented |
| 3 | OS sandbox | `BubblewrapSandboxBackend` | `bwrap` on `PATH` **and able to build a namespace** — see below | **Shipped** |
| — | Fake | `FakeSandboxBackend` | none | Dev/test only, never registered automatically |

Tier 2 is *probed* but has no backend. Tier 1 is supported only through the
Kata deployment profile named above: a generic VMM binary is not enough to
claim support. `detect_host_capabilities()` and `build_selector` refuse a host
that cannot construct that exact profile. The result is a refusal, not a
silent downgrade.

### Caller-wired vm substrate: the launcher seam (deny-only)

`LauncherVMSandboxBackend` wraps SPEC-205's `VMMLauncher` seam as a vm-tier
backend. It is never registered by `build_selector` — a launcher cannot be
probed as a host capability — but callers that wire one (the opencode harness
factory is the shipped example) register it behind a `SandboxSelector`, so
policy admission, egress and budgets remain the selector's decision (#76).
Its support surface is deliberately narrow: **deny-only**. No shipped launcher
can filter destinations, and none provides a networked guest profile, so a
`SCOPED` grant is refused at selection and a `HOST` grant at spawn — the
substrate's own `network` field is overridden to `none` by the policy grant
rather than trusted.

## What each workload requires

From `maistro.sandbox.policy`:

| Policy | Minimum tier | Supported disposition |
|---|---|---|
| `UNTRUSTED_CODE` | `vm` | **Yes, when the Kata profile is available; otherwise refused** |
| `BENCHMARK_EVAL` | `vm` | **Yes, when the Kata profile is available; otherwise refused** |
| `TRUSTED_TOOL` | `container` | **Yes, selected on Kata (VM is stronger); otherwise refused** |
| `BROWSER_AUTOMATION` | `container` | **Yes, selected on Kata (VM is stronger); otherwise refused** |
| `BUILDER_AGENT` | `vm` (autonomous) | **No — a builders session is unattended model-generated work; Kata profile or refusal** |
| `DEV_ONLY` | `fake` | Only when the process opted into the fake |

`BUILDER_AGENT` (#76) is the policy the builders agent session runs under
(`ContainerBuilderSandbox`): the tier floor is the same `vm` as
`UNTRUSTED_CODE`; its larger memory/time ceilings are session envelopes, not
isolation strength. The adapter owns only the host-side credential boundary
(denylist-filtered seed copy, `.git`-filtered sync-back); the sandbox itself
comes from the selector, so a host without the Kata profile refuses the
session instead of running it in a weaker private container.

On a host with only bubblewrap, every standard policy refuses. This reads as
restrictive because it is: ADR-093's Tier 3 is "a guardrail against accidents
and prompt-injection mistakes, **not** a security boundary against hostile
code", so a Tier-3 host is not permitted to run the workloads whose stated
reason for existing is containment of hostile code.

## Execution-mode floors (ADR-093 decision 6)

Selection always prefers the strongest backend available; the *floor* decides
whether execution is permitted at all.

| Mode | Meaning | Minimum tier |
|---|---|---|
| `interactive` | A human at the keyboard, confirmation gates live | Tier 3 |
| `autonomous` | Unattended — builders pipelines, scheduled DAG nodes, benchmark harnesses | Tier 2 |
| unstated | Read as `autonomous` | Tier 2 |

An unstated mode gets the stricter floor because the errors are asymmetric:
treating an unattended run as supervised is the failure that matters, while
treating a supervised run as unattended only costs a refusal on a weak host.

The floor applies to **untrusted** workloads. ADR-093 decision 3 is as explicit
as decision 1 in the other direction — "trusted first-party services keep
container isolation" — so `TRUSTED_TOOL` and `BROWSER_AUTOMATION` carry
`untrusted=False` and are not floored by mode. Applying it to them would refuse
a first-party API call on every host without gVisor, which is the ADR being
read past its own scope.

### Tier-1 runtime notes (live-profile verified)

The live conformance (`test_kata_live_conformance.py`) ran green against real
Kata VMs on a 3.32.0 static deployment with docker registered via
`runtimeType: io.containerd.kata.v2`. Two host behaviors it exposed are now
part of the backend contract, not the guest's goodwill:

- **No-new-privileges is enforced per exec.** Kata's guest agent applies the
  container's NNP flag to the init process but not to later `docker exec`
  processes, so `KataSandboxBackend.exec` re-asserts the promise itself via
  util-linux `setpriv --no-new-privs`. A guest image without `setpriv` fails
  the exec closed instead of silently weaker — this is why `setpriv` appears
  in the Tier-1 requirements above.
- **virtiofs enforces host mode bits against the guest's id mapping, and the
  guests run with every capability dropped.** A 0700 mkdtemp bind or a 0600
  transferred file is unreadable in-guest even to root there. The bind root
  therefore gets /tmp semantics (sticky, world-writable — it is the
  workload's scratch by definition) and `write_file` widens exactly the
  written chain through the same `O_NOFOLLOW` walk as the write itself
  (`make_beneath_guest_readable`); a symlink swapped in after the transfer
  aborts the widening instead of escaping the sandbox root. Residual edge: a
  directory the *guest* creates inside the bind is not writable by the
  host-side transfer until the caller widens it — guest-created paths are
  guest-owned on the share.

## Egress

Default-deny. A sandbox gets no interface unless its policy carries an
`EgressGrant`, which must name a reason — so a grant cannot be made by accident
and an audit line always has a subject.

| Mode | Meaning | Bubblewrap |
|---|---|---|
| `deny` | No interface. The default. | `--unshare-all`, nothing shared back |
| `scoped` | An allowlist of destinations | **Refused** — cannot filter |
| `host` | The host's namespace, whole | `--share-net` |

`scoped` is refused rather than approximated. Bubblewrap has exactly two
network states, so reading "scoped" as "on" would grant unrestricted egress
while the audit record said scoped. A backend declares
`supports_scoped_egress`, and the refusal happens before a sandbox exists.

Both outcomes are logged — `sandbox_egress_granted` with the reason and
allowlist, `sandbox_egress_denied` otherwise — because a reader needs to tell
"denied" from "never asked".

The grant is decided before the sandbox exists and is frozen onto
`SandboxConfig`, so there is nothing for candidate code to widen. `build_config`
takes it from the policy and never from its overrides, which would otherwise be
a widening path straight through the clamp that exists to prevent widening.

This is the sandbox boundary, and it is a different thing from
`maistro.security.ssrf`, which guards the engine's *own* outbound calls. That
guard is worth nothing against candidate code, which can open a socket without
going through Python at all.

## Product consumers (the cutover invariant, #76)

Every supported code-execution consumer enters through the selector; none
constructs a direct Docker/process/microVM sandbox of its own:

| Consumer | Policy | Backend it gets |
|---|---|---|
| Sandbox MCP tools (`maistro.tools.sandbox.canonical`) | `UNTRUSTED_CODE` | Kata profile, else refusal |
| Evolve benchmark checks (`maistro_evolve.benchmarks.sandbox_exec`) | `UNTRUSTED_CODE` | Kata profile, else refusal |
| RSI microVM adapter (`maistro_rsi.sandbox.microvm`) | `UNTRUSTED_CODE` | Kata profile, else refusal |
| RSI contained validation + builders sessions (`ContainerBuilderSandbox`) | `BUILDER_AGENT` | Kata profile, else refusal |
| opencode foreign harness (`opencode_microvm_factory`) | `UNTRUSTED_CODE` | launcher-vm substrate registered behind the selector (deny-only) |

The generic command facade defaults to `UNTRUSTED_CODE`, not `TRUSTED_TOOL`:
model-generated shell and benchmark code are not trusted first-party API calls.
Settings memory/time requests are clamped through `selector.build_config`.
`network_disabled=True` tightens any policy to DENY; false cannot manufacture
an egress grant. A networked first-party caller must explicitly supply its
policy. Launcher factories register only through canonical wiring; their
memory/time requests are capped by the selected canonical config.

Kata transfers share the canonical descriptor-relative no-follow primitives,
anchored to an instance-owned workspace fd. Execution and teardown serialize
with transfers. Bounded concurrent output capture terminates the host client
and removes the guest on overflow, timeout, or cancellation; killing only the
Docker client is insufficient. Lifecycle CLI capture is bounded as well.

The builders adapter's host-side credential boundary (denylist-filtered seed
copy, `.git`-filtered sync-back) is caller policy on top of the selected
backend, not a second isolation implementation. The retired direct Docker
adapter (`maistro.tools.sandbox.docker`) was removed outright by the #76
cutover after its last product callers converged on the selector: no product
path may import or construct it again
(`packages/maistro-core/tests/sandbox/test_single_authority.py`). The
bootstrap hardening suite asserts the adapter never constructs a container
CLI itself.

## Failure behaviour

- **No backend at all** — `build_selector` returns an empty selector, logs
  `sandbox_no_backends` with a per-tier reason, and every `select()` raises
  `NoSuitableBackendError`. There is no bare-subprocess tier.
- **A tier detected but unconstructible** (the binary left `PATH` between probe
  and build) — the tier is left unregistered and a warning is logged. The build
  is believed over the probe, because an unregistered tier refuses while a
  half-built one would raise on first use.
- **A backend registered at a tier it does not declare** — `TierMismatchError`.
  A backend may be registered at a weaker tier than hoped for; it can never be
  relabelled into a stronger boundary.
- **`bwrap` present but unable to isolate** — not reported as Tier 3.
  Detection runs a functional probe (`--unshare-all` around `true`), not a
  `which` check, because the two genuinely differ: Ubuntu 24.04 ships
  `kernel.apparmor_restrict_unprivileged_userns=1`, and there `bwrap` is
  installed and fails at `loopback: Failed RTM_NEWADDR: Operation not
  permitted`. An operator seeing this note can enable unprivileged user
  namespaces (`sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`) or
  accept that the host has no Tier 3.
- **`/dev/kvm` present but not openable** — not reported as Tier 1. This is the
  common container case, and reporting Tier 1 on the strength of a visible
  device node would fail at spawn, after the policy check meant to prevent it.

## What the bubblewrap backend does

Every sandbox is `--unshare-all --die-with-parent --new-session --cap-drop ALL`,
with a private `/proc`, `/dev` and tmpfs `/tmp`, read-only binds of the host's
runtime directories, and exactly one writable **host** path: the sandbox's own
workdir, bound at `/work`. The sandbox's own `/` and `/tmp` are writable tmpfs
and vanish with it — that distinction is asserted rather than assumed, because
"one writable path" read literally is false and the property that matters is
that nothing a workload writes outlives the sandbox except under `/work`. The
environment is `--clearenv`'d and repopulated only from `SandboxConfig.env`.
Network requires `--share-net`, which is reachable only through a policy whose
`egress` grant names `EgressMode.HOST`. Egress is the sole network authority: a
policy carries no separate `network_allowed` boolean, and `SandboxConfig.network`
is mechanically rejected when true rather than silently ignored.

### Resource budgets (#80)

`SandboxConfig.memory_mb` and `cpu_cores` were declared and applied by nothing
until #80: a caller could ask for 256 MB and watch the workload allocate two
gigabytes. They are now rlimits, set between `fork` and `exec` so they land on
`bwrap` and every process inside inherits them.

| Budget | Limit | Enforced? |
|---|---|---|
| `memory_mb` | `RLIMIT_AS` | **Yes** — measured: a 1 GB allocation raises `MemoryError`. |
| `cpu_cores` | `RLIMIT_CPU`, read as a rate: `ceil(timeout_s × cpu_cores)` CPU-seconds plus a 2-second start-up grace | **Yes** — measured: a busy loop is killed by the kernel, before the wall-clock timeout. |
| `max_file_mb` | `RLIMIT_FSIZE` | **Yes** — measured: `dd` stops at the ceiling. The workdir is a host directory, so without this a workload fills the host's disk while never leaving its sandbox. |
| `max_processes` | `RLIMIT_NPROC` | **Best effort.** The kernel does not enforce `RLIMIT_NPROC` for a parent holding `CAP_SYS_ADMIN` or `CAP_SYS_RESOURCE`, so a Conductor running privileged bounds a fork bomb by the wall-clock timeout and the process-group kill instead. Set regardless — it costs nothing and holds wherever the process is unprivileged — but not claimed as a guarantee. |

`--new-session` is load-bearing beyond its name: without a fresh session the
sandboxed process keeps the caller's controlling terminal and can push
characters into it with `TIOCSTI`.

Host-side file transfer (`write_file` / `read_file`) accepts only `/work` paths
and walks each component from an opened workdir descriptor with `O_NOFOLLOW`.
The final file is opened with `O_NOFOLLOW` too, so a directory or leaf symlink
swap cannot redirect the operation to the host. These calls run on the host —
they are how work gets in and results come out — so descriptor-relative access
is part of the boundary rather than an optimization.

`SandboxConfig.writable_paths` is not a caller-owned bind escape. Bubblewrap
canonicalizes each requested directory and accepts it only below the explicit
host-owned workspace roots (`/tmp/maistro-workspace`, `/repos`, or roots passed
as backend capabilities). The backend's own workdir parent is an additional
capability. A requested symlink itself is refused; symlinked parent components
are allowed only when canonical resolution remains below an authorized root.
Sensitive or broad roots (`/`, `/home`, `/etc`, `/run`, `/dev`, and the generic
`/tmp`) are never writable mount roots. File transfer, execution, and teardown
serialize on a per-instance ownership lock, so teardown cannot remove the
workdir while a host operation or bwrap process is using it.

## Verification

- Flag construction is asserted on **every** host, because the flags are the
  security content of a Tier-3 backend and a test that needs `bwrap` installed
  would leave them unverified on most machines.
- Real isolation — execution, host filesystem invisibility, timeout kill, an
  empty network namespace — is asserted against the kernel wherever `bwrap`
  exists. CI installs `bubblewrap` in `ci.yml`'s `test` job and `quality.yml`'s
  `coverage (no services)` job so these run rather than skip.
- **The conformance and escape suite** is
  `packages/maistro-core/tests/sandbox/test_escape_conformance.py` (#80). It
  covers the classes ADR-093 and SPEC-190 name — filesystem, process,
  namespace, device, host socket, credential, privilege — plus resource
  exhaustion and cleanup, and every expectation in it was measured against a
  live sandbox before it was written down. The bubblewrap lane in CI *is* the
  designated conformance lane for Tier 3. The canonical Kata backend has the
  protocol-level launch and real-host-child safety assertions in
  `packages/maistro-core/tests/sandbox/test_kata_backend.py`. Live selected-VM
  checks are in `test_kata_live_conformance.py` (same directory): all four
  policies launch workloads, with containment, deny egress, file limits,
  transfer, overflow, timeout, and cancellation checks on the untrusted policy.
  They explicitly skip when the host lacks Kata/KVM evidence. These skips
  **do not establish VM acceptance**; a supported deployment must execute
  this lane before issue #76 can be considered complete.

  What it establishes, concretely: the host's `/etc/passwd` and `/home` are not
  there to read; `/usr` is read-only; `/proc/1/root` is the sandbox's root and
  not the host's; fewer than ten PIDs are visible; `unshare -Ur`, `chroot` and
  `mount` are all refused; no block device, no `/dev/kvm`, no `mknod`;
  `/proc/net/unix` and `/proc/net/tcp` are empty and no container socket is
  reachable; the environment holds only what the config put in it; `CapEff` is
  zero and `NoNewPrivs` is 1, so the `sudo` and `su` that *are* visible under
  the read-only `/usr` cannot escalate.

  What it does **not** establish is the thing ADR-093 already says it cannot: a
  user-namespace sandbox exposes the full host syscall surface, so this is a
  guardrail against accidents and prompt-injection mistakes, not a boundary
  against hostile code. Tier 1 remains the answer for that, and the ladder
  refuses rather than substituting this for it.

## Adding a Tier 1 or Tier 2 backend

The protocol is `maistro.sandbox.protocol.SandboxProtocol`; the backend
declares `tier` and the selector refuses a mismatch. Register it in
`maistro.sandbox.wiring.build_selector` behind the capability its tier needs,
and add its probe to `maistro.sandbox.detect`. Nothing else changes: no
business logic names a substrate, which is ADR-093 decision 4.
