# maistro-server

FastAPI HTTP service wrapping `maistro-core`.

## Dashboards

- **Knights / Armory / etc.** — HTML under `dashboard/` at **`/dashboard/`** (existing Maistro web UI).
- **Hive Conductor shell** — `src/maistro_server/static/hive/` at **`/conductor/`** (health + tasks against the same origin: `GET /health`, `GET /health/ready`, `GET`/`POST /tasks`).

The upstream `HiveConductor` Git repo currently has **no commits**; the Conductor shell is maintained here.
