---
inventory-delta:
  packages/maistro-core/tests: +4
---
# m2-856 — OIDC verification dependencies are mandatory: never fall back to unverified JWT claims

#856 removes the last way an OIDC login could authenticate from unverified
claims. `UnverifiedJWTClaimsValidator` — which satisfied `IdTokenVerifier`
and stayed injectable into `OAuth2Client` — is deleted outright, the PyJWT
import is guarded so a broken install refuses the module with an actionable
error, and `MissingCryptographyError` surfaces as provider unavailability
instead of a generic verification failure.

Net +4 node IDs for `packages/maistro-core/tests`, in two files:

- `tests/auth/test_oauth.py` (net 0: −6 / +6). The three claims-validator
  tests (four of the six nodes via parametrize) tested the deleted class and
  go with it. Six mandatory-verification nodes replace them: a future-`nbf`
  token is refused, key rotation retires the old JWKS key while the new one
  keeps working, a payload that is not JSON (and one that is JSON but not an
  object) is refused without parsing claims, the `alg=none` downgrade is
  rejected by the algorithm allowlist, and a stop-condition guard asserts no
  unverified validator exists on any module or package-export path and that
  `default_id_token_verifier()` is the JWKS verifier.
- `tests/auth/test_mandatory_verification.py` (new, +4) removes the
  verification dependency itself (the
  `tests/archive/test_optional_dependency.py` pattern): blocking `jwt`
  proves the oauth module and its lazy package exports refuse to import with
  an actionable fail-closed error; blocking `cryptography` proves a real JWKS
  verification attempt against a real signed token raises
  `OAuthTokenValidationError` naming the missing backend rather than
  returning claims; and an in-flow test proves a login whose JWKS is
  unreachable is refused at the verification step even when the provider
  happily returns an id_token. The fourth node is the in-process seam
  (b4859acf): with `cryptography` hidden from the verifier import, the
  fail-closed handler fires without a subprocess. (Ledger correction: the
  original note declared +3 and missed this fourth collected node — the
  suite-inventory gate flagged the branch at +1 drift.)
