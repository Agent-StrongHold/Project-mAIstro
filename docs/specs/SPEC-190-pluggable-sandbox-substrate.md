---
id: SPEC-190
title: "Pluggable sandbox substrate — SandboxProtocol with container and microVM (Kata/Firecracker) backends"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-31
substrate:
  - maistro-engine#ADR-093
implements:
  - maistro-engine#ADR-093
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-012
  - maistro-engine#SPEC-011
  - maistro-engine#SPEC-013
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Tools
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-31
---

# SPEC-190: Pluggable Sandbox Substrate

## Context

Per ADR-093, untrusted agent/tool code must run behind a hardware-VM boundary, and the substrate must
sit behind a protocol rather than being hardwired to Docker. Today `maistro.tools.sandbox.docker`
exposes a single concrete `SandboxContainer` that shells out to the `docker` CLI and assumes a
reachable Docker socket — there is no interface, so the runtime cannot be swapped.

This spec defines the `SandboxProtocol`, refactors the existing Docker code into one backend behind
it, and adds hardware-VM backends (Kata, then Firecracker). The host already exposes `/dev/kvm` with
virtualization-capable CPUs, so the substrate is available; the work is abstraction + backends +
migration.

## Goals

- A `SandboxProtocol` that all sandbox callers depend on (no direct Docker references in business code).
- Today's Docker behaviour preserved as one backend (no behavioural regression during migration).
- A microVM backend (Kata first — drop-in OCI; Firecracker second — max isolation) satisfying ADR-093.
- A conformance suite (including escape/containment assertions) every backend must pass.
- Backend selection via configuration, defaulting safe (fail-closed when KVM is required but absent;
  autonomous/"overnight" execution refuses on hosts whose best backend is shared-kernel — ADR-093
  Decision 6).

## Non-goals

- Image supply-chain hardening (distroless/Chainguard) — separate track.
- A general container orchestrator; this is a single-tenant, ephemeral execution sandbox.
- Hyperlight/wasm execution — noted as a future backend, not in this spec's scope.

## Decision

### SandboxProtocol (sketch)

```python
class SandboxHandle(Protocol):
    id: str
    async def exec(self, argv: list[str], *, timeout_s: float, stdin: bytes | None = None) -> ExecResult: ...
    async def write_file(self, path: str, data: bytes) -> None: ...
    async def read_file(self, path: str) -> bytes: ...
    async def stop(self) -> None: ...

class SandboxProtocol(Protocol):
    async def spawn(self, spec: SandboxSpec) -> SandboxHandle: ...
    def capabilities(self) -> SandboxCapabilities: ...   # isolation level, kvm_required, max_mem, net policy

@dataclass(frozen=True)
class SandboxSpec:
    image_ref: str                 # OCI ref or rootfs id
    workspace: WorkspaceMount      # read-write scratch; host paths never bind-mounted raw
    network: NetPolicy             # default DENY; explicit egress allowlist
    limits: ResourceLimits         # cpu, mem, pids, wall-clock
    env: Mapping[str, str]         # already passed through env_sanitize
```

`SandboxCapabilities.isolation` is an enum, ordered weakest → strongest:
`SHARED_KERNEL` (container/bubblewrap) < `USERSPACE_KERNEL` (gVisor) < `VM` (Kata/Firecracker).
ADR-093 requires `VM` for untrusted code; callers handling untrusted input assert the minimum.

### Backends

| Backend | isolation | runs OCI image? | kvm_required | phase |
|---------|-----------|-----------------|--------------|-------|
| `container` (rootless, **no docker socket**) | SHARED_KERNEL | yes | no | 1 (refactor of today) |
| `gvisor` (`runsc` runtime under docker/podman) | USERSPACE_KERNEL | yes, unchanged | no | 1 (fallback tier) |
| `kata` (kata-runtime under containerd) | VM | yes, unchanged | yes | 2 |
| `firecracker` (kernel + ext4 rootfs, jailer) | VM | no (rootfs build) | yes | 3 |
| `hyperlight` (wasm/guest binary) | VM, no guest kernel | no | yes | future |

