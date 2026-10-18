# Conductor Persistence Map — durability and acknowledgement modes

**Status:** living document. Structural counterpart: `docs/architecture/CONVERGENCE-MATRIX.md` (persistence *owners*); this map records the durability/ack *contract* per store family. Referenced by the persistence convergence effort (#1135) and owned by #333/#1179.
**Scope:** every user-visible mutation surface in `packages/hive-conductor/backend` — the model stores, JSON stores, and record stores that HTTP routes write through.

## The acknowledgement contract

Every mutation that claims durable success acknowledges at the **State writer's commit** (`SPEC-010` singleton writer). The write APIs do not return when a command enters the writer queue; they return when the commit has landed and raise the writer's failure when it has not (`State.submit_sync`, #1238). An HTTP handler therefore cannot turn a queued command into a 2xx durable-success claim, and a process crash after a 2xx cannot lose the acknowledged mutation (WAL commit on disk before the response).

- **`durable-ack`** — the write returns only after the State commit; a failed write raises to the caller (routes answer 5xx, never a 2xx carrying the mutation as stored).
- **`ephemeral` / `memory`** — process-lifetime only, labelled as such by the API and by `/health`; an in-memory write never wears the shape of a durable one (#333).
- **`fire-and-forget`** — queued without acknowledgement. Exists only on internal subsystem paths that return no durable-success claim to a user (see Reactor below); no HTTP mutation surface uses it.

## Where the mode is visible

`GET /health` reports the current mode per family under `persistence`:

```json
"persistence": {
  "ack": "state-commit",
  "families": {
    "model_json_stores": "durable-ack",
    "settings": "durable-ack",
    "profiles": "durable-ack",
    "registration_policy": "durable-ack"
  }
}
```

With no state database configured (`memory://` deployments, tests), `ack` is `process-memory` and the families read `memory`/`ephemeral`. An unreadable state reports `unknown`, never durable.

## Store families

All writes below route through `services/model_store.py` (`ModelStore`/`JsonStore`) or the three record-store services; all persistence goes through `maistro.state.PersistedStore` over the single `kv_store` table (`State.submit_sync`).

### Model stores (`ModelStore`, `stores._all_model_stores`)

| Store | Model | Mode | Notes |
|---|---|---|---|
| `missions` | `Mission` | durable-ack | |
| `schedules` | `Schedule` | durable-ack | |
| `skills` | `Skill` | durable-ack | |
| `agents` | `Agent` | durable-ack | product projection, one writer (`services.agent_materialization`) |
| `mcp_servers` | `MCPServer` | durable-ack | |
| `mcp_tools` | `MCPTool` | durable-ack | |
| `containers` | `Container` | durable-ack | |
| `memory_entries` | `MemoryEntry` | durable-ack | |
| `chat_sessions` | `ChatSession` | durable-ack | |
| `users` | `HiveUser` | durable-ack | unique-field writes wait on the claim transaction (`put_model_unique`) |
| `workspaces` | `Workspace` | durable-ack | |
| `persona_feedback` | `PersonaFeedback` | durable-ack | |

`__setitem__` persists **before** mutating memory: a refused write raises with memory still coherent with disk, and `pop`/`discard`/`retire_record` delete durably before dropping the cache entry.

### JSON stores (`JsonStore`, `stores._all_json_stores`)

`mission_steps`, `cli_sessions`, `sessions`, `program_contexts`, `brief_interviews`, `work_item_drafts`, `dags`, `messages`, `audit_log`, `eval_verdicts`, `optimizer_proposals`, `user_provider_config`, `dashboard_layouts`, `oauth_identity_links`, `dag_runs`, `registration_invitations`, `username_claims` — all **durable-ack** via acknowledged `put_raw`/`delete`; conflict-safe inserts (`put_if_absent`, invitations, username claims) wait on the durable single-winner decision (`put_raw_if_absent`, claim-and-row in one transaction).

### Record stores (single-document services)

| Service | Store name | Mode | Failure surface |
|---|---|---|---|
| `services/settings_store.py` | `conductor_settings` | durable-ack | `SettingsPersistenceError` → `503` (`routes/settings.py`) |
| `services/profile_store.py` | `user_profiles` | durable-ack | `ProfilePersistenceError` → `503` (`routes/profile.py`, chat tools report the failure) |
| `services/registration_policy.py` | `registration_policy` | durable-ack | write raises; an admin's mode change is never acknowledged on a refused write |

Each record store does write-then-read-back and refuses to acknowledge a write the store does not hold. There is no per-store `flush`: the shared acknowledgement primitive is `State.submit_sync` inside `PersistedStore.put_raw`/`put`/`delete` (#1179 removed the injected-flush wiring that predated it).

### Internal subsystems (not user-visible mutations)

| Subsystem | Mode | Notes |
|---|---|---|
| Reactor event persist (`maistro.reactor.state_submit`) | fire-and-forget | internal event loop, no durable-success claim returned; owned by #1178, converging under #1135 |
| `State.flush()` callers | drain barrier only | startup seeding drain (`services/foundation.py`) and CLI paths; never an acknowledgement |

## Crash semantics

- Crash **after** a `durable-ack` response: the commit is already in the WAL; a fresh `State` over the same file reads the mutation (pinned by restart probes in `packages/maistro-core/tests/state/test_write_acknowledgment.py` and `packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py`).
- Crash **before** the acknowledgement: the write was queued at best; no 2xx was returned, so nothing was presented as committed. A failed commit is rolled back and raises to the awaiting mutation.
