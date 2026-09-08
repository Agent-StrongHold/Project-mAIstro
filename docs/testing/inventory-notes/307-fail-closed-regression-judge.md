---
inventory-delta:
  packages/maistro-rsi/tests: +15
---

# 307 fail-closed regression judge

Fifteen new tests for the fail-closed regression-judge posture (#307),
all additions, no removals or renames:

- `test_regression_judge.py` (+6, rewritten around `judge_regression_verdict`):
  empty diff passes without an LLM call; below-threshold reply is "reject";
  above-threshold is "pass"; out-of-range score clamps; JSON embedded in prose
  is extracted; gateway raise / timeout / malformed JSON / missing score key /
  non-numeric score / non-dict JSON each yield status "unavailable", score
  None, and the right cause ("gateway_error", "timeout", "unparsable_reply");
  a 3x-cap diff is "oversized_diff" without calling the LLM while a
  two-thirds-retained diff is still judged.
- `test_candidate_fitness.py` (+2 net; 3 rewritten from tuple inputs to
  `JudgeVerdict`): unavailable verdict fails the `no_flagged_regression` gate
  with the cause in the reason and `detail["score"] is None`; every cause
  class fails the gate; reject/pass behavior preserved.
- `test_local_loop.py` (+4): `_judge_regression` fails closed on a raising
  gateway and on a construction failure; a stubbed ruling passes through;
  end-to-end `evaluate_candidate` does not accept a candidate whose judge
  came back unavailable.
- `test_promotion_review.py` (+2): `extract_features` stores judge_score None
  (never 0.7); a None feature contributes nothing and learns nothing;
  `explain_prediction` handles a None-valued feature.
- `test_review_promotions.py` (+1): an unavailable-judge promotion's flagged
  review evidence records `features.judge_score: null`, not 0.7.

Verified +15 = collected (666) vs recorded (651); every suite besides
`packages/maistro-rsi/tests` unchanged.
