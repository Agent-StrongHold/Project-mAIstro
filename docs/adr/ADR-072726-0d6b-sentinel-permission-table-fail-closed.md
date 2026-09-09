---
id: ADR-072726-0d6b
title: "Sentinel permission table: fail-closed default"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-07-27
accepted: 2026-09-09
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# Sentinel permission table: fail-closed default

## Context

`AuthContext.can_use_tool` (`packages/maistro-core/src/maistro/security/_types.py:31-35`)
returns `True` whenever `permission_table.get(tool_name)` is `None`. An absent entry means
*permitted*.

A 2026-07-27 codebase review initially characterised this as "Sentinel fails open" and
recommended inverting the default. That characterisation was wrong, and the correction matters
enough to record.

The behaviour is **deliberate, documented, and property-tested**. It is asserted as a Hypothesis
property under invariant **I6 — Sentinel Permission Enforcement**:

```python
# formal/models/test_sentinel_policy.py:221-223
@settings(max_examples=20)
def test_can_use_tool_no_entry(tool_name):
    auth = AuthContext(user_id="u1", roles=frozenset({"user"}))
    assert auth.can_use_tool(tool_name, {})
```

That invariant is listed in `formal/README.md` and gated in CI by
`.github/workflows/formal-conformance.yml`, and additionally by `quality.yml`'s Pillar 2. The
design is allowlist-*optional*: a deployment that configures nothing gets no denials.

What was genuinely defective was that **nothing ever populated the table**. `create_container`
passed a literal `{}` and no code anywhere in `packages/*/src` wrote to it, so tool authorization
was a live mechanism with a permanently empty policy. That is fixed on branch
`fix/security-wiring`: the table is now built by
`maistro.security.permission_policy.build_permission_table` from
`config.security.permission_preset` and `config.security.permissions`, defaulting to empty so
runtime behaviour is unchanged. The mechanism is now *armable*. It is not *armed*, and the
default was not inverted.

## Decision

