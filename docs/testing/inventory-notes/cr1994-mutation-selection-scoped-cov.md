---
inventory-delta:
  tests/: +20
---
# cr1994-mutation-selection-scoped-cov

Two additions in `tests/test_mutation_select_tests.py`; nothing removed. They
pin the root cause of the #1994 CI mutation-gate failure: the selector's
pytest argv carried pytest-cov's bare `--cov` ("record everything") alongside
its own `--cov=<dir>`, and the bare flag wins — so a test inside the scope
that imports a scratch module and deletes it before the run ends (the
extension lifecycle proof does exactly this) left the coverage data file
referencing a vanished path, and `coverage json --show-contexts` died with
"No source for code" before any selection could be produced. The gate never
reached the mutants; the debt was the tooling, not governance.

**`TestTheMeasuredScopeIsTheDeclaredSource::test_the_pytest_run_is_scoped_and_never_records_everything`.**
Asserts the selector's own argv contract: no bare `--cov`, exactly one
scoped `--cov=<source dir>`, and `coverage json` carries `--ignore-errors`.
Fails against the pre-fix argv, which passes both the bare flag and omits
the ignore.

**`TestTheMeasuredScopeIsTheDeclaredSource::test_an_ephemeral_module_deleted_by_the_suite_does_not_break_selection`.**
The real failure, end to end: a real pytest run whose suite imports a
scratch module and `rmtree`s it mid-run. Under the old argv `coverage json`
red with "No source for code"; under the fixed argv selection completes and
still attributes the killing test. `--ignore-errors` cannot mask a lost
critical source: a report with no entry for the target file still fails
`_coverage_file_entry`.

## PR-gate budget repair round (merge of origin/develop c9636e99f1 + mutation.yml cap)

The selection-scoping fix above removed the bare-`--cov` crash, but the gate
still starved: run 45645094537 at PR head 5de7d17254 was killed with
"The job has exceeded the maximum execution time of 45m0s" 25m into
`mutation_pr_gate.py`, inside `select()` — and the step log shows zero
selection output before the cancel. Selection for this PR's one critical
overlap, `privilege.py`, re-runs the whole core suite under coverage
(~30m on CI; run 45574782108 step 08:16:44Z→08:46:57Z), because the
production dispatch (`resolve_script_tests(...) or resolve_package_tests(...)`,
mutation_critical.py) widens privilege.py to bare `packages/maistro-core/tests`
— no `tests/maistro/test_privilege.py` mirror exists. Other PRs' mutation runs
finish in ~15-25m because their critical overlaps resolve to narrow scopes.

Repair, evidence-backed and non-weakening (pass/fail logic, critical list,
fail-closed behaviors untouched):

- `.github/workflows/mutation.yml` pr-gate `timeout-minutes: 45` → `150`,
  with the measured numbers cited in place. 150 = widest-scope selection
  (~30m) + collection + a nightly-shard-scale mutation phase (packets get
  60m each) + cold-runner overhead, with headroom so the required producer
  emits a verdict instead of a permanent CANCELLED (`gates-ran` stayed red
  because it never observed a completed mutation run on this PR).
- `tests/test_mutation_targets.py` (+2, class
  `TestPrGateBudgetCoversTheWidestMappedScope`):
  `test_at_least_one_critical_source_widens_to_a_whole_suite_directory` pins
  the widening assumption through the production dispatch (fails if a mirror
  ever de-widens privilege.py, telling the author to re-measure the floor),
  and `test_the_pr_gate_budget_is_not_starved_below_the_measured_floor`
  parses the shipped workflow and fails against the 45m cap that cancelled
  #1994's gate (verified: the predicate fails on the pre-repair file at
  merge commit 2ce345573a, passes at 150).

Develop sync: origin/develop tip `c9636e99f1` (abandoned-Attempt recovery
activation) merged conflict-free; `quality/` numstat vs origin/develop shows
only this branch's two intended files and the vulture multiset row count is
identical (15 = 15). Gates at the merged head: ruff check + format clean,
root + server inventory gates ok, principal-identity ratchet "4 tolerated →
0 current, none new", mutation governance validate ok, issue test paths
(privilege, principal-identity fitness, server auth) 71 passed.

