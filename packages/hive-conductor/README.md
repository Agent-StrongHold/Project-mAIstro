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
docker run --rm -p 8101:8101 -v hive-conductor-data:/data hive-conductor:local
```

`/data` is the Conductor's durable state directory (`CONDUCTOR_DATA_DIR`,
pre-created in the image and owned by the nonroot runtime uid 65532). Without
a volume mounted there the process **refuses to start** (`DATA_DIR_EPHEMERAL`)
— see [Persistent state](#persistent-state) below.

Or from **`packages/hive-conductor/`** (compose uses the local `Dockerfile`):

```bash
docker compose up --build
```

Then open `http://localhost:8101`.

## Persistent state

Everything the Conductor must survive a restart lives in one directory,
`CONDUCTOR_DATA_DIR` (default `~/.conductor` on a host; `/data` in Docker).
The standalone [`docker-compose.yml`](docker-compose.yml) mounts the named
volume `conductor-data` there, so `docker compose down/up` and image
replacement preserve every account, session, setting, and vault entry; the
startup guard refuses to serve from an unwritable or (inside a container)
unmounted data directory instead of silently discarding state (#331).

### What lives there (the full inventory)

| File | What | Written by |
|------|------|------------|
| `state.db` (+ `state.db-wal`, `state.db-shm` while live) | SQLite: accounts, sessions, settings, registration policy, profiles, setup marker | `maistro.state` via `Foundation._init_state` |
| `secrets.age` | age-encrypted vault entries | `maistro.vault` via `Foundation._init_vault` |
| `admin.key` | age identity that opens `secrets.age` | setup wizard / vault init |
| `credential_master.key` | Fernet master key for the credential store (mode `0600`) | `UserCredentialStore.open` |
| `user_credentials.enc` | encrypted per-user integration credentials | `UserCredentialStore` |

These files are **coupled**: the vault only opens with its identity key and
the credential store only decrypts under its master key. Copy them
piecemeal and you get a deployment that boots but cannot read itself —
move them as one unit (below).

### Backup and restore (atomic)

Stop the Conductor first (`docker compose stop hive-conductor`): a running
process holds `state.db` open and will write stale state back over you.

```bash
# One archive, whole directory, staged + renamed so it is never partial.
docker compose run --rm --entrypoint maistro -v "$PWD/backups:/backup" \\
  hive-conductor security backup --data-dir /data --out /backup/conductor-data.tar.gz

# Restore (replaces the directory; dry-run without --yes):
docker compose stop hive-conductor
docker compose run --rm --entrypoint maistro -v "$PWD/backups:/backup:ro" \\
  hive-conductor security restore --data-dir /data \\
  --from /backup/conductor-data.tar.gz --yes
docker compose start hive-conductor
```

The restore verifies the archive (a corrupt or truncated tarball is refused
before anything is touched) and swaps the extracted tree in atomically. The
archive contains key material — store it encrypted, off-box.

### Volume migration

`conductor-data` is an ordinary named volume; to move it (e.g. to another
host or to a bind mount), back it up as above, recreate the destination,
and restore into it:

```bash
# On the target, after `docker compose up -d && docker compose stop`:
docker compose run --rm --entrypoint maistro -v "$PWD/backups:/backup:ro" \\
  hive-conductor security restore --data-dir /data --from /backup/conductor-data.tar.gz --yes
```

To switch from a named volume to a host directory, replace the `volumes:`
entry in `docker-compose.yml` with `- /srv/conductor-data:/data` and make
that directory owned by uid `65532` (the image's nonroot runtime user):
`sudo install -d -o 65532 -g 65532 -m 700 /srv/conductor-data`.

### Deletion is destructive

`docker compose down` keeps the volume; **`docker compose down -v` deletes
it**, and with it every account, session, setting, and vault entry. There is
no second copy. Back up first if the data matters.

### Escape hatch for throwaway harnesses

`CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1` acknowledges that the configured
data directory is deliberately ephemeral (used by
[`docker-compose.test.yml`](docker-compose.test.yml) so each e2e run starts
from a fresh setup wizard). Never set it where state must survive a
recreate.

## Ports & protocols

Hive keeps **HTTP routes** thin and pushes vendor specifics behind small **Protocols** in `backend/protocols/` (`LLMPort`, `TelemetryPort`) with **adapters** in `backend/adapters/`. That lets you swap LiteLLM for another OpenAI-shaped gateway, or Langfuse for OTLP-only stacks, without rewriting FastAPI handlers.

- **LLM:** `LLM_HTTP_VARIANT` (`auto` | `responses` | `chat_completions`) controls whether we try the stateful **Responses** path first (`POST …/v1/responses`) and fall back to **chat.completions**, or pin one. See [`backend/.env.example`](backend/.env.example).
- **Telemetry:** Langfuse is an **optional** `TelemetryPort` when `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and **`LANGFUSE_BASE_URL`** are set (SDK **≥ 3.9**; Langfuse **server ≥ 3.125** for full features). `LANGFUSE_HOST` aliases `LANGFUSE_BASE_URL` when unset. For a lightweight local alternative, run **`docker compose --profile observe up`** to start **Arize Phoenix** and point generic **OTEL** exporters at it (see [Phoenix documentation](https://docs.arize.com/phoenix)); wiring full auto-instrumentation is left as a learning exercise.

## Production task identity

When Hive calls maistro-server, `MAISTRO_ROUTER_API_KEY` authenticates the
Conductor service and `MAISTRO_DELEGATION_KEY` signs the originating Hive user.
Configure the same delegation key as `TASK_DELEGATION_KEY` on maistro-server.
The server stores the user as the effective Run actor while retaining the
service principal and delegation id in Run provenance; never use a caller-
editable `user_id` as a substitute for this signed context.

## Boundaries

Hive’s **`GET /v1/tasks`** returns **missions** (this package’s stub orchestration view). Maistro core’s **`/tasks`** is the engine task queue—same English word, different API and data model. When you wire the two together later, treat it as an explicit mapping layer, not a drop-in URL swap.

This stub does not ship an application database. If you add **LiteLLM** (or any other service with its own persistence), give that service its own connection string; do not reuse one URL for “everything on the box.”

## Install plan (web)

The **Install** page (`/install`) calls **`GET /v1/install/session`** (defaults template), **`POST /v1/install/session`** (merge partial answers), and **`POST /v1/install/plan`** (full plan JSON). In a **monorepo checkout** the API loads `maistro-bootstrap` from disk; the standalone Docker image **503**s these routes until bootstrap is bundled (use the CLI from the host instead). See [SPEC-180](../../docs/specs/SPEC-180-maistro-install-bootstrap.md).

## Registration Policy

Public self-registration is **closed by default** after the one-time setup wizard creates the first admin and daily user. The setup endpoint is a bootstrap-only path; it cannot be used to replace accounts after setup or partial initialization, including across a restart. A missing or corrupted policy record also fails closed.

An administrator can explicitly manage the active policy after signing in:

- `GET /v1/auth/registration/policy` reports the current mode and record health.
- `PUT /v1/auth/registration/policy` with `{"mode":"open"}` enables public user registration; use `{"mode":"closed"}` to disable it again. The change is durable and audited.
- `POST /v1/auth/registration/invitations` issues a single-use, expiring invitation. The token is shown only in the response and is stored as a digest; share it with the intended user.
- `GET /v1/auth/registration/invitations` lists invitation status and metadata, never invitation tokens.

Unauthenticated clients may read only `GET /v1/setup/status`, which exposes the setup state and active mode needed by the login surface. It does not disclose account names or counts. Invitation registration remains available while public mode is closed; the first owner can only be created by setup.

## SPEC

See [docs/specs/SPEC-176-hive-conductor-package.md](../../docs/specs/SPEC-176-hive-conductor-package.md) and [SPEC-180](../../docs/specs/SPEC-180-maistro-install-bootstrap.md).
