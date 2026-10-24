---
id: ADR-101826-c3f1
title: "WebAuthn verification adapter — py_webauthn (`webauthn` 3.0.1) as the candidate verifier for Hybrid Leg 1"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-10-18
substrate:
  - maistro-engine#ADR-090726-9a4e
  - maistro-engine#ADR-068
  - maistro-engine#ADR-039
implements: []
related:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-022
  - maistro-engine#ADR-083026-6c72
  - maistro-engine#ADR-081226-6b46
supersedes: []
blocks: []
blocked-by: []
# ADR-032's cross-check: `contracts:` kinds must be proven by marker-carrying
# tests listed in `tests:`. This document is an unaccepted decision candidate
# that claims no implementation test (see "Acceptance boundary"), so no kinds
# are declared yet — the accepting revision, together with its implementation
# task, declares them alongside the tests that prove them.
contracts: []
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-10-18
    reason: "Adapter contract drafted for the #1837 decision gate. Selecting and accepting a WebAuthn verification library is an ADR-owner decision; this document is the review candidate, not the acceptance."
---

# ADR-101826-c3f1: WebAuthn verification adapter — py_webauthn (`webauthn` 3.0.1) as the candidate verifier for Hybrid Leg 1

## Context

[ADR-090726-9a4e](ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-biscuit-hash-chain.md)
(accepted 2026-09-07) decided Leg 1 of the Hybrid: approvals that prove *human
presence* are finalized by a WebAuthn assertion whose challenge is the
`request_digest` of the exact effect. What the Hybrid deliberately did not
select is the **concrete Python library that performs registration and
assertion verification** — the WebAuthn library/RP/origin/user-verification
boundary. Issue #1837 is that decision gate.

State revalidated on 2026-10-18 against this repository:

- No WebAuthn code exists under `packages/*/src` (grep over all packages), and
  no `webauthn`/`fido2` distribution is locked. There is no predecessor
  implementation to reconcile.
- The engine floor is Python `>=3.12` (root `pyproject.toml`); the shared
  asymmetric-crypto substrate is already pinned:
  `packages/maistro-core` requires `cryptography>=50.0.0,<51`.
- Linked PR #1362 is closed and is not a vehicle for this contract; its
  subject (durable effect-context wiring) is unrelated to the WebAuthn seam.

This document is a **decision candidate**: it records the selected
library/version, the full adapter contract, and reproduction vectors so the
ADR owner can review and accept. It does not resolve the gate — acceptance is
the owner's recorded decision (#1837), and until then this ADR stays
`Proposed` and downstream leaves remain blocked.

## Decision (candidate)

Adopt **py_webauthn** — the `webauthn` distribution on PyPI, source
`https://github.com/duo-labs/py_webauthn`, version **3.0.1** — as the WebAuthn
verification adapter behind Hybrid Leg 1, wrapped by a first-party adapter
module so that `webauthn` remains the only new import and no production module
imports the library directly.

### Why this library (ADR-039 §3 maintainer-signal gate)

`maistro-engine` is a substrate repo under ADR-039 §1: new imports must
satisfy stronghold's bar, and ADR-039 §3's gate is exactly the evidence this
contract records. Evaluated against the published 3.0.1 artifact
(inspection date 2026-10-18):

| Signal | Evidence | Pass |
|---|---|---|
| Organizational backing | Authored and released by Duo Labs (`labs@duo.com`, Cisco/Duo Security) | ✔ |
| Activity | 3.0.1 released 2026-09-25; 2.7.1 (2026-02-11), 2.8.0 (2026-06-13), 3.0.0 (2026-06-29) — four releases inside 12 months | ✔ |
| License | `License-Expression: BSD-3-Clause` in the 3.0.1 wheel metadata — OSI-approved, compatible with the engine's Apache-2.0 cascade | ✔ |
| Open-issue health | Upstream repo active and maintained (not archived); multi-maintainer org project | ✔ |
| Tests | Upstream ships an HTTP-free unit suite exercising both verification calls; library is typed (`py.typed`) | ✔ |
| Transitive deps | `pyasn1>=0.6.2`, `pyasn1-modules>=0.4.2`, `cbor2>=6.1.2`, `cryptography>=49.0.0`, `pyOpenSSL>=26.3.0` — all established; `cryptography` already pinned by maistro-core (>=49 satisfied by the existing `>=50,<51` window; an ephemeral resolve of 3.0.1 selects 50.0.2, the same major the lock already carries) | ✔ |

