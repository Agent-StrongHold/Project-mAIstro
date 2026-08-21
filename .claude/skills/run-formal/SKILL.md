---
name: run-formal
description: Run the Hypothesis property-based conformance tests under formal/. These cover security invariants I1-I22+ and are NOT part of regular CI (they run in formal-conformance.yml). Use before touching security, auth, warden, sentinel, PII, or quota code.
---

Run the formal property-based conformance test suite:

```bash
PYTHONPATH=packages/maistro-core/src pytest formal/ -v
```

If the suite is slow or you want to target a specific invariant model, pass a keyword filter:

```bash
PYTHONPATH=packages/maistro-core/src pytest formal/ -v -k "<model_name>"
```

After the run:
1. Report how many tests passed/failed and which invariants (I1–I22+) were exercised.
2. If any failed, show the Hypothesis shrunk counterexample and identify which source file likely caused the regression.
3. Remind the user that formal tests are not run in regular CI — a green regular test suite does not mean formal invariants are satisfied.
4. If a passing run still surfaces behavior worth a closer look (output that "looks wrong" but technically satisfies the property, a flaky-seeming case, an untested edge the model didn't generate), don't let the observation evaporate — start an exploratory session per `docs/EXPLORATORY-TESTING.md` and log it under `docs/exploratory-sessions/`.
