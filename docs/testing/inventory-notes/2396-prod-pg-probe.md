---
inventory-delta:
  tests/: +9
---

# Production postgres-primary application-level readiness probe (#2396)

`tests/test_prod_postgres_probe.py` (6 node IDs) pins the shipped
`deploy/docker-compose.prod.yml` shape: the postgres-primary healthcheck
probes TCP to the service's own network address and runs a real query as
the application user with the application password (deferred to the
container with `$$`, reading the parameterized POSTGRES_USER/POSTGRES_DB
this stack sets), a start_period absorbs slow first boots, the
init-replication.sh init flow is untouched, every primary consumer
(replica, both engines, Conductor) waits on its health, and the replica's
socket probe stays by reviewed decision (no initdb.d window there; a
credential probe would widen POSTGRES_PASSWORD exposure). A fail-before
baseline keeps the racy socket-probe checker honest.

`tests/test_prod_postgres_probe_live.py` (3 node IDs, integration scope,
skipped without Docker) proves the behavior on the production
pgvector/pgvector:pg17 image, reading the healthcheck, environment, and
init script from the tracked compose file: first boot never reports ready
inside the entrypoint's temporary-server window (measured: socket
accepting, TCP refusing) and healthy implies the replicator role
init-replication.sh creates exists; wrong credentials stay not-ready with
the auth failure named in the health log; an existing volume restarts
healthy with the role intact. No existing test was removed or renamed.
