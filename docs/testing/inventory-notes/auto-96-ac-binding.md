---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +1
  packages/maistro-server/tests: +1
---
# auto-96-ac-binding

Repair round for the acceptance-state gate at #96: ADR-076's `status:
Implemented` front-matter claim was unverifiable (`tier: unmeasured`) because
the document declared no measurable criteria, so
`completion_claims_unverifiable` exceeded its 0 ceiling. The repair binds the
ADR's five provable acceptance criteria to evidence (**AC-1**–**AC-5** ids,
`ac-modules: maistro.api_versioning` anchors, `@pytest.mark.ac` markers) and
moves the two not-yet-true properties (first v2 breaking change; canonical
UI/API parity) out of the measured set with explicit reasons.

Test-count movement — three tests, each the direct evidence for one criterion:

- `packages/maistro-core/tests/api_versioning/test_middleware.py` (+1) —
  `test_additive_change_ships_within_version_1_without_breaking_silent_clients`
  (AC-3): the version table still advertises exactly one non-deprecated
  version and a selector-less pre-negotiation client keeps the exact
  pre-change response shape. Existing tests gained markers: AC-1/AC-2 on
  `test_all_selector_forms_resolve_to_the_same_version`, AC-4 on
  `test_no_selector_serves_the_default_and_advertises_it`, AC-5 on
  `test_deprecated_version_signals_deprecation_sunset_and_link`.
- `packages/maistro-server/tests/api/test_version_negotiation.py` (+1) —
  `test_business_routes_have_no_path_version_twins` (AC-2): read from the
  client-facing OpenAPI table, no `/vK` path serves the same resource as a
  `/v1` route; the canvas `/v2/canvas` mount has no `/v1` twins, so it
  satisfies the property rather than being special-cased. AC-1/AC-4 markers
  added to the existing selector-agreement and default-advertisement tests.
- `packages/hive-conductor/backend/tests/test_version_negotiation.py` (+1) —
  the same OpenAPI-table twins property for the conductor's 213-route `/v1`
  mount, plus AC-1/AC-4 markers.

No removals and no skip-machinery changes: every delta is a new test or an
added marker on an existing test.
