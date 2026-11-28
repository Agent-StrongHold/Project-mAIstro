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

## Unverified here (environmental)

`scripts/check-suite-inventory.py` cannot complete in this worktree:
`packages/maistro-ext-harness/tests` fails collection with
`ModuleNotFoundError: No module named 'maistro_ext_harness'` (package not
installed in the local uv env; unrelated to this change, which touches no
packaging). Collection of `tests/test_check_ac_state.py` itself is clean: 133
passed locally, +21 versus the previous 112-file state of the module.