### Alternatives considered

- **python-fido2 (Yubico), `fido2` 2.2.1 (2026-06-29, BSD-2-Clause)** —
  excellent and equally maintained, but it is a lower-level CTAP2/webauthn
  toolkit: an RP would have to assemble credential parsing, UP/UV flag
  policy, sign-count tracking, and attestation-format verification itself.
  Every one of those is a security decision this contract wants owned *once*,
  in one reviewed place. Kept as a pattern reference (ADR-039 §5), and as the
  natural source of a soft authenticator for test vectors — its role here is
  generating ceremonies, not verifying them.
- **The PyPI distribution literally named `py-webauthn`** — an unrelated
  project by a different maintainer (AS207960, `as207960/python-webauthn`,
  `certvalidator`/`requests`-based): releases 0.0.1–0.0.4 in 2021, then
  0.0.5/0.0.6 re-uploaded 2026-05-27 after the four-and-a-half-year gap —
  not the duo-labs library, and never a WebAuthn *verifier* this engine
  evaluated. Recorded deliberately: the dependency line must be
  `webauthn==3.0.1` from `duo-labs/py_webauthn`; installing `py-webauthn`
  would be a typosquat-class mistake (re-verified against PyPI
  2026-10-20).

## The contract (what the owner is asked to accept)

### Library identity

| Field | Value |
|---|---|
| Distribution | `webauthn` (PyPI) |
| Version | `3.0.1` (pin exact; install belongs to a later implementation task) |
| Source | `https://github.com/duo-labs/py_webauthn` |
| Wheel digest (3.0.1, `webauthn-3.0.1-py3-none-any.whl`) | `sha256:9927b2f530773bd1d7f8194cd643a2e634a20995ea31f2d8f7a3e70b11c93e31` |
| License | BSD-3-Clause |
| Requires | Python >=3.10 (engine floor 3.12 ✔) |
| Dependency owner | @BlakeMatthews-dev (ADR owner); additions go through ADR-039 §3 re-review on every version bump |

### Exact adapter module path

`packages/maistro-core/src/maistro/capabilities/webauthn.py` — module
`maistro.capabilities.webauthn`. It is the single seam between this engine
and the library: the only module permitted to `import webauthn`. Public
surface, all additive, no new execution authority:

- `verify_approval_registration(...) -> VerifiedRegistration` — thin,
  opinionated wrapper over `webauthn.verify_registration_response`.
- `verify_approval_assertion(...) -> VerifiedAuthentication` — wrapper over
  `webauthn.verify_authentication_response`.
- Credential persistence joins the existing durable `ApprovalStore`
  (`maistro.capabilities.approval_store`) and the settlement record stays the
  canonical write of ADR-083026-6c72; this module mints no authority.

### The two verification calls (verbatim 3.0.1 signatures)

Both are keyword-only; both fail closed by raising. The adapter forwards the
opinionated inputs below and never re-derives them from request data.

```python
webauthn.verify_registration_response(
    *,                                    # webauthn/registration/verify_registration_response.py
    credential: str | dict | RegistrationCredential,
    expected_challenge: bytes,
    expected_rp_id: str,
    expected_origin: str | list[str],
    require_user_presence: bool = True,   # adapter passes True explicitly
    require_user_verification: bool = False,  # adapter passes True for approvals
    supported_pub_key_algs: list[COSEAlgorithmIdentifier] = default_supported_pub_key_algs,
    pem_root_certs_bytes_by_fmt: Mapping[AttestationFormat, list[bytes]] | None = None,
) -> VerifiedRegistration  # credential_id, credential_public_key, sign_count,
                           # aaguid, fmt, credential_type, user_verified,
                           # attestation_object, credential_device_type,
                           # credential_backed_up
# raises webauthn.helpers.exceptions.InvalidRegistrationResponse

webauthn.verify_authentication_response(
    *,                                    # webauthn/authentication/verify_authentication_response.py
    credential: str | dict | AuthenticationCredential,
    expected_challenge: bytes,
    expected_rp_id: str,
    expected_origin: str | list[str],
    credential_public_key: bytes,         # stored at registration, never from the wire
    credential_current_sign_count: int,   # stored counter, never from the wire
    require_user_verification: bool = False,  # adapter passes True for approvals
) -> VerifiedAuthentication  # credential_id, new_sign_count, credential_device_type,
                             # credential_backed_up, user_verified
# raises webauthn.helpers.exceptions.InvalidAuthenticationResponse
```

