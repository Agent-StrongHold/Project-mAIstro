# Credential Authority

The credential authority is intentionally split by responsibility, not by storage implementation:

- Product credential CRUD is owned by `services.user_credentials`, which uses the per-user encrypted `maistro.credentials.store.UserCredentialStore`. Every operation receives the authenticated user id before it reaches the store.
- Runtime provider selection and outcome-driven rotation are owned by `maistro.credentials.router` on the canonical Provider/Binding/Invocation path.
- `services/credential_store_v2.py` is retired by #1186. It was an uncalled PostgREST helper whose id-only get, secret, update, and delete methods had no principal predicate. It must not be revived or wired into a Workspace/API route.

`quality/credential-authority.json` is the authority classification. `scripts/check-credential-authority.py` joins that ledger to the same production import graph as `scripts/check-reachability.py`: every reachable credential-shaped implementation must be classified with an owner, scope, and storage contract, while retired paths must remain absent. For the owner-scoped kinds (`product_crud`, `encrypted_store`) the audit also corroborates the asserted scope in the implementation itself: the module must reference the principal dimension outside docstrings, and no record operation may select records by id without an owner/principal scope — the exact shape of the retired `credential_store_v2`. Its behavior-shaped scan is covered by `tests/test_credential_authority.py`, including a renamed CRUD store fixture and a classified-but-unscoped counterexample, so a new implementation must be classified, scoped on paper, and scoped in code before it can become reachable.
