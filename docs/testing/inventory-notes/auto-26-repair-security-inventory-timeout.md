---
inventory-delta:
  tests/: +1
---

# auto-26 repair — security-inventory gate runtime (issue #26 / PR #1742)

Adds one test to the root suite: `test_recomputing_every_counted_claim_parses_the_core_census_once`
in `tests/test_check_security_inventory.py`.

## What failed, and what the count has to do with it

The merge-queue evaluation of this branch failed
`Coverage gate (publish-set floor + diff coverage)` — not on either coverage
number, but on the root-suite producer inside the `combine` step:
`tests/test_check_security_inventory.py::test_the_shipped_document_passes`
exceeded its 30s `pytest-timeout` (CI run 37292468211). The self-check runs
`check-security-inventory.py` over the whole tree under `coverage run --branch
--source=scripts`, and its runtime scales with the repository. This branch
added the corpus-aware retrieval package under
`packages/maistro-registry/src/` — one of the trees that gate walks — and
pushed a test that already measured **24.93s locally under CI-equivalent
tracing** over the line on a slower runner.

## The repair is structural, and this test pins it

Profiling `main()` showed the census
(`_outbound_fetch_census`) fully re-parsing maistro-core once **per counted
claim** (five parses per run), and `_unpooled_fetch_modules` re-reading and
re-parsing every census member again for its classification. The repair parses
the core census exactly once per process (`_core_fetch_census`, `functools.cache`)
and projects both public figures from it; measured locally, `main()` went from
12.1s to 5.5s bare and the timed-out test from 24.93s to **11.26s** under the
same coverage tracing.

The new test asserts the structural bound, not a wall clock: recomputing all
four counted-claim figures parses at most one AST per file under `_CORE_SRC`.
Against the pre-fix code the same four calls perform 3,591 parses for 705
files — the bound fails there, so the regression this repair fixed cannot
return silently. Roots that tests deliberately monkeypatch (`ROOT`,
`_REPO_PRODUCTION_ROOTS`, `_SIBLING_SRC_ROOTS`) stay outside the cache; only
the census's `_CORE_SRC` input is cached, and no test rewrites maistro-core
between calls.

## Count movement

`tests/` +1: the new bound test. No test was removed or renamed; the other 48
identities in the file are unchanged.
