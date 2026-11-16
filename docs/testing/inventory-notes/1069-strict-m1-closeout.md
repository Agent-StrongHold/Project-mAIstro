---
inventory-delta:
  tests/: +17
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

CI-repair round at 2abb645a2 (hosted `test` + `Coverage gate` failures):

- `tests/test_check_compliance.py::test_release_workflow_resolves_and_preserves_evidence_before_build`
  previously asserted `jobs["wheels"]["needs"] == "guard"` verbatim, so adding
  the `m1-closeout` job to the release chain reds both the `test` job and the
  coverage gate (whose `scripts` producer re-runs the same root suite). The test
  now pins the strengthened contract instead: `wheels`/`pypi`/`images` each need
  `guard` (evidence resolved before build — the property the test has always
  checked) and `m1-closeout` (an abstained scenario cannot ship). No node count
  change: the assertion body was rewritten, not duplicated.
- `tests/test_run_m1_closeout.py` (+3): the named strict invocation is now
  executed in process with the subprocess boundary stubbed — it must set both
  strict spellings (`MAISTRO_PARITY_MODE=m1-closeout` and
  `MAISTRO_PARITY_STRICT=1`), run the real parity suite path, propagate a
  failing suite exit code without `check=True` swallowing it, and run under its
  `__main__` guard (`runpy.run_path(..., run_name="__main__")`, the repo
  convention for CI-shelled scripts). This also gives the new `scripts/` file
  the measured coverage the diff-coverage gate requires of a changed file under
  a measured root.
- `tests/cross_product_parity/test_cross_product_parity.py` (+1): a strict
  PASSED now requires real observation evidence and a named invariant. Codex
  review (PR #2210) found that the observation was required only when a
  validator was configured, so a degenerate `ScenarioExecution()` (no
  observation, no `validate_observation`) was recorded as `executed=true,
  PASSED` even in strict release mode — proven by reproduction before the fix.
  The harness now requires a non-null observation for PASSED in every mode and
  an observation invariant in strict mode; development mode stays lenient per
  the two-mode contract. The new test pins all three behaviors, and
  `test_closeout_report_passes_only_after_real_execution` gained the invariant
  it now needs to stay a valid green closeout.
