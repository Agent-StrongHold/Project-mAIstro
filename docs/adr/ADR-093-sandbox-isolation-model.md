---
id: ADR-093
title: Sandbox isolation model — hardware-VM isolation for untrusted agent code
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-31
substrate:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-012
  - maistro-engine#SPEC-190
  - maistro-engine#SPEC-200
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-31
  - status: Accepted
    date: 2026-05-31
---

# ADR-093: Sandbox isolation model — hardware-VM isolation for untrusted agent code

## Context

The engine executes **untrusted, model-generated code** in several places: the tool sandbox
(`maistro.tools.sandbox`), tool execution in `chat_completion._execute_tool`, benchmark harnesses
that `exec()` generated code, and browser automation (browser-use / Playwright). Today this runs in
Docker containers, and the production image mounts the host Docker socket so the sandbox can spawn
sibling containers.

A shared-kernel container is a **namespace + seccomp + cgroup** boundary, not a security boundary
against hostile code: a single Linux kernel/syscall exploit crosses it. Worse, **a mounted Docker
socket is effectively root on the host** — code that reaches it can start a privileged container and
own the machine. We are, in effect, running adversarial input behind a boundary designed for
*resource isolation between cooperating processes*, not *containment of an attacker*.

## Problem

What isolation guarantee do we require for code we did not write and cannot trust, and is the current
container-with-socket model acceptable?

## Decision

1. **Untrusted agent/tool code MUST run behind a hardware-virtualization boundary (a microVM), not a
   shared-kernel container.** The trust boundary becomes the CPU's VM-exit / hypervisor, so a guest
   kernel or syscall exploit does not reach the host.
2. **The Docker-socket-mounting sandbox is deprecated for untrusted workloads.** Sharing the host
   Docker socket into a sandbox is prohibited; if a container runtime is retained transitionally it
   MUST be a rootless, socket-less, single-tenant configuration.
3. **Trusted first-party services keep container isolation.** The API server, hive-conductor backend,
   and other first-party services are not adversarial and continue to run as (distroless, non-root)
   containers. MicroVM isolation is reserved for the *sandbox* — where density is traded for
   containment deliberately.
4. **The substrate is an implementation detail behind a protocol.** No business logic depends on
   "Docker" or "Firecracker"; it depends on a `SandboxProtocol` (per the project's protocol-driven DI
   rule). The concrete backend (rootless container, Kata, Firecracker, Cloud Hypervisor, Hyperlight)
   is selected by configuration. The protocol and migration are specified in SPEC-190.
5. **Fallback ladder (resolves former open question 2).** The substrate always selects the
   *strongest* tier available on the host, in this order:
   - **Tier 1 — hardware VM:** Hyperlight, Firecracker, Kata / Cloud Hypervisor. The required
     guarantee of this ADR.
   - **Tier 2 — user-space kernel:** gVisor (`runsc`). Guest syscalls terminate in the Sentry, not
     the host kernel; the host syscall surface shrinks to the small Sentry→host set and io_uring is
     never exposed. The strongest option on hosts without KVM, and the minimum acceptable boundary
     for *unattended* execution.
   - **Tier 3 — OS sandbox / hardened container:** bubblewrap, or a rootless socket-less container
     with `cap-drop=ALL`, seccomp, `no-new-privileges`, read-only rootfs. A guardrail against
     accidents and prompt-injection mistakes, **not** a security boundary against hostile code.
   - **Fail closed:** if none of the above is present, refuse to execute. There is no
     bare-subprocess tier.
   gVisor ranks **above** bubblewrap and hardened containers: a user-namespace sandbox still exposes
   the full host syscall surface (~350+ syscalls), while gVisor's user-space kernel removes the host
   kernel from the direct attack path.
6. **Execution-mode isolation floors.** Selection always prefers the strongest backend regardless of
   mode; the *floor* decides whether execution is permitted at all.

   | Mode | Meaning | Minimum tier |
   |------|---------|--------------|
   | `interactive` | Human at the keyboard (builders CLI/TUI session); SPEC-200 confirmation gates are live and the human supervises each destructive action | Tier 3 |
   | `autonomous` | Unattended / "overnight" / full-auto: builders pipeline runs, scheduled DAG nodes, evolve benchmark harnesses — anything with nobody watching | Tier 2 |

   If the host's best available backend is Tier 3, interactive use proceeds (with a logged warning),
   but **full-auto is blocked** — the run refuses to start rather than executing unsupervised
   adversarial code behind a shared kernel. Rationale: interactive use has a short exposure window
   and a human approving gated actions; an autonomous overnight run is precisely the unsupervised,
   long-window, nobody-at-the-keyboard scenario that the multi-tenant vendors (below) put behind VM
   or user-space-kernel boundaries. Unknown/unspecified modes get the autonomous (stricter) floor.

This is a **posture decision**, not a substrate mandate: it fixes the *required guarantee*
(hardware-VM containment for untrusted code) and forbids the *known-weak* configuration (shared Docker
socket). Which microVM technology satisfies the guarantee is SPEC-190's design space.

## Consequences

### Positive
- Adversarial code that escapes the guest hits a hypervisor boundary, not the host kernel.
- Removing the host Docker socket eliminates the single worst privilege-escalation path in the system.
- The protocol indirection makes the substrate swappable and testable (a fake backend for unit tests).

### Negative / Trade-offs
- MicroVMs cost more memory (per-VM guest kernel for Kata/Firecracker) and add operational surface
  (KVM dependency, TAP networking, kernel/rootfs management). Density drops for the sandbox tier.
