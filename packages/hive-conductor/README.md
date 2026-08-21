# Hive Conductor

React + Vite UI and FastAPI stub API for mission control, agents, MCP, and related surfaces. Lives under `packages/hive-conductor/` in the maistro-engine monorepo.

## Ports

| Service | Port | Notes |
|---------|------|--------|
| Hive Conductor API + static SPA (prod) | **8101** | `uvicorn` + `StaticFiles` |
| maistro-server | ~8000 | Separate; do not mount Hive into maistro-server in phase 1 |

## Development

Two terminals from this directory (`packages/hive-conductor/`):

```bash
# Terminal 1 — API (stub data)
cd backend && uv pip install -r requirements.txt && uvicorn main:app --reload --port 8101
```

```bash
# Terminal 2 — Vite dev server (proxies `/v1` and `/health` to 8101)
cd frontend && npm ci && npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`). The UI uses relative `fetch` to `/v1/...`; Vite proxies those to the API.

## Production (local Docker)

From the **monorepo root** (`maistro-engine/`):

```bash
docker build -f packages/hive-conductor/Dockerfile packages/hive-conductor -t hive-conductor:local
docker run --rm -p 8101:8101 hive-conductor:local
```

Or from **`packages/hive-conductor/`** (compose uses the local `Dockerfile`):

```bash
docker compose up --build
```

Then open `http://localhost:8101`.

## Ports & protocols

Hive keeps **HTTP routes** thin and pushes vendor specifics behind small **Protocols** in `backend/protocols/` (`LLMPort`, `TelemetryPort`) with **adapters** in `backend/adapters/`. That lets you swap LiteLLM for another OpenAI-shaped gateway, or Langfuse for OTLP-only stacks, without rewriting FastAPI handlers.

- **LLM:** `LLM_HTTP_VARIANT` (`auto` | `responses` | `chat_completions`) controls whether we try the stateful **Responses** path first (`POST …/v1/responses`) and fall back to **chat.completions**, or pin one. See [`backend/.env.example`](backend/.env.example).
- **Telemetry:** Langfuse is an **optional** `TelemetryPort` when `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and **`LANGFUSE_BASE_URL`** are set (SDK **≥ 3.9**; Langfuse **server ≥ 3.125** for full features). `LANGFUSE_HOST` aliases `LANGFUSE_BASE_URL` when unset. For a lightweight local alternative, run **`docker compose --profile observe up`** to start **Arize Phoenix** and point generic **OTEL** exporters at it (see [Phoenix documentation](https://docs.arize.com/phoenix)); wiring full auto-instrumentation is left as a learning exercise.

## Boundaries

Hive’s **`GET /v1/tasks`** returns **missions** (this package’s stub orchestration view). Maistro core’s **`/tasks`** is the engine task queue—same English word, different API and data model. When you wire the two together later, treat it as an explicit mapping layer, not a drop-in URL swap.

This stub does not ship an application database. If you add **LiteLLM** (or any other service with its own persistence), give that service its own connection string; do not reuse one URL for “everything on the box.”

## Install plan (web)

The **Install** page (`/install`) calls **`GET /v1/install/session`** (defaults template), **`POST /v1/install/session`** (merge partial answers), and **`POST /v1/install/plan`** (full plan JSON). In a **monorepo checkout** the API loads `maistro-bootstrap` from disk; the standalone Docker image **503**s these routes until bootstrap is bundled (use the CLI from the host instead). See [SPEC-180](../../docs/specs/SPEC-180-maistro-install-bootstrap.md).

## SPEC

See [docs/specs/SPEC-176-hive-conductor-package.md](../../docs/specs/SPEC-176-hive-conductor-package.md) and [SPEC-180](../../docs/specs/SPEC-180-maistro-install-bootstrap.md).
