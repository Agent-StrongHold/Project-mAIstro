---
id: SPEC-248
title: "RLPHD — glass-box predictive approval, confidence threshold (ADR-068 §E)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-051
implements:
  - maistro-engine#ADR-068
related:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-247
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-245
  - maistro-engine#SPEC-247
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_rlphd.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-248: RLPHD — glass-box predictive approval, confidence threshold

## Context

ADR-068 §E replaces ADR-051's counter-based learned-trust ("5 approvals, 0 denials →
promote") with RLPHD: a confidence-calibrated, **glass-box** (not ML/LLM — interpretable
parameter tuning, every weight human-readable and hand-editable) predictor of `p = P(human
approves | action, args, context, history)`, gated by an adaptive threshold `θ` per
`(principal, action-class, gate)`. ADR-068 explicitly defers "the detailed model class,
feature vector, and update rule" to a follow-up SPEC — this is that SPEC, scoped to the
policy ADR-068 already fixed: confidence-gated, dual-signal threshold update, hard-limited.

## Goals

- Add `RlphdVerdict` (`p: float`, `theta: float`, `auto_acted: bool`) — already referenced
  as a field type on `AuthzDecision` (SPEC-245) but undefined until now.
- Add `RlphdModel`: a per-`(principal_id, action_class)` glass-box predictor — a small,
  explicit linear feature-weight vector (`feature_weights: dict[str, float]`) over a fixed,
  documented feature set (e.g. `time_of_day_bucket`, `arg_risk_score` from Warden, `recency
  since last approval of this action_class`, `principal_role`). `predict(features) -> float`
  is a sigmoid over the weighted sum — fully inspectable, no opaque model.
- Add `RlphdThresholdStore`: per-`(principal_id, action_class, gate)` adaptive `theta`,
  starting at a configurable cold-start default (e.g. 0.7).
- `RlphdModel.update(features, human_decision: Literal["approve","deny"], predicted_p: float)`:
  dual-signal update —
  - deny at high `p` (surprise) → raise `theta` by `surprise_gain * (predicted_p - actual)`,
    nudge `feature_weights` down for the features that drove `predicted_p` up;
  - approve at low `p` (surprise) → lower `theta` toward the margin, nudge weights up;
  - confirmations (low-surprise approve/deny) move `theta` less than surprises (asymmetric
    update magnitude is the "surprises move θ more than confirmations" rule from ADR-068).
- `Sentinel.authorize()` (SPEC-245), at the `DELEGATED` gate **only if the approver scope has
  opted in** (a per-`(principal, action_class)` opt-in flag, default off): calls
  `RlphdModel.predict`, and if `p >= theta`, auto-acts and records `RlphdVerdict(p, theta,
  auto_acted=True)`; otherwise surfaces the predicted confidence to the human
  ("I'm 78% sure you'd approve — acting in N s unless you stop me" is a product-level UX
  concern, out of scope for this SPEC, which only computes and exposes `p`/`theta`).
- **Hard limits enforced in code, not just policy**: `RlphdModel`/`Sentinel` must reject any
  attempt to apply RLPHD to `ADMIN` or `BLOCKED` tiers, and must never run before the ADR-054
  budget hard-veto (SPEC-245 step 3 already precedes step 4's gate, so this falls out of the
  existing evaluation order — verified by a regression test here, not re-implemented).

## Non-goals

- Any actual ML/LLM model — explicitly glass-box only, per ADR-068 §E's 2026-05-30
  clarification.
- The UX/notification surfacing of confidence to the human — product-level.
- Cross-principal or global learning — every model instance is strictly
  per-`(principal_id, action_class)`; this SPEC does not pool data across principals.

## Decision

```python
@dataclass(frozen=True)
class RlphdVerdict:
    p: float
    theta: float
    auto_acted: bool

class RlphdModel:
    def __init__(self, feature_weights: dict[str, float] | None = None) -> None: ...
    def predict(self, features: dict[str, float]) -> float: ...  # sigmoid(weighted sum)
    def update(
        self, features: dict[str, float], decision: Literal["approve", "deny"], predicted_p: float
    ) -> "RlphdModel":  # returns updated copy; pure, like memory/episodic/tiers.py's style
        ...

class RlphdThresholdStore(Protocol):
    async def get_theta(self, principal_id: str, action_class: str, gate: str) -> float: ...
    async def set_theta(self, principal_id: str, action_class: str, gate: str, theta: float) -> None: ...
    async def opted_in(self, principal_id: str, action_class: str) -> bool: ...
```

Following the `maistro.memory.episodic.tiers` convention established in SPEC-240:
`RlphdModel.update` is a pure function returning a new `RlphdModel`, not mutating in place —
keeps the glass-box parameter history auditable and trivially testable.

## Acceptance criteria

- [ ] `predict()` is a pure function of `feature_weights` and `features` — fully
      reproducible, no hidden state.
- [ ] `RlphdModel.update` on a deny-at-high-`p` raises `theta` and lowers the weights that
      drove the prediction up; an approve-at-low-`p` lowers `theta` and raises those weights.
- [ ] A confirmation (low-surprise decision) moves `theta` by a strictly smaller magnitude
      than a surprise of equal `|predicted_p - actual|` would — i.e. the update rule is
      surprise-weighted, not flat-rate.
- [ ] `Sentinel.authorize()` never invokes RLPHD for `ADMIN`/`BLOCKED` tiers, and never
      invokes it before the budget check — regression test asserts call order.
- [ ] `Sentinel.authorize()` never invokes RLPHD for a `(principal, action_class)` that
      hasn't opted in; default is opted-out.
- [ ] Auto-acting (`p >= theta`) records an `RlphdVerdict` with `auto_acted=True`,
      `tests=...` includes it in the resulting `AuthzDecision`.

## Testing

- `packages/maistro-core/tests/security/test_rlphd.py` (new) — predictor purity, dual-signal
  update direction and surprise-weighting, opt-in gating, tier exclusion (`ADMIN`/`BLOCKED`),
  evaluation-order regression against SPEC-245's `authorize()`.

## Open questions

- Exact feature set for v1 (this SPEC names illustrative features; finalize during
  implementation against what `ToolCall`/`Principal`/Warden risk score actually expose).
- Cold-start `theta` default and `surprise_gain` constant — implementation-tunable, not an
  ADR-level invariant.

## References

- `packages/maistro-core/src/maistro/memory/episodic/tiers.py` (precedent for pure-update style)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- [SPEC-245: Authorization tier ladder](SPEC-245-authz-tier-ladder.md)
- [SPEC-247: Elevation flows](SPEC-247-authz-elevation-flows.md)
