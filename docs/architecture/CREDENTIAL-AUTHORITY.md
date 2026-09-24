# Credential Authority

The credential authority is intentionally split by responsibility, not by storage implementation:

- Product credential CRUD is owned by `services.user_credentials`, which uses the per-user encrypted `maistro.credentials.store.UserCredentialStore`. Every operation receives the authenticated user id before it reaches the store.
- Runtime provider selection and outcome-driven rotation are owned by `maistro.credentials.router` on the canonical Provider/Binding/Invocation path.
- `services/credential_store_v2.py` is retired by #1186. It was an uncalled PostgREST helper whose id-only get, secret, update, and delete methods had no principal predicate. It must not be revived or wired into a Workspace/API route.

`quality/credential-authority.json` classifies the current authority boundary.
`scripts/check-credential-authority.py` joins it to the production import graph
from `scripts/check-reachability.py`. Retired paths must remain absent, including
imports from currently unreachable production modules.

## Classification is not authorization

The gate resolves policy through `ratchet_provenance.resolve_baseline`. A
candidate cannot add an implementation, reclassify a surface, or erase retirement
by editing its own ledger: `canonical`, `reachable`, and `retired` must match the
trusted base. An unreadable named base fails closed. If the base predates this
ledger (or only a local worktree baseline is available), a fixed six-surface
initial census and the v2 retirement are required. This bootstrap is not an
exception allowing new stores. Policy expansion needs independent governance
review, not an ordinary implementation PR or a candidate-authored scope claim.

The earlier identifier-based scope heuristic is removed: an unused `user_id`
parameter, decorative local `user`, or owner-shaped string proves nothing about
a database predicate. The gate now rejects additional classified implementations
regardless of such decoration, including list-only implementations and claimed
protocol adapters. Unclassified CRUD-shaped implementations are also rejected by
the behavior-shaped reachability scan. A conservative scope-propagation lint
additionally checks record operations inside owner-scoped modules: required
owner inputs must reach the canonical bucket lookup or store/config delegate.
It covers every operation that can address or carry credential material —
id/record selectors, the canonical (provider, workspace, connection) scope
selectors, secret-bearing parameters, and selector-free lists (except the two
exact public provider-catalog helpers) — so the retired v2 shape of unscoped
provider-keyed global-bucket mutations cannot return inside an approved
surface. Bare master-key parameters stay outside per-user scope: key-material
administration such as `rotate_master_key` is deployment-scoped, not record
CRUD. The lint rejects unused owner parameters and decorative locals. This is a
regression tripwire, not a substitute for behavioral tests or security review.

This census is an architecture boundary, **not a general Python authorization
proof**. Changes inside approved modules still require executable isolation tests
and security review; arbitrary obfuscation/dynamic imports are outside the static
scanner's guarantees. `tests/test_credential_authority.py` and
`packages/hive-conductor/backend/tests/test_credentials_api.py` exercise the
actual canonical store and authenticated two-user CRUD path. Owner scope is
proven by those behaviors, never by ledger prose. Master-key rotation and the
ADR-063 runtime selection authority remain separate from per-user CRUD; no new
storage, authorization, or execution authority is introduced.
