---
name: verify-evolve
description: Run the maistro-evolve test suite (83 tests covering tournament selection, fitness, cycle detection, diversity, population, harness). Use when touching packages/maistro-evolve/.
---

Run the maistro-evolve tests:

```bash
PYTHONPATH=packages/maistro-core/src:packages/maistro-evolve/src pytest packages/maistro-evolve/tests/ -v
```

After the run:
1. Report pass/fail counts and flag any failures with the relevant module (tournament, fitness, cycle, diversity, mutate, crossover, harness, optimizer).
2. Note that maistro-evolve is NOT in the root pytest testpaths config, so it won't run with a bare `pytest` — this skill or explicit path is required.
3. If a passing run still surfaces something worth a closer look (a fitness score that looks off, a selection result that's surprising but not technically wrong), don't let the observation evaporate — start an exploratory session per `docs/EXPLORATORY-TESTING.md` and log it under `docs/exploratory-sessions/`.