What 3.0.1 checks inside those calls (verified by reading the release and by
the vectors below): credential `id`/`raw_id` equality; `type == "public-key"`;
`clientDataJSON.type` (`webauthn.create` / `webauthn.get`); challenge
byte-equality; origin equality (single string or allowlist); token-binding
status; RP-ID SHA-256 hash over authenticator data; UP flag on every
assertion (unconditional); UV when required; sign-count monotonicity
(replay); signature over `authenticatorData || SHA256(clientDataJSON)` against
the *stored* public key.

### RP / origin / user-verification inputs under the Hybrid

| Input | Contract |
|---|---|
| `expected_challenge` | The `request_digest` of the exact effect — Hybrid Leg 1 verbatim. The ceremony is bound to what is being approved, not to a session. Freshly generated per ceremony, single-use, persisted with the pending approval; expiry/replay handled by the ApprovalStore, never by the library. |
| `expected_rp_id` | Deployment configuration (e.g. `maistro.local`), resolved once per process, never from the HTTP request. |
| `expected_origin` | Deployment origin allowlist (e.g. `https://approvals.maistro.local`), again configuration, not request data. |
| `require_user_presence` | `True`, always, for approval ceremonies. |
| `require_user_verification` | `True`, always, for approval ceremonies. The library default is `False`; the adapter exists partly so that default can never leak into the approval path. An assertion with UP but not UV is a refusal, and `user_verified` in the result is recorded with the settlement as presence evidence. |
| `supported_pub_key_algs` | Exactly `[-7, -8, -257]` (see below). |
| `pem_root_certs_bytes_by_fmt` | `None` for the initial contract: only self-attestation / `packed` without a trust path is accepted. Direct (enterprise) attestation with root certificates is a separate future decision — this contract does not admit an attestation trust store. |

### Permitted algorithms

Registration pins `supported_pub_key_algs` to the WebAuthn baseline triple —
the library's own default list:

| COSE | Name | Status |
|---|---|---|
| -7 | ES256 (ECDSA P-256 / SHA-256) | **Required** — every authenticator must support it; reference vectors below use it |
| -8 | EdDSA (Ed25519) | Permitted |
| -257 | RSASSA-PKCS1-v1_5 / SHA-256 (RS256) | Permitted (enterprise authenticators) |

Excluded by this contract: the RSASSA-PSS family and RS256/SHA-1 (`-65535`),
and post-quantum ML-DSA (`-48`/`-49`/`-50`) — accepted by the library's enum
but outside the reviewed surface; admitting them is a new contract, not a
flag flip. Assertion verification is keyed by the *stored* public key, so the
algorithm is fixed once at registration and cannot drift per ceremony.

### Required flags and durable state

- **UP (user present)** — required on every ceremony; the library refuses
  assertions without it unconditionally.
- **UV (user verified)** — required (`require_user_verification=True`); the
  observed `user_verified` value is persisted with the settlement as the
  presence-evidence field of the hash-chained record (Hybrid Leg 3).
- **Sign counter** — `VerifiedRegistration.sign_count` and
  `VerifiedAuthentication.new_sign_count` are persisted per credential in the
  ApprovalStore; the next ceremony must use the stored value as
  `credential_current_sign_count`. The library's monotonicity check then makes
  counter reuse a refusal (clone signal). A refusal is terminal for that
  ceremony: fail closed, audit, never retry the same challenge.
- **Backup flags (BE/BS)** — `credential_device_type` and
  `credential_backed_up` are recorded as provenance. They are *never*
  substitutes for UP/UV and never gate an approval by themselves.
- **Fail-closed mapping** — `InvalidRegistrationResponse` /
  `InvalidAuthenticationResponse` (or any library exception) map to refusal of
  the ceremony. There is no default actor, no approved-Boolean shortcut, and
  no server-side HMAC substitute for the verified assertion (ADR-090726-9a4e
  scope and safety, preserved verbatim).

