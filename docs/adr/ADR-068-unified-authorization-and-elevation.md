---
id: ADR-068
title: "Unified Authorization & Elevation — tiers, an approver graph, sudo-style self-elevation, and RLPHD predictive approval"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-29
substrate:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-054
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-023
  - maistro-engine#ADR-024
  - maistro-engine#ADR-037
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - boundary
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-29
  - status: Implemented
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# ADR-068: Unified Authorization & Elevation

**Status:** Proposed
**Date:** 2026-05-29
**Amends:** ADR-028 (configurable roles + approver graph + the agent principal — retires
its "Full RBAC out of scope"), ADR-051 (its layer-3 "learned trust" becomes RLPHD;
"orthogonal to ADR-028" retired), ADR-019 / Key Design Decision 7 (scope hierarchy)

---

## Context

Four ADRs each own one slice of "may this action run, and does a human need to see it
first," none states how they compose, and they contradict:

- **ADR-028 (privilege separation)** — *who* the principal is. A mandatory two-tier
  `admin`/`user` split; privileged ops route through admin via wallet-signed elevation.
  Explicitly puts **"Full RBAC (roles beyond admin/user)" out of scope**.
- **ADR-050 (reversibility taxonomy)** — *what class* the action is
  (`internal | reversible | irreversible`). The classifier the others read.
- **ADR-051 (approval gates)** — *whether this call* needs a human now (plan-preview /
  impact escalation / a crude "N approvals → auto-promote" learned-trust). Its Context calls
  ADR-028 *"orthogonal; process-level, not task-level."*
- **ADR-054 (task budgets)** — *whether spend remains*.

This produced real ambiguity the implementation tripped on (hive-conductor `_PROTECTED_OPS`
had to guess whether a DAG-run POST is a privilege check, an approval gate, both, and in what
order), and three structural gaps the two-tier model can't express:

1. **More than two outcomes.** Actions need a *ladder*: open → role/team-auto → self-elevation
   → delegated-approval → admin-elevation → blocked.
2. **Self-elevation (sudo).** A user clears a within-authority gate by re-authenticating with
   **their own** password/passkey — they are not asking *admin*, they are proving liveness +
   intent over authority they already hold. An **agent cannot do this**; it must send its
   owning human a **scoped 2FA** approval request.
3. **A relational approver graph.** "Team-1 approves team-2," manager→employee, parent→child.
   *Who* may satisfy a gate for principal P is a configurable relation, not just "admin."

And ADR-051's learned-trust is too crude: a counter ("5 approvals, 0 denials → promote") can't
express *confidence*, can't get *more* cautious after a surprising denial, and can't act on a
borderline call the human just taught it to allow.

## Decision

### A. Principals, roles, scope (amends ADR-028 + ADR-019)

Roles and the scope hierarchy are **core**, not Stronghold:

```
scope (soft, in core):   global > org > team > user > agent > session
tenant (hard, Stronghold-only): full segmentation; one tenant per user
```

- `admin`/`user` (ADR-028) become the **base roles** of a configurable role system. Admin
  retains the Conductor Seed (ADR-021) and is always a valid root approver. This **retires
  ADR-028's "Full RBAC out of scope"** — configurable roles + an approver graph are now in
  scope for core (the homelab Conductor needs team-1/team-2 too). Custom *AgentSpec* role
  definitions (Medley) and `tenant` isolation (Stronghold) remain out of scope.
- A user may belong to **multiple teams/orgs** within a tenant.
- An **agent** is a principal that always acts **on behalf of an owning human** and holds a
  **subset** of that human's authority — never more. (This is the missing piece that made
  ADR-028 and ADR-051 look orthogonal: ADR-028 only ever modelled a human signing.)

### B. The gating-tier ladder

Every action resolves, per `(action, requesting principal's role/scope)`, to exactly one
tier (most-specific policy wins):

| Tier | Cleared by | Agent equivalent |
|------|-----------|------------------|
| `open` | nobody — auto for everyone | same |
| `role/team-auto` | auto **iff** principal's role/team ∈ allow-set, else falls to the next applicable gate | same (within owner's authority) |
| `self-elevation` (**sudo**) | the **principal re-authenticates** (own password / passkey) — within-authority, high-consequence confirmation | agent **cannot**; it sends its owning human a **scoped 2FA** request (this action, these args, short TTL) |
| `delegated-approval` | **any member of the approver scope** resolved from the policy matrix (§C) — beyond the principal's own authority | same approver scope; the agent's request carries its owner identity |
| `admin-elevation` | the **root/admin** signature specifically | same — admin only |
| `blocked` | nobody (admin break-glass only, if ever) | same |

`internal`/`reversible` actions (ADR-050) default to `open` or `role/team-auto`;
`irreversible` actions default to **at least** `self-elevation` and escalate by impact
(ADR-051 §2) and by whether they exceed the principal's authority (→ `delegated-approval`).

### C. Approver graph — policy matrix

