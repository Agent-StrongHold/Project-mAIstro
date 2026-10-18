---
inventory-delta:
  tests/: +13
---
# Issue #1069 strict M1 closeout parity

Adds the fail-closed M1 closeout layer for the cross-product parity suite:

- `tests/cross_product_parity/harness.py`: the `ParityScenario`/`ScenarioExecution`
  closeout machinery (`execute_scenario`, `execute_scenario_sync`, `execute_closeout`)
  emits one machine-readable `M1_PARITY_EVIDENCE` JSON record per required scenario
  (EXECUTED/PASSED or FAILED; no BLOCKED-as-green state). The develop-side
  `MAISTRO_PARITY_STRICT` spelling and the closeout `MAISTRO_PARITY_MODE=m1-closeout`
  spelling are unified into one mode authority (`parity_mode()`), so
  `dependency_assessment` fails closed under either while the machinery keeps its
  per-scenario evidence contract via the non-raising `_assess_dependencies` core.
- `scripts/run-m1-closeout.py`: the named strict invocation; sets both spellings so
  early-return blockers, unavailable seams, and abstentions all fail the job.
- `.github/workflows/release.yml`: the `m1-closeout` job runs that invocation and
  `wheels`/`pypi`/`images` depend on it, so a release cannot proceed on abstained
  scenarios.

Test delta vs the develop-side suite (+13 in `tests/cross_product_parity/
test_cross_product_parity.py`; node-ID delta vs merge base 420d503d4 is
5549 -> 5562, re-measured after the develop-sync merge union):

- 3 closeout-machinery tests (kept from this branch's implementation, unconflicted
  in the merge): unavailable dependency emits `FAILED` evidence without invoking the
  producer; a source-ready scenario that abstains still fails in strict mode; the
  aggregate closeout reports every required scenario before raising.
- 4 strict-evidence tests (one per required scenario 1/2/3/6) drive the real
  required scenarios through the closeout machinery under distinct names so they
  compose with develop's activation contracts of the same scenarios; in development
  mode they tolerate named BLOCKED evidence, in strict mode they fail closed.
- 3 follow-up tests from this branch's later commits: the golden closeout must
  cover every manifest-required scenario; `MAISTRO_PARITY_STRICT=1` combined with
  a conflicting explicit `MAISTRO_PARITY_MODE` is rejected; the strict-spelling
  plus explicit `m1-closeout` combination stays a valid strict invocation.
- 3 success-path evidence tests (CI-repair round): an executed scenario emits a
  machine-readable `PASSED`/`executed:true` record (pinning the success half of
  the EXECUTED/PASSED-or-FAILED contract); the aggregate closeout report passes
  only after real execution (`CloseoutReport.passed`, `as_dict` payload); and a
  validator failure under strict mode is recorded as `FAILED` evidence with the
  exception named instead of crashing without a record.
