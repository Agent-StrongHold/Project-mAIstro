---
inventory-delta:
  packages/maistro-core/tests: +17
---

# 1191 — Advisory proportionality-judge failures are explicit, not silent allows (#1191)

**+17 `packages/maistro-core/tests`** — pins the new failure semantics of the
DAG-shape proportionality critic, spread so that re-collapsing a judge failure
into an affirmative allow fails at three independent layers:

- `tests/security/test_proportionality.py` (+10 net): the critic's own
  contract — timeout (`asyncio.TimeoutError`), provider exception, malformed
  response envelope (empty choices, non-string content, non-dict body),
  unparseable JSON, missing boolean `justified`, non-boolean `justified`
  (the `bool("false") is True` silent-allow hazard), and non-dict JSON all
  yield `disposition="unavailable"` with `justified=False`; explicit
  allow/deny judgments carry `disposition="allow"`/`"deny"`; the
  `ProportionalityVerdict.unavailable` constructor fails safe on both
  readings; junk `add`/`drop` types no longer raise out of parsing. The old
  `..._defaults_to_justified` pins were inverted, not deleted.
- `tests/security/test_dag_shape.py` (+6): at the evaluator — an unavailable
  judge produces `approved_degraded` (distinct from `approved`, `can_execute`
  still true, no revision), the degraded literal cannot collapse back into
  `approved`, degraded proceeds ring `maistro_security_advisory_degraded_total`
  (and clean approvals / hard blocks do not), and the degraded disposition
  cannot weaken a Warden rationale block, a Sentinel policy block, or the
  over-budget `needs_revision` path.
- `tests/graph/nodes/test_agent_synth_dag.py` (+2): at the node — an
  unavailable critic still dispatches (the advisory layer is not an
  availability dependency) but the child Run's durable provenance records
  `proportionality: unavailable`, and a hostile rationale still refuses even
  with an unavailable critic; the clean-approval test now also pins that an
  affirmative approval writes no proportionality annotation at all.