**Accepted 2026-09-09** (issue #1165), with the scope honestly bounded in the
implementation reconciliation below. The fail-closed direction is taken: an
absent permission-table entry now denies, at the shared Sentinel boundary, and
allow-on-miss survives only as an explicit compatibility mode for
non-production/test/demo wiring. What remains consciously deferred is stated
there — this acceptance does NOT claim the preconditions below are all met.

The original (2026-07-27) proposal record, kept for the sequencing precedent
it set: invert `can_use_tool` so an absent entry denies, behind a configuration
flag and a deprecation window. This ADR existed to record what must be true
before that inversion is safe, and to make the sequencing explicit for whoever
picked it up.

## What must change first

**1. Invariant I6 must be amended first, in its own change.**
`test_can_use_tool_no_entry` would have to be rewritten or removed. Flipping the default while
editing `formal/` in the same commit would mean *changing a formal security invariant so that our
own fix passes* — the reward-hacking pattern this repository already defends against elsewhere:
the RSI candidate scorecard requires a diff's own tests to kill ≥50% of diff-scoped mutants
(`packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py`), and the Warden quarantine escalates
any diff touching `maistro/security/` to adversarial review
(`packages/maistro-rsi/src/maistro_rsi/quarantine.py:33-72`).

**A pull request that flips the default and touches `formal/` in the same commit should be
rejected on sight.** Amend the invariant, with its own justification, as a separate reviewed
change; then implement against the amended invariant.

**2. A complete tool inventory must exist.**
Fail-closed requires enumerating every tool name that can reach `Sentinel.pre_call`. Today those
names come from per-agent `identity.tools` (`agents/base.py:257-262`) — arbitrary strings from
agent YAML, with no central registry. Without an inventory, fail-closed does not harden the
system; it breaks every agent whose tool happens not to be listed.

**3. A role model must exist.**
Roles reach `AuthContext` from JWT claims (`security/auth_jwt.py:87-90`) and may legitimately be
empty. `auth_static.py:40-47` issues `frozenset({"user"})` in read-only mode and the broader
`SYSTEM_AUTH` otherwise. There is no documented role taxonomy to write a permission table
against, so any table written today would encode an accident rather than a policy.

**4. A shadow mode must run first.**
An audit mode that logs what *would* have been denied, exercised against real traffic for a
defined period, with the resulting deny-list reviewed — before any enforcement.

## Consequences

**Positive.** Closes the gap where a deployment that has configured no permissions silently
authorizes every tool for every role. For a multi-tenant posture (Stronghold) that default is the
wrong one, and the inversion is likely a prerequisite there.

**Negative.** Every missed tool name is an outage. The four preconditions above are substantial
work, and preconditions 2 and 3 are effectively "design the authorization model", not
"change a boolean".

**Neutral.** The configuration surface added on `fix/security-wiring`
(`security.permission_preset`, `security.permissions`) is forward-compatible with either default,
so adopting this ADR later requires no further config migration. The `dangerous_tools_admin`
preset added there is the natural seed for a future default table: it maps the already-reviewed
`DANGEROUS_TOOL_NAMES` set to `admin`, and can be exercised in shadow mode under precondition 4
before anything is enforced.

## Implementation reconciliation (2026-09-09, issue #1165)

Implemented on branch `m2-1165-a1`, following this ADR's own sequencing rule:

1. **Invariant I6 was amended first, in its own commit** (`3d593b17`). The three
   allow-on-miss properties in `formal/models/test_sentinel_policy.py`
   (`test_can_use_tool_no_entry`, `test_no_permission_entry_means_allowed`,
   `test_pre_call_open_by_default`) were amended to assert deny, and a new
   property pins the explicit compatibility mode. The semantic flip landed in
   a separate following commit, exactly as this ADR requires.
2. **The deny direction is taken at the shared boundary, not at callers.**
   `AuthContext.can_use_tool` returns False on a table miss — the primitive
   carries no permissive switch. `check_permission` / `Sentinel` gained a
   keyword-only `allow_on_miss` flag defaulting to False; arming it logs a
   warning. Every Sentinel construction inherits deny-on-miss. The two known
   empty-table production sites now fail closed through the shared semantics:
   `orchestrator/output_security.py`'s gate performs only post-call output
   processing (no permission lookups; any future pre_call/authorize against it
   denies), and a bare-constructed `agent.synth_dag` node refuses to approve
   (and therefore dispatch) synthesized sub-graphs until it is wired with a
   Sentinel whose governed table grants the action. Wiring that grant is
   #804's governed tool-use work, not an empty-table default.
3. **The compatibility mode is explicit and non-production-reachable.** The
   only way to arm allow-on-miss is `Sentinel(allow_on_miss=True)` in
   non-production/test/demo wiring; each such construction in the test suite
   is marked `COMPATIBILITY (#1165)`. No configuration field routes to it:
   `SecurityConfig` has no such field and a test pins that absence, so no
   production profile can express allow-on-miss. This is deliberately stricter
   than the original "configuration flag + deprecation window" shape: the
   shipped config schema cannot weaken the default at all.
4. **Mutation resistance.** Flipping the miss branch back to allow fails the
   suite at four independent layers: the amended formal I6 properties, the
   core `can_use_tool`/`check_permission` units, Sentinel `pre_call` /
   `authorize` on empty and governed tables, and the container wiring test
   asserting the default production Sentinel denies unlisted tools.

**Consciously deferred (not done here — do not assume otherwise):**

- Precondition 2 (complete tool inventory) and precondition 3 (documented role
  model) remain open. Deny-by-default at shipped config means an un-configured
  deployment authorizes nothing; operators must configure
  `security.permissions` or a preset explicitly. There is still no central
  tool registry that would let a default table be *generated* rather than
  hand-maintained.
- Precondition 4 (shadow mode) was not built: there is no audit-only mode that
  logs what a richer table *would* have denied before enforcement. The
  compatibility mode's warning log is the only soft signal.
- Reconciliation with canonical Capability/Binding/policy state (the
  #55/#57/#846 family) is NOT implemented: the table remains a governed
  deployment configuration, not a projection of capability bindings, and
  runtime revoke-without-restart is out of scope here.
- Message precision follow-up: a denied `agent.synth_dag` authorization
  surfaces as a generic needs-revision verdict whose revision text mentions
  budget. The refusal is correct and fail-closed; the wording is not.
- The captured-provider and AllowAllGate bypasses on live harness/effect paths
  remain #846's scope, untouched here.
