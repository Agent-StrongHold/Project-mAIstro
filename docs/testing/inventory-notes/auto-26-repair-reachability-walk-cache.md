---
inventory-delta:
  tests/: +1
---

# auto-26 repair — reachability walk cache (issue #26 / PR #1742)

Adds one test to the root suite:
`test_an_identical_second_walk_reparses_nothing` in
`tests/test_check_reachability.py`.

## What failed, and what the walk has to do with it

The merge-queue evaluation of this branch failed
`Coverage gate (publish-set floor + diff coverage)` — not on either coverage
number, but on the root-suite producer inside the `combine` step: two
reachability self-checks,
`test_new_unreachable_module_fails_the_gate` and
`test_module_becoming_reachable_fails_until_the_baseline_is_pruned`, both
exceeded their 30s `pytest-timeout` (CI run 37522612054:
`2 failed, 4629 passed ... in 996.89s`). The same gate had passed on this
branch's parent commit 38ebcadb4; the merge that produced 8c2f58eaa brought in
the extension-host-harness package and other trees, growing the module
universe the walk parses (now 1,342 production modules) past what the two
tests could finish inside the bound on a traced runner.

Each of those tests pays the full repository walk **twice** — once through
`unreachable_modules()` and once through `check.main()` — and every other
consumer paid it again per call: the remaining self-checks in the file, the
credential-authority and reachability-provenance gates, and
`check-reachability.py`'s own `main()`. Measured locally under CI-equivalent
`coverage run --branch --source=scripts` tracing, the two tests cost 17.8s
each bare; the CI runner multiplies that past 30s.

## The repair is structural, and this test pins it

`_reachability` is a pure function of its four immutable arguments
(`root`, `flat_apps`, `static_roots`, `dynamic_roots`; `FlatApp` is a frozen
dataclass), so the walk is now computed once per argument tuple
(`_reachability_walk`, `functools.cache`) and the public `_reachability`
returns copies of the cached dict/set — callers keep mutable results without
sharing mutable cache state. Nothing that varies between calls is cached:
`main()` reads `BASELINE` after walking, and the tests that vary it
monkeypatch that module attribute, not the tree; tests that need a different
tree pass a different `root`, which is a different cache entry.

Measured locally, the same two tests went from 17.8s to sub-second and the
whole `tests/test_check_reachability.py` file from 90.8s to 10.1s under the
same tracing; the full root-suite producer went from 644s to 457s.

The new test asserts the structural bound, not a wall clock: with the cache
cleared, one full walk parses at most one AST per discovered module, and an
identical second walk parses **nothing**. Counting `ast.parse` calls makes
the bound hold on any machine. Against the pre-fix code the test cannot pass
— there is no cache to clear, and the measured behavior there is 1,342 parses
for the first walk and 1,342 more for the identical second one (verified
against the pre-fix blob before repair: `parses_after_first=1342,
second_walk_added=1342`; post-fix `second_walk_added=0`).

## Count movement

`tests/` +1: the new bound test. No test was removed or renamed; the other
identities in `tests/test_check_reachability.py` are unchanged.
