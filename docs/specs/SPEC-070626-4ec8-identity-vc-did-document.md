---
id: SPEC-070626-4ec8
title: "W3C-shaped VerifiableCredential and DIDDocument types over the existing did:key identity"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-024
  - maistro-engine#SPEC-070226-6489
implements:
  - maistro-engine#ADR-024
related:
  - maistro-engine#ADR-026
  - maistro-engine#ADR-029
  - maistro-engine#SPEC-005
  - maistro-engine#SPEC-018
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
  - cross-service
tests: []
layer: Identity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070626-4ec8: W3C-shaped VerifiableCredential and DIDDocument types

## Context

`maistro.identity.lifecycle` (SPEC-070226-6489, ADR-084) ships `AgentIdentity` (did:key) and
`CapabilityToken` — a JWT-like, Ed25519-signed authority grant. That closes ADR-084's
agent-to-agent delegation need, but ADR-024 asks for more: a general-purpose
`VerifiableCredential`/`DIDDocument` surface that other specs already assume exists — signed
audit-log entries (SPEC-005 publisher VCs), federation trust credentials (SPEC-018), and
plugin-publisher signing.

This SPEC adds W3C-VC-*shaped* types (the core `@context`/`type`/`credentialSubject`/`proof`
envelope) layered over the existing did:key infrastructure, without pulling in a full JSON-LD
processor or DIDComm stack.

## Goals

- `VerifiableCredential` and `DIDDocument` dataclasses matching the W3C VC/DID Core data model
  shape closely enough to be recognizable and forward-compatible with real JSON-LD tooling,
  without requiring one.
- `issue_vc()` / `verify_vc()` functions building on the same Ed25519 signing already used by
  `CapabilityToken` — one signing primitive, two credential shapes (narrow capability grant vs.
  general-purpose claim).
- `DIDDocument.from_identity(AgentIdentity)` — the did:key resolves to a self-describing
  document (verification method, public key) without a network call, matching did:key's
  "resolve from the identifier itself" property.
- A `did:web` document *type* (see SPEC-070626-a675 for the resolver/substrate side) so VCs can
  name either did:key or did:web subjects/issuers uniformly.

## Non-goals

- Full JSON-LD processing (context expansion/compaction, RDF canonicalization) — the `@context`
  field is carried as data, not interpreted; verification is over a fixed canonical JSON
  serialization of the credential, not JSON-LD normalization.
- DIDComm v2 messaging — out of scope; this is the credential *shape*, not a messaging protocol.
- Real did:web network resolution (HTTP GET to `/.well-known/did.json`) — that's
  SPEC-070626-a675's substrate/resolver concern; this SPEC only defines the document shape.

## Decision

### VerifiableCredential and DIDDocument shapes

```python
# maistro/identity/vc.py

@dataclass(frozen=True)
class VerifiableCredential:
    """W3C VC Core-shaped credential. Canonical form (context+type+subject+issuer+
    issuance/expiration, sorted keys, no proof field) is what gets signed."""
    context: tuple[str, ...]                  # ("https://www.w3.org/ns/credentials/v2",)
    id: str                                    # e.g. "urn:uuid:..."
    type: tuple[str, ...]                      # ("VerifiableCredential", "AuditLogEntry")
    issuer: str                                # issuer DID
    credential_subject: dict[str, Any]         # the claim payload
    issuance_date: str                         # ISO-8601
    expiration_date: str | None = None
    proof: "Proof | None" = None                # set by issue_vc, absent before signing

@dataclass(frozen=True)
class Proof:
    type: str                                  # "Ed25519Signature2020"
    created: str                                # ISO-8601
    verification_method: str                    # issuer DID + key fragment, e.g. "did:key:z6Mk...#key-1"
    proof_purpose: str                          # "assertionMethod"
    proof_value: str                            # base64/base58-encoded signature bytes

@dataclass(frozen=True)
class VerificationMethod:
    id: str                                     # DID + fragment
    type: str                                   # "Ed25519VerificationKey2020"
    controller: str                              # the DID this key belongs to
    public_key_multibase: str                    # multibase-encoded raw public key

@dataclass(frozen=True)
class DIDDocument:
    context: tuple[str, ...]
    id: str                                      # the DID itself
    verification_method: tuple[VerificationMethod, ...]
    authentication: tuple[str, ...]              # verification_method ids usable for auth
    assertion_method: tuple[str, ...]            # verification_method ids usable for VC issuance

    @staticmethod
    def from_identity(identity: AgentIdentity) -> "DIDDocument":
        """did:key resolves to itself — no network call. Single verification
        method derived from the did:key's embedded public key."""
        ...

    @staticmethod
    def for_did_web(did: str, public_key: bytes) -> "DIDDocument":
        """Construct the document a did:web resolver would publish at
        /.well-known/did.json for this DID."""
        ...
```

