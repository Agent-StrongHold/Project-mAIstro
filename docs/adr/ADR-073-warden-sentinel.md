---
id: ADR-073
title: "Warden + Sentinel — threat detection and the policy decision/enforcement substrate"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-072
implements: []
related:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-069
  - maistro-engine#ADR-070
  - maistro-engine#ADR-074
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
  - status: Accepted
    date: 2026-05-30
---

# ADR-073: Warden + Sentinel

**Status:** Proposed
**Date:** 2026-05-30
**Implements the enforcement substrate** that ADR-068 (authz), ADR-050 (reversibility), and ADR-051
(approval gates) all delegate to but never specified — they exist only in code today.

---

## Context

ADR-068 says "Sentinel is the PDP/PEP; Warden scans untrusted input and feeds risk into CLASSIFY,"
and ADR-050/051 say "Sentinel enforces tool-call policy" — but neither Warden nor Sentinel has an
ADR. The detection taxonomy, the policy model, the decision/enforcement architecture, and the audit
format are undocumented. This ADR specifies them. It is the engine's *immune system* against the
ADR-072 threats (anchor: malicious third-party code).

## Decision

Two cooperating components in `maistro.security`:

### Warden — trust-boundary scanner (detection)

Warden scans untrusted data at **every trust boundary** (ADR-072), and — at the MCP boundary — in
**both directions** (ingress *and* egress; an exfiltration attempt leaves as much as it enters).
Detection is **layered, cheap-first**:

1. **Fast tier (heuristics, deterministic, free)** — regex/pattern/anomaly rules: the ADR-023
   "Bouncer" crypto-prompt patterns, dangerous-command signatures, known-bad indicators, structural
   anomalies. Produces a clear allow / clear block for the common case.
2. **Escalation tier (LLM-judge, on ambiguity only)** — inputs the fast tier can't classify are sent
   to a model that scores risk `0..1`. Cost/latency only on the margin.

Warden's output is a **risk score + reasons**, fed into the ADR-068 **CLASSIFY** step (it does not
itself allow/deny — it informs Sentinel). Warden is tuned in **code** (detectors evolve fast;
detection logic is not safely product-authorable).

```python
class Warden(Protocol):
    def scan(self, data: Untrusted, *, boundary: Boundary, direction: Literal["in","out"]) -> Risk: ...
class Risk(BaseModel):
    score: float                 # 0..1
    reasons: list[str]
    tier: Literal["heuristic","llm_judge"]
```

### Sentinel — policy decision + enforcement point (PDP/PEP)

Sentinel is the authoritative adjudicator at the **tool-call boundary** (in-process, MCP gateway,
A2A). It evaluates the **ADR-068 model**: resolve the tier ladder, consult the approver matrix, run
the RLPHD gate, honor the budget veto — taking Warden's risk as a CLASSIFY input. It returns a
decision the caller enforces; it raises nothing.

**Hybrid policy model** (the decided shape):
- **Code** owns the *mechanism* — Warden detectors, the gate/tier logic, the evaluation order.
- **A declarative layer owns the *tunables*** — thresholds, allow/deny lists, the approver matrix,
  and the RLPHD `θ` weights. This layer is **stored in the DB as the online source of truth**,
  **editable at runtime under RBAC**, and **exported to human-readable YAML/JSON for backup** (the
  engine config model). No code deploy to change a threshold or an approver binding.

```python
class SentinelPolicy(Protocol):                       # extends the ADR-050 SentinelPolicy
    def resolve_tier(self, call: ToolCall, p: Principal) -> Tier: ...        # ADR-068 §B/§C
    async def authorize(self, call: ToolCall, p: Principal, risk: Risk) -> AuthzDecision: ...  # ADR-068 §F
```

### Decision audit

Every Sentinel decision (allow/deny/elevate/gate) is recorded as a **signed VC** (ADR-024) and an
ADR-037 event (`policy.decision` with `policy_id`, `decision`, `inputs_hash`; `security.violation`
on a Warden block). The audit is what the deconfliction loop (ADR-074) reads to detect drift, and
what a compromised agent must not be able to forge or read (the policy store and audit are
admin-scoped, ADR-068).

### Learned-policy changes route through here

When the declarative layer changes — a human RBAC edit, or an RLPHD/learned adjustment — the change
does **not** take effect directly. It is a Repertoire *Compose* and must pass the ADR-070 *Rehearse*
gate, which is the **ADR-074 deconfliction check** (conformance vs ADRs → Specs → prior policy). Pass
→ commit; conflict → held for admin review. This is how online-mutable policy stays honest.

## Acceptance criteria

- [ ] Warden scans every trust boundary; MCP boundary scanned **both** directions.
- [ ] Fast-tier heuristics resolve the common case with no model call; only ambiguous inputs escalate
      to the LLM-judge (property test: a clearly-benign input never calls the judge).
- [ ] Sentinel evaluates the ADR-068 order (CLASSIFY→AUTHORIZE→BUDGET→GATE) and returns a decision;
      Warden risk is a CLASSIFY input.
- [ ] Policy tunables (thresholds, allow/deny, approver matrix, RLPHD θ) live in the DB, are
      RBAC-gated online-editable, and export to human-readable form; mechanism stays in code.
- [ ] Every Sentinel decision is a signed VC + `policy.decision` event; a Warden block emits
      `security.violation`.
- [ ] A change to the declarative policy passes through the ADR-074 conformance/Rehearse gate before
      activating; a conflict is held, not applied.
- [ ] The policy store + decision audit are admin-scoped — an agent principal can neither read the
      approver matrix nor forge a decision record.

## Consequences

- ADR-068/050/051 gain their named enforcement substrate; "Sentinel enforces" is now specified.
- Warden's risk signal is the concrete CLASSIFY input ADR-068 assumed.
- The declarative-policy-in-DB decision (config model) + the ADR-074 conformance gate together make
  online policy edits safe (no silent drift).

## Out of scope

- The LLM-judge model choice / prompt (a tuning detail; follow-up SPEC with RLPHD).
- The on-disk schema of the policy + audit stores.
- Multi-tenant policy partitioning — Stronghold (ADR-019).
