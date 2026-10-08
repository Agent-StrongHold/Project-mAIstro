---
inventory-delta:
  packages/maistro-rsi/tests: +11
---
# 933 M8-E4: destination-aware escalation policy frontier (+11)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #933 (M8-E4) asks the abstention research to evaluate decision policies
with distinct escalation destinations — stronger model, specialist Agent,
verifier, HITL — and to report human-intervention rate and escalation
cost/latency, which the existing answer-vs-defer frontier in
`test_m8e_uncertainty_calibration_research.py` deliberately collapsed into a
single defer cost. This change extends that test-suite-only research harness
(no `maistro` imports, no product code, M8 guardrails 1–2) with the
destination-aware frontier: `EscalationDestination` (operator-measured
eventual success rate, marginal cost, latency, human-intervention flag),
`m8e_route_to_destination` (validated ascending confidence bands, least
confident to HITL, nearly confident to the cheap verifier), and
`m8e_escalation_frontier` (per-threshold expected utility, unsafe-action
rate, escalation rate, human-intervention rate, unnecessary-escalation rate,
mean escalation cost/latency, destination shares). All outputs stay frozen
measurement records; nothing can act.

The 11 new cases hand-check the destination arithmetic (all-deferred and
mixed-threshold points computed by hand), pin band-routing edge semantics
(exclusive bounds, above-final-bound routing, malformed tables rejected),
assert monotone escalation and human-intervention rates across thresholds,
show destination quality/cost moving utility in the stated directions,
demonstrate a #930-style agreement signal routing escalations better than
self-report at the same threshold, evaluate the policy on the held-out half
of a temporal split with calibration fit on the earlier half only, measure
drift suppressing human escalation (HITL share 33% → 0%, unsafe rate
14% → 31%) under a stale self-report threshold while recalibrated scores
absorb it, and extend the evidence-only contract to the new record types. A
mutation check (band-routing loop removed and the human-intervention flag
ignored) fails 5 of the 11 new cases, so the assertions bind to the routing
behavior rather than passing vacuously. Results are recorded in
`docs/research/904-uncertainty-calibration-abstention.md`; the #933
disposition stays WATCH on synthetic parameters.
