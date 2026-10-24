---
id: SPEC-257
title: "Code registry — signed entry resolution, semver compatibility, fail-closed refs (ADR-069)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-028
related:
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-053
  - maistro-engine#ADR-054
  - maistro-engine#ADR-056
  - maistro-engine#ADR-068
implements:
  - maistro-engine#ADR-069
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/code_registry/test_registry.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-257: Code registry — signed entry resolution, semver compatibility, fail-closed refs

## Context

ADR-050, ADR-051, ADR-053, and ADR-056 all lean on a "code registry" that resolves `name@version`
refs to executable code, but none defines it. ADR-069 resolves the dangling abstraction and,
centrally, requires that registered code execute inside a microVM (Hyperlight or equivalent) under
the ADR-068 authorization envelope. This SPEC scopes the part of ADR-069 that is pure and testable
without that infrastructure: the registry's entry model, signature verification, `resolve()`/
`compatible()` lookup contract, and the fail-closed behavior on unversioned/missing/unsigned refs.
The microVM execution harness, Sentinel/Warden routing, and resource caps depend on substrate
(ADR-054 sandbox tiers, ADR-068 authorization) that isn't implemented yet — see Non-goals.

## Goals

- Add `maistro/code_registry/types.py`: `CodeKind` (`StrEnum`: `COMPENSATOR`, `IMPACT_ESTIMATOR`,
  `IDEMPOTENCY_KEY`, `MERGE_RESOLVER`, `DYNAMIC_GATE`), `CodeEntry` (frozen dataclass: `name: str`,
  `version: str`, `kind: CodeKind`, `code_sha256: str`, `signature: bytes`, `trusted: bool =
  False`), `CodeRefUnresolved` (exception), `InvalidSignature` (exception).
- Add `maistro/code_registry/verify.py`: `SignatureVerifier` (`Protocol`: `verify(message: bytes,
  signature: bytes) -> bool`) and `Ed25519Verifier` (a concrete implementation wrapping
  `cryptography.hazmat.primitives.asymmetric.ed25519`, given a raw public key) — protocol-driven so
  the registry depends on the abstraction, consistent with maistro-core's DI convention; the
  registry's signed payload is `f"{name}@{version}:{code_sha256}".encode()`.