## Verification vectors (recorded 2026-10-18, `webauthn==3.0.1`, Python 3.12)

Generated with the appendix script (a minimal ES256 soft authenticator; ECDSA
is randomized, so the recorded blobs are the canonical artifacts and the
script reproduces the *outcomes*, not the bytes). The RP/origin values are
contract examples; deployment supplies real ones.

### Valid registration (`packed` self-attestation, ES256, UP+UV+AT)

```text
rp_id        = "maistro.local"
origin       = "https://approvals.maistro.local"
challenge    = request_digest = sha256(b"approval-request:ws_1:effect_1234:v1")
             = bd4e186e687d97fa1ea22044a5977421d320aa2f6bf08e84894cdff03c3fe18a
credential   = {"id": "HLomX3CNojUKfWRbrPoLZltC6IB_VXtW7RrEFaeMAag", "rawId": "HLomX3CNojUKfWRbrPoLZltC6IB_VXtW7RrEFaeMAag", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uY3JlYXRlIiwiY2hhbGxlbmdlIjoidlU0WWJtaDlsX29lb2lCRXBaZDBJZE1ncWk5cjhJNkVpVXpmOER3XzRZbyIsIm9yaWdpbiI6Imh0dHBzOi8vYXBwcm92YWxzLm1haXN0cm8ubG9jYWwiLCJjcm9zc09yaWdpbiI6ZmFsc2V9", "attestationObject": "o2NmbXRmcGFja2VkZ2F0dFN0bXSiY2FsZyZjc2lnWEgwRgIhAPY1NOUbiJySstZW_VY6sa2zqvAG-57QrEJN73BCHYdTAiEAtt7TAAno4LCdAG2b1IH-pnkXSEgVjxRBU1vOU6Ra00RoYXV0aERhdGFYpBy6l1yjtwmOh2KUqEs-rVIjHFgbrVWNLYP49dbimPMxRQAAAAAAAAAAAAAAAAAAAAAAAAAAACAcuiZfcI2iNQp9ZFus-gtmW0LogH9Ve1btGsQVp4wBqKUBAgMmIAEhWCCIwvUuWrF1UHbvve2Iwc7d-6Hr16rAcrN8eyF7Ufbf1iJYIBLXvyLrKQOfdWK2Cp6X6uIE_VxXA-Lh3WHcX7WGURLz"}}
verified with expected_rp_id / expected_origin above, require_user_presence=True,
require_user_verification=True
→ VerifiedRegistration: credential_id as above, aaguid 00000000-0000-0000-0000-000000000000,
  fmt=packed, sign_count=0, user_verified=True, device_type=single_device, backed_up=False
```

### Valid assertion (UP+UV, counter 0 → 1)

```text
challenge    = sha256(b"approval-request:ws_1:effect_1234:v1:settle")
             = d4f03a5ee2f18a937a1500787a31d88e367501f4d689e709c86387d5032b2dd4
credential   = {"id": "HLomX3CNojUKfWRbrPoLZltC6IB_VXtW7RrEFaeMAag", "rawId": "HLomX3CNojUKfWRbrPoLZltC6IB_VXtW7RrEFaeMAag", "type": "public-key", "response": {"clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uZ2V0IiwiY2hhbGxlbmdlIjoiMVBBNlh1THhpcE42RlFCNGVqSFlqaloxQWZUV2llY0p5R09IMVFNckxkUSIsIm9yaWdpbiI6Imh0dHBzOi8vYXBwcm92YWxzLm1haXN0cm8ubG9jYWwiLCJjcm9zc09yaWdpbiI6ZmFsc2V9", "authenticatorData": "HLqXXKO3CY6HYpSoSz6tUiMcWButVY0tg_j11uKY8zEFAAAAAQ", "signature": "MEYCIQCInNBp0aa0K8s98DpLlimsJvnzXqubwv98mTzWDcPGRAIhAJfdynG7n0-qywIOTYisdT_A0AguqYUqrwflEqTSzlEi", "userHandle": "dXNyX3dzMV9hZG1pbg"}}
verified with credential_public_key = the VerifiedRegistration.credential_public_key above
(stored at registration), credential_current_sign_count=0, require_user_verification=True
→ VerifiedAuthentication: new_sign_count=1, user_verified=True
```

