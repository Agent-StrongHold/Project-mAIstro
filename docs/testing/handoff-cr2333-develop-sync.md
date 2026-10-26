# Handoff — cr-2333 repair round (develop sync + full validation)

Branch: `cursor/m1-assetinstance-cutover-ea7e`, merge commit `bce78e920`
(parents: `e3fe4bd6f` branch work, `292ff7a00` origin/develop tip).

## What this round did

1. Prior attempts (jobs `7f1e878b`, `bb454bf3`, `7466a236`) all died on
   **provider timeouts**, not code: driver checks at `fe6e0c036` were green
   (ruff, pytest 28 passed, suite inventory canvas 638 / server 658).
2. `origin/develop` advanced 4 commits past the branch's last develop merge
   (`e3fe4bd6f` merged develop@`78133c093`). `git merge-tree` proved a
   **conflict in `quality/reachability-baseline.json`** that would have broken
   CI's develop merge.
3. Merged `origin/develop` and resolved the conflict by **unioning both sides'
   row removals**: develop's `maistro.tools.reversibility_registry` (#57
   governed-tool wiring) and this branch's five `maistro_canvas.canvas.asset_*`
   rows (ADR-044 CONNECT, #2311). `quality/reachability-dispositions.json`
   auto-merged (disjoint regions) and was audited by numstat against both
   parents — no rows silently lost.

## Post-merge validation evidence (all exit 0)

- `scripts/check-reachability.py` — 1486 production modules, 96 unreachable
- `scripts/check-reachability-dispositions.py` — 34 groups cover all 96
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — 1248 findings, 0 unclassified
- `ruff check .` / `ruff format --check .` — clean
- pytest: canvas suite 583 passed / 75 skipped; server suite 659 passed /
  10 skipped; targeted CONNECT + wiring tests 28 passed
- `scripts/check-suite-inventory.py` canvas (638) + server (669) — match
- `maistro-registry lint . --strict` — 443 files, 0 errors
- E2E production probe (not just tests): real `FastAPI()` +
  `_wire_canvas_assetinstance` → `canvas_asset_tool` bound, router mounted,
  `GET /v2/canvas/asset-definitions` returns 200 with `Authorization: Bearer`
  (`maistro_canvas.auth` gate behaves: 503 without `CANVAS_API_TOKEN`, 401
  with wrong token). Lifespan chain `main.py:557 → _wire_canvas_ability →
  _wire_canvas_assetinstance` verified in source.

## Notes for the next operator

- Local mypy on canvas/server src shows 157 `import-untyped`-dominated errors
  because `maistro-server` is not a root workspace dependency (tests resolve it
  via pytest's src-path config). CI's mypy gate scopes to
  `packages/maistro-core/src` only — untouched by this branch. Non-issue.
- Actual GitHub CI run on the post-merge head is the only unproven acceptance
  item (no-push policy); every CI-equivalent local gate is green.
