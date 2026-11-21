-- Initialize databases for all services sharing this PostgreSQL cluster.
-- Each service gets its own database within the same Postgres instance.
--
-- Idempotent by construction (#339): this file runs from
-- /docker-entrypoint-initdb.d on the volume's first boot, and again from the
-- postgres-init one-shot on every `docker compose up`. CREATE DATABASE has
-- no IF NOT EXISTS form, so each creation is guarded by a catalog probe with
-- \gexec: the statement runs only when the database is missing. A first boot
-- interrupted inside this file (some databases committed, the container
-- killed before the rest) therefore completes on the next start instead of
-- leaving the cluster permanently half-initialized -- the image entrypoint
-- never re-runs initdb.d on a non-empty PGDATA.

SELECT 'CREATE DATABASE litellm' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm')\gexec
SELECT 'CREATE DATABASE langfuse' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
SELECT 'CREATE DATABASE openwebui' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'openwebui')\gexec

-- Enable pgvector extension in the main maistro database
\c maistro
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
