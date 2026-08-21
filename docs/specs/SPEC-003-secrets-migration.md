---
id: SPEC-003
title: "Secrets migration — move plaintext secrets to the vault backend"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-03-23
substrate:
  - maistro-engine#ADR-028
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-03-23
---

# SPEC-003: Secrets Migration

## Problem

Some secrets are still stored as environment variables or plaintext in config files. The correct vault backend depends on the product SKU:

- **Agent Conductor** (household/personal) — SPEC-011 age-encrypted file vault. Today the
  vault's `age` identity is always a standalone keypair (`admin.key`, produced by
  `age-keygen`) — *not* derived from the Conductor Seed, despite the original wording above.
  ADR-021's 2026-06-19 amendment corrects this: the standalone identity is the **baseline**
  (kept, unconditionally available, no seed required), and Conductor-Seed-derived identity at
  path `m/44'/9000'/1'` is an **opt-in upgrade** for deployments that already have a seed.
  Secrets belong in `~/.conductor/secrets.age`; accessed via `vault.use(name, callback)`.
- **Agent Stronghold** (multitenant) — Vaultwarden API. Secrets read from Vaultwarden at startup.

### Vault identity tiers (per ADR-021 amendment)

| Tier | Identity source | Default? | How to enable |
|---|---|---|---|
| Baseline | Standalone X25519 keypair from `age-keygen`, stored at `admin.key` | Yes — always available, zero seed dependency | n/a (current behavior, unchanged) |
| Upgraded | X25519 key derived from `ConductorSeed` at `m/44'/9000'/1'` (Ed25519→X25519 birational conversion of the SLIP10 Ed25519 derived key) | No — only if a seed exists, and only when explicitly requested | New `maistro vault rotate-identity --source=conductor-seed` CLI step, or a setup-wizard toggle |

Both tiers store the identity in the same `age`-compatible on-disk format and go through the
same `Vault.use()` API — the upgrade only changes where the private key material originates,
never the vault's file format or access pattern. Switching tiers is never automatic: presence
of a `ConductorSeed` must not silently change which key unlocks the vault, because folding
vault-unlock into the seed increases blast radius (losing the seed then loses wallets *and*
secrets, not just one).

## Acceptance Criteria

- [ ] Zero plaintext secrets in any tracked config file or `.env` file; `gitleaks` pre-commit hook passes on all tracked files with no suppressions
- [ ] All API keys, passwords, tokens, and connection strings are accessed via `vault.use()` from the appropriate vault backend — covers, at minimum, the known plaintext-env call sites: `maistro/auth/registry.py` (`SERVICE_KEYS_FILE`), `hive-conductor/run_hill_climb.py` (`LITELLM_API_KEY`), `maistro/credentials/store.py` (master key env), `maistro/config/loader.py` (`LITELLM_MASTER_KEY`, `ROUTER_API_KEY`, `JWT_SECRET`, `MAISTRO_WEBHOOK_SECRET`), `hive-conductor/backend/services/mcp_client.py` (MCP server keys)
- [ ] Conductor fails closed at startup when a required secret is absent from the vault: conductor logs `SECRET_MISSING` naming the missing key and exits; it does not start in a degraded mode. This replaces the current `foundation.py` behavior of catching vault-init failure and silently falling back to env vars ("Vault unavailable... secrets stay in env vars")
- [ ] Migration is idempotent: re-running the migration process does not duplicate vault entries or produce errors on subsequent runs
- [ ] Any secret that was ever in git history has been rotated in the vault (old value is no longer valid at the upstream service)
- [ ] `gitleaks` scan covers full git history, not only the working tree (already satisfied in CI — `security.yml`'s `gitleaks` job runs with `fetch-depth: 0`; still missing a local pre-commit hook for the same check)
- [ ] Baseline vault identity (`age-keygen` standalone keypair) continues to work with no `ConductorSeed` present — no regression for non-seed deployments
- [ ] `m/44'/9000'/1'`-derived vault identity is available as an explicit, non-default opt-in once a `ConductorSeed` exists, and produces a valid `age` X25519 identity that round-trips encrypt/decrypt
- [ ] Tier switch (baseline → seed-derived) is never triggered by mere presence of a seed; it requires an explicit user action