Who may satisfy a `delegated-approval` (or stand in for `admin-elevation` where delegated) is
a **declarative binding**, not a fixed tree:

```yaml
policy:
  - action: deploy            # name or reversibility/impact class
    for-scope: team:2         # the requesting principal's scope
    approved-by: team:1       # ANY member of this scope may approve
  - action: spend
    for-scope: user:*         # any user
    approved-by: role:manager # role-relative
```

Resolution: pick the most-specific binding for `(action, requester-scope)`; the approver set
= members of `approved-by`. **Admin is always an implicit root approver.** Self-elevation is
the degenerate case where `approved-by == the principal themselves` (re-auth).

This expresses your examples directly: users A,B (team 1) run `X` at `role/team-auto`; users
C,D (team 2) hit `delegated-approval` for `X` with `approved-by: team:1`; manager→employee and
parent→child are the same binding with different scopes.

### D. Elevation, two flavors, and the agent leg

- **Self-elevation (sudo)** — human re-auths (password/passkey) for an action **within** their
  granted authority. Proves liveness + intent. Recorded as a **short-TTL elevation grant**
  (the ADR-028 time-boxed mode, scoped to the action class).
- **Agent → scoped 2FA** — an agent NEVER holds a password and NEVER self-elevates. To take an
  action that would require self-elevation for its owner, it emits a **scoped approval request**
  (single action, concrete args, short TTL) to its owning human, who signs it. The human's
  signature is the agent's second factor.
- **Delegated / admin approval** — signed by a member of the approver scope (§C).
- **One signing substrate**: local human factor = password/passkey; remote or agent-relayed =
  DID/wallet signature (ADR-023/024). Every grant/denial is recorded as a VC (ADR-024) and an
  audit event (ADR-037). "Send 1000 sats," "delete directory," and "agent X may post once" are
  the same cryptographic act.

### E. RLPHD — Reinforcement-Learned Policy from Human Decisions (replaces ADR-051 layer-3)

ADR-051's counter-based learned-trust is replaced by a **confidence-calibrated predictor** of
the human's own approval policy. **RLPHD is glass-box, not ML/LLM** (clarified 2026-05-30): it is
**interpretable parameter-tuning of explicit gate parameters** (the threshold `θ`, per-feature
weights) — every parameter is human-readable, overridable, and hand-editable in the DB config
(ADR-078). "Learning" = the transparent dual-signal nudging of those parameters below; there is no
opaque model. This is what makes it auditable and reconcilable by the ADR-074 deconfliction loop
(you cannot deconflict a black box):

- For any pending gate, a per-`(principal, action-class, context)` model estimates
  `p = P(the human approves | action, args, context, history)`.
