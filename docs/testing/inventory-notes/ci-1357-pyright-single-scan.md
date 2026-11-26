---
inventory-delta:
  tests/: +63
---

# Single-scan Pyright evidence (#1357 / #160)

Adds 63 collected cases in `tests/test_check_pyright_report.py`. They preserve
the existing error-count allowance, retain warning/information diagnostics,
and reject fatal analyzer exits, empty scans, inconsistent counts, duplicate
JSON keys, missing reports and malformed evidence.

Five cases execute the actual shell extracted from `quality.yml` under Bash
with a controlled analyzer boundary. They assert exactly one analysis call,
the unchanged source arguments and baseline, the complete displayed report,
and the propagated final exit code. The report gate itself is real, not mocked.

The focused suite was run locally against the full fetched workflow, with
100% statement and branch coverage of the new report consumer. This is focused
implementation evidence, not a claim that the full repository battery,
Pyright analysis of the repository, or the merge-group candidate has passed.
No existing test, source file, dependency profile, workflow context, threshold,
service-backed leg or event trigger is removed by this slice.
