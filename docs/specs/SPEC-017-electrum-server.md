---
id: SPEC-017
title: "Electrum server — Medley plugin for household-private Bitcoin backend"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-025
  - maistro-engine#ADR-028
implements:
  - maistro-engine#ADR-025
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-017: Electrum Server Plugin

See `blakematthews-dev/project_maistro` specs/tools/S-154-electrum-server.md for full spec.

## Acceptance Criteria

- [ ] `medley install electrum-server` brings up bitcoind + electrs as supervised services
- [ ] Initial sync completes and dashboard reflects accurate progress throughout
- [ ] Conductor's wallet automatically uses the local backend once sync is current
- [ ] Tailnet-private exposure is the default; public exposure is not offered through normal config flow
- [ ] Plugin survives conductor restart with no data loss; bitcoind and electrs come back to a consistent state
- [ ] RPC credentials and TLS material are stored in the SPEC-011 vault, never in plaintext config files visible to other plugins
- [ ] `medley update electrum-server` follows the ordered stop/update/restart sequence; wallet falls back to public endpoint during the update window; failed update rolls back to previous binaries and posts to board
- [ ] Chain data backup policy is documented in `medley info electrum-server`: chain data is NOT vault-backed; re-sync is the recovery path; only vault credentials require backup
- [ ] Port conflict detection: if the configured Electrum TLS port (default 50002) is already in use at install time, the install fails with a clear error message
