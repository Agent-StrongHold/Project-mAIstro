---
inventory-delta:
  packages/maistro-core/tests: +3
---
# claude-m1-231-hive-scheduler-admitter-6b83

Three new tests in `tests/test_container_wiring.py` for the schedule-admission
seam (#231), purely additive:

- `create_container` builds a `ScheduleRunAdmitter` from the three stores the
  execution spine already wires. Until now nothing constructed one, which is
  the unnamed half of #251's finding that it had no production caller.
- The declared default is `None`, so a Container assembled by hand — the case
  the default exists for, since `Container` takes thirteen required arguments
  and such a Container never runs `create_container`'s wiring — carries no
  admitter rather than one that raises on first use.
- the branch behind that default, executed rather than declared: the wiring
  returns None for an absent template store and an admitter for a present one.
