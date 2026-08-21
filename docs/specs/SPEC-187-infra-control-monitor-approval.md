---
id: SPEC-187
title: "Infra control & monitoring — infra_monitor, infra_action, approval slots over the host-health API"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#SPEC-184
  - maistro-engine#SPEC-011
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-184
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# SPEC-187: Infra Control, Monitoring & Approval

## Context

The original migration goal is for mAIstro to **control the server** and **monitor infra + smart
home**, replacing the conductor. The reusable backend already exists and is **verified running**: the
standalone host-health API at `http://<host-health-host>:8150` (systemd `conductor-host-health`), which the
old conductor calls via its `infra_health` / `infra_action` tools. mAIstro does not reimplement host
access — it adds the SPEC-184 slots and a thin provider that calls this API. The dangerous parts
(action allowlist, VMID allowlist, path-traversal guards) stay **server-side** in the host API as
defense-in-depth.

**Verified live surface (2026-05-30):**
- Monitor `GET /full` → sections `gpu, storage, docker, vms, services` (+ per-resource endpoints).
- Action `POST /action/{name}` allowlist (`POST_ACTIONS`): `restart_container`, `restart_stack`,
  `restart_service`, `vm_control` (VMID-allowlisted; start/stop/reboot/status), `docker_logs`,
  `docker_prune`, `ollama_list`, `ollama_pull` (path-traversal guarded), `snapraid_status`.
- Bearer-token auth.

> Note: `snapraid_status` is **stale** — SnapRAID was replaced by ZFS (`dbpool`). The provider should
> surface ZFS (`zpool status`) and treat `snapraid_status` as deprecated.

This spec is decomposition item #3 of SPEC-184 and the foundation for SPEC-188 (`self_repair`).

## Goals

1. `infra_monitor` slot — observe host health (GPU/storage/docker/VMs/services) through one provider.
2. `infra_action` slot — perform host actions through one provider, each tagged by **blast radius**.
3. `approval` slot — the human gate that risky actions consult ("auto for safe, approve risky").
4. Keep all privilege server-side; mAIstro holds only a bearer token (in the SPEC-011 vault).

## Non-goals

- Re-implementing host access in mAIstro (it calls the host-health API).
- The autonomous remediation loop (that is SPEC-188; this spec provides the primitives it uses).
- Widening the host-API allowlist (changes there are a separate, reviewed host-side task).

## Decision

### `infra_monitor` slot

A read-only slot. Provider `host_health_monitor` GETs `/full` (and per-resource endpoints) and maps
the response to a normalized `InfraHealth` model: `{gpu, storage, docker, vms, services, ts}`, each
resource carrying `status ∈ {ok, degraded, down}` + raw detail. Fallback policy: `safe_noop`
(typed "monitoring unavailable" when the host API is unreachable; never throws into a consumer).
Health is cached briefly (short TTL) to avoid hammering the host API.

### `infra_action` slot

Provider `host_health_action` POSTs `/action/{name}` with params. It mirrors the host API's allowlist
verbatim — it never invents actions. **Every action carries a blast-radius `tier`**, which decides
whether it runs autonomously or must consult the `approval` slot:

| Action | Tier | Default behavior |
|---|---|---|
| `docker_logs`, `ollama_list`, `snapraid_status`(dep.), all monitor reads | `read` | always auto |
| `restart_container`, `restart_service`, `ollama_pull`, `vm_control:start`/`status` | `reversible` | auto **iff** `infra_action.autonomy = auto_safe`; else approval |
| `restart_stack`, `docker_prune`, `vm_control:stop`/`reboot` | `destructive` | **always** requires approval |

The `autonomy` setting (`approve_all` | `auto_safe` | `detect_only`) maps to the SPEC-184 question
answer "auto for safe, approve risky" → default `auto_safe`. Fallback policy: `safe_noop`.

### `approval` slot