### Invalid vectors — one-field mutations of the valid artifacts

Recorded against 3.0.1; each refusal names its cause (fail closed, never a
default):

| # | Case | Mutation | Observed refusal (exact) |
|---|---|---|---|
| I1 | Wrong origin | clientData origin → `https://evil.example.com` (registration) | `InvalidRegistrationResponse: Unexpected client data origin "https://evil.example.com", expected "https://approvals.maistro.local"` |
| I2 | Wrong RP ID | rpIdHash recomputed over `evil.local` | `InvalidRegistrationResponse: Unexpected RP ID hash` |
| I3 | UV missing, UV required | registration flags `0x41` (UP+AT, no UV), signature consistent | `InvalidRegistrationResponse: User verification is required but user was not verified during attestation` |
| I4 | Challenge mismatch | assertion clientData challenge → random 32 bytes | `InvalidAuthenticationResponse: Client data challenge was not expected challenge` |
| I5 | Tampered signature | one assertion signature byte flipped | `InvalidAuthenticationResponse: Could not verify authentication signature` |
| I6 | Counter reuse (clone signal) | same assertion replayed with `credential_current_sign_count=1` | `InvalidAuthenticationResponse: Response sign count of 1 was not greater than current count of 1` |

## Test plan (post-acceptance, not part of this gate)

No test is claimed by this document. On acceptance, the implementation task
owns: the adapter module with the two wrappers pinned by the vectors above
(valid + I1–I6 as parametrized cases), a `docs/testing/inventory-notes/`
delta, and the ApprovalStore persistence seam. Until that lands, `tests:`
here stays empty by design.

## Dependencies

- [ADR-090726-9a4e](ADR-090726-9a4e-crypto-bound-approvals-hybrid-webauthn-biscuit-hash-chain.md)
  — accepted; this adapter implements Leg 1's verification half. If the Hybrid
  is ever revised, this contract dies with it.
- ADR-039 — accepted; the maintainer-signal table above is the §3 gate.
- ADR-068 §D / ADR-022 / ADR-024 — accepted; human-factor and key substrate
  decisions this adapter plugs into without replacing.

## Out of scope

- Installing the dependency (`uv add webauthn==3.0.1`), lockfile changes, and
  any production wiring — later implementation tasks after owner acceptance.
- Ceremony HTTP routes/endpoints, challenge issuance UX, and the HITL door
  integration (ADR-083026-6c72 settlement gains evidence, unchanged shape).
- Attestation trust roots / enterprise attestation policy (deliberately
  `None` in this contract).
- Biscuit delegation (Leg 2) and hash-chain verification tooling (Leg 3).
- Renegotiating WebAuthn as a mechanism, the canonical Principal model, or
  any accepted ADR listed above.

## Acceptance boundary (why this gate stays open)

Per #1837: a hygiene pass cannot resolve a security decision. This document
is the reviewed-contract *candidate* — the ADR owner
(@BlakeMatthews-dev, or an explicitly designated architecture/security
reviewer) must record acceptance of the library choice, the permitted
algorithms, the required flags, and the vectors, with the reviewed revision
and decision link, before any downstream leaf is assigned. Until that record
exists this ADR remains `Proposed`, the dependency stays uninstalled, and
issue #1837 stays visibly open.

```sh
uv run python scripts/check-adr-status-language.py && git diff --check
```

runs clean on this revision and proves document hygiene only — nothing else.

## Source references

- `duo-labs/py_webauthn` @ v3.0.1 — `webauthn/registration/verify_registration_response.py`,
  `webauthn/authentication/verify_authentication_response.py`,
  `webauthn/helpers/cose.py`, `webauthn-3.0.1.dist-info/METADATA`
  (License-Expression, requires-dist, wheel digest recorded above).
- Yubico `python-fido2` 2.2.1 — evaluated alternative; pattern reference.
- `packages/maistro-core/pyproject.toml` — existing `cryptography` pin.
- Appendix script — vector regeneration procedure.

## Links

- Issue: #1837 (decision gate; stays open until the owner records acceptance)
- Parent: #329
- Related PR: #1362 (closed; historical context only, not a vehicle)

## Appendix — vector regeneration procedure

