---
inventory-delta:
  tests/: +27
---
# claude-655-merge-latency-baseline-4c1e

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_measure_merge_latency.py` — 27 node IDs for the merge-queue
latency measurement behind `docs/ci/MERGE-LATENCY.md` (#654/#655).
Twenty-seven distinct test functions, none parametrised, so the node count
equals the function count. Seven of them exist because Codex's review of the
first push found real defects: the dequeue rate that counts abandoned PRs,
interpolated percentiles, success-only wall-clock, and the page-boundary
cohort exclusion (per-PR, because dropping only the boundary candidate makes
its PR look better).

The suite pins the arithmetic the way `test_measure_ci_cost.py` pins #161's:
the places a plausible implementation gives a wrong number. Three matter most
here — a requeue is a **new candidate SHA** under the same `pr-N`, and folding
it into the first candidate would hide exactly the re-execution the requeue
rate counts; a candidate with an unconcluded run must not contribute a
foreshortened wall-clock; and an ejected-then-abandoned PR has attempts but no
residency, because scoring it as zero would make the queue look faster the more
PRs it fails.

The network edge (`_get`, `collect`) and both `main` failure exits are covered
with monkeypatched fakes rather than left to the diff-coverage gate to find
bare — the gate's per-file floor applies to the whole new script, entry point
included.

Nothing was removed or rewritten.
