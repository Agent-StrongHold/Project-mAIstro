---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# 1048-home-retirement-compliance

CI at the #1048 candidate flagged the adaptive-Home feature against two
cutover gates: `stores.py::missions` and `stores.py::chat_sessions` had gained
a new consumer (`services/home_projections.py`), and the two stores the feature
added to `stores.py` (`home_layouts`, `home_adaptive_dismissals`) had no
retirement-ledger row — a row the ledger's importer freeze makes impossible to
write honestly, since a new entry's importer list starts from an empty trusted
baseline.

The repair follows the `settings`-store precedent (#334): both #1048 stores now
live beside the only code that writes them (`services/home_layouts.py`,
`services.home_projections.dismissal_store`) and register through the new
`stores.register_json_store`, so the central persistence wiring still reaches
them while `stores.py` grows no new ledger-bound rows. The chat projection now
reads through `services.owned_records.owned_chat_sessions` (the #312 scoping
seam), and the goals section reports `unavailable` instead of consuming the
frozen `missions` store.

The two added node IDs pin the repair rather than pad it:

- `test_the_home_stores_are_service_owned_but_registered_for_persistence` and
  `test_a_second_registration_is_a_no_op_and_late_registration_wires_persistence`
  (one replacement plus one addition in `test_home_layout_service.py`, +1 net):
  the service-owned stores must stay reachable by
  `configure_persistence`/`initialize_stores`, the registration seam must be
  idempotent, and a store registered after `configure_persistence` must be
  wired immediately instead of silently missing the configured backend.
- `test_the_goals_section_names_its_unavailable_rather_than_reading_the_retiring_store`
  (+1 in `test_home_routes.py`): with Goal rows deliberately planted, the
  projections section must answer `unavailable` naming the canonical Goal
  service and the adaptive list must offer no Goal candidate — the exact
  regression the retirement freeze forbids.
