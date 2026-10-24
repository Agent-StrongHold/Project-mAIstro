---
id: ADR-083
title: "Skills and MCP Gateway Trust"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-069
  - maistro-engine#ADR-072
  - maistro-engine#ADR-073
implements: []
related:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-050
  - maistro-engine#ADR-058
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-083: Skills and MCP Gateway Trust

**Status:** Proposed
**Date:** 2026-05-30
**Defends the ADR-072 anchor** (malicious third-party code) at the two places untrusted code
enters the engine: the **Skills marketplace** and the **MCP gateway**.

---

## Context

ADR-073 specifies Warden + Sentinel as the engine's immune system, and ADR-072 names the threat:
malicious third-party code. But the two concrete ingress points for foreign code — installed
**skills** and **external MCP servers** — have no trust model. Today a skill is run on the
publisher's word, and an MCP server's tool calls cross the trust boundary with no egress control.
This ADR closes both: every skill is signed and tiered, and every MCP server is an explicit,
allow-listed, sandboxed, both-directions-scanned boundary.

## Decision

Two parts, each defending the same anchor.

### Part A — Skills: signed, trust-tiered, sandbox-by-default

Every skill is **signed by a publisher Verifiable Credential** (ADR-024). The signature binds the
skill artifact to a publisher identity; an **unsigned or invalid-signature skill is refused at
install** — there is no "run anyway" path.

Each skill carries a **trust tier** on a one-way ladder:

```
untrusted ──canary metrics + admin sign──▶ canary ──canary metrics + admin sign──▶ trusted
```

- **untrusted / canary** — run inside a **microVM** (ADR-069). Canary metrics (error rate, policy
  violations, resource use, Warden hits) **gate promotion**; promotion is never automatic.
- **promotion** — each step up the ladder requires an **admin signature**. The metrics propose;
  the admin disposes.
- **trusted** — granted **relaxed resource limits** (still Sentinel-policed per ADR-073), having
  earned trust through observed canary behavior.

```python
class SkillTrust(BaseModel):
    publisher_vc: VerifiableCredential        # ADR-024; absent/invalid -> refused
    tier: Literal["untrusted", "canary", "trusted"]
    sandbox: Literal["microvm", "relaxed"]    # microvm for untrusted/canary; relaxed only when trusted
```

### Part B — MCP gateway: untrusted-code boundary

An external MCP server is **untrusted code** by definition. The gateway treats every such server as
a hostile boundary:

- **Admin allow-list** — a server is usable only after an admin explicitly allow-lists it. No
  discovery-and-use.
- **Egress allow-list (SSRF guard)** — its tool calls run under an egress allow-list, the same
  posture as the ADR-058 federation egress controls. A tool cannot reach an arbitrary host.
- **Default `irreversible`** — tools from an untrusted server default to `irreversible` (ADR-050)
  until proven otherwise, so they pull the strictest reversibility gate.
- **Code execution → microVM** — any tool whose path executes code goes through a microVM (ADR-069).
- **Sentinel on every call** — Sentinel applies policy on every tool call (ADR-073); no MCP call
  bypasses the PDP/PEP.
- **Warden scans both directions** — Warden scans **every ingress and every egress** at the MCP
  boundary (ADR-073). An exfiltration leaves as much as an injection enters, so both directions are
  in scope.

```python
class MCPServerPolicy(BaseModel):
    allow_listed_by: AdminPrincipal           # required; no implicit trust
    egress_allow: list[Host]                  # SSRF guard, ADR-058 posture
    default_reversibility: Literal["irreversible"] = "irreversible"  # ADR-050
    code_paths_sandboxed: bool = True         # microVM, ADR-069
    # Sentinel (ADR-073) on every call; Warden scans in AND out
```

## Acceptance criteria

- [ ] An unsigned or invalid-signature skill is refused at install with no override path.
- [ ] Untrusted and canary skills execute inside a microVM (ADR-069); only `trusted` skills get
      relaxed resource limits.
- [ ] Skill promotion (untrusted→canary→trusted) requires both passing canary metrics and an admin
      signature; no automatic promotion.
- [ ] An external MCP server is callable only after explicit admin allow-listing.
- [ ] MCP tool calls run under an egress allow-list (SSRF guard, ADR-058); a call to a non-allowed
      host is blocked.
- [ ] Tools from untrusted MCP servers default to `irreversible` (ADR-050); code-execution paths
      route through a microVM (ADR-069).
- [ ] Sentinel evaluates policy on every MCP tool call (ADR-073).
- [ ] Warden scans both ingress and egress at the MCP boundary; an egress exfiltration attempt is
      scanned, not just ingress injection.

## Consequences

- The two foreign-code ingress points named by ADR-072 now have a single, explicit trust model.
- Skill trust is *earned* through observed canary behavior, not asserted by the publisher; the
  signed VC gives attribution and the tier ladder gives graduated exposure.
- The MCP gateway is a fully-policed boundary (allow-list + egress guard + microVM + Sentinel +
  bidirectional Warden), so an external server is no more trusted than untrusted input.
- Cost: every new skill starts in a microVM with reduced limits, and every MCP server needs an
  admin allow-list action — friction that is intentional at a hostile boundary.

## Out of scope

- The canary metric thresholds and promotion scoring (a tuning detail; follow-up SPEC).
- The microVM image/runtime selection — ADR-069.
- The signing-key distribution / publisher-VC issuance flow — ADR-024.
- Multi-tenant partitioning of allow-lists and trust tiers — Stronghold (ADR-019).
