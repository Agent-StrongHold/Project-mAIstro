---
inventory-delta:
  packages/maistro-evolve/tests: +1
---
# auto-113-devskim-repair

CI-repair round for #113 (devskim check-run 111261555695 failed at head
119ba9b5): the run's single new alert was `archive.py:534` —
`random.Random(seed)` inside `RetentionGate.select_scenarios`, flagged by the
weak/non-cryptographic-RNG rule. The seed was SHA-256-derived, so the sampling
was already deterministic, but the flagged construct is gone now rather than
suppressed: the sampler ranks scenarios on
`sha256(scenario_set + "\0" + scenario)` and takes the first
`sample_size` names. Same contract (pure function of the proven set — two
evaluations of one population state sample the same scenarios), no process RNG
state, and the `import random` in `archive.py` is gone with it.

Added (test_archive.py):

- `test_sample_policy_does_not_degenerate_to_prefix_truncation` — pins the
  degenerate path where the keyed-digest sampler is replaced by plain
  `sorted(names)[:k]` truncation, which would bias every retention check
  toward early-alphabet scenarios and quietly stop re-checking the rest.
  (`select_scenarios` existing tests already pin determinism, declared size,
  subset validity, and the replay degeneration; this covers the one way the
  implementation could silently weaken while still "sampling".)

All other checks re-confirmed green this round with CI's exact arguments; no
test was removed or modified.
