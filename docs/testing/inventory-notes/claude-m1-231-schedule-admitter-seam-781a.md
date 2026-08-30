---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +3
---
# claude-m1-231-schedule-admitter-seam-781a

Three new tests in `packages/maistro-core/tests/test_container_wiring.py`, for
the schedule-admission seam (#231), all additive:

- `test_the_container_wires_a_schedule_admitter` — `create_container` builds a
  `ScheduleRunAdmitter` from the three stores the execution spine already
  wires. Until now nothing constructed one, which is the unnamed half of
  #251's finding that it had no production caller.
- `test_a_container_without_a_template_store_has_no_schedule_admitter` — the
  declared default is `None`, so a Container assembled by hand (the case the
  default exists for, since `Container` takes thirteen required arguments and
  such a Container never runs `create_container`'s wiring) carries no admitter
  rather than one that raises on first use.
- `test_wiring_declines_to_build_an_admitter_with_no_template_store` — the
  branch behind that default, executed rather than declared: the wiring
  returns `None` for an absent template store and an admitter for a present
  one.

Two more in `packages/hive-conductor/backend/tests/test_engine_service.py`,
mirroring `episodic_store`'s existing test pair for the new
`EngineService.schedule_admitter` passthrough property:

- `test_schedule_admitter_is_none_without_a_bridge` — no `_agent_port` at all
  (the unconfigured/stub case) reads `None`.
- `test_schedule_admitter_exposes_the_container_seam_when_bridged` — with a
  bridge whose `container.schedule_admitter` is set, the property returns it.

Re-landing #551's seam now that #44 has unblocked #231; the actual live-scheduler
migration remains separately blocked on `maistro.runs.consumption`'s deliberate
single-node-Run scope, since Hive's bundled `daily-status` DAG is multi-node.