- Add `maistro/code_registry/registry.py`: `CodeRegistry` — an in-memory, store-agnostic registry:
  - `register(entry: CodeEntry, *, verifier: SignatureVerifier) -> None` — verifies
    `entry.signature` against the canonical signed payload via `verifier.verify(...)`; raises
    `InvalidSignature` and refuses to store the entry if verification fails. Unversioned names
    (`version == ""` or no `@` separator implied by the ref grammar — see `resolve`) are refused at
    registration too (ADR-053's "unversioned refs refused" applies at both load and resolve time).
  - `resolve(ref: str) -> CodeEntry` — parses `"name@version"`; raises `CodeRefUnresolved` if the
    ref has no `@version` suffix, or if no matching registered entry exists. Never returns `None`.
  - `compatible(base_ref: str, overlay_ref: str) -> bool` — semver compare on the two refs'
    versions: same major version is compatible (`v2.x` accepts `v2.y` regardless of minor/patch
    direction); differing major version is incompatible. Raises `CodeRefUnresolved` if either ref
    fails to parse as `name@semver`.
- `CodeEntry.trusted` is accepted and stored as-is (caller-asserted) — this SPEC does not derive
  trust from anything; that derivation (engine-signing-key check) is part of the execution harness
  in Non-goals.

## Non-goals

- The microVM execution harness (`invoke()`, Hyperlight/Firecracker integration, `isolation`
  labelling, resource-cap enforcement) — ADR-069's security core, but it requires a real microVM
  runtime dependency and the ADR-054 sandbox-tier budget machinery; follow-up once that
  infrastructure exists. This SPEC defines the registry `invoke()` will call `resolve()` on.
- Routing `invoke()` through Sentinel/Warden (ADR-068) — ADR-068 itself has no tier ladder or
  RLPHD predictor implemented yet (see backlog); this SPEC's registry is usable standalone and
  the execution harness will wire the ADR-068 envelope around it once that substrate exists.
- Deriving `trusted` from "signed by the engine's own key" vs. an admin/operator key — this SPEC
  takes `trusted` as a caller-supplied flag on `CodeEntry`; the policy for *which* signer implies
  `trusted=True` is an execution-harness concern once real key management (ADR-028 pattern) is
  wired to this module.
- Persistence (`code_entries` table) — in-memory dict only in this SPEC, consistent with the
  store-agnostic-core pattern used by SPEC-254/255/256.
- ADR-070 Repertoire Pattern — related but independent; tracked as a separate SPEC.
- `compensator`/`impact_estimator` body authoring and ADR-050/051 call-site wiring — those ADRs'
  own scope, not this registry's.
- Event/span/metric wiring (ADR-037) — follow-up once an event-bus call site invokes this module.

## Decision

```python
# maistro/code_registry/types.py
class CodeKind(StrEnum):
    COMPENSATOR = "compensator"
    IMPACT_ESTIMATOR = "impact_estimator"
    IDEMPOTENCY_KEY = "idempotency_key"
    MERGE_RESOLVER = "merge_resolver"
    DYNAMIC_GATE = "dynamic_gate"

@dataclass(frozen=True)
class CodeEntry:
    name: str
    version: str
    kind: CodeKind
    code_sha256: str
    signature: bytes
    trusted: bool = False

class CodeRefUnresolved(Exception): ...
class InvalidSignature(Exception): ...

# maistro/code_registry/verify.py
class SignatureVerifier(Protocol):
    def verify(self, message: bytes, signature: bytes) -> bool: ...

class Ed25519Verifier:
    def __init__(self, public_key: bytes) -> None: ...
    def verify(self, message: bytes, signature: bytes) -> bool: ...

# maistro/code_registry/registry.py
class CodeRegistry:
    def register(self, entry: CodeEntry, *, verifier: SignatureVerifier) -> None: ...
    def resolve(self, ref: str) -> CodeEntry: ...
    def compatible(self, base_ref: str, overlay_ref: str) -> bool: ...
```

## Acceptance criteria

- [x] `resolve("name@version")` returns the registered entry for an exact match.
- [x] `resolve()` raises `CodeRefUnresolved` for an unversioned ref (no `@version` suffix) — never
      returns `None`.
- [x] `resolve()` raises `CodeRefUnresolved` for a ref with no matching registered entry.
- [x] `register()` raises `InvalidSignature` and does not store the entry when
      `verifier.verify(...)` returns `False`.
- [x] `register()` raises (refuses) for an entry with no version component.
- [x] `Ed25519Verifier.verify` returns `True` for a signature produced by the matching private key
      over the canonical payload, and `False` for a tampered payload or wrong key.
- [x] `compatible("name@2.1.0", "name@2.9.0")` is `True` (same major); `compatible("name@2.1.0",
      "name@3.0.0")` is `False` (major bump).
- [x] `compatible()` raises `CodeRefUnresolved` if either ref is malformed (no version, not valid
      semver).

## Testing

- `packages/maistro-core/tests/code_registry/test_registry.py` (new) — `CodeEntry`/`CodeKind`
  shape, `Ed25519Verifier` round-trip (real key generation via `cryptography`, no mocking),
  `register()` signature-refusal and unversioned-refusal matrix, `resolve()` matrix (exact match,
  unversioned, unknown), `compatible()` semver matrix across major/minor/patch combinations.

## Open questions

- Whether `compatible()` should also reject a *downgrade* (overlay version less than base version)
  within the same major — deferred; ADR-053's stated contract only specifies major-version
  compatibility, not directionality. Revisit once a real overlay-merge call site needs it.

## References

- [ADR-069: Code Registry](../adr/ADR-069-code-registry.md)
- [ADR-050: Tool reversibility taxonomy](../adr/ADR-050-tool-reversibility-taxonomy.md)
- [ADR-053: Recipe overlay composition](../adr/ADR-053-recipe-overlay-composition.md)
- [SPEC-252: Tool reversibility taxonomy](SPEC-252-tool-reversibility-taxonomy.md)
