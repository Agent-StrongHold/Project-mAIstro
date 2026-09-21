---
inventory-delta:
  packages/maistro-core/tests: +28
  packages/maistro-evolve/tests: +6
  packages/maistro-rsi/tests: +15
---

# 350 pin security-critical formula magnitudes against governed fixtures

Tests only — no production values changed, none removed or renamed. Four new
test files, each paired with an independently governed JSON fixture that states
the expected magnitudes apart from the implementation constants:

- `packages/maistro-rsi/tests/test_magnitude_pins.py` (+15, new) with
  `governed_magnitudes_rsi.json`: pins `REJECT_BELOW=0.4`,
  `_MIN_RETAINED_FRACTION=0.5`, `_MAX_DIFF_CHARS=8000`,
  `_MUTATION_KILL_THRESHOLD=0.5` (exact) plus `_MUTATION_MAX_MUTANTS` and
  `_DELETED_TRACE_CAP` (governed safe ranges — cost/record-shape knobs, not
  over-pinned) and the free-router de-dup attempt multiplier (4×count, pinned
  behaviorally via an exact call-count). Boundary/calibration tests use literal
  expected values: verdict mapping at 0.4/0.3999, the 16000/16001-char
  fail-closed diff boundary (exactly twice the cap), 500/1000 vs 499/1000
  mutation-kill boundary, and the ADR-070126-6386 v3 ladder ordering through
  `compose_scorecard` (finishing a contracted AC 0.8814 > proposing a spec
  0.8704 — kills a subtle 0.45→0.40 swap).
- `packages/maistro-evolve/tests/test_magnitude_pins.py` (+6, new) with
  `governed_magnitudes_evolve.json`: the full `FitnessWeights` table (exact,
  field-by-field) plus the ADR's ladder invariants (spec_completion is the
  max weight, spec_proposed just below it, code_quality the min) and a
  literal composite calibration.
- `packages/maistro-core/tests/router/test_magnitude_pins.py` (+13, new) with
  `governed_magnitudes_router.json`: shipped `RoutingConfig` defaults
  (quality 0.6 / cost 0.4 / reserve 0.05) and `priority_multipliers` pinned
  in BOTH copies (types/config.py and config/settings.py) plus a no-drift
  check; `SPEED_WEIGHTS` and `_MAX_SPEED=2000` exact with a literal bonus
  calibration; scorer cost band (`_RAW_FLOOR`/`_RAW_CEIL`/`_NORM_CAP`) exact
  with a derivation check (1/ln(1e9), 1/ln(100)); `OVER_QUOTA_FLOOR` and
  `INELIGIBLE_COST` exact with the free-quota-wins invariant; one full
  end-to-end score calibration with literal outputs (quality 0.92, cost
  0.117410, score 0.8292) that catches `strength_mult` 1.15→1.5.
- `packages/maistro-core/tests/memory/episodic/test_magnitude_pins.py` (+15,
  new) with `governed_magnitudes_memory.json`: SPEC-240 decay/reinforce
  constants exact with literal scenario values (thumbs-up +0.075, thumbs-down
  −0.025, decay_rate ×0.5/×2.0, 10h tick −0.1, 3:1 boost:drop asymmetry);
  promote/demote thresholds pinned AND boundary-tested with literal counts
  (4 do not, 5 do); `WEIGHT_BOUNDS` exact (REGRET floor 0.6 structurally
  unforgettable); `SIMILARITY_MERGE_THRESHOLD=0.85` with the 0.85-merges /
  0.84-does-not boundary; contradiction delta 0.05 literal; the Σw²/Σw
  weighted-merge formula calibrated to exactly 0.52.

Mutation drill (18 representative large+subtle mutations applied one at a
time to production constants, reverted after): every one killed by the new
tests, including REJECT_BELOW→0.04, threshold→0.25, spec_completion→0.40
swap, DEFAULT_DECAY_RATE→0.1, REGRET floor→0.06, _RAW_FLOOR 1e9→1e6, and a
one-sided settings.py cost_weight drift. All four fixture files live under
tests/ and are not scanned by the vulture ratchet (packages/*/src only);
no dead code added.
