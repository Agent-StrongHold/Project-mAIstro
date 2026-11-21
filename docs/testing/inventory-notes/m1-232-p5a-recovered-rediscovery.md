---
inventory-delta:
  packages/maistro-core/tests: +4
---
# m1-232-p5a-recovered-rediscovery

#232 P5a: recovery tick rediscovers typed RECOVERED Attempts after a crash
between physical reclaim and first reconciliation; consumption looks past
typed RECOVERED only (no string-prefix look-past).

Net **+4** against the develop base. An earlier revision of this note recorded
the three files' collected totals (18/4/1) instead of their deltas; the
suite-inventory gate caught the +19 over-claim and this note records the
measured movement, re-measured at the develop tip (8f4806be, #2430 round)
during the #2427 repair round: the three files below collect 63 → 67 (**+4**).
The whole-suite movement (18716 → 18775) additionally carries the stacked
P4a/P4b test deltas from #2424/#2425, which ride in this branch's history and
are documented by their own inventory notes — they are not P5a movement:

- `test_interrupted_reclaim_rediscovery.py` **+3** — one new
  spine-parametrized case, `test_spoofed_reclaim_prefix_without_typed_cause_is_not_rediscovered`
  (memory / sqlite / postgres). The retry-owned ×3, newer-Attempt, and
  parks-only-its-own-node cases already existed at the base; the tick's
  assertions were retargeted from string-prefix `is_reclaimed_attempt` to
  typed `is_typed_recovered_attempt` in place.
- `test_interrupted_reclaim_characterization.py` **+0** — the two existing
  memory+sqlite cases were strengthened in place (typed-RECOVERED assertion,
  disposition-park contract), count-neutral.
- `test_parked_run_resume.py` **+1** — spoofed reclaim error text is not
  looked past when resuming a parked run.
