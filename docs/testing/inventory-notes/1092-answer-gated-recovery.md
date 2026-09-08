---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 1092-answer-gated-recovery

Six new tests in `tests/graph/durable_runs/test_answer_gated_recovery.py`
(4 sync + 2 async), all additions, no removals:

- system-owned answer wait redispatches when a durable answer exists
- system-owned answer wait does not redispatch on elapsed time alone
- human answer wait still uses durable answer evidence
- elapsed timer wait still redispatches (+ async variants)

Verified +6 = collected (9456) vs recorded (9450); every suite besides
`packages/maistro-core/tests` unchanged.
