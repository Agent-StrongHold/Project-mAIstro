---
id: ADR-101826-2a63
title: "Biscuit verification adapter — biscuit-python on the Ed25519 identity substrate"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-18
substrate:
  - maistro-engine#ADR-090726-9a4e
  - maistro-engine#ADR-024
  - maistro-engine#ADR-039
implements: []
related:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-077
  - maistro-engine#ADR-083026-6c72
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
    date: 2026-10-18
    reason: "Decision gate (issue #1838): adapter selected and contract drafted with pinned evidence; architecture/security owner acceptance is required before this becomes authority."
---

# ADR-101826-2a63: Biscuit verification adapter — biscuit-python on the Ed25519 identity substrate

## Context

[ADR-090726-9a4e](ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-biscuit-hash-chain.md)
accepted the Hybrid: WebAuthn presence (Leg 1), Biscuit delegated authority (Leg 2),
hash-chained evidence (Leg 3). Leg 2 names the *format* — attenuable, caveat-first,
offline-verifiable Ed25519 capability tokens — but not the *library* that mints, attenuates
and verifies them. Issue #1838 is the owner decision gate for that one contract: select the
concrete maintained Biscuit library/version and its mint/attenuate/verify calls on the
already-accepted Ed25519 identity substrate. The Biscuit-vs-alternatives choice is not
reopened here; it is settled by the accepted Hybrid ADR.

Source examined: `01b3b363b02c82fb8914536eee18a1d748eee68e`. Revalidated against this
repository's implementation head `31d891a561dffd6db1312ea4a85c4835c8048440`: no Biscuit
dependency, import, or adapter module exists anywhere under `packages/` today (verified by
tree search at that head), so this contract has no predecessor implementation to reconcile
with. All upstream library evidence below was re-fetched on 2026-10-18.

## Decision (proposed — owner acceptance outstanding)

Adopt **`biscuit-python` 0.4.0** — the official Python binding of the Biscuit
authorization-token platform — as the only Biscuit implementation this engine uses, imported
as **`biscuit_auth`**, pinned exactly, Ed25519-only, behind a single adapter module.

| Property | Selected value | Evidence (checked 2026-10-18) |
|---|---|---|
| Distribution | `biscuit-python==0.4.0` (exact pin) | PyPI release uploaded 2025-09-26; import package `biscuit_auth` |
| Implementation core | Rust reference implementation `biscuit-auth` 6.0.0 | Binding's `Cargo.toml`: `biscuit-auth = { version = "6.0.0", features = ["pem"] }`; the Rust crate *is* the reference implementation maintained by the Biscuit project |
| Stewardship | Eclipse Biscuit project | Repository `biscuit-auth/biscuit-python` redirects to `eclipse-biscuit/biscuit-python` (GitHub API "Moved Permanently"); not archived; last push 2026-09-27; documentation at `python.biscuitsec.org` |
| Algorithm | Ed25519 only | Key material uses the `ed25519/` and `ed25519-private/` prefixed hex forms; matches ADR-024's `did:key`/Ed25519 substrate. Upstream 6.x also supports P256; P256 is out of scope for this adapter (see Out of scope) |
| License | Apache-2.0 | Repository `LICENSE` (Apache License 2.0); compatible with the engine's Apache-2.0 |
| Platform | Prebuilt CPython wheels incl. cp312 `manylinux_2_17_x86_64` and `musllinux_1_2_x86_64` | PyPI 0.4.0 file manifest; matches the repo's Python 3.12 + Ubuntu target with no local Rust toolchain requirement |
| Transitive surface | Zero Python-level runtime dependencies | PyPI metadata `requires_dist: None`; the Rust core is statically compiled into the wheel (PyO3), so there is no Python transitive dependency graph to audit |
| Typing | Ships type stubs | `biscuit_auth.pyi` in the binding repository (added in 0.3.0); note: at the pinned revision the stub lags the extension — `set_time`/`set_limits` exist in `src/lib.rs` but not yet in the `.pyi` — so the adapter carries a narrow local stub override for those two methods (no code, signatures only) |
| Dependency owner | `@BlakeMatthews-dev` | Sole owner of the pin and of every version-bump review, per the owners of ADR-090726-9a4e and ADR-039 |

Maintainer-signal gate ([ADR-039](ADR-039-external-library-adoption-policy.md) §3): the
engine row of the per-repo policy applies the stronghold bar to new imports.

