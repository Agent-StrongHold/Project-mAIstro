# p0-1-principal-final

Workspace cutover P0.1 final slice — burn the last four `parallel_principal_class`
entries and clear `quality/principal-identity-baseline.json`.

## Inventory effect

No collected test count moved.

## What changed

- `AuthenticatedPrincipal` → `maistro.identity.Principal`
- `CurrentUser` → `Principal` via `get_current_user`
- `HiveUser` → `HiveAccount` (persistence model)
- `_SubsystemIdentity` → `_SubsystemCredential`
- `capabilities.py`: `require_principal` instead of nested `state.user`
- Baseline: **4 → 0**
