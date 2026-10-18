---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# auto-1137-audit-wiring — the Hive resolver composes delegation with the Container's Warden and audit trail

`dag_agents._resolve_nodes_with` is the node resolver behind Hive's shipped
durable executor (`run_durable_graph`) and the registered-DAG recovery sweeps.
It forwarded every Container authority except the two #1137 added, so
`agent.delegate_remote` was composed with `audit_log=None`: the scan still ran
(the constructor's `_WARDEN_UNSET` default built a fresh canonical Warden and
`scan_inbound` fails closed), but `_record_scan` early-returned on the missing
audit trail, so no ingress verdict on this surface ever reached the canonical
audit log. The repair forwards `warden=container.warden` and
`audit_log=container.audit_log`, matching what `Container.node_resolver()`
already does in maistro-core. No behavior elsewhere changed: the two hermetic
container stubs (conftest `canonical_graph_spine`, the `test_registered_dag_recovery`
fixture) gained the same two fields they were previously missing from the
Container contract (`warden` always built, `audit_log` None when unwired).

Two cases, both in `test_dag_agents.py`:

- `test_the_delegate_node_scans_and_audits_with_the_container_authorities` —
  the delegate node composed by `_resolve_nodes_with` is wired with the
  Container's own `warden` and `audit_log` instances (identity, not fresh
  defaults), the same shape the #147 wiring tests pin for the other
  authorities.
- `test_a_denied_ingress_on_the_hive_executor_path_is_audited` — end to end
  over the composed node: a refused payload is rejected before any transport
  is touched, Warden judged the exact canonical JSON representation of the
  validated input, and the Container's audit log records one `denied` entry
  whose detail correlates decision, parent Run, and policy version with
  identifiers only — the peer-controlled text appears nowhere in the record.