| Signal | Verdict | Evidence |
|---|---|---|
| Organizational backing | Pass | Eclipse Foundation project org (`eclipse-biscuit`); the binding, the Rust reference implementation, and sibling Go/Java/WASM bindings are governed as one ecosystem rather than a solo project |
| Activity | Pass | Binding 0.4.0 released 2025-09-26; repository last pushed 2026-09-27; upstream reference `biscuit-auth` `main` carries unreleased post-6.0.0 work (crypto trait refactor, `KeyPair` removed), showing a live core |
| License compatibility | Pass | Apache-2.0, same as the engine |
| Open-issue health | Pass | Not archived; 18 open issues; SECURITY.md and CODE_OF_CONDUCT.md present |
| Test coverage | Pass | Binding ships a test suite plus the official token vector corpus (`samples/`); CI workflows present in-repo |
| Transitive deps | Pass | None at the Python level (see table above); Rust-side dependencies compile into the wheel and are the reference implementation's own audited closure |

Known upstream security history is *before* the pinned version: GHSA-rgqv-mwc3-c78m was
fixed in `biscuit-auth` 5.0.0; the pin is 6.0.0, so the advisory is already remediated in the
selected version.

Rejected alternatives:

- **Bespoke PyO3/FFI binding of `biscuit-auth` ourselves** — re-owns the exact boundary
  `biscuit-python` already maintains; new unsafe-FFI audit surface for zero capability gain.
- **`biscuit-wasm`** — a WASM/JS binding; wrong host for a Python server process.
- **Pure-Python reimplementation of the Biscuit format** — reimplements signature
  verification and the binary format, which this task and the accepted architecture
  explicitly prohibit.
- **The bare `biscuit` PyPI name** — an unrelated web-framework package (0.0.1); recorded as
  a namespace hazard. The dependency line must read `biscuit-python`, never `biscuit`.

Version pin policy: the implementation task adds `biscuit-python==0.4.0` to
`packages/maistro-core`'s dependencies, resolved through `uv lock` with hash pinning per
ADR-039 §4. Minor/patch upgrades that stay on the 6.x core may be treated as maintenance;
anything that moves the core (upstream `main` has already removed `KeyPair` and generalized
the crypto trait layer in unreleased post-6.0.0 work — no 7.x release exists on crates.io as
of 2026-10-20, so the next core release will be a new major line) or changes the format
contract is a new owner decision, not a routine bump.

## Interface (the adapter contract)

Exact module path: **`packages/maistro-core/src/maistro/capabilities/biscuit_adapter.py`**.
That module is the only place in the engine permitted to import `biscuit_auth`; every other
module consumes the adapter's functions. Nothing else about the library leaks.

The adapter exposes exactly three operations, mapping 1:1 onto the binding's calls:

### Mint

```python
token = BiscuitBuilder(datalog, params).build(private_key)   # signs the authority block
token = token.append(BlockBuilder(checks_datalog, params))   # initial narrowing, if any
wire = token.to_base64()                                     # opaque carrying form
```

- The authority block carries the delegated capability facts (subject, action, resource
  scope, approval digest, issued-at, expires-at) and their `check if ...` caveats.
- When the workspace identity record carries a rotation key id, `set_root_key_id(k)` is used
  at mint time so verifiers can select the right public key during rotation.

### Attenuate

```python
narrowed = token.append(BlockBuilder("check if ...", params))
```

- Attenuation appends **checks only** — never facts that widen, never `allow` policies, and
  never `merge`/`append_third_party`/`third_party_request` (third-party blocks are out of
  scope until a separate owner decision accepts a third-party seam).
- A Biscuit is cryptographically incapable of widening by append; the adapter keeps the
  builder surface restricted so a caller cannot be handed a minting builder mid-chain.

### Verify (fail-closed)

```python
token = Biscuit.from_base64(wire, public_key_or_key_selector)
authorizer_builder = AuthorizerBuilder(policies, params)
authorizer_builder.set_time()               # no argument: stamps the host clock
authorizer_builder.set_limits(pinned_limits)  # AuthorizerLimits(max_facts, max_iterations, max_time)
authorizer = authorizer_builder.build(token)
policy_id = authorizer.authorize()          # raises on any failure
```

- Verification runs signature (whole chain), caveat/check evaluation, scope checks, expiry
  (via the `time($t) < expiration` facts and `set_time`), and revocation (below) before any
  effect is authorized. **Every** exception type the binding can raise — `AuthorizationError`,
  `BiscuitValidationError`, `BiscuitSerializationError`, `BiscuitBuildError`,
  `BiscuitBlockError`, `DataLogError`, or any other error — maps to DENY. A verify call never
  interprets an error into an allow.
