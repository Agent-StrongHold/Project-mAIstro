---
inventory-delta:
  tests/: +11
---

# PostgreSQL readiness waits for completed initialization (#339)

`tests/test_pg_readiness_compose.py` (7 node IDs) pins the shipped
`docker-compose.yml` shape: the `postgres` healthcheck probes the
application endpoint over TCP to the service's own network address and runs
a real query as the application user with the application password (a socket
`pg_isready` answers inside the init entrypoint's temporary server, before
the litellm/langfuse databases exist); a `start_period` absorbs slow first
boots; the `postgres-init` one-shot re-runs the now-idempotent `init-db.sql`
on every `up` so an interrupted first boot completes on restart; and every
PostgreSQL consumer (litellm, langfuse, maistro-engine, hive-conductor)
waits on both the healthcheck and the one-shot's completion. A fail-before
baseline keeps the racy socket-probe checker honest.

`tests/test_pg_readiness_live.py` (4 node IDs, integration scope, skipped
without Docker) proves the behavior on the production pgvector/pgvector:pg18
image, reading the healthcheck command, intervals, one-shot script, and init
SQL from the shipped files: first boot never reports ready inside the
temporary-server window (measured: socket accepting, TCP refusing), an
interrupted init completes after restart through the one-shot, wrong
credentials stay not-ready with the auth failure named in the health log
(server-ready versus application-ready), and an existing volume restarts
healthy with the one-shot an idempotent no-op.

No existing test was removed or renamed.