### Execution modes and isolation floors (ADR-093 Decision 5-6)

Backend selection always prefers the strongest isolation available on the host
(`VM > USERSPACE_KERNEL > SHARED_KERNEL`; gVisor outranks bubblewrap/hardened containers). The
caller's *execution mode* then sets a floor that decides whether execution is permitted at all:

| Mode | Minimum isolation | Behaviour below the floor |
|------|-------------------|---------------------------|
| `interactive` (human-supervised CLI/TUI; SPEC-200 gates live) | SHARED_KERNEL | fail closed only when *no* backend exists |
| `autonomous` (unattended / "overnight" / full-auto: builders pipeline, scheduled DAGs, evolve harnesses) | USERSPACE_KERNEL | **refuse to start** — full-auto is blocked on a shared-kernel-only host |

Unknown or unspecified modes get the `autonomous` (stricter) floor. There is no bare-subprocess
tier in any mode. `SandboxProtocol.spawn` callers pass the mode (or assert
`capabilities().isolation >= floor`) so the policy is enforced in the substrate, not re-implemented
per caller. Reference implementation:
`packages/hive-conductor/backend/services/hyperlight_executor.py`.

### Wiring

Registered in the DI container like every other subsystem; selected by config
(`sandbox.backend`). Fail-closed: if the configured backend needs KVM and `/dev/kvm` is absent, the
container refuses to start rather than silently falling back to a weaker boundary (configurable
override for dev). Secrets reach the sandbox only via the SPEC-011 vault broker, never the raw
environment; privilege boundaries follow SPEC-012.

## Acceptance criteria

- [ ] `SandboxProtocol` + `SandboxSpec`/`SandboxHandle` defined in `protocols/`; `tools/sandbox/docker.py`
      reworked into a `ContainerSandbox` backend implementing it, **with the host Docker socket removed**.
- [ ] A `FakeSandbox` backend exists for unit tests; all existing sandbox callers depend only on the protocol.
- [ ] Conformance suite passes for `container` and at least one `VM` backend, including:
      network-deny-by-default, no host-path escape, resource-limit enforcement, and a negative
      "attempt to reach host / docker socket fails" test.
- [ ] Backend selectable by config; KVM-required backend fails closed when `/dev/kvm` is missing.
- [ ] No regression: existing sandbox-dependent tool tests pass on the `container` backend.

## Testing

- Protocol-level conformance tests parametrized across backends (skip VM backends when `/dev/kvm`
  absent, and **log the skip** — never silently treat unskipped as covered).
- Escape/containment tests are the security core: assert the sandbox cannot read a host marker file,
  cannot reach the Docker socket, and cannot egress outside the allowlist.
- Property-based fuzzing of `SandboxSpec` (resource limits, env, paths) under `formal/` for the
  boundary invariants.

## Open questions

1. Kata vs Firecracker as the *default* VM backend — Kata is lower-effort (drop-in OCI); Firecracker is
   leaner/denser but needs rootfs+kernel management. Start Kata, revisit?
2. Networking model for VM backends (TAP + bridge per VM) and its interaction with the egress allowlist.
3. Snapshot/restore for sub-100ms spawn — needed for the SPEC-013 reactor cadence, or acceptable to
   pool warm sandboxes?
4. Does the sandbox register as a SPEC-184 capability provider so "isolation level" is a declared slot?

## References

- ADR-093 — sandbox isolation model (the decision this implements).
- `packages/maistro-core/src/maistro/tools/sandbox/` — current implementation (`docker.py`,
  `env_sanitize.py`, `workspace.py`, `server.py`).
- SPEC-011 (vault), SPEC-012 (privilege separation), SPEC-013 (reactor), SPEC-184 (capability platform).
- Firecracker, Kata Containers, Cloud Hypervisor, Microsoft Hyperlight (substrate candidates).
