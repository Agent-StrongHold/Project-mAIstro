---
inventory-delta:
  packages/maistro-core/tests: +5
---
# m1-2405-durable-inbox-approval

#2405 / M1-B8: stop HostHealthAction / self-repair from awaiting
`InboxApproval`'s in-process `asyncio.Event`.

- `test_durable_hitl_approval.py` **+5**: admit parks `PAUSED` waiting-human
  NodeRun; canonical `create_run` before executor when `run_store` is set;
  Run scope is explicit (not Binding ids); RuleBasedRepair uses durable
  admittor and releases governor `in_flight` when the approval Run settles;
  missing admittor suppresses rather than spawning an Event wait.
- `test_host_health_action.py` / `test_self_repair_integration.py` /
  `test_infra_e2e.py` rewritten for the `approved=` / durable-admittor
  contract (same node counts as develop).
- Hive `test_capabilities_routes` / `test_capabilities_wiring` /
  `test_self_repair_routes` updated to the non-blocking executor contract
  (no new node IDs).
