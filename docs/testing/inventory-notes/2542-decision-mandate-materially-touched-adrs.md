---
inventory-delta:
  tests/: +39
---

# #2542 decision mandate: materially touched ADRs must close their own evidence gaps

Thirty-nine tests added to `tests/test_check_ac_state.py`; no test removed or
renamed; `tests/` count is otherwise unchanged.

## What the tests pin

Sixteen in `TestNormativeMateriality` pin the editorial/material boundary the
issue draws for a normative decision/contract: formatting, link churn,
renumbering and front-matter/administrative edits never fire; a typo-sized
repair (character edit distance ≤ 2) never fires; the modal-verb flip
(`may`→`must`), an inserted negation, and a deleted obligation always do; and
only `Decision`/`Contract`/`Interface`/`Requirements` sections are compared —
a wholesale `## Context` rewrite is not a changed decision. The review round
grew this class further: subsections of a normative section stay inside it
(ADR-038 carries its retry rule under `### 1. Retries`), and code spans and
fenced blocks keep their content verbatim — an operator reversal
(`!=`→`==`, the SPEC-247 shape) is material even though it is a
one-character edit under the typo budget, while a reflow, a
backtick-styling flip in either direction, and a ≤2-character fragment move
stay editorial, and the capped edit distance abandons once no row can come
back under budget.

Six in `TestGateWritePath` pin main's tail: the report lands after the
mandates so it carries `decision_traceability` (with its rows) beside the
measured aggregate; gate exit codes merge rather than mask; one base read
serves all three mandates and an unreadable base fails before any of them;
and `_head_text` reads the checkout when no caller text is supplied, reading
a missing file as empty.

Seventeen in `TestDecisionMandate` pin the mandate itself:

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
with this note's `+39` delta folded into the expected `tests/` count. All 151
tests in `tests/test_check_ac_state.py` pass (`uv run pytest
tests/test_check_ac_state.py -q`: 151 passed).

The review round (PR #2570 Codex findings) was repaired and re-proven:

- **exempt owned evidence** — a touched owned criterion carrying an
  `ac-state: unproven AC-N` marker previously read as `owned-evidence`
  (absence from `mandate_violations` is not proof). Reproduced with a
  planted rung-`declared` exempt criterion (exit 0 before the fix), fixed to
  require every owned touched criterion at the `reachable` rung, with the
  gap named in the row and the report (exit 1 after;
  `test_an_exempt_owned_criterion_is_not_owned_evidence`).
- **standing disposition vs status-only promotion** — a follow-up change
  promoting `status: Implemented` while a `decision-unproven` marker stands
  previously passed (no normative edits → no checks). Reproduced (exit 0),
  fixed: the mandate validates standing dispositions independently of the
  materiality diff (exit 1, `contradicted-disposition`;
  `test_a_standing_disposition_blocks_a_status_only_promotion`), with proof
  superseding a stale marker (`test_a_disposition_marked_and_proved_in_one_change_still_passes`).
- **operator reversal inside code** — `!=`→`==` in SPEC-247's fenced python
  contract was invisible (punctuation stripped) and also a one-character
  edit under the typo budget. Reproduced against the real corpus Decision
  (no edits detected), fixed: code spans and fenced blocks keep their content
  verbatim and get no typo forgiveness, while reflows and styling flips stay
  editorial (`test_an_operator_reversal_inside_code_is_material`,
  `test_an_operator_flip_inside_a_fenced_block_is_material`,
  `test_code_reflow_and_backtick_styling_stay_editorial`). Nested normative
  subsections (ADR-038's `### 1. Retries`) and qualified `implements:`
  references (`maistro-engine#ADR-002`) were the first two review findings;
  their fixes and tests were already on the branch and re-verified here.

The coverage gate that failed on the review round was reproduced locally with
CI's own checker and base — `uv run python scripts/check-diff-coverage.py
coverage.xml --base 547eb70afd64…` reported `FAIL: scripts/check_ac_state_impl.py:
89.3% of 225 changed lines (need 90%)` — and now passes: `ok: every measured
file this change touches is at or above 90% lines / 80% branch arcs`, measured
with the workflow's scripts producer over the nine suites that exercise
`check_ac_state_impl.py` (426 passed). The publish-set floor is unaffected:
this change touches no `packages/*` source.

The full CI gate was also executed against this branch with a live pg18
service and migrated schema, CI's exact invocation:
`check-ac-state.py --run-tests --ratchet --mandate 547eb70afd64…`. Result:
exit 0; measured `design_coverage` 44.7934% sits exactly on its banked floor
(87/167 taken decisions at zero); criterion, chain and decision mandates all
report OK (`decisions materially touched: 0`); the report carries
`decision_traceability` beside the measured aggregate (`measured: true`).

The planted candidate was re-run on both sides for exact before/after
negative evidence, in detached scratch worktrees at develop 547eb70afd and at
this HEAD (re-executed this round): a wholesale rewrite of ADR-002's Decision
(a taken ADR with `implements: []`), applied identically to both. At develop
every gate passes (exit 0) — that is the source gap. At HEAD the same plant
fails with exit 1, the decision mandate naming ADR-002 with the was/now diff.
Adding the explicit
`<!-- ac-state: decision-unproven ADR-002 - … -->` disposition (reason
included) to the same plant turns the run green again (exit 0,
`declared unproven, visibly: 1`). Note for reproducers: with
`RATCHET_BASE_REV` unset the grant provenance falls back to `origin/develop`;
set it to the mandate base as CI does, or a stale local `develop` ref can
fail the run on an unrelated #166 grant.
