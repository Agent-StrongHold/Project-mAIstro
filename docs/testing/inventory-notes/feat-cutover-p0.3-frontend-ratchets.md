---
inventory-delta:
  tests/: +6
---
# feat-cutover-p0.3-frontend-ratchets

Workspace cutover Phase 0, step P0.3: the frontend typed-client ratchet lands
with an honest baseline for raw `fetch(` and hand-typed local declarations.

`scripts/check-frontend-typed-client.py` scans `packages/hive-conductor/frontend/src`:

- **raw_fetch** — any `fetch(` outside `src/lib/` (64 call sites banked).
- **hand_typed** — any `interface`/`type` in `src/pages/` or `src/components/`
  (142 declarations banked).

The ledger is `quality/frontend-typed-client-baseline.json`, judged against the
trusted merge base per `docs/ci/RATCHET-PROVENANCE.md`. First introduction uses
the same bootstrap rule as `check-adr-status-language-provenance.py`: the
candidate ledger must match the tree exactly; growth after merge needs a grant.

CI: `quality.yml` beside `check-principal-identity.py` and `check-route-permissions.py`;
`ci.yml` lint job runs the same static scan for early feedback.

Measured on `develop` at branch creation: 64 raw fetch, 142 hand-typed (plan
census was 67/75; the tree grew and the ratchet records what is actually there).
