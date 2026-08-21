---
id: SPEC-070626-a675
title: "Networking substrate protocol, did:web resolution, and two concrete substrate implementations"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-029
implements:
  - maistro-engine#ADR-029
related:
  - maistro-engine#ADR-026
  - maistro-engine#SPEC-016
  - maistro-engine#SPEC-070626-4ec8
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070626-a675: Networking substrate protocol, did:web resolution, two concrete substrates

## Context

ADR-029 names 8 pluggable "substrate" transports a Conductor can run over (direct HTTP,
Tailscale mesh, cloud load balancer, etc.), each pairing a network transport with an identity
attestation story. Building all 8 up front is unverifiable in this environment — several need
external control-plane APIs or cloud provider accounts. This SPEC builds the abstraction
everything else (ADR-024's did:web, ADR-026's name-constrained CA) actually depends on, plus
two concrete substrates that are testable here: a direct-HTTP loopback substrate (no external
dependency) and a Tailscale substrate (already named as a near-term target by SPEC-016,
shelling out to the `tailscale` CLI the same way `vault.py` shells out to `age` — no new
pyproject dependency).

## Goals

- A `Substrate` protocol: given a peer identifier, resolve how to reach it (endpoint URL) and
  what identity attestation applies (is this peer's DID pinned, how is it verified at the
  transport layer).
- `did:web` resolution: given `did:web:example.com`, fetch `https://example.com/.well-known/
  did.json` and parse it into the `DIDDocument` type from SPEC-070626-4ec8.
- Two concrete substrates: `DirectHttpSubstrate` (loopback/LAN, no identity attestation beyond
  TLS) and `TailscaleSubstrate` (resolves peers by Tailscale hostname, attests identity via
  Tailscale's own node identity + optionally the local CA from SPEC-070626-5341 for
  app-layer TLS).
- Config loading: `~/.conductor/substrate/*.toml`-style declarative substrate selection per
  ADR-029, so a Conductor's active substrate is configuration, not code.

## Non-goals

- The other 6 named substrates (cloud LB, VPN mesh alternatives, etc.) — follow-up work behind
  the same `Substrate` protocol once there's a concrete need and testable environment.
- Public-exposure safety review UI — ADR-029 mentions gating public exposure; the protocol
  supports a substrate declaring itself `public_exposure_allowed: bool`, but the approval
  workflow itself is a hive-conductor concern.