- Requires `/dev/kvm`; nested virtualization must be available wherever the engine runs (bare metal or
  a nested-virt-enabled VM — not a plain LXC container).
- A migration period where both backends coexist behind the protocol.

### Neutral
- First-party service deployment is unchanged (still containers).

## Industry survey — why others accept shared-kernel isolation (surveyed 2026-06)

The market splits by **threat model**, not by conviction; nobody serious argues a plain container
contains a determined attacker.

| Who | Isolation | Why it is "enough" for them |
|-----|-----------|------------------------------|
| E2B, Fly.io Machines, AWS Lambda | Firecracker microVM | Hostile multi-tenant code — same conclusion as this ADR |
| Modal, Google (GKE Sandbox) | gVisor user-space kernel | Hostile multi-tenant; accepts 2-9× syscall overhead to cut the host kernel out of the direct attack path |
| Daytona | Configurable: Docker+seccomp ↔ Kata/Cloud Hypervisor | Customer picks the tier per workload |
| Claude Code, Codex CLI, Gemini CLI | OS sandbox (Seatbelt / bubblewrap / Landlock+seccomp), containers opt-in | Single user, own machine, human watching: guards against accidents and prompt-injection mistakes, not deliberate kernel exploitation; no cross-tenant blast radius |

The four arguments offered for "containers are enough", and our assessment:

1. **Threat-model scoping** (local agents): the code already runs as the developer's own user; the
   sandbox prevents accidents, and a human supervises the session. *Valid for interactive use — it is
   why the `interactive` floor is Tier 3. It does not transfer to unattended builders runs, where
   nobody is watching and ADR-072's #1 adversary (malicious third-party code) is in scope.*
2. **Defense-in-depth raises attacker cost**: rootless + cap-drop + seccomp + no socket eliminates
   the misconfiguration class behind nearly all real-world escapes. *True, and required of our Tier 3
   anyway — but it leaves the kernel-0-day class open.*
3. **The adversary mostly doesn't need to escape**: supply-chain malware overwhelmingly exfiltrates
   what is reachable *inside* the sandbox (env, tokens, workspace, network) rather than attacking the
   kernel. *True and important — isolation tier and egress/secrets hygiene are orthogonal axes. A
   microVM with permissive egress is weaker in practice than a container with deny-by-default egress
   and no secrets. This is why SPEC-190's egress-allowlist work is as load-bearing as the boundary.*
4. **Patch cadence as compensating control**: accept the 0-day window, patch runc/kernel fast.
   *Works for the known-CVE class only; a homelab box has no tenancy layer above it to absorb a miss.*

Residual-risk record for the shared-kernel class: container-runtime escapes recur roughly yearly
(runc CVE-2019-5736; CVE-2024-21626 plus the BuildKit "Leaky Vessels" trio, 2024; runc
CVE-2025-31133 / CVE-2025-52565 / CVE-2025-52881, 2025), and kernel LPEs reachable from default
seccomp profiles keep appearing (Dirty Pipe; the io_uring family — bad enough that Google disabled
io_uring fleet-wide; nf_tables). One Linux LPE reachable through the profile is full host
compromise: on the builders host that means the age vault, SSH keys, and a LAN pivot.

Conclusion: the vendors whose threat model matches ours (hostile code, unattended) chose VM or
user-space-kernel isolation; the ones shipping weaker isolation rely on a supervising human. Decision
items 5-6 encode exactly that split.

## Acceptance criteria

- A `SandboxProtocol` exists and the Docker backend is one implementation behind it (SPEC-190).
- No code path mounts the host Docker socket into a sandbox running untrusted code.
- At least one hardware-VM backend (Kata or Firecracker) passes the sandbox conformance/escape tests
  defined in SPEC-190.
- Backend selection follows the Decision 5 ladder (gVisor above bubblewrap/hardened container) and
  enforces the Decision 6 mode floors: autonomous execution refuses on a Tier 3-only host.

## Open questions

1. Default backend for self-hosted (Agent Conductor) vs enterprise (Stronghold) deployments?
2. Does the sandbox become a capability provider under SPEC-184 (so isolation level is a declared
   capability slot)?

(The former question — rootless-container as fallback vs hard-fail — is resolved by Decision items
5 and 6: gVisor-or-better for unattended runs; Tier 3 acceptable for interactive use only; fail
closed below that.)

## Source references

- `packages/maistro-core/src/maistro/tools/sandbox/docker.py` — current Docker sandbox.
- `packages/hive-conductor/backend/services/hyperlight_executor.py` — fallback ladder + mode-floor
  enforcement (reference implementation of Decision items 5-6).
- ADR-019 (canonical source split), ADR-038 (reliability taxonomy), ADR-072 (threat model).
- SPEC-190 — pluggable sandbox substrate (the design implementing this decision).
- SPEC-200 — builders safety layer (the interactive confirmation gates the `interactive` floor
  relies on).
- Industry survey sources: Snyk Labs (Leaky Vessels), Sysdig & CNCF (2025 runc escape CVEs),
  Northflank sandboxing surveys (E2B/Modal/Daytona architectures), Claude Code sandboxing docs
  (Seatbelt/bubblewrap), openai/codex sandboxing implementation (Landlock+seccomp), Modal gVisor
  documentation.

## Out of scope

- The concrete protocol shape, backend selection, and phased migration — see SPEC-190.
- Supply-chain hardening of the *images* (distroless/Chainguard) — separate track.
