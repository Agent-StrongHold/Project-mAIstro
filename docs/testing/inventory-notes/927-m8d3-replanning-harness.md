---
inventory-delta:
  packages/maistro-rsi/tests: +46
---
# 927 M8-D3: observation-driven replanning benchmark harness (+46)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #927 (epic #903 M8-D, initiative #879) asked for an evaluation of
observation-driven replanning after failures, surprises, and changed constraints. No
experiment on real MAIstro workloads exists — the deterministic CI has no live
providers, tools, or capability authorities, and no corpus of representative Goal
executions with injected surprises — so the research record
(`docs/research/927-observation-driven-replanning.md`) registers WATCH and this change
adds the reproducible benchmark machinery the issue's measure list demands, as one
self-contained test module in `packages/maistro-rsi/tests/`
(`test_m8d3_replanning_benchmark_research.py`, +46 node IDs).

The module is deliberately test-side and imports no maistro module (asserted via AST):
it is research evidence, not product code (M8 guardrails 1-2), so no vulture/reachability
identities change. The 46 cases validate the accounting and the policy mechanics on
deterministic, hand-checked fixtures: the six surprise injections on a scheduled world
clock (provider outage, changed artifact, failed tool, denied capability, stale
assumption, newly satisfied subgoal), the three policies on one shared sequential NodeRun
spine (no-replan as the canonical retry-only shape, local repair, full replan with a
deterministic alternate-substituting planner), and the issue's full measure list with
exact-unit assertions — the blind baseline completing while shipping falsified derivations
(2 violation edges on the changed-artifact fixture, an assumption-violating output on the
stale-assumption fixture), local repair dominating the blind baseline (3/6 clean at 34
units vs 1/6 at 44), full replan buying the two structural recoveries through declared
alternates (5/6 clean at 48 units, ~41% over local repair) while degenerating to local
repair plus a planner fee on data-freshness surprises, the hot-world fixture thrashing an
unbounded replanner (5 same-structure replans, 21 units) until the oscillation guard
stops it loudly with the budget named, capability denial never re-attempted by
observation-aware policies while blind denial re-attempts are counted, sunk-spend
accounting (failed attempts and failed replans pay in full), reuse counting for skipped
externally satisfied subgoals, the provenance walk naming each falsified edge exactly
once, and the evidence-only contract itself (advisory marker, frozen records,
measurement-only outputs, no maistro imports, empty/duplicate/negative-budget rejection,
planner cycle rejection). Four mutation checks (blind assumption judgment, denial
requeue, free replans, dirty recoveries) each fail the test that names them.
