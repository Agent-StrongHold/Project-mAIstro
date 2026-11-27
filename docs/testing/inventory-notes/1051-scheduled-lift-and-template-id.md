---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
---
# Scheduled-fire lift glue and canonical-only template identity (issue #1051)

Verifier follow-up on PR #2520 at head `9b333f68`: the discovery "while away"
path had its generic seams pinned elsewhere but its own glue untested, and the
`dag_id` resolution b326cb5 added for canonical-only summaries had no direct
test. Both gaps are closed with focused tests in existing files — nothing else
moves.

**+4** in `test_discovery_service.py` close the scheduled-fire lift
(`services/discovery.py::_lift_pending_scheduled_runs`), driven through the
same public read (`surfaced_items`) production uses, with run inspection and
the canonical run store faked at their import seams:

- the first authorized read lifts a completed scheduled Run's curated output
  and records the run id in the lifted ledger; the second read re-asks the
  run store nothing (idempotent per Run);
- the candidate filter: foreign dag ids, foreign Workspaces, non-terminal
  statuses and already-lifted ids never reach the run store (asserted by the
  store being asked for nothing);
- an unreadable run record (store raises, record vanished) is skipped per run
  and left un-lifted so a later read re-attempts it;
- inspection being down degrades the read to the plain surface instead of
  failing it.

**+9** in `test_canonical_run_inspection.py` close
`services/dag_run_inspection.py::_canonical_template_id` and its one
consumer:

- a snapshot with `source_template.template_id` resolves to that id (+1);
- seven degenerate snapshots resolve honestly to the empty string
  (parametrized): no graph, empty definition, unparsable JSON, missing
  `source_template`, non-mapping `source_template`, blank `template_id`,
  name-only `source_template` (+7);
- `_canonical_only_detail` names the snapshot template as `dag_id` while the
  event-history fields stay honestly empty (+1).

The schedule stamping itself (`source_template` on the admitter's snapshot)
was already pinned at `test_scheduler_canonical_due.py`; these tests pin the
read-side glue that consumes it.