- Substrate **auto-acts only when `p ≥ θ`**, the adaptive confidence threshold for that
  `(principal, action-class, gate)`. The predicted confidence is **surfaced** ("I'm 78% sure
  you'd approve — acting in N s unless you stop me") and logged.
- **Every human decision updates both the predictor and θ** — the threshold *is* part of the
  signal:
  - Human **denies** a high-confidence prediction (say p=0.65) → **raise θ** (demand more
    certainty before auto-acting) **and** correct the predictor down.
  - Human **approves** a low-confidence one (p=0.20) → **lower θ** near that margin (more
    willing on borderline) **and** correct the predictor up.
  - Approvals and denials both sharpen calibration; surprises move θ more than confirmations.
- **Hard limits (non-negotiable):** RLPHD may only stand in for tiers the human has opted to
  let it learn — `role/team-auto`, `self-elevation`, and `delegated-approval` **where the
  approver opted in**. It can **never** auto-clear `admin-elevation` or `blocked`, and can
  **never** bypass the budget hard-veto (§F step 3). Per-`(principal, action-class)`; never
  global; never cross-principal; revocable; a per-action always-ask override always wins.
- The detailed model class, feature vector, and update rule are deferred to a follow-up SPEC;
  this ADR fixes the *policy* (confidence-gated, dual-signal, hard-limited).

### F. Evaluation order

For every tool call / privileged operation, in this order, **stop at first deny**:

Enforced by the existing security substrate — **no new component**: **Warden** scans untrusted
input at the trust boundary (Principle 6) and contributes a risk signal into CLASSIFY;
**Sentinel** is the policy decision + enforcement point (PDP/PEP) that resolves the tier,
consults the approver matrix, runs the RLPHD gate, and emits the allow/deny. ADR-050/051
already place tool-call policy in Sentinel — this ADR is the model Sentinel evaluates.

```
1. CLASSIFY  reversibility (ADR-050) + tier (§B, from policy) + cost (ADR-054)
             + Warden risk score on untrusted args (Principle 6). Pure; no side effects.
2. AUTHORIZE Does the principal's role/scope grant the capability at all?
             (agent authority = its own ∩ its owner's). No grant ⇒ it is at least
             `delegated-approval`/`admin-elevation`, never `self-elevation`.
3. BUDGET    (ADR-054) Hard veto. Over-budget ⇒ ADR-051 "approve more budget?" gate;
             elevation/RLPHD CANNOT bypass a zero balance — only an explicit grant.
4. GATE      Resolve the §B tier:
               open / role-auto-in-set        → EXECUTE
               self-elevation                 → human re-auth | agent→scoped-2FA-to-owner
               delegated-approval             → approver scope signs (§C);
                                                RLPHD may auto-satisfy iff p≥θ AND opted-in
               admin-elevation                → admin signs (RLPHD excluded)
               blocked                        → DENY
5. EXECUTE / on denied-mid-saga → compensator (ADR-050).
```

Authorize precedes approve so a principal lacking the capability never sees a content-bearing
prompt (no existence leak, no social-engineering the approver). Reversibility (ADR-050) feeds
the tier; it never decides.

## Interface (sketch)

```python
class Tier(StrEnum):
    OPEN = "open"; ROLE_AUTO = "role_team_auto"; SELF_ELEVATION = "self_elevation"
    DELEGATED = "delegated_approval"; ADMIN = "admin_elevation"; BLOCKED = "blocked"

class Principal(BaseModel):
    id: str
    kind: Literal["human", "agent"]
    roles: list[str]
    scopes: list[str]                 # e.g. ["team:1", "org:acme"]
    owner: str | None = None          # required when kind == "agent"

class AuthzDecision(BaseModel):
    tier: Tier
    authorized: bool                  # step 2
    needs: Literal["none","self_elevation","scoped_2fa","delegated","admin"]
    approver_scope: str | None        # resolved from the policy matrix (§C)
    within_budget: bool               # step 3
    rlphd: RlphdVerdict | None        # predicted p, threshold θ, auto-acted?
    reason: str

# Realized by Sentinel; NOT a new component. Warden feeds the risk signal into step 1.
class SentinelPolicy(Protocol):                # extends the ADR-050 SentinelPolicy
    def resolve_tier(self, call: ToolCall, p: Principal) -> Tier: ...      # §B/§C
    async def authorize(self, call: ToolCall, p: Principal) -> AuthzDecision: ...  # §F 1-4

class Warden(Protocol):
    def risk(self, untrusted: ToolArgs) -> RiskScore: ...   # boundary scan → CLASSIFY input
```

**Enforcement points.** Sentinel is the per-tool-call PDP/PEP (in-process, MCP gateway, and
A2A boundaries). Warden scans untrusted content at every trust boundary and supplies the risk
input. The hive-conductor `_PROTECTED_OPS` table is the **coarse HTTP front gate** — the first
concrete implementation of §F step 2+4 for the route surface — but the authoritative decision
is Sentinel's at the tool-call boundary. WebSocket handlers must call the same `authorize()`
(BaseHTTPMiddleware does not run for the websocket scope).

## Acceptance criteria

- [ ] `authorize()` runs §F steps in order, short-circuits on first deny; property test: no
      `open`/in-set `role_auto` action ever raises a prompt.
- [ ] A within-authority gated action is cleared by the principal's **own** re-auth
      (self-elevation) — not by admin — and recorded as a short-TTL grant.
- [ ] An **agent** with the same action gets `needs == scoped_2fa`; its owner's signature over
      the scoped request clears it; the agent never receives a password.
- [ ] A beyond-authority action resolves `approver_scope` from the policy matrix; **any**
      member of that scope can approve; admin always can.
- [ ] Over-budget cannot be cleared by elevation or RLPHD — only an explicit budget grant.
- [ ] RLPHD auto-acts only when `p ≥ θ`; a denial of a high-`p` call **raises** θ, an approval
      of a low-`p` call **lowers** θ; both update the predictor. Never auto-clears
      `admin_elevation`/`blocked`; per-`(principal, action-class)`, revocable.
- [ ] Every elevation/approval/denial/expiry is a signed VC (ADR-024) + event (ADR-037).

## Consequences

- **ADR-028**: "Full RBAC out of scope" retired (configurable roles + approver graph in core);
  gains the agent principal and the self-elevation vs delegated distinction.
- **ADR-051**: layer-3 learned-trust → RLPHD; "orthogonal to ADR-028" retired (authorize
  precedes approve).
- **ADR-019 / Decision 7**: amended for `tenant > org > team > user` (separate edits in this PR).
- **hive-conductor**: the staged security cluster (`_PROTECTED_OPS`, WS auth, audit anti-spoof)
  implements §F; its previously-failing tests assert the *documented* model (privileged ops
  need elevation / route to an approver), not the pre-model open behavior.
- **Follow-up SPEC**: RLPHD predictor mechanics (model class, features, θ update rule, cold-start).

## Out of scope

- RLPHD model internals (follow-up SPEC).
- Notification channel for approval/2FA prompts (product-level, ADR-051).
- On-disk schema of the elevation-grant, approver-policy, and RLPHD stores.
- `tenant` isolation mechanics — Stronghold (ADR-019).
- Custom AgentSpec role definitions — Medley plugin (ADR-028 out-of-scope still holds).
