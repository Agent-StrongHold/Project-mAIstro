# Deployment Stance

> **Corrected against what ships, 2026-08 (#81).** This document described a
> `maistro-sandbox-worker` service in all four supported profiles, assigned
> sandbox execution to it, and listed Kata, Firecracker, Hyperlight, gVisor and
> rootless containers as available backends. **No such package or compose
> service exists**, and the only backend that ships is bubblewrap. The
> statements below are the ones the code can back; the ones that described a
> plan are marked as plans.

## The guiding rule

> Isolation is in-process, not a separate service. The engine measures what the
> host can do and **refuses** work it cannot isolate, rather than falling back
> to a bare subprocess.
> Hive is optional. UI is optional.
> Running untrusted code with no isolation is never supported in production.
> Partial/control-plane-only installs are source-only paths.

## Supported profiles

The sandbox is a library inside whatever process executes work
(`maistro.sandbox`), so it is not a row in this table. It is present in every
profile by construction.

| Profile | Components | Use case |
|---------|-----------|----------|
| `full-ui` | maistro-server + Hive + persistence | Full deployment with dashboard |
| `full-headless` | maistro-server + persistence | API-only, no UI |
| `proxmox-vm` | maistro-server + persistence | Self-hosted on Proxmox; separate VMs preferred |
| `docker-vps` | maistro-server + persistence | Single VPS with Docker/Podman |

**Planned, not shipped:** a separate sandbox-worker service, which is what a
Tier-1 or Tier-2 backend would need in order to own a VMM or a gVisor runtime.
Until one exists, isolation is bounded by what `maistro.sandbox` can do in the
executing process.

## NOT supported by the installer

| Configuration | Reason | Path |
|---------------|--------|------|
| Serverless | No durable host to isolate on | Source-install only |
| Running untrusted code on a host with no sandbox backend | The engine refuses it; there is no fallback tier | Never |
| Host Docker socket as the execution path | Effectively root on the host | Dev/source only |
| Hive-only real runtime | Hive is not an execution engine | Dev/demo only |
| Control-plane only | Incomplete — no execution capability | Source-only |

## Sandbox ownership

- **Sandbox policy** (what isolation level is required) lives in `maistro.sandbox.policy`
- **Host capability detection** lives in `maistro.sandbox.detect` — a *functional*
  probe, not a `which` check: a host can have `bwrap` on PATH and still be
  unable to build the namespace, and can have `/dev/kvm` visible and unopenable
- **Selection and refusal** live in `maistro.sandbox.selector` and `wiring`
- **Execution** lives in the backend, in-process: `maistro.sandbox.backends.bubblewrap`
- **Sandbox display** is `maistro sandbox status` on the CLI; a Hive surface is planned
- **Docker socket** is dev-only legacy, NEVER production

## Isolation tiers

The ladder is `vm → gvisor → container → bubblewrap`, and a policy that cannot
be satisfied is **refused** rather than served by a weaker rung. See
[`docs/security/SANDBOX-SUPPORT-MATRIX.md`](../security/SANDBOX-SUPPORT-MATRIX.md).

| Tier | Backend | Ships? |
|---|---|---|
| 1 — VM-grade | microVM (Firecracker / Cloud-Hypervisor / QEMU) | **No backend.** Probed only; a host that reaches nothing better refuses `UNTRUSTED_CODE`. |
| 2 — Syscall interception | gVisor (`runsc`) | **No backend.** Probed only; the autonomous floor cannot be met, so unattended work is refused. |
| 3 — User namespace | `maistro.sandbox.backends.bubblewrap` | **Yes.** The only backend that ships. ADR-093 is explicit that this is a guardrail against accidents and prompt-injection mistakes, not a boundary against hostile code. |

Kata Containers, Hyperlight and rootless-container backends have been discussed
and none is implemented. They are not options an operator can select today.

### Forbidden in production

| Configuration | Why |
|---------------|-----|
| Host Docker socket mount | Effectively root on host |
| Bare subprocess | No isolation at all — and there is deliberately no such tier to fall back to |
| `HIVE_MODE=demo` with real users | Demo mode has no security boundary |

## Installer preflight checks

The installer runs before the engine is installed, so it cannot import the
engine's detector and does not pretend to. It reports **hints** and names
`maistro sandbox status` as the thing that settles it:

- [x] `bubblewrap` present — the only binary whose presence maps to a working
      tier. Absent, the report says so and gives the install command, because
      the engine will refuse to run a workload rather than fall back
- [x] `/dev/kvm` node and VMM binaries — reported as **inventory**, explicitly
      not as capability. A visible `/dev/kvm` is not Tier 1: the device has to
      open and a VMM has to exist, which is a check only the engine makes
- [x] No Docker socket mounted into maistro-server container
- [ ] Auth enabled (`MAISTRO_ACCESS_TOKEN` set)
- [ ] Secrets generated (not defaults)
- [ ] Sandbox network denied by default
- [ ] Bind host is `127.0.0.1` unless explicitly overridden
