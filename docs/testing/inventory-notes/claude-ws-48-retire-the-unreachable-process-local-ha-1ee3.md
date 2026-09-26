---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# claude-ws-48-retire-the-unreachable-process-local-ha-1ee3

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->
`tests/test_ha_confirm_retired.py` adds three parametrized cases pinning that
`GET /v1/confirms`, `GET /v1/confirms/pending` and
`POST /v1/confirms/{id}/respond` answer 404 now that the process-local HA
confirmation store and `services/ha_tools.py` are retired (#48). No test was
removed: nothing exercised the deleted module.
