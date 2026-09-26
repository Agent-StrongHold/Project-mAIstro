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
| 1 | Hardware VM | *none yet* | `/dev/kvm` readable/writable **and** one of `firecracker`, `cloud-hypervisor`, `qemu-system-x86_64` on `PATH` | Detected, not implemented — see below |
| 2 | User-space kernel | *none yet* | `runsc` on `PATH` | Detected, not implemented |
| 3 | OS sandbox / hardened container | `ContainerSandboxBackend` | Docker or Podman CLI on `PATH` **and** a *reachable* runtime — the probe runs `docker info`/`podman info`, not a `which` check | **Shipped** (transitional rung, ADR-093 decision 2) |
| 3 | OS sandbox / hardened container | `BubblewrapSandboxBackend` | `bwrap` on `PATH` **and able to build a namespace** — see below | **Shipped** |
| — | Fake | `FakeSandboxBackend` | none | Dev/test only, never registered automatically |

Both Tier-3 rows are one ADR tier with two shipped rungs. In the selector's
ladder (`policy._TIER_ORDER`: `vm` > `gvisor` > `container` > `bubblewrap` >
`fake`) the hardened container outranks bubblewrap, so a Docker/Podman host
runs its tool-sandbox code execution on `ContainerSandboxBackend`. It is
retained *transitionally* by ADR-093 decision 2: the runtime is driven by CLI
argv from the host process, no sandbox ever receives the host Docker socket,
and it is not a stronger trust boundary than the ADR grants Tier 3.

Tiers 1 and 2 are *probed* but have no backend. That is deliberate and is the
honest state: `detect_host_capabilities()` will report `vm` or `gvisor` where
the host has them, and `build_selector` will simply not register a tier it
cannot construct. The result is a refusal, not a silent downgrade.

## What each workload requires

From `maistro.sandbox.policy`:

| Policy | Minimum tier | Bubblewrap-only host | Host with a reachable Docker/Podman runtime |
|---|---|---|---|
| `UNTRUSTED_CODE` | `vm` | **Refused** | **Refused** |
| `BENCHMARK_EVAL` | `vm` | **Refused** | **Refused** |
| `TRUSTED_TOOL` | `container` | Refused | **Runs** — on `ContainerSandboxBackend` (`test_selector.py::test_container_satisfies_trusted_tool` pins the selection) |
| `BROWSER_AUTOMATION` | `container` | Refused | **Runs** — on `ContainerSandboxBackend` |
| `DEV_ONLY` | `fake` | Runs on any registered tier | Runs on any registered tier |

The `fake` backend itself is dev/test-only, opt-in, and never registered
automatically; a `DEV_ONLY` workload simply accepts whatever the host's ladder
registered, strongest first. A host with no backend at all refuses it too.

On a host with only bubblewrap, every policy above `bubblewrap` refuses. Where
a container runtime is reachable, the shipped container rung satisfies the two
`container`-tier policies while the `vm`-tier policies still refuse. This
reads as restrictive because it is: ADR-093's Tier 3 is "a guardrail against
accidents and prompt-injection mistakes, **not** a security boundary against
hostile code", so a Tier-3 host is not permitted to run the workloads whose
stated reason for existing is containment of hostile code — hardened container
defaults narrow the accident surface; they do not move the trust boundary.

**The sandbox MCP tool is an `UNTRUSTED_CODE` consumer.**
`maistro.tools.sandbox.server` runs model-chosen shell, which ADR-093's
context classifies as untrusted model-generated code — not a first-party API
call — so `create_sandbox` there selects `UNTRUSTED_CODE` and refuses with
`NoSuitableBackendError` on every host shipped today. That is deliberate: an
earlier wiring handed this path the `TRUSTED_TOOL` profile and served
model-chosen commands from a container with the host network namespace (#77
violated, measured live). It refuses until a Tier-1/2 backend ships behind
the protocol — the same honest disposition as the legacy evolve/RSI seams.

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

## Egress

Default-deny. A sandbox gets no interface unless its policy carries an
`EgressGrant`, which must name a reason — so a grant cannot be made by accident
and an audit line always has a subject.

| Mode | Meaning | Bubblewrap | Container |
|---|---|---|---|
| `deny` | No interface. The default. | `--unshare-all`, nothing shared back | `--network=none` |
| `scoped` | An allowlist of destinations | **Refused** — cannot filter | **Refused** — cannot filter (`supports_scoped_egress = False`) |
| `host` | The host's namespace, whole | `--share-net` | `--network=host` |

`scoped` is refused rather than approximated. Neither shipped backend can
filter: bubblewrap has exactly two network states, and the container backend
likewise only selects between no interface and the host's whole namespace, so
reading "scoped" as "on" would grant unrestricted egress while the audit
record said scoped. A backend declares `supports_scoped_egress`, and the
refusal happens before a sandbox exists.

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
`network_allowed` is true.

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

Host-side file transfer (`write_file` / `read_file`) is confined at `open`
time, not before it (#1198): both backends walk directory file descriptors
with `O_NOFOLLOW` (`read_beneath`/`write_beneath`), so a symlink swapped into
a path after a check is refused by the kernel (ELOOP) rather than followed.
Resolution alone is not enough — the check-to-open window was a real escape,
closed and race-tested in `test_host_transfer_race.py`.

## What the container backend does

`ContainerSandboxBackend` (`maistro.sandbox.backends.container`) runs one
ephemeral, socket-less container per sandbox — the transitional Tier-3 rung of
ADR-093 decision 2, wired into the same selector, policy ladder, egress-grant
and fence machinery as every other backend, with no second policy surface:

- **Socket-less.** The host process drives the runtime by CLI argv. No
  container receives the host Docker socket, ambient environment, or an
  unvalidated host mount — the exact misconfiguration class ADR-093 names as
  the reason the shared-kernel model was demoted.
- **Hardened by default.** Read-only root (`--read-only`), `--cap-drop=ALL`,
  `no-new-privileges`, a fixed non-root uid (65532), and a `noexec,nosuid`
  tmpfs `/tmp`.
- **Budgets enforced by the runtime** (`--memory`, `--cpus`, `--pids-limit`),
  plus the shared host-side capture ceiling of #1197 on stdout/stderr.
- **One writable host path:** a single authorized workspace root bound at
  `/work`; more than one `writable_paths` entry is refused, and host-side
  `write_file`/`read_file` resolve beneath that authorized root via
  `write_beneath`/`read_beneath` (#1198).
- **Environment** comes only from `sanitize_env(config.env)` plus the canonical
  fence variables (#79) — never the caller's ambient environment.
- **Network** follows the same egress-grant table above: deny (default) is
  `--network=none`, `host` is `--network=host`, `scoped` is refused.

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
  live sandbox before it was written down. Each shipped rung has its own
  conformance lane: `test_escape_conformance.py` is the bubblewrap lane, and
  `packages/maistro-core/tests/sandbox/backends/test_container.py` is the
  container lane — argv-pure assertions on any host, live-daemon assertions
  (default-deny network, env allowlist, output bounds, fence propagation,
  cleanup) wherever a runtime is reachable, skipped with the probe's reason
  where it is not. Tiers 1 and 2 have no backend to conform, so there is
  nothing a hardware-capable runner would additionally exercise until one
  ships.

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
