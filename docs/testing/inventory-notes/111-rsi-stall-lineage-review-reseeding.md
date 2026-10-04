---
inventory-delta:
  packages/maistro-rsi/tests: +18
---
# 111 — RSI stall detection, lineage review, and reseeding (M5-B)

Adds one test module:

- `packages/maistro-rsi/tests/test_intervention.py` — 18 tests covering the
  new `maistro_rsi.intervention` policy (SPEC.md §11, intervention-1..7), the
  coordinator's stall fold-in (coordinator-6), and the autorun wiring
  (autorun-13..15):
  - `StallTracker` threshold validation, fire-once-at-N semantics, and resets;
  - the review context carrying the *full* root-to-failure lineage with
    evidence plus the archived promising candidates (older non-champion branch
    present; `archive_limit` bound);
  - `materially_distinct` dropping duplicates, tried-hypothesis rewords, and
    blanks while preserving seed bindings;
  - `intervene` reseeding from the archived candidate each direction names
    (falling back on None/unknown/ABANDONED seeds), `intervention_id`
    provenance artifacts, verbatim direction preservation, cost recording,
    subsequent-gain measurement, and the `ObjectiveParked` park after
    `park_after` gainless interventions;
  - `template_lineage_reviewer` + `InterventionConfig` validation;
  - coordinator-6: `htr_stall_detected` logged with the configured threshold,
    exactly one intervention per stall, no-policy behavior unchanged;
  - autorun-13/14: config→policy wiring with interventions accumulated on the
    result, and the `objective.parked` audit record as the backlog hand-off;
  - autorun-15: `make_llm_lineage_reviewer` gateway-failure degradation to the
    template reviewer and `SEED=<node_id>` parsing (honored for archived
    candidates, stripped otherwise).

No existing test was modified: the coordinator's new `policy` keyword is
opt-in and defaults to the previous behavior.
