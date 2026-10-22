# Gate-C reproduction: isolated stack (sanctioned method)

## Why this exists

On 2026-10-21 an agent lane reproducing the Gate C canonical clean install
stopped the production `maistro-*` containers to free ports 8000/8101/5432,
passed its verification, and ended — leaving the fleet down ~4h45m
(16:24–21:14Z). Root cause: `docker-compose.yml` hardcodes
`container_name: maistro-*` and fixed ports, so any local repro collides
with the live fleet.

## The rule

**Never `docker stop` / `docker rm` a `maistro-*` container. Never bind
8000/8101/5432 outside the production stack. Production is not a resource
pool.**

## The sanctioned method

Use `docker-compose.repro.yml` (repo root) — standalone, isolated names
(`repro-*`), offset ports (8800/5433/8400), its own compose project:

```bash
export DB_PASSWORD=throwaway-1 LITELLM_MASTER_KEY=throwaway-2
docker compose -f docker-compose.repro.yml -p repro-$$ up -d --build
curl -f http://127.0.0.1:8800/health/live
# teardown (safe: touches only repro-*):
docker compose -f docker-compose.repro.yml -p repro-$$ down -v --remove-orphans
```

Notes:
- Engine migrations run against `repro-postgres` (pgvector pg18, same major
  as production) with throwaway credentials.
- The engine boots with auth enabled: throwaway API key `repro:repro-dev-key`
  (`principal:secret` format per #843; override with `REPRO_API_KEY`), and
  `ROUTER_API_KEY` reuses `LITELLM_MASTER_KEY`.
- Add `compose.override`-style extras only via additional `-f` files; keep
  names/ports inside the `repro-*` / offset ranges.
- If a needed service is missing from this file (e.g. langfuse for a trace
  repro), add it with a `repro-` container name in your PR — do not reach
  for the production stack.
