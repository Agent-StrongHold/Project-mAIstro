# PostgreSQL volume layout and major upgrades

The root Compose stack defaults to PostgreSQL 18. PostgreSQL 18 changed the
official image contract:

- the persistent volume is mounted at `/var/lib/postgresql`;
- `PGDATA` is `/var/lib/postgresql/18/docker`.

The Compose file states both values explicitly. Do not change the image major
without changing and testing this contract.

## Existing PostgreSQL 17 volumes

Do not attach a PostgreSQL 17 data directory directly to a PostgreSQL 18
container. Before changing `POSTGRES_IMAGE`:

1. Stop writers and take a verified logical backup with the PostgreSQL 17
   tools (`pg_dumpall` or per-database `pg_dump`).
2. Keep the original volume intact until restore verification completes.
3. Start PostgreSQL 18 with a new volume using the root Compose layout.
4. Restore the backup, run the engine migration entrypoint, and verify
   `/health/live`, `/health/ready`, and application row counts.
5. Retain the PostgreSQL 17 volume through the rollback window.

For large installations, use PostgreSQL's supported `pg_upgrade` procedure
with both major-version binaries instead of a logical dump. In either case,
major upgrades are explicit maintenance operations, never an image-tag swap.
