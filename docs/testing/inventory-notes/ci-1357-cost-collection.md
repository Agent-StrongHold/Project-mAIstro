---
inventory-delta:
  tests/: +43
---

# Complete observed CI-cost collection (#1357 / #160 / #161)

Adds 43 cases in `tests/test_ci_cost_collection.py`; no existing test is
removed. The existing duration, aggregation, historical #161 split, HTTP-fetch
and table-rendering functions retain identical ASTs to develop@8bfd3590.

The collector now requests every job attempt (`filter=all`), follows every
reported workflow/job page, retains run/job identities, and refuses incomplete,
malformed, changing, capped or duplicate listings. In-flight jobs cannot become
zero-cost completed work. A manual measurement may explicitly exclude its own
Runner cost execution; the path/head identity is validated and the exclusion
is printed. It cannot exclude an ordinary CI run or hide another pending run.

Tests replace the external API boundary, not the collector or arithmetic.
A failed attempt plus its successful retry contributes both durations. Tests
exercise 205 jobs and 101 workflows, malformed evidence, pending work, duplicate
identities, API limits and the self-measurement boundary. Two cases execute the
actual Runner cost workflow shell with a controlled process boundary, proving
inputs remain arguments and that the current measurement run is identified.

Focused local validation: 43 passed under Python 3.13.5; 94% combined statement
and branch coverage of the entire existing script. All new collector-region
statements were exercised. This is not a claim of full repository CI, a live
new-version Actions API measurement, or a measured compute saving.

The manual workflow remains manual-only and read-only. No required check,
coverage threshold, producer, test profile, service leg or production behavior
is removed. The historical #161 before/after calculation remains specific to
that trigger change; it is not repurposed as the saving from this optimization.

API basis: GitHub's Actions workflow-jobs documentation defines default
`filter=latest` versus `filter=all`; its workflow-runs documentation defines
the 1,000-result cap for filtered searches. These are collector constraints,
not reasons to omit old attempts or report partial evidence as a complete cost.
