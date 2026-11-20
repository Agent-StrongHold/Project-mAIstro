---
inventory-delta:
  packages/maistro-core/tests: +23
---
# m1-232-p5a-recovered-rediscovery

#232 P5a: recovery tick rediscovers typed RECOVERED Attempts after a crash
between physical reclaim and first reconciliation; consumption looks past
typed RECOVERED only (no string-prefix look-past).

- `test_interrupted_reclaim_characterization.py` **+4** (memory+sqlite × 2)
- `test_interrupted_reclaim_rediscovery.py` **+18** spine-parametrized
  (retry-owned ×3, spoofed prefix, newer Attempt, sibling park × memory /
  sqlite / postgres)
- `test_parked_run_resume.py` **+1** spoofed look-past refusal
