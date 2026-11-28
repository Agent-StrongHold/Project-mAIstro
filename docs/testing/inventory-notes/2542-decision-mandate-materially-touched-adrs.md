---
inventory-delta:
  tests/: +21
---

# #2542 decision mandate: materially touched ADRs must close their own evidence gaps

Twenty-one tests added to `tests/test_check_ac_state.py`; no test removed or
renamed; `tests/` count is otherwise unchanged.

## What the tests pin

Eight in `TestNormativeMateriality` pin the editorial/material boundary the
issue draws for a normative decision/contract: formatting, link churn,
renumbering and front-matter/administrative edits never fire; a typo-sized
repair (character edit distance ≤ 2) never fires; the modal-verb flip
(`may`→`must`), an inserted negation, and a deleted obligation always do; and
only `Decision`/`Contract`/`Interface`/`Requirements` sections are compared —
a wholesale `## Context` rewrite is not a changed decision.

Thirteen in `TestDecisionMandate` pin the mandate itself:

- the planted regression the issue verified — an already-uncovered taken ADR
  (`ADR-002`, `implements: []`, no own criteria) materially rewritten — now
  fails the gate (before this change it passed both existing mandates; the
  planted before-run is recorded in the change description);
- an editorial-only touch of the same document passes;
- unrelated debt reduction (a proven criterion on a spec implementing a
  *different* ADR) cannot pay for the rewritten decision;
- owned proven evidence (a touched, reachable criterion on a spec whose
  `implements:` names the touched ADR) closes the gap;
- a marker without a passing test (owned criterion stopping at `covered`) is
  not evidence — the mandate still fails;
- a valid `decision-unproven` disposition (reason mandatory, naming the
  document) closes the gap; a reasonless marker, a marker naming another
  document, and a disposition under `status: Implemented` do not;
- a disposition cannot ride on a ticked-but-unproven owned criterion (row
  reads `unproven` and the criterion surfaces through the mandate violations);
- documents added or removed by the change are not this mandate's (the chain
  and criterion mandates govern them), and an untouched document passes.

## Re-validation evidence (executed, PG-backed)

An earlier run recorded this suite as unverifiable locally because
`scripts/check-suite-inventory.py` failed on a `maistro_ext_harness` import.
That no longer holds: `uv run python scripts/check-suite-inventory.py`
completes here and passes — `ok: 21 suite(s) match the recorded inventory`,
with this note's `+21` delta folded into the expected `tests/` count. All 133
tests in `tests/test_check_ac_state.py` pass (`uv run pytest
tests/test_check_ac_state.py -q`: 133 passed).

The full CI gate was also executed against this branch with a live pg18
service and migrated schema, CI's exact invocation:
`check-ac-state.py --run-tests --ratchet --mandate 547eb70afd64…`. Result:
exit 0; measured `design_coverage` 44.7934% sits exactly on its banked floor
(87/167 taken decisions at zero); criterion, chain and decision mandates all
report OK (`decisions materially touched: 0`); the report carries
`decision_traceability` beside the measured aggregate.

The planted candidate was re-run on both sides for exact before/after
negative evidence: a wholesale rewrite of ADR-002's Decision (a taken,
uncovered ADR — `specs: []`, no criteria), applied identically to develop
547eb70afd and to this HEAD. At develop every gate passes (exit 0) — that is
the source gap. At HEAD the same plant fails with exit 1, the decision
mandate naming ADR-002 with the was/now diff. Adding the explicit
`<!-- ac-state: decision-unproven ADR-002 - … -->` disposition (reason
included) to the same plant turns the run green again (exit 0,
`declared unproven, visibly: 1`). Note for reproducers: with
`RATCHET_BASE_REV` unset the grant provenance falls back to `origin/develop`;
set it to the mandate base as CI does, or a stale local `develop` ref can
fail the run on an unrelated #166 grant.