The recorded artifacts were produced by the procedure below (run under
Python 3.12 with only `webauthn==3.0.1` — its transitive `cryptography`/
`cbor2` come from the same resolve; no engine code involved). It simulates a
minimal ES256 authenticator, exercises both public verification calls, and
prints the valid outcomes plus every invalid-case refusal. ECDSA signatures
are randomized, so each run yields fresh bytes but identical verification
outcomes; the blobs recorded above are the canonical reviewed artifacts.

```python
import base64, cbor2, hashlib, json, os, struct
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from webauthn import verify_registration_response, verify_authentication_response
from webauthn.helpers.exceptions import (
    InvalidRegistrationResponse, InvalidAuthenticationResponse)

RP_ID = "maistro.local"
ORIGIN = "https://approvals.maistro.local"

b64u = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")

def es256_cose_key(priv):
    n = priv.private_numbers().public_numbers
    return cbor2.dumps({1: 2, 3: -7, -1: 1,
                        -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

def client_data(typ, challenge, origin):
    return json.dumps({"type": typ, "challenge": b64u(challenge),
                       "origin": origin, "crossOrigin": False},
                      separators=(",", ":")).encode()

def auth_data(rp_id, flags, sign_count, attested=b""):
    return (hashlib.sha256(rp_id.encode()).digest() + bytes([flags])
            + struct.pack(">I", sign_count) + attested)

REQUEST_DIGEST = hashlib.sha256(b"approval-request:ws_1:effect_1234:v1").digest()
priv = ec.generate_private_key(ec.SECP256R1())
cred_id = os.urandom(32)
attested = (bytes(16) + struct.pack(">H", len(cred_id)) + cred_id
            + es256_cose_key(priv))

# Valid registration: flags UP|UV|AT (0x45), packed self-attestation.
cd = client_data("webauthn.create", REQUEST_DIGEST, ORIGIN)
ad = auth_data(RP_ID, 0x45, 0, attested)
sig = priv.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
att_obj = cbor2.dumps({"fmt": "packed",
                       "attStmt": {"alg": -7, "sig": sig}, "authData": ad})
reg = json.dumps({"id": b64u(cred_id), "rawId": b64u(cred_id), "type": "public-key",
                  "response": {"clientDataJSON": b64u(cd),
                               "attestationObject": b64u(att_obj)}})
vr = verify_registration_response(
    credential=reg, expected_challenge=REQUEST_DIGEST, expected_rp_id=RP_ID,
    expected_origin=ORIGIN, require_user_presence=True,
    require_user_verification=True)

# Valid assertion: flags UP|UV (0x05), counter 0 -> 1.
SETTLE = hashlib.sha256(b"approval-request:ws_1:effect_1234:v1:settle").digest()
cd2 = client_data("webauthn.get", SETTLE, ORIGIN)
ad2 = auth_data(RP_ID, 0x05, 1)
sig2 = priv.sign(ad2 + hashlib.sha256(cd2).digest(), ec.ECDSA(hashes.SHA256()))
assertion = json.dumps({"id": b64u(cred_id), "rawId": b64u(cred_id),
                        "type": "public-key",
                        "response": {"clientDataJSON": b64u(cd2),
                                     "authenticatorData": b64u(ad2),
                                     "signature": b64u(sig2)}})
va = verify_authentication_response(
    credential=assertion, expected_challenge=SETTLE, expected_rp_id=RP_ID,
    expected_origin=ORIGIN, credential_public_key=vr.credential_public_key,
    credential_current_sign_count=0, require_user_verification=True)

# Invalid cases (I1–I6): rebuild the artifacts with exactly one mutation —
# I1 clientData origin -> "https://evil.example.com";
# I2 rpIdHash over "evil.local";
# I3 registration flags 0x41 (drop UV), signature recomputed over the mutated
#    authData so the refusal names UV, not the signature;
# I4 assertion challenge -> os.urandom(32);
# I5 flip one byte of the assertion signature;
# I6 replay the valid assertion with credential_current_sign_count=1.
# Each must raise Invalid{Registration,Authentication}Response.
```

An owner reviewing this contract can regenerate the outcome set (2 valid
ceremonies verified, I1–I6 each refused with the recorded messages) in one
command:

```sh
uv run --with webauthn==3.0.1 --python 3.12 python <script-from-this-appendix>
```
