# Inventory note — P0.3 typed-client debt burn wave 1 (#1995)

Rebased onto current `develop` after organic burns past the original
wave-1 ledger (60→43 raw / 142→131 hand-typed). Those earlier page
migrations landed via other PRs; this branch keeps only remaining
wave-1 value without regressing the develop floor.

## Changes

- Add `packages/hive-conductor/frontend/src/api/entities.ts` (OpenAPI
  aliases from `types.gen.ts`, plus path-derived / loose demo+provider
  shapes).
- Route remaining bare `fetch(` sites through `lib/api` helpers:
  AccountBanner logout, TemplatePicker demos, Settings elevate,
  LlmProviders list/key/activate.
- Drop the local `Template` type and LlmProviders local interfaces in
  favor of `entities.ts`.
- Preserve develop's AuthorizationContext / AuthorizationNotice on
  LlmProviders and Settings (do not reintroduce #2283 debt).

## Ratchet

`quality/frontend-typed-client-baseline.json`: **42 → 40** raw fetch,
**124 → 123** hand-typed (net of develop's already-lower floor).
