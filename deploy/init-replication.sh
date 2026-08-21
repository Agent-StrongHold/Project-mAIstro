#!/bin/bash
# Runs once at primary initdb time: create the streaming-replication role
# used by postgres-replica's pg_basebackup bootstrap (SPEC-070226-fbe3).
set -euo pipefail

: "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
	CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
SQL

# Allow the replica container to connect for replication.
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
