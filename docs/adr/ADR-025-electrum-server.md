---
id: ADR-025
title: "Electrum Server — Medley plugin for household-private Bitcoin backend"
repo: maistro-engine
kind: adr
status: Deferred
created: 2026-05-07
substrate:
  - maistro-engine#ADR-023
  - maistro-engine#ADR-029
implements: []
related:
  - maistro-engine#ADR-026
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Deferred
    date: 2026-05-07
---

# ADR-025: Electrum Server — Medley plugin for household-private Bitcoin backend

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-023 (Agent Crypto Ops), ADR-029 (Networking Substrate)

---

## Context

Crypto operations (ADR-023) require a chain backend. Public Electrum servers leak every address the conductor queries. Running your own is historically a 60GB, multi-component setup. Meanwhile, every household member's phone wallet faces the same privacy problem.

**Source:** `Project_mAIstro/specs/tools/S-154-electrum-server.md` (166 lines)

## Decision

A Medley plugin (`medley install electrum-server`) packaging a complete household-private Bitcoin backend:

- **Bitcoin Core** (pruned by default, ~10GB chain state)
- **electrs** (Rust Electrum-protocol server)
- Substrate exposure (ADR-029) for household wallet access over TLS

Once installed:
1. Conductor's wallet (ADR-023) routes all chain queries to localhost
2. Household phone wallets point at `electrum.<instance>.<tailnet>.ts.net:50002`
3. Lightning plugin gets local chain-data source

### Plugin shape

```yaml
name: electrum-server
type: skill+service
resources:
  disk: 60GB
  memory: 2GB
services:
  - bitcoind (pruned, outbound-only peers)
  - electrs (depends on bitcoind)
exposes:
  - port: 50002 (electrum-tls, tailnet-private)
  - port: 8332 (bitcoin-rpc, localhost-only)
```

### Substrate exposure

| Substrate | Mechanism | URL for wallets |
|---|---|---|
| Tailscale | `tailscale serve` TCP 50002 | `<instance>.<tailnet>.ts.net:50002` |
| NetBird | Equivalent mesh exposure | `<instance>.<netbird>:50002` |
| LAN-mDNS | Direct LAN port | `<instance>.local:50002` |
| Localhost-only | Not exposed externally | Conductor wallet only |

**Default: tailnet/LAN-private only. Public exposure NOT offered.**

### Pairing with Lightning

- `medley install lightning` with no chain backend → prompts to install electrum-server
- Both at once → auto-wires LDK/LND to local Bitcoin Core + electrs

### Initial sync UX

- Install completes immediately; sync runs in background (~6-12h pruned)
- Dashboard shows sync progress (current block / chain tip / ETA)
- Optional pre-sync snapshot import (~30 min) with explicit trust gate
- Conductor wallet falls back to public Electrum until local sync completes

## Interface (spec)

```python
class ElectrumServerPlugin:
    def install(self, config: ElectrumConfig) -> None: ...
    def sync_status(self) -> SyncStatus: ...
    def is_chain_current(self) -> bool: ...
    def get_electrum_endpoint(self) -> str: ...     # for household wallets
    def get_rpc_endpoint(self) -> str: ...           # localhost-only
```

## Acceptance criteria

- [ ] `medley install electrum-server` brings up bitcoind + electrs as supervised services
- [ ] Sync progress reflected accurately in dashboard
- [ ] Conductor wallet auto-uses local backend once sync is current
- [ ] Lightning plugin detects and uses local Bitcoin node when both installed
- [ ] Household phone wallets connect using documented endpoint
- [ ] Tailnet-private exposure is default; public exposure not offered
- [ ] Plugin survives conductor restart with no data loss
- [ ] RPC credentials stored in vault, not plaintext
- [ ] Phantom verifies plugin on signet before mainnet promotion

## Out of scope

- Full archival node (~700GB) — optional via config
- Public internet Electrum server
- Block explorer web UI (future `medley install mempool`)
- Multi-chain support v1 (Bitcoin mainnet/signet/testnet only; Liquid/Litecoin future)

## Source references

- `~/maistro-engine/specs/tools/S-154-electrum-server.md` — full 166-line spec

## Links

- Source spec: S-154
- Related ADRs: ADR-023 (Agent Crypto Ops), ADR-026 (Internal Trust Root), ADR-029 (Networking Substrate)
