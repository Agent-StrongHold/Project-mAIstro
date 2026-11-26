---
inventory-delta:
  packages/maistro-rsi/tests: +1
---
# auto-302-ccdf

One test added to `packages/maistro-rsi/tests/test_local_loop.py` while
resolving the develop sync conflict for #302 (quarantine + signed approval
before RSI promotion).

`test_candidate_touching_the_loop_itself_is_vetoed_before_scoring` pins the
layered containment the merge produced: develop's #109 evaluator-oracle
integrity veto and the #302 promotion gate now both sit in front of the
`rsi-baseline` fast-forward. A candidate that edits the promotion machinery
itself (`maistro_rsi/local_loop.py`) is oracle surface, so the #109 veto
refuses it before scoring — it never reaches the promotion gate at all. The
test proves that path leaves the baseline unmoved and names the veto in the
cycle note.

Two sibling tests were retargeted from `maistro_rsi/local_loop.py` to a
sensitive-but-not-oracle path (`maistro/security/warden/detector.py`) so they
keep exercising the gate they name: the quarantine refusal without approval,
and the full signed-approval promotion path. `test_candidate_cannot_self_score_through_an_oracle_rewrite`
now asserts the #109 veto refusal (note + `tests_passed=False`) instead of the
gate refusal — the same adversarial guarantee (a candidate cannot self-score
through an oracle rewrite) enforced one layer earlier, with the modified
oracle never executed. Net: +1 test, no test lost.
