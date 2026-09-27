---
inventory-delta:
  tests/: +55
---

# Head-attributed CI-cost collection (#1357 / #160 / #161)

Adds 55 cases in `tests/test_ci_cost_collection.py`; no existing test is
removed. The existing duration arithmetic, aggregation, historical #161 split
and HTTP-fetch functions retain identical ASTs to develop@8bfd3590. Rendering
now labels the result HEAD-ATTRIBUTED SUBTOTAL, not full candidate/fleet cost.

The collector requests every job attempt (`filter=all`), follows every
reported workflow/job page, retains run/job identities, and refuses incomplete,
malformed, changing, capped or duplicate listings. In-flight jobs cannot become
zero-cost completed work. Backwards timestamps are rejected for jobs that ran;
the existing documented skipped-job timestamp exception remains.

A manual measurement may explicitly exclude its own currently active Runner
cost execution, requiring matching path, head, workflow_dispatch event,
in_progress state and GITHUB_RUN_ID. The exclusion is printed. Completed
historical reporters, ordinary CI runs, wrong heads and other runtime IDs
cannot use that self-wait exception. Other pending work remains incomplete.

Tests replace the external API boundary, not the collector or arithmetic.
A failed attempt plus its successful retry contributes both durations. Tests
exercise 205 jobs and 101 workflows, malformed evidence, pending work, duplicate
identities, API limits and the self-measurement boundary. Two cases execute the
actual Runner cost workflow shell with a controlled process boundary, proving
inputs remain arguments and that the current measurement run is identified.

The review follow-up adds twelve cases for backwards timings, skipped-job
parity, active/current manual measurement identity and explicit CLI disclosure
that default-branch workflow_run publishers such as Gates Ran are outside the
head query. Their costs are NOT zero or included: broader candidate-attribution
and fleet-cost measurement remain open under the #1357 audit. These head-only
figures must not be used as a claim of total CI savings.

Focused local validation: 55 passed under Python 3.13.5; 94% combined statement
and branch coverage of the entire existing script. All new collector-region
statements were exercised. This is not a claim of full repository CI, a live
new-version Actions API measurement, or a measured compute saving.

The manual workflow remains manual-only and read-only. No required check,
coverage threshold, producer, test profile, service leg or production behavior
is removed. The historical #161 before/after arithmetic remains specific to
that trigger change and shares the explicitly limited head-attribution scope;
it is not repurposed as the saving from this optimization.

API basis: GitHub's Actions workflow-jobs documentation defines default
`filter=latest` versus `filter=all`; its workflow-runs documentation defines
the 1,000-result cap for filtered searches. These are collector constraints,
not reasons to omit old attempts or report partial evidence as a full cost.
