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
| 3 | OS sandbox | `BubblewrapSandboxBackend` | `bwrap` on `PATH`; unprivileged user namespaces enabled | **Shipped** |
| — | Fake | `FakeSandboxBackend` | none | Dev/test only, never registered automatically |

Tiers 1 and 2 are *probed* but have no backend. That is deliberate and is the
honest state: `detect_host_capabilities()` will report `vm` or `gvisor` where
the host has them, and `build_selector` will simply not register a tier it
cannot construct. The result is a refusal, not a silent downgrade.

## What each workload requires

From `maistro.sandbox.policy`:

| Policy | Minimum tier | Runs on a Tier-3-only host? |
|---|---|---|
| `UNTRUSTED_CODE` | `vm` | **No** — refused |
| `BENCHMARK_EVAL` | `vm` | **No** — refused |
| `TRUSTED_TOOL` | `container` | No — refused (no container backend is shipped) |
| `BROWSER_AUTOMATION` | `container` | No — refused |
| `DEV_ONLY` | `fake` | Only when the process opted into the fake |

On a host with only bubblewrap, every policy above `bubblewrap` refuses. This
reads as restrictive because it is: ADR-093's Tier 3 is "a guardrail against
accidents and prompt-injection mistakes, **not** a security boundary against
hostile code", so a Tier-3 host is not permitted to run the workloads whose
stated reason for existing is containment of hostile code.

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
- **`/dev/kvm` present but not openable** — not reported as Tier 1. This is the
  common container case, and reporting Tier 1 on the strength of a visible
  device node would fail at spawn, after the policy check meant to prevent it.

## What the bubblewrap backend does

Every sandbox is `--unshare-all --die-with-parent --new-session --cap-drop ALL`,
with a private `/proc`, `/dev` and tmpfs `/tmp`, read-only binds of the host's
runtime directories, and exactly one writable path: the sandbox's own workdir,
bound at `/work`. The environment is `--clearenv`'d and repopulated only from
`SandboxConfig.env`. Network requires `--share-net`, which is reachable only
through a policy whose `network_allowed` is true.

`--new-session` is load-bearing beyond its name: without a fresh session the
sandboxed process keeps the caller's controlling terminal and can push
characters into it with `TIOCSTI`.

Host-side file transfer (`write_file` / `read_file`) resolves every path inside
the workdir and refuses anything that escapes it. Those calls run on the host —
they are how work gets in and results come out — so an unchecked path would be
a host write with no sandbox involved.

## Verification

- Flag construction is asserted on **every** host, because the flags are the
  security content of a Tier-3 backend and a test that needs `bwrap` installed
  would leave them unverified on most machines.
- Real isolation — execution, host filesystem invisibility, timeout kill, an
  empty network namespace — is asserted against the kernel wherever `bwrap`
  exists. CI installs `bubblewrap` in `ci.yml`'s `test` job and `quality.yml`'s
  `coverage (no services)` job so these run rather than skip.

## Adding a Tier 1 or Tier 2 backend

The protocol is `maistro.sandbox.protocol.SandboxProtocol`; the backend
declares `tier` and the selector refuses a mismatch. Register it in
`maistro.sandbox.wiring.build_selector` behind the capability its tier needs,
and add its probe to `maistro.sandbox.detect`. Nothing else changes: no
business logic names a substrate, which is ADR-093 decision 4.