## Sixteenth-round repair: selection memory + operator gap (head 9146009b97 + this commit)

The gate at CI head 9146009b97 (run 45659598032 / job 139365521685,
17:09→18:12Z = 63m under the new 150m budget) was still red — because the
budget was never the binding resource. Two root causes, both reproduced
locally at the exact head and both fixed without touching the gate's
pass/fail logic, critical list, baselines, or fail-closed behaviors:

**1. Selection memory (the actual CI red).** `select()` produced its per-test
attribution from `coverage json --show-contexts` over a whole-package scope.
With `dynamic_context = test_function`, that report serializes every measured
line of every file once per test that ran it: for the privilege.py selection
scope (bare `packages/maistro-core/tests`, ~19k tests) the report reached
~4.8GB on this machine (prior rounds' killed `mutation-select-*` temp dirs
carried exactly such files, with no `TemporaryDirectory` cleanup — the OOM
signature), and its parse outgrows a 16GB CI runner. Run 44700198260's step
log already showed `coverage json --show-contexts` exiting 1 with the data
file successfully written — the report step is the killer, not the trace.
Fix: the report step no longer requests contexts (executed/missing lines
still come from it, `--ignore-errors` retained, argv contract still pinned);
per-line contexts are read straight from the coverage data file via
`CoverageData.contexts_by_lineno`, verified line-for-line equivalent to the
JSON report (same names, same import-time empty-string contexts) on real runs.
`scripts/mutation_select_tests.py` only; the pytest argv, its dir scoping, and
every verdict rule are untouched.

**2. The operator gap (exposed once selection completes).** The changed
critical lines of privilege.py are the rename `_SubsystemIdentity` →
`_SubsystemCredential`: 117 (class stmt) and 394 (def stmt) execute only at
import time — excluded by the selector — and 395
(`return _SubsystemCredential(role="user", ...)`)'s only runtime tokens are a
constructor call and two string literals. Cosmic-ray's core provider has no
string mutator: the diff-scope intersection check (pinned fail-closed:
"zero mutants is a configuration error, not a pass") would have failed the
gate on any such rename, forever. Fix: an in-repo provider registering the
standard empty-string mutator through the same stevedore group cosmic-ray's
own `core` provider uses
(`packages/maistro-core/src/maistro/mutation_operator_provider.py`, entry
point in packages/maistro-core/pyproject.toml). This strictly ADDS
mutational power: privilege.py enumerates 363 mutants instead of 314, the
changed line is actually scored — and the existing heartbeat test kills its
mutant (1/1 adjusted = 100%). Cache correctness is preserved by folding the
registered operator set into `tool_fingerprint()` (a result cached before an
operator landed can never be accepted for a session enumerating different
mutants). Reachability roots the module as an entry-point surface (the
`maistro_registry.cli` precedent); it sits at maistro/ top level so rooting
it does not execute maistro.testing's __init__ and reclassify its
test-support imports. No vulture or reachability ledger edits were needed:
the provider's classes and contract methods are referenced by its own
fail-fast registration check and `__all__`, and no previously-unreachable
module becomes reachable.

**End-to-end evidence (this machine, CI-exact steps from mutation.yml):**
targets → `privilege.py → packages/maistro-core/tests`; trusted baseline from
merge-base c9636e99f1 (entries empty → report-only policy); diff artifact;
`mutation_pr_gate.py --scope changed` → selection OK, 363 enumerated /
362 filtered / **1 in-scope mutant executed and killed** (adjusted 1/1 =
100%), decision `report-only`, **exit 0** — the workflow job now emits a
verdict instead of dying in selection.

**Tests (+16):** `tests/test_mutation_operator_provider.py` (+13): the
entry-point wiring pin (`operator_names()` must contain
`maistro/ReplaceStringWithEmpty`), the provider contract, mutation surface
(runtime strings mutated; docstrings, f-string parts, empty literals never),
and the fingerprint operator-set pin. `tests/test_mutation_select_tests.py`
(+3 net): the contexts-from-data-file seam (fixtures write real data files),
a `--show-contexts` regression pin, a repo-relative-source resolution pin;
all verified failing against the pre-fix selector (8 failures on a HEAD
tree export).

