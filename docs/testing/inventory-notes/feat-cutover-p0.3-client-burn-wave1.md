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
**120 → 119** hand-typed (net of develop's already-lower floor).
(An earlier draft of this note said 124 → 123 hand-typed; that figure
predated the final rebase and disagreed with the ledger JSON — the gate
run below is the authority.)

## Verification (repair round, head `6b8c0921ecab`)

The hosted run at this head shows no content-gate failure: every leaf job
was `cancelled` by a concurrency supersede at 11:07Z and only the
`if: always()` aggregators (`Quality gate (Pillars 1–4, 7, 8)`,
`SAST (bandit + semgrep + gitleaks)`) then failed on cancelled needs.
The change-bearing gates were re-run locally with CI's exact arguments,
all green:

- `uv run python scripts/check-frontend-typed-client.py` → exit 0
  ("40 raw fetch and 119 hand-typed declaration(s) tolerated, none new").
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1253
  identities, exact ledger match, `unclassified: 0`).
- `uv run python scripts/check-ratchet-provenance.py` → exit 0.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0
  (matrix complete after dropping the 4 stale `mutating-api-call` rows).
- SAST legs: bandit Medium+ count 0; semgrep 1.182.1, 364 rules, 0
  findings with `--error`; gitleaks 8.30.1 over
  `78133c093..6b8c0921` — no leaks.
- `uv run python scripts/check-doc-links.py` → exit 0 (CHANGELOG fix).
- `npm run build` in `packages/hive-conductor/frontend` → exit 0.

The diff vs merge base `78133c093` touches no Python and no workflow
files, so the Python-only quality pillars measure trees identical to
protected `develop`. Settings/Skills/Profile smoke from the original
test plan remains UNVERIFIED here — it needs the live stack.
