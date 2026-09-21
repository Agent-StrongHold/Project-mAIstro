---
inventory-delta:
  packages/maistro-core/tests: +7
---
# 1092-answer-gated-recovery

Seven new tests in `tests/graph/durable_runs/test_answer_gated_recovery.py`
(4 sync + 2 async recovery tests, plus 1 covering the unknown-pause-reason
fallthrough in `_requires_continuation_redispatch`), all additions,
no removals:

- system-owned answer wait redispatches when a durable answer exists
- system-owned answer wait does not redispatch on elapsed time alone
- human answer wait still uses durable answer evidence
- elapsed timer wait still redispatches (+ async variants)

Verified +7 = collected (9457) vs recorded (9450); every suite besides
`packages/maistro-core/tests` unchanged.
