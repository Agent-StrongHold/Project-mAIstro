---
id: ADR-072
title: "Threat Model — assets, adversaries, trust boundaries (anchor: malicious third-party code)"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate: []
implements: []
related:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-050
  - maistro-engine#ADR-063
  - maistro-engine#ADR-068
  - maistro-engine#ADR-069
  - maistro-engine#ADR-073
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-072: Threat Model

**Status:** Proposed
**Date:** 2026-05-30

---

## Context

Security is defended piecemeal across the corpus (ADR-023 Bouncer, ADR-028 privilege, ADR-050
reversibility, ADR-064 redaction, ADR-068 authz, ADR-069 microVM) with **no document that states
what we are defending, against whom, and where the trust boundaries are.** Without it, coverage is
reactionary and we can't tell whether a new feature widens the attack surface. This ADR is the
checkable spine the other security ADRs hang off.

**Primary adversary (the anchor): malicious third-party code.** A bad skill, a compromised MCP
server, or a poisoned dependency is the threat we design *first* against — it is the most likely and
most damaging vector for a homelab Conductor that installs community skills and connects external
tools. Defense is structural (ADR-028's thesis): signing, microVM isolation, trust tiers, SBOM —
not "ask the model to behave."

## Decision

### Assets (what's worth protecting)

| Asset | Why | Guarded by |
|-------|-----|-----------|
| Conductor Seed / derived keys | Root of all signing + wallets | ADR-021/022/026 (HD, hardware, immutable CA) |
| Provider credentials | Money + data access | ADR-063 pool, ADR-064 redaction, vault |
| Audit log / VCs | Integrity of the record | ADR-024 signed VCs; tamper-evidence (open, ADR-068) |
| Sessions / user identity | Account takeover | ADR-068 authz; web-session ADR (banked) |
| Memory (learnings/episodic) | Exfiltration / poisoning | ADR-013 scopes; PII tiers (ADR-055) |
| Repertoire / code-registry entries | Executable; a poisoned entry = RCE | ADR-069 signing + microVM; ADR-070 verify-gate |
| The policy store (Sentinel) | Subverting it disables defenses | ADR-073 RBAC; ADR-074 deconfliction |

### Adversaries (ranked)

1. **Malicious third-party code (PRIMARY)** — skill / MCP server / dependency that exfiltrates,
   escalates, or poisons. Cisco's finding: a third-party skill ran with full privilege and
   exfiltrated. Defense: ADR-069 microVM (fail-closed), signing + trust tiers, SBOM, egress control.
2. **Prompt injection** — untrusted content/LLM output coerces the agent into unintended tool calls
   or exfiltration. Defense: Warden boundary scans (ADR-073), reversibility gates (ADR-050), the
   ADR-068 authority envelope (an injected request still can't exceed the principal's authority).
3. **Local device / LAN compromise** — stolen device, hostile LAN peer, seed theft. Defense:
   hardware signing (ADR-022), CA name-constraints (ADR-026), networking substrate (ADR-029),
   memory-zeroization (ADR-021).
4. **Compromised federation peer** — a delegated-to peer turns hostile. Defense: DID-pinning +
   egress allow-list + per-peer circuit breaker (ADR-058), advisory peer-usage accounting.
5. **Over-privileged / drifting agent** — an agent (or a *learned policy*) gradually acquiring
   authority it shouldn't. Defense: agent-holds-subset-of-owner-authority (ADR-068), and the
   **deconfliction immune system** (ADR-074): a learned policy drifting against a safety ADR is
   treated as a poisoning signal.

### Trust boundaries (where Warden/Sentinel sit)

```
untrusted input ─►[Warden scan]─► classify ─►[Sentinel authorize]─► tool call
external MCP/skill ─►[Warden in+out]─►[microVM, ADR-069]─► effect
federation peer ─►[egress allow-list + DID pin, ADR-058]─► remote
human ⇄ agent ─►[ADR-068 elevation / 2FA]─► privileged op
```

Every boundary crossing is scanned (Warden, both directions for MCP) and every tool call is
adjudicated (Sentinel) — ADR-073 specifies both.

### Defense posture (invariants)

- **Structural, not behavioral** (ADR-028) — defenses are enforced by substrate, never by asking the
  model to self-limit.
- **Fail-closed** — absent isolation/verification, refuse (ADR-069 microVM; the Repertoire Rehearse
  gate; the deconfliction hold).
- **Untrusted-by-default** — external code/tools default to `irreversible` (ADR-050) and run in a
  microVM; explicit downgrade requires a signed Sentinel policy.
- **The ADRs are the immune system** — a learned policy that drifts against a safety-critical ADR is
  a detected attack (ADR-074), not a silent update.

## Threat → defense map (acceptance)

- [ ] Every adversary above maps to at least one enforced control (table maintained as ADRs land).
- [ ] A poisoned Repertoire/registry entry cannot execute outside a microVM (ADR-069) and cannot be
      recalled unsigned (ADR-070).
- [ ] A prompt-injected request cannot exceed the principal's authority (ADR-068) — property test.
- [ ] A learned-policy drift against a safety-critical ADR raises a security review, not an
      auto-update (ADR-074).
- [ ] Warden scans every ingress **and** egress at the MCP boundary (ADR-073).

## Accepted risks / out of scope

- Physical coercion of the admin (rubber-hose); nation-state targeted attacks.
- Compromise of the base OS / hypervisor beneath the microVM.
- Side-channels (timing/cache) — tracked separately if/when crypto goes in-process.
- Multi-tenant isolation threats — Stronghold's threat model (this is the homelab Conductor's).

## Consequences

- ADR-073 (Warden/Sentinel) implements the boundary scanning + adjudication this model assumes.
- ADR-074 (deconfliction) is the immune response for adversary #5 (drift/poisoning).
- New ADRs state which asset/adversary/boundary they touch (a one-line "threat impact" note).
