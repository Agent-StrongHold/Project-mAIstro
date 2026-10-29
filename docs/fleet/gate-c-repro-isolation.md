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

## Scope: stack reproduction, NOT the gate verdict

Be precise about what this stack gives you. Gate C
(`.github/workflows/gate-c.yml`) proves the **installer path** on a clean
runner: wipe `.env`, then `./install.sh --skip-wizard --no-cli --no-open`
with a fixed env matrix. `install.sh` drives the *production-named* compose
stack by design, so it can never be the isolation vehicle on this box. This
file reproduces the resulting **stack topology** (same engine image,
pgvector pg18, litellm config) for interactive debugging.

- **Reproduce a Gate-C verdict**: use the real thing —
  `gh workflow run gate-c --ref <branch>` then `gh run watch <id>`. Do not
  claim gate success from this stack.
- **Debug** what the gate's stack was doing when it failed: use this
  isolated stack with the same env the gate sets.

## The sanctioned method

Use `docker-compose.repro.yml` (repo root) — standalone, isolated names
(`repro-*`), offset ports (8800/5434/8400), its own compose project:

```bash
export DB_PASSWORD=throwaway-1 LITELLM_MASTER_KEY=throwaway-2
export API_KEYS='["repro:throwaway"]'   # principal:secret; required, no committed default
docker compose -f docker-compose.repro.yml -p repro-$$ up -d --build
curl -f -H "Authorization: Bearer repro:throwaway" http://127.0.0.1:8800/health/live
# teardown (safe: touches only repro-*):
docker compose -f docker-compose.repro.yml -p repro-$$ down -v --remove-orphans
```

Notes:
- Engine migrations run against `repro-postgres` (pgvector pg18, same major
  as production) with throwaway credentials.
- The engine boots with auth enabled: supply a throwaway `API_KEYS` JSON list
  yourself (`principal:secret` format per #843). Compose refuses to start
  without it — same `${VAR:?message}` contract as production (#367).
  `ROUTER_API_KEY` reuses `LITELLM_MASTER_KEY`.
- Add `compose.override`-style extras only via additional `-f` files; keep
  names/ports inside the `repro-*` / offset ranges.
- If a needed service is missing from this file (e.g. langfuse for a trace
  repro), add it with a `repro-` container name in your PR — do not reach
  for the production stack.
