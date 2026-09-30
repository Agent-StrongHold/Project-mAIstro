---
inventory-delta:
  packages/maistro-core/tests: +13
---

# Issue #990 contract-forbid a second design product

New fitness suite `packages/maistro-core/tests/fitness/test_no_second_design_product.py`
(13 collected node IDs; `test_no_competing_execution_lifecycle_name` is
parametrized over the three forbidden lifecycle names). It freezes the M7
product boundary in CI, extending the #790 runtime registry fencing and the
#796 Evolve/RSI consumer guards with the static, product-shaped tripwires they
do not cover. One forbidden shape per test:

1. Package/app identity — no `packages/atelier` / `maistro-atelier` /
   `maistro-book` / `maistro-game`, no `Atelier.tsx` page, no
   `/atelier` `/book` `/game` `/product` route segment in the frontend route
   table or a backend router prefix, no Atelier-as-shipped-surface copy
   outside the maistro-design catalog data.
2. Execution identity — the names `DesignRun` / `EvalRun` / `VariantStore`
   may not appear in production Python or Hive frontend source; Run/NodeRun/
   Attempt is the one execution lifecycle.
3. Client persistence — no `zustand/persist` import and no
   `localStorage`/`sessionStorage`/IndexedDB key whose name carries loop
   state (goal/rubric/eval/wave/fence).
4. Director/judge egress — no provider SDK import, model-host endpoint
   fragment, or provider API-key read in `maistro_design`, the four Design
   Studio surfaces, or the Hive frontend at large; provider keys may only be
   named by the backend provider-configuration route; no non-same-origin
   `fetch` or `setTimeout`/`setInterval` stage animation in a Design Studio
   page (honest-chrome rule, #286/#465).
5. Prototype import — the SPEC-178-removed legacy snapshot trees must not
   reappear and production code must not import the `sbx` kit tree.

Validation beyond collection: a synthetic-tree probe ran every guard against
a clean tree (all pass — no false positives, including word-boundary
non-matches like `DesignRunner` and catalog slugs like `atelier-zero`) and
against a violation tree carrying one instance of every forbidden shape
(all 13 guards trip with named offenders).
