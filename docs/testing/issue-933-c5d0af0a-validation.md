# Issue #933 validation — repair round c5d0af0a (M8-E4 escalation-destination frontier)

Verification record for lane L933 ([RESEARCH M8-E4] abstention / ask-for-help /
confidence-triggered escalation policies) at head
`c22364beaa6ae55b620b600c6d8ffeb50fd144f0` (branch `auto-933`, develop base
`d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`). This note carries **no
`inventory-delta:` block**: it adds and removes no tests; the M8-E4 delta itself
(+12 cases) is already banked and recorded in
[`docs/testing/inventory-notes/0933-m8e4-escalation-destination-frontier.md`](inventory-notes/0933-m8e4-escalation-destination-frontier.md).

The prior repair attempt (`ff3d4feedf5b445b84faea2cba35d168`) died on a provider
timeout before committing anything, so this round re-derives the acceptance
evidence from scratch. The dispatch reported the merge-queue checks **green**
(31 `success` check-runs at PR head `be33b5cb1`), and no `check-*.log` verifier
artifacts were supplied with this job (`checks: []`), so every criterion below
was re-executed locally.

## Scope integrity of the branch

- `git diff --name-status d7fb3baa6..HEAD` = exactly the three PR #2082
  surfaces: `docs/research/904-uncertainty-calibration-abstention.md`,
  `docs/testing/inventory-notes/0933-m8e4-escalation-destination-frontier.md`,
  `packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py`.
- `git diff --numstat d7fb3baa6..HEAD -- quality/` is empty: the develop merge
  (`c22364bea`) drifted no per-identity ledger rows.
- The test module imports only stdlib + `pytest` — no `maistro` imports (M8
  guardrails 1–2: research artifact cannot become an authority).

## Acceptance criteria -> executed evidence

| Criterion (issue #933) | Evidence at this head |
| --- | --- |
| Calibrated policy improves expected outcome vs always answering | `pytest ...::TestEscalationPolicyDestinations::test_escalation_policy_evaluates_on_the_held_out_split` passes; direct computation: held-out policy EU **0.47** vs always-answer **0.20**, unsafe rate **0.13** vs **0.27**, escalation rate **0.33** (matches the research note verbatim). Answer-vs-defer counterpart: `test_threshold_dominates_always_answer`. |
| Thresholds × escalation destinations: stronger model / specialist Agent / verifier / HITL | `EscalationDestination` + `m8e_route_to_destination` + `m8e_escalation_frontier`; `m8e_destination_fixture()` carries all four classes; 12/12 `TestEscalationPolicyDestinations` cases pass (verbose run). |
| Measure: expected task utility, unsafe/incorrect rate, human-intervention rate, escalation cost/latency, unnecessary abstention | `EscalationPolicyPoint` fields `expected_utility`, `unsafe_action_rate` (wrong answers + expected escalation failures — `test_all_escalated_never_succeeding_destination_is_fully_unsafe`), `human_intervention_rate`, `escalation_cost`, `escalation_latency`, `unnecessary_escalation_rate`; defer-frontier `unnecessary_deferral_rate` in `TestAbstentionPolicy`. Hand-checked all-deferred and mixed-threshold points pin the arithmetic. |
| Threshold robustness under model drift | `m8e_apply_overconfidence_drift`; `test_drift_suppresses_escalation_when_scores_are_not_recalibrated` passes; direct computation reproduces the note: stale self-report HITL share **21% → 0%**, unsafe **18.5% → 29%**, while the recalibrated frontier is exactly invariant (escalation 0.335 → 0.335, unsafe 0.120 → 0.120). |
| Deliverable: decision-policy frontier + GRADUATE/INCUBATE/REJECT/WATCH disposition | `docs/research/904-uncertainty-calibration-abstention.md` records the destination-aware frontier and the **WATCH** disposition for #933 (honest: synthetic parameters only, no real-model corpus in deterministic CI). |
| Research policy cannot authorize actions outside canonical Warden/HITL/delegation controls | Frozen measurement dataclasses only (`test_policy_outputs_are_measurements_not_actions`, `test_escalation_outputs_are_measurements_not_actions`); no `maistro` imports; trust-boundary section of the research note; destinations are descriptions, never invocations. |
| Meaningful tests (assertions bind to behavior) | Out-of-tree mutation spot-check (worktree untouched): band-routing loop removed + `human_intervention` flag ignored → **5 of 12** destination cases fail, exactly as the inventory note claims (`test_bands_route_by_confidence_with_urgency_first`, both hand-checked frontier points, the variation-signal case, and the drift case). |

## Gates re-run at this head

| Gate (CI-exact arguments where applicable) | Result |
| --- | --- |
| `uv run pytest packages/maistro-rsi/tests/test_m8e_uncertainty_calibration_research.py -q` | 42 passed |
| `uv run pytest packages/maistro-rsi/tests -q` | 1335 passed, 4 skipped |
| `uv run ruff check .` / `uv run ruff format --check .` | clean |
| `python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory (the +12 delta is banked) |
| `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1326 reviewed identities -> 1326 findings (exit 0) |

## Residuals

- The disposition is **WATCH**, by design: all numbers above are synthetic
  fixture results validating the machinery; the leaf still needs the real
  held-out, operator-measured destination parameters (#915 cascade data) the
  benchmark procedure describes. No adoption is authorized by this round.
- The research-note per-number claims were re-derived this round and matched to
  the digit; the `AUROC 1.0 vs 0.0` disagreement-vs-self-report claim is pinned
  by `test_disagreement_can_be_the_better_error_predictor` (passing).