- did:web *publishing* (serving `/.well-known/did.json` from a maistro-server route) — this
  SPEC covers resolution (consuming someone else's did:web document); publishing one's own is
  a natural follow-up once maistro-server routing for it is scoped.

## Decision

### Substrate protocol

```python
# maistro/connectivity/substrate.py

@dataclass(frozen=True)
class PeerAddress:
    endpoint: str                    # resolved URL/host:port to actually connect to
    identity_attested: bool          # did the substrate itself vouch for peer identity
    public_exposure: bool = False    # is this endpoint reachable from the public internet

class Substrate(Protocol):
    name: str                        # "direct_http" | "tailscale" | ...

    async def resolve(self, peer_id: str) -> PeerAddress:
        """Resolve a peer identifier (hostname, Tailscale name, DID, etc.) to
        a connectable PeerAddress. Raises PeerUnresolvableError if unknown."""

    async def healthcheck(self) -> bool:
        """Whether this substrate is currently usable (e.g. tailscale daemon
        running and authenticated)."""

class SubstrateRegistry(Protocol):
    async def active(self) -> Substrate:
        """The currently configured/active substrate."""
    async def list_available(self) -> list[Substrate]:
        ...
```

### did:web resolution

```python
# maistro/connectivity/did_web.py

async def resolve_did_web(
    did: str, *, http_client: HTTPClient
) -> DIDDocument:
    """did:web:example.com:path -> GET https://example.com/path/.well-known/did.json
    (or https://example.com/.well-known/did.json with no path segment), per the
    did:web method spec. Parses the response into SPEC-070626-4ec8's DIDDocument.
    Raises DidWebResolutionError on network failure or malformed document;
    DidWebMismatchError if the resolved document's `id` field doesn't match
    the requested DID (prevents a server from serving an unrelated document)."""
```

- SSRF guard reused from the existing marketplace host-denylist pattern (`skills/marketplace.
  py`'s `_BLOCKED_HOSTNAME_PREFIXES` / `_block_ssrf`) — a did:web DID pointing at
  `localhost`/`metadata.`/link-local is rejected before any fetch, same posture as skill import
  (SPEC-062126-d421).

### Concrete substrates

```python
class DirectHttpSubstrate(Substrate):
    """peer_id is treated as a hostname/URL directly; no identity attestation
    beyond whatever TLS cert the endpoint presents."""
    name = "direct_http"

class TailscaleSubstrate(Substrate):
    """peer_id is a Tailscale hostname (e.g. "pi-conductor"); resolve() shells
    out to `tailscale status --json` to confirm the peer is a known tailnet
    node before returning its Tailscale IP, so identity_attested=True (the
    tailnet's own node auth vouches for who's on the other end)."""
    name = "tailscale"

    async def resolve(self, peer_id: str) -> PeerAddress: ...
    async def healthcheck(self) -> bool:
        """`tailscale status` succeeds and reports a logged-in tailnet."""
```

### Config loading

```python
# ~/.conductor/substrate/active.toml
# [substrate]
# name = "tailscale"

def load_substrate_config(path: Path) -> SubstrateConfig: ...
def build_registry(config: SubstrateConfig) -> SubstrateRegistry: ...
```

## Acceptance criteria

- [ ] `DirectHttpSubstrate.resolve("host:port")` returns a `PeerAddress` with
      `identity_attested=False` (no attestation claim beyond raw connectivity).
- [ ] `TailscaleSubstrate.resolve(peer)` for a peer present in `tailscale status --json`'s
      output returns `identity_attested=True`; for a peer absent from that output, raises
      `PeerUnresolvableError` (never fabricates an address for an unknown peer).
- [ ] `TailscaleSubstrate.healthcheck()` returns `False` (not an exception) when the
      `tailscale` binary is absent or the daemon isn't authenticated — matches the
      `CapabilitySlot`/`FallbackPolicy.SAFE_NOOP` degradation convention already used elsewhere
      (SPEC-208).
- [ ] `resolve_did_web("did:web:example.com")` fetches `https://example.com/.well-known/
      did.json` and parses it into a `DIDDocument` (mocked HTTP client in tests, no real
      network call).
- [ ] `resolve_did_web` rejects a DID resolving to a loopback/link-local/`metadata.` host
      before any fetch (SSRF test, reusing the marketplace denylist pattern).
- [ ] A did:web document whose `id` field doesn't match the requested DID raises
      `DidWebMismatchError` (property: no document is ever trusted for a DID it doesn't claim
      to be).
- [ ] `load_substrate_config` + `build_registry` produces a `SubstrateRegistry` whose
      `active()` matches the configured `name`.

## Testing

- Unit: `DirectHttpSubstrate` resolve shape; `TailscaleSubstrate` resolve/healthcheck against a
  mocked `subprocess` call returning canned `tailscale status --json` output (both
  peer-present and peer-absent, and binary-absent cases).
- Unit: `resolve_did_web` happy path (mocked HTTP client), SSRF-blocked host, id-mismatch
  rejection, malformed JSON document.
- Unit: config loading from a temp TOML file, registry construction.
- Property (Hypothesis): SSRF guard rejects the same host-prefix set the marketplace importer
  already rejects (shared fixture/parametrization against `_BLOCKED_HOSTNAME_PREFIXES`).

## Open questions

- Whether `TailscaleSubstrate` should cache `tailscale status` output (avoid a subprocess call
  per resolve) — deferred; correctness first, add a short-TTL cache if resolve() latency
  becomes a problem in practice.
- Public-exposure gating workflow (who approves a substrate marking itself
  `public_exposure_allowed=True`) — explicitly deferred to hive-conductor per Non-goals.

## References

- [ADR-029: Networking & Identity Substrate](../adr/ADR-029-networking-substrate.md)
- [ADR-024: Agent Identity & Verifiable Credentials](../adr/ADR-024-agent-identity-did-vc.md)
- [SPEC-070626-4ec8: VC/DIDDocument types](SPEC-070626-4ec8-identity-vc-did-document.md)
- [SPEC-016: Tailscale-native connectivity](SPEC-016-tailscale-native.md)
- `packages/maistro-core/src/maistro/skills/marketplace.py` (`_BLOCKED_HOSTNAME_PREFIXES`, SSRF pattern precedent)