- `set_limits` is pinned to bounded facts/rules/checks/loop values at the adapter so a
  hostile token cannot spend unbounded authorizer work.
- `UnverifiedBiscuit` may be used only to read `revocation_ids` / `block_source` for
  inspection and revocation bookkeeping. It is never an authorization basis; enforcement
  always re-verifies with `Biscuit.from_base64(...)` + `Authorizer`.
- Revocation: each block's revocation id (`token.revocation_ids`) is checked against the
  workspace revocation register before `authorize()` is called; a registered revocation id
  denies regardless of unexpired caveats (ADR-077's live-revocation rule).
- `set_time()` takes **no argument** (binding revision `a505042e`, `src/lib.rs`: it adds the
  `time($now)` ambient fact from the verifier host's own clock) — there is deliberately no
  clock parameter to inject, so server-time policy is the host clock and the adapter never
  lets a token- or caller-supplied clock stand in for the authorizer's. Expiry checks
  evaluate against that fact.

### Key binding to the accepted identity substrate

No key is generated, stored, or lifecycle-managed here. Key material comes from the accepted
identity substrate — `ConductorSeed` (ADR-021, `maistro.identity._crypto`, ADR-024 `did:key`
Ed25519). The adapter performs only these mechanical mappings:

| Substrate form | Binding form |
|---|---|
| raw 32-byte Ed25519 private key (SLIP-0010-derived at a named path) | `PrivateKey.from_bytes(raw)` |
| raw 32-byte Ed25519 public key (`DerivedKey.public_key`) | `PublicKey.from_bytes(raw)` |
| `did:key:z...` (multicodec `0xed 0x01` prefix + base58btc body) | strip prefix, base58-decode → raw 32 bytes → `PublicKey.from_bytes` |

The biscuit root keypair for a workspace is the substrate's Ed25519 key at the delegation
path the approval contract names; the adapter takes already-derived raw bytes and never
touches mnemonics. `did:key` remains the public identity form; the `ed25519/`-prefixed hex
form is the adapter's internal representation only.

## Test vectors

The binding vendors the platform's official conformance vectors, and the adapter contract
pins them at an exact upstream revision:

- Source: `eclipse-biscuit/biscuit-python`, revision
  `a505042ec9ded701f8a9f6374c39b038ec41947a` (`main` as of 2026-09-27), files
  `samples/samples.json` + `samples/test1_basic.bc` … `test21_parsing.bc`.
- Integrity anchor: `samples.json` SHA-256
  `460b3d543fc1e3933144b7d982c4fb3dc22ca79f219a1309bb202c357e45c492` (33,702 bytes,
  21 test cases), root public key
  `acdd6d5b53bfee478bf689f8e012fe7988bf755e3d7c5152947abc149bc20189`.
- Coverage the vector set provides: valid basic token; alternate root key id; invalid
  signature (and invalid signature *format*); random/garbage block; reordered blocks;
  scoped rules; scoped checks; expired token; authorizer scope; authorizer authority
  checks; authority-scoped checks; block rules; regex constraints; multi-query checks;
  check-head/fact-name independence; expression operators; unbound variables in rules;
  authority/ambient symbol generation ban; sealed tokens; parsing.

Adapter-level vector requirements (assigned with the implementation task, below): the
implementation test loads this exact corpus and asserts each case's `validations` outcome
through the adapter's verify path — including the negative cases, which must reach DENY
through the adapter's error mapping, not through a test-side try/except. Any transition
vectors specific to this engine's delegation datalog profile (approval-digest caveats,
expiry-at-boundary, attenuation chains) are added in that test file with expectations
reviewed by the dependency owner; they do not replace the upstream corpus.

## Acceptance criteria

Layered contracts per [ADR-032](ADR-032-contracts-as-acceptance-criteria.md). **This
document records a proposed contract; no implementation test is claimed by it.** The `tests:`
front-matter field stays empty and `ac-modules` anchors are added only when the owner accepts
this contract and an implementation task is assigned — anchors may not name modules that do
not exist.

- **AC-1 (boundary)**: `biscuit_auth` is imported in exactly one module,
  `maistro.capabilities.biscuit_adapter`; the dependency line pins
  `biscuit-python==0.4.0` exactly (no floating ranges).
- **AC-2 (behavioral)**: mint produces a token whose base64 form verifies at
  `Biscuit.from_base64` + `AuthorizerBuilder(...).build(token).authorize()` with the paired
  public key; the authority block carries subject, action, resource scope, approval digest,
  issued-at and expires-at facts.
- **AC-3 (behavioral)**: attenuation appends checks only; an attenuated token still
  verifies within the narrowed scope and fails (DENY) outside it; no adapter path can add
  `allow` policies or third-party blocks to an existing token.
- **AC-4 (behavioral, fail-closed)**: every binding exception (`AuthorizationError`,
  `BiscuitValidationError`, `BiscuitSerializationError`, `BiscuitBuildError`,
  `BiscuitBlockError`, `DataLogError`, unexpected errors) maps to DENY; an expired token, a
  token with a registered revocation id, and a token with an invalid signature are each
  denied by the adapter.
- **AC-5 (behavioral, vectors)**: the pinned upstream corpus (revision and SHA-256 above)
  reproduces its declared outcomes through the adapter's mint/attenuate/verify path,
  negatives included.
- **AC-6 (behavioral, key binding)**: keys flow only from the identity substrate; the
  `did:key` ↔ raw-32-byte mappings round-trip; the adapter generates no key material and
  accepts no mnemonic.

## Test plan (assigned with implementation — not claimed by this document)

| Test | Type | Covers |
|---|---|---|
| `packages/maistro-core/tests/capabilities/test_biscuit_adapter.py` | boundary / behavioral | AC-1…AC-6 against the pinned binding and vector corpus |

The implementation change adds the campaign-required inventory note for that test file.

## Dependencies

- [ADR-090726-9a4e](ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-biscuit-hash-chain.md)
  (Accepted) — the Hybrid this adapter implements Leg 2 of. Not modified by this document.
- [ADR-024](ADR-024-agent-identity-did-vc.md) / ADR-021 (Accepted) — the Ed25519
  `did:key` substrate the key mapping binds to.
- [ADR-039](ADR-039-external-library-adoption-policy.md) (Accepted) — the maintainer-signal
  gate and supply-chain controls this adoption is filed under.
- ADR-068 / ADR-077 / ADR-083026-6c72 (Accepted) — the authorization, live-revocation and
  canonical-settlement seams the adapter serves; the adapter introduces no new execution
  authority and no second approval path.

## Out of scope

- The WebAuthn verification adapter (sibling gate, issue #1837) and the exact-effect payload
  byte freezing (issue #1836).
- Third-party (externally signed) attenuation blocks; P256 or any non-Ed25519 algorithm;
  key generation, rotation scheduling, or key lifecycle policy (ADR-021/022/024 own those).
- The delegation datalog profile's concrete caveats and TTL defaults — invented only in the
  implementation task this contract gates, with owner review.
- Any change to the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` execution model;
  the adapter is evidence plumbing behind the `GovernedInvocation` boundary, not an
  authority.

## Decision acceptance record (to be completed by the owner — the gate is open)

This contract becomes authority only when the ADR owner `@BlakeMatthews-dev`, or an
explicitly designated architecture/security reviewer, accepts it. The acceptance history
entry must record: the reviewed document section(s), the exact revision (git SHA of this
file) reviewed, the reviewer, and the decision link (review/issue reference). Until that
entry exists this document's status remains `Proposed`, issue #1838 remains open, and
downstream implementation leaves stay blocked. A green hygiene command cannot resolve this
decision; neither can this document's own syntax.

## Source references

- PyPI `biscuit-python` 0.4.0 metadata and wheel manifest (fetched 2026-10-18).
- `eclipse-biscuit/biscuit-python`: `Cargo.toml` (`biscuit-auth = "6.0.0"`, `pem` feature),
  `CHANGELOG.md`, `LICENSE` (Apache-2.0), `samples/` vector corpus at revision
  `a505042ec9ded701f8a9f6374c39b038ec41947a`.
- Official binding documentation: `python.biscuitsec.org` (basic use and API reference;
  fetched 2026-10-18).
- `packages/maistro-core/src/maistro/identity/_crypto.py` — the `ConductorSeed` substrate
  the key mapping binds to.
- `packages/maistro-core/src/maistro/capabilities/approval_store.py` — the approval seam
  the delegated capabilities will reference (approval digest).

## Links

- Issue: #1838 (this decision gate; remains open until owner acceptance)
- Parent: #329 — M1-D6 crypto-bound approvals
- Governing ADR: ADR-090726-9a4e (Accepted; preserved unmodified by this document)
