---
id: SPEC-070626-5341
title: "Internal trust root: CA derivation from ConductorSeed, X.509 leaf minting, and 90-day rotation"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-026
implements:
  - maistro-engine#ADR-026
related:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-077
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070626-5341: Internal trust root — CA derivation, X.509 leaf minting, 90-day rotation

> **Unresolved on migration.** This document was written on a stale branch and is
> migrated at `Proposed` to preserve design intent; it has not been reconciled
> against the ADR it claims to implement. Automated review (#457) raised the
> following, and the first was verified against the ADR text:
>
> - **Diverges from ADR-026 while declaring `implements: ADR-026`.** ADR-026
>   derives the root as `HKDF(seed, info=instance_name)` producing a **P-256**
>   key, chosen because "P-256 — universally supported in X.509 / TLS / OS trust
>   stores" and deliberately "independent of BIP32 paths". This spec instead uses
>   a single constant BIP32 Ed25519 path, which drops instance scoping (one seed
>   provisioning several conductors would share one CA key) and the X.509/TLS
>   compatibility the ADR selected P-256 for. Reconcile the spec or amend the ADR
>   before implementing either.
> - Default name constraints (`.local`, `.internal`) are broader than ADR-026's
>   restriction to the conductor's own hostnames.
> - `mint_leaf` returns only a certificate, with no leaf key or CSR input.
> - A deterministic certificate with a fixed validity window has no defined
>   renewal or trust-store rollover path.

## Context

Internal services (maistro-server, hive-conductor backend, agent-to-agent HTTP, foreign
harness sessions) need TLS between components without depending on an external CA or manual
certificate management. ADR-026 specifies deriving a local Certificate Authority from the
`ConductorSeed` HD root, so trust bootstraps from the same seed already backing agent identity
and signing — no separate CA key to generate, back up, or lose track of.

The `cryptography` library (already a `maistro-core` dependency) provides native X.509
generation, so this closes the ADR without adding a new dependency.

## Goals

- Derive a CA keypair deterministically from `ConductorSeed` via a dedicated derivation path
  (domain-separated from signing/identity/wallet paths).
- Mint leaf X.509 certificates signed by that CA for internal service TLS.
- 90-day leaf rotation: a leaf approaching expiry is reissued automatically; the CA itself is
  long-lived (not rotated on the same schedule).
- Name constraints on the CA so it cannot mint certificates for arbitrary public internet
  domains (scoped to internal `.local`/`.internal`/configured suffixes only) — limits blast
  radius if the CA key were ever misused.

## Non-goals

- QR-code trust-ceremony UI (how a new device learns the CA's fingerprint) — that's a
  hive-conductor frontend concern; this SPEC documents the manual fingerprint-verification
  step as a stopgap.
- HSM/secure-enclave protection of the CA private key — the CA key is derived on-demand from
  the seed (via `SecretStore`, SPEC-070626-17d0) like any other derived key; no hardware
  protection in this environment.
- Public CA / ACME / Let's Encrypt integration — this is strictly an internal trust root.

## Decision

### CA key derivation

```python
# maistro/identity/local_ca.py

_CA_PATH = "m/44'/9001'/0'"  # domain-separated from _PATHS["signing"]/wallet/identity paths

def derive_ca_key(seed: ConductorSeed) -> DerivedKey:
    """The CA's Ed25519 keypair, deterministically derived. Same seed always
    produces the same CA key — no separate CA key material to generate or lose."""
    return seed.derive(_CA_PATH)
```

### CA certificate construction

```python
@dataclass(frozen=True)
class LocalCA:
    certificate: x509.Certificate       # self-signed CA cert (cryptography.x509)
    private_key: Ed25519PrivateKey

def build_ca(
    seed: ConductorSeed,
    *,
    allowed_suffixes: tuple[str, ...] = (".internal", ".local"),
    validity_years: int = 10,
) -> LocalCA:
    """Self-signed CA certificate with a Name Constraints extension restricting
    it to allowed_suffixes (RFC 5280 permitted subtrees, DNS name form).
    A CA built this way cannot validly mint a cert for e.g. "example.com"."""

def mint_leaf(
    ca: LocalCA,
    *,
    common_name: str,          # must match one of ca's allowed_suffixes
    san_dns_names: tuple[str, ...],
    validity_days: int = 90,
) -> x509.Certificate:
    """Mint and sign a leaf certificate. Raises NameConstraintViolationError
    if common_name/SANs fall outside allowed_suffixes (checked before signing,
    not just relying on the CA cert's own constraint enforcement by clients)."""
```

### Rotation

```python
@dataclass(frozen=True)
class RotationPolicy:
    rotate_within_days: int = 14   # reissue when < 14 days remain on a 90-day leaf

def needs_rotation(leaf: x509.Certificate, policy: RotationPolicy, *, now: datetime) -> bool:
    """True when leaf.not_valid_after - now < policy.rotate_within_days."""

async def rotate_leaf(
    ca: LocalCA, leaf: x509.Certificate, *, policy: RotationPolicy, now: datetime
) -> x509.Certificate | None:
    """Returns a freshly minted leaf (same CN/SANs, new validity window) if
    needs_rotation is True, else None (no-op)."""
```

The CA certificate itself uses a long validity (`validity_years`, default 10) and is not
subject to the 90-day rotation policy — only leaves rotate. Re-deriving `build_ca` from the
same seed always reconstructs the identical CA cert (deterministic serial/validity window
derived from the seed + a fixed epoch), so the CA does not need separate persistence beyond
the seed itself.

## Acceptance criteria

- [ ] `derive_ca_key(seed)` is deterministic: calling it twice on seeds reconstructed from the
      same mnemonic produces identical keys (property test).
- [ ] `build_ca` produces a self-signed certificate with `basicConstraints.ca=True` and a
      Name Constraints extension containing exactly `allowed_suffixes`.
- [ ] `mint_leaf` for a `common_name`/SAN within `allowed_suffixes` succeeds and produces a
      certificate that validates against the CA (via `cryptography`'s own verification, or a
      hand-rolled chain-of-trust check) with `not_valid_after - not_valid_before` == 90 days
      by default.
- [ ] `mint_leaf` for a name outside `allowed_suffixes` raises `NameConstraintViolationError`
      before any certificate is signed (property: no leaf is ever minted for a disallowed
      name).
- [ ] `needs_rotation` returns `True` only when fewer than `rotate_within_days` remain
      (boundary tests at exactly the threshold).
- [ ] `rotate_leaf` on a certificate that doesn't need rotation returns `None`; on one that
      does, returns a new certificate with the same CN/SANs and a fresh 90-day window.

## Testing

- Unit: CA derivation determinism, name-constraint enforcement (allowed and disallowed cases),
  leaf minting shape (validity window, CN/SAN correctness).
- Unit: rotation boundary conditions (exactly at threshold, well before, well after).
- Property (Hypothesis): for any generated seed and any DNS name, minting succeeds iff the name
  is within `allowed_suffixes`; the resulting leaf, when it succeeds, always validates against
  the CA.
- Integration: mint a leaf, use it to serve TLS on a local socket (e.g. via `ssl.SSLContext`),
  confirm a client trusting the CA cert connects successfully and a client that doesn't trust
  it rejects the connection.

## Open questions

- QR trust-ceremony UI is explicitly out of scope (Non-goals); the interim distribution
  mechanism is documented as "operator manually copies/verifies the CA fingerprint" — revisit
  once a UI surface exists.
- Whether leaf rotation should be push-driven (a background task per SPEC-070226-b234's
  durable event/trigger machinery) or pull-driven (checked lazily on each TLS context
  construction) — leaning pull-driven for v1 (simpler, no new background loop), revisit if a
  service needs push-based renewal notifications.

## References

- [ADR-026: Internal Trust Root](../adr/ADR-026-internal-trust-root.md)
- [ADR-021: Conductor Seed](../adr/ADR-021-conductor-seed.md)
- `packages/maistro-core/src/maistro/identity/__init__.py` (`ConductorSeed`, `_PATHS`)
- [ADR-077: Web and Session Security](../adr/ADR-077-web-session-security.md)
