---
inventory-delta:
  packages/maistro-rsi/tests: +26
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

CI-repair round (radon D(22→C(17)) refactor + diff-coverage arcs), +8 more:

- the park path now checkpoints the triggering cycle's already-executed
  steps (`ObjectiveParked.steps`), asserted end-to-end: returned steps,
  snapshot statuses, and a resume that would not re-execute any executed
  node;
- the reviewer's degrade matrix is closed: a refused review context never
  reaches the gateway, refused *directions* fall back to the template
  reviewer with the refusal logged, and a directionless (blank/bullet-only)
  completion falls through without a spurious refusal;
- `parse_review_directions` edge cases: blank/bullet-only lines skipped and
  a bare `SEED=<id>` with no direction text dropped (the marker regex now
  makes that case reachable instead of emitting the marker as a hypothesis);
- recalled ledger entries are proven to be re-scanned at use time: a flagged
  entry is refused with its verdict flags logged, an entry whose scan has no
  verdict is refused with empty flags, and the admitted lesson flows on;
- `_checkpoint_steps` degenerate scans: an empty-insight node appends as
  unscanned (the ledger skips it) and a verdict-less scan still records the
  insight with its admission outcome.
