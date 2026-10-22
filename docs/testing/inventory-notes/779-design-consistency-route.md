---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# Design Studio consistency inspection route (#779)

Adds `packages/hive-conductor/backend/tests/test_design_consistency_route.py`:
8 tests for `POST /v1/design/projects/{id}/consistency`, the Design Studio's
synchronous inspection surface over the same pure evaluator the canonical
graph node `design.consistency_eval` runs inside a Run.

Route-relevant acceptance mapping (issue #779):

- a planted Persona violation returns a failed evaluation whose refinement
  names exactly the affected branch (local root cause, no unrelated targets);
- a shared factual contradiction is rooted in the shared decision and names
  every consumer — impact from real `consumes` edges;
- a locked accepted artifact is reported as a refinement target with
  `requires_unlock`, the response carries no rewritten content and the
  caller's snapshot is unchanged (proposal, never mutation);
- the result cites the exact brief version, goal revision, per-decision and
  per-artifact versions and evidence ids it evaluated;
- the same snapshot yields the same interpretable verdict across calls
  (identical findings/dimensions/provenance modulo the evaluation's own
  instance identities), so stored results stay interpretable after edits;
- a consistent family passes with no refinement proposal;
- a snapshot naming a different project than the path is refused (400),
  mirroring the graph node's canonical-provenance guard;
- an unready design service answers 503 with its recorded cause.

Also makes `maistro_design.consistency` reachable from a production entry
point (`routes.design` is a hive-conductor dynamic root), which replaces the
repair-round reachability-baseline entry that could not carry a prior landed
`reachability` authorization (the two-merge rule); the baseline entry is
removed again.
