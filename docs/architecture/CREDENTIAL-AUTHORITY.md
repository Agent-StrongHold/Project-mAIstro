# Credential Authority

The credential authority is intentionally split by responsibility, not by storage implementation:

- Product credential CRUD is owned by `services.user_credentials`, which uses the per-user encrypted `maistro.credentials.store.UserCredentialStore`. Every operation receives the authenticated user id before it reaches the store.
- Runtime provider selection and outcome-driven rotation are owned by `maistro.credentials.router` on the canonical Provider/Binding/Invocation path.
- `services/credential_store_v2.py` is retired by #1186. It was an uncalled PostgREST helper whose id-only get, secret, update, and delete methods had no principal predicate. It must not be revived or wired into a Workspace/API route.

`quality/credential-authority.json` is the authority classification. `tests/test_credential_authority.py` verifies that the retired path stays absent, the canonical owners remain present, and no second production credential-store implementation is introduced. Reachability continues to ratchet the production module graph; a new implementation must be classified and scoped before it can become reachable.
