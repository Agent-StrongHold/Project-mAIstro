-- Initialize databases for all services sharing this PostgreSQL cluster.
-- Each service gets its own database within the same Postgres instance.

CREATE DATABASE litellm;
CREATE DATABASE langfuse;
CREATE DATABASE openwebui;

-- Enable pgvector extension in the main maistro database
\c maistro
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