Per SPEC-184: baseline = the **built-in approval inbox** (pending-action queue in the Hive Conductor
UI + `maistro approvals` CLI + API), needs nothing external. Enhanced providers (`ha_push`,
`crypto_did_signature`) fill the same slot when installed. A `destructive`/gated `reversible` action
creates a pending approval carrying `{action, params, tier, requester, rationale}`; it executes only
on approve, expires/denies otherwise, and the outcome is audit-logged.

### Tiered-autonomy flow (composition, not bespoke code)

```
caller → infra_action(name, params)
  ├─ resolve tier(name, params)
  ├─ read  → execute via host API
  ├─ reversible → if autonomy=auto_safe: execute ; else approval-gate
  └─ destructive → approval-gate (always)
        approval slot → baseline inbox (or ha_push / crypto_did if active)
            approved → execute via host API ; denied/expired → no-op + audit
```

This is exactly SPEC-184's "`infra_action` consults `approval`" composition; the operator chooses *how*
approval happens by choosing the `approval` provider.

### Security boundary

- The allowlist, VMID allowlist, and path-traversal guards remain in `host_health_api.py` — mAIstro
  cannot execute anything the host API doesn't already permit (defense-in-depth).
- The bearer token lives in the **SPEC-011 vault**, never on disk in cleartext.
- All actions (auto or approved) are recorded to the audit log with tier + actor + outcome.

## Acceptance criteria

- [ ] `infra_monitor` provider returns a normalized `InfraHealth` with the five verified sections
      (`gpu, storage, docker, vms, services`); host-API unreachable → typed `safe_noop`, not an
      exception (tested with a fake host API).
- [ ] `infra_monitor` surfaces **ZFS** (`storage`) correctly and does not depend on the deprecated
      `snapraid_status`.
- [ ] `infra_action` exposes exactly the host API's allowlisted actions and refuses any other name
      (server-side rejection asserted).
- [ ] Blast-radius tiering matches the table; with `autonomy = auto_safe`: a `read`/`reversible`
      action executes without approval, a `destructive` action is **blocked** until the `approval`
      slot resolves (tested with the baseline inbox provider).
- [ ] `vm_control` honors the server-side VMID allowlist; a non-allowlisted VMID is rejected.
- [ ] The bearer token is read from the SPEC-011 vault; a test asserts it is never written to config
      in cleartext.
- [ ] Every executed/denied action produces an audit-log entry with `{action, params, tier, actor,
      outcome}`.
- [ ] With `autonomy = detect_only`, no action ever executes (monitor-only mode).

## Testing

- Unit: tier resolution per (action, params); autonomy-mode branching; `InfraHealth` mapping.
- Contract: `infra_monitor` / `infra_action` conform to their slot Protocols (SPEC-184); the action
  provider's allowlist mirrors the host API's `POST_ACTIONS`.
- Integration: monitor read + each tier's path against a **fake host-health API**; destructive action
  blocked → approve via baseline inbox → executes; deny → no-op.
- Property (formal/): "a `destructive` action never executes without a resolved approval"; "no action
  outside the host-API allowlist is ever dispatched".

## Open questions

- Per-action override of tier (operator wants `restart_stack` reversible on a specific stack)?
  Default: tiers are fixed; overrides require admin + audit.
- Whether `infra_monitor` should poll-and-cache centrally (one loop) vs per-call fetch — leaning a
  short-TTL shared cache to protect the host API.
- Backups visibility: the live `/full` lacks a `backups` section; add a host-API endpoint or read PBS
  separately (defer to SPEC-188 needs).

## References

- [SPEC-184: Modular capability platform](SPEC-184-modular-capability-platform.md)
- [SPEC-011: vault](SPEC-011-vault.md)
- Verified backend: `/root/docker/conductor-router/scripts/host_health_api.py`
  (`POST_ACTIONS`, `/full`, VMID allowlist, path-traversal guards) — host-health API :8150.
- Next: SPEC-188 `self_repair` (detect→diagnose→propose→act-via-`infra_action`).
