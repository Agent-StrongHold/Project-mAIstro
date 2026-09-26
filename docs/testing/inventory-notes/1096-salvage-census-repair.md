---
inventory-delta:
  tests/: +6
---

# 1096-salvage-census-repair

Salvage repair for #1096. Five of the six `tests/` node IDs came in with the
develop merge (b533e2abf) that completed the interrupted prior-salvage merge;
their authors' own notes live on develop. The sixth is
`tests/test_check_security_inventory.py::test_the_census_sees_function_local_httpx_imports`,
the regression test for the census scanner gap the prior run left open: a
module-level-only alias scan reported no finding for
`def make(): from httpx import Client; return Client()`, so the completion gate
could be dodged by moving an import inside a function. `_httpx_aliases` now
walks the whole tree, and the test proves both the constructor census and the
sibling call census see function-local imports.

## Repair-round verification (2026-09-15, head e381e459e)

The prior verifier block was "worker made no commit; clean tree is not proof
of repair". This round re-ran every prior finding and the full gate battery
against the committed head; no code change was needed — the evidence below is
what the block asked for. Tests added this round: +0 (the inventory delta
above is unchanged).

- Full CI mypy command (`uv run mypy` over all nine `packages/*/src` roots,
  exactly as `.github/workflows/ci.yml` spells it): `Success: no issues found
  in 831 source files` — prior finding "union-attr on `.rstrip()` at
  free_router.py:155" does not reproduce.
- `uv run python scripts/check-ratchet-provenance.py`: every ratchet OK
  (reachability 189/189, shell 3/3, contract-markers 373/373, enumerations,
  lifecycle, provenance) — prior finding "declared-kind-unproven contracts"
  does not reproduce; ADR-102's boundary/behavioral contracts are counted as
  proven.
- `uv run python scripts/check-security-inventory.py`: exit 0; the
  function-local-import regression test
  (`test_the_census_sees_function_local_httpx_imports`) passes — prior
  scanner-gap finding does not reproduce.
- Census re-run by hand: the only `httpx.Client(`/`httpx.AsyncClient(`
  constructions under any `packages/*/src` are in `maistro-core/src/maistro/http.py`
  (the pool itself); all five sibling packages acquire clients via
  `maistro.http.sync_client`/`shared_client` with
  `configure_outbound_policy` for operator-configured origins.
- `uv run pytest` scoped to the changed surface: `tests/test_check_security_inventory.py`,
  `tests/test_http_client_sites.py`, `tests/test_check_adr_index.py` (61
  passed) and the five sibling packages' suites (1864 passed, 7 skipped);
  maistro-core seam tests (`test_outbound_policy.py`, `test_http_pool.py`:
  69 passed) prove `OutboundBlockedError` fires through the shared transport.
- Gates: `uv run ruff check .` and `uv run ruff format --check .` clean;
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0 (1415/1415 identities banked, no ledger
  amendment needed); merge-markers, suite-inventory, direct-effects,
  cross-package-imports, and monorepo-layout checks all ok.