### Issue / verify

```python
async def issue_vc(
    issuer_identity: AgentIdentity,
    credential_subject: dict[str, Any],
    *,
    vc_type: tuple[str, ...],
    secret_store: SecretStore,
    expiration: datetime | None = None,
) -> VerifiableCredential:
    """Sign a canonical (context, type, issuer, subject, dates) tuple with the
    issuer's Ed25519 key (re-derived via secret_store, same pattern as
    issue_capability_token — private keys are never persisted). Returns the
    credential with `proof` populated."""

def verify_vc(vc: VerifiableCredential, *, now: datetime | None = None) -> bool:
    """Recompute the canonical form, verify proof.proof_value against the
    public key recovered from proof.verification_method's DID, and check
    expiration_date if present. Raises a typed VcError subclass on any
    failure (InvalidVcSignatureError, VcExpiredError, VcMalformedError) —
    never returns False silently, matching verify_capability_token's contract."""
```

Canonicalization: `(context, id, type, issuer, credential_subject, issuance_date,
expiration_date)` serialized as JSON with sorted keys and no whitespace — the same
"canonical form, not full JSON-LD normalization" tradeoff the Non-goals section names.

## Acceptance criteria

- [ ] `DIDDocument.from_identity(identity)` produces a document whose single verification
      method's public key matches `identity.public_key` (round-trip: encode the did:key,
      decode it back via the document, get the same bytes).
- [ ] `issue_vc` + `verify_vc` round-trips: a credential issued by identity A verifies
      successfully against A's DID.
- [ ] A tampered `credential_subject` (any field changed after issuance) fails verification
      with `InvalidVcSignatureError` (property test: any single-byte mutation of the signed
      canonical form is detected).
- [ ] `expiration_date` in the past fails verification with `VcExpiredError`, even with a valid
      signature.
- [ ] `DIDDocument.for_did_web(did, public_key)` produces a document shape resolvable by an
      HTTP client fetching `/.well-known/did.json` (shape-only test — no real HTTP call here).
- [ ] Existing `CapabilityToken`/`issue_capability_token`/`verify_capability_token` are
      unchanged — this SPEC adds a parallel credential type, it does not replace or modify the
      capability-token path.

## Testing

- Unit: DIDDocument construction from both did:key and did:web identities; verification method
  round-trip.
- Unit: issue_vc/verify_vc happy path, tampered subject, expired credential, wrong-issuer
  signature.
- Property (Hypothesis): any generated `credential_subject` dict issues and verifies
  successfully; any single-field mutation post-issuance fails verification.
- Reuses `InMemorySecretStore`/`InMemoryIdentityStore` fixtures already established in
  `tests/identity/test_lifecycle.py`.

## Open questions

- Whether `VerifiableCredential`/`DIDDocument` should be exposed as real JSON-LD (via a
  lightweight `pyld`-style dependency) in a later phase, for interop with external VC
  verifiers — deferred; the canonical-JSON approach is sufficient for maistro-internal
  consumers (audit VCs, federation trust, publisher signing) named by ADR-024.

## References

- [ADR-024: Agent Identity & Verifiable Credentials](../adr/ADR-024-agent-identity-did-vc.md)
- [ADR-021: Conductor Seed](../adr/ADR-021-conductor-seed.md)
- [SPEC-070226-6489: Identity lifecycle](SPEC-070226-6489-identity-lifecycle.md)
- [SPEC-070626-a675: Networking & identity substrate](SPEC-070626-a675-networking-identity-substrate.md) — did:web resolution
- W3C Verifiable Credentials Data Model v2 (shape reference, not a hard dependency)
