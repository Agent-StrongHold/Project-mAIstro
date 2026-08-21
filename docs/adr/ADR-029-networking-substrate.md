---
id: ADR-029
title: "Networking & Identity Substrate — Pluggable transport layer"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-07
substrate:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-028
implements: []
related:
  - maistro-engine#ADR-020
  - maistro-engine#ADR-026
  - maistro-engine#ADR-027
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-07
---

# ADR-029: Networking & Identity Substrate — Pluggable transport layer

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-024 (DID/VC Identity), ADR-028 (Privilege Separation)

---

## Context

The conductor needs HTTPS, stable addressing, mesh networking for federation, identity-verified connections, and access control (admin vs user). Different operators have different constraints (corporate Tailscale ban, self-hosting preference, offline use, existing Cloudflare account). The networking layer must work out of the box for the easy case while not requiring any specific vendor.

**Source:** `Project_mAIstro/specs/infra/S-153-tailscale-native.md` (259 lines)

## Decision

Define networking as a **substrate abstraction**. The conductor exposes HTTP on a localhost socket. Substrates connect that socket to the outside world and tell the conductor who is calling.

### Substrate contract

| Capability | What it means |
|---|---|
| **Reachability** | Externally-resolvable address pointing at conductor's local socket |
| **Transport security** | TLS termination with valid cert (or N/A for localhost) |
| **Identity attestation** | Verified identity of the caller on each request |
| **Peer connectivity** *(optional)* | Direct reachability between conductors for federation |
| **Public exposure** *(optional)* | Selective endpoint exposure to public internet |

No conductor code is substrate-aware. Substrate-specific glue lives in `~/.conductor/substrate/<name>.toml`.

### Supported substrates (8 implementations)

#### Mesh (recommended)

| Substrate | TLS | Identity | Public exposure | License |
|---|---|---|---|---|
| **Tailscale** *(default-recommended)* | Auto-LE for `*.ts.net` | Tailscale headers | `tailscale funnel` | Client BSD; coord proprietary |
| **Headscale** | Same as Tailscale | Same | Funnel-equivalent | BSD-3 (full stack) |
| **NetBird** | Self-signed today; auto-LE pending LE DNS-PERSIST-01 GA | OIDC headers | Built-in Reverse Proxy (v0.65+) | Apache-2 (full stack) |
| **ZeroTier** | Self-managed | No native identity (S-149 challenge) | Operator's reverse proxy | BSL |

#### Tunnel

| Substrate | Notes |
|---|---|
| **Cloudflare Tunnel** | Easy public exposure; CF sees metadata |

#### Local-only

| Substrate | Notes |
|---|---|
| **LAN-mDNS** | Same-network only, self-signed cert |
| **Localhost-only** | Always-available floor, Unix socket peer-cred |

#### Manual

| Substrate | Notes |
|---|---|
| **Bring-your-own** | Operator wires Caddy/nginx/Traefik; conductor trusts configured identity header |

### Why Tailscale is default

For a typical household, Tailscale collapses four problems into one decision: HTTPS with auto-renewing certs, stable MagicDNS address, identity on every connection, mesh peering for federation. It also fails closed — unreachable from public internet until operator opts in.

### Identity mapping

The conductor reads caller identity from configured headers per substrate:

```toml
# Tailscale
identity_headers = ["Tailscale-User-Login"]
admin_match = { type = "group", value = "group:conductor-admin" }

# NetBird
identity_headers = ["X-NetBird-User-Email"]

# ZeroTier (identity-blind)
identity_mode = "keypair-challenge"
admin_pubkeys = ["<m/0' pubkey>"]
```

ADR-028's admin/user split enforced inside the conductor against substrate-attested identity.

### Public exposure

Dashboard configures per-endpoint. **Defaults: nothing public.** Operator opts in deliberately.

## Interface (spec)

```python
from typing import Protocol

class Substrate(Protocol):
    def name(self) -> str: ...
    def has_tls(self) -> bool: ...
    def has_identity(self) -> bool: ...
    def external_url(self) -> str | None: ...
    def extract_identity(self, headers: dict) -> str | None: ...
    def is_public(self, path: str) -> bool: ...
```

## Acceptance criteria

- [ ] Networking layer is substrate abstraction; no conductor code references any specific substrate
- [ ] All 8 substrates selectable at setup, reconfigurable without reinstall
- [ ] Tailscale: dashboard reachable at `https://<instance>.<tailnet>.ts.net` within 60s
- [ ] NetBird: dashboard reachable after OIDC sign-in; admin/user mapping against IdP
- [ ] ZeroTier: S-149 keypair challenge for identity (ZT is identity-blind)
- [ ] Cloudflare Tunnel: CF Access JWT validated
- [ ] LAN-mDNS: `<instance>.local` reachable, S-149 challenge
- [ ] Localhost-only: `127.0.0.1` only; remote connections refused at socket
- [ ] Substrate switch recoverable between any pair
- [ ] No substrate required to start; localhost-only always valid

## Out of scope

- Tailscale/Headscale/NetBird client distribution (platform package managers)
- LE DNS-PERSIST-01 integration (waiting on upstream GA + substrate adoption)
- NetBird Reverse Proxy auto-configuration (documented, not automated yet)
- Custom substrate implementation framework (config-driven only)

## Source references

- `~/maistro-engine/specs/infra/S-153-tailscale-native.md` — full 259-line spec
- References: LE DNS-PERSIST-01 announcement (2026-02-18), cert-manager#8373, netbirdio/netbird#2375, netbirdio/netbird#5479

## Links

- Source spec: S-153
- Related ADRs: ADR-020 (Setup Wizard), ADR-024 (DID/VC), ADR-026 (Internal Trust Root), ADR-027 (Lightning Federation), ADR-028 (Privilege Separation)
