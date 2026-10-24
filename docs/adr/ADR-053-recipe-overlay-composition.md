---
id: ADR-053
title: Recipe overlay composition — engine simple + product overlay
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-13
substrate:
  - maistro-engine#ADR-006
  - maistro-engine#ADR-035
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-050
  - maistro-engine#ADR-051
  - maistro-engine#ADR-054
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-13
---

# ADR-053: Recipe overlay composition — engine simple + product overlay

## Context

ADR-006 defines `AgentRecipe` + `RecipeRegistry` as a flat YAML model — one file, one set of fields, no inheritance. ADR-035 splits catalogs two-tier: engine simple form + stronghold multi-tenant variant. Together, today's situation is:

- A product wanting to ship N similar recipes copy-pastes shared fields across them.
- A product wanting to set product-wide defaults (memory mode per ADR-057, approval thresholds per ADR-051, observability tier per ADR-055) has no mechanism — it bakes the defaults into every recipe.
- New fields that are inherently code (impact estimators per ADR-050, compensators, merge resolvers) live as dotted-path strings with no version pinning, so a code-side semantic change silently shifts deployed recipe behaviour.

This ADR adds a single overlay layer to ADR-006 aligned with ADR-035's two-tier split, and formalises code-registry references for the fields that need them.

## Problem

Flat recipes force copy-paste for product-wide defaults; code-shaped fields lack stable versioning.

## Decision

### Two-axis composition

- **Base recipe** — the canonical YAML declaration, engine- or product-shipped. Always present. Lives in `recipes/yaml/`.
- **Product overlay** — optional, single layer applied at registry load time. Product-wide defaults (memory mode, observability tier, approval thresholds, sandbox tier, wave caps) live here.

This is the two-tier shape from ADR-035 — engine simple form (base + optional product overlay). A third tenant-overlay layer is out of scope for the engine and deferred to stronghold per ADR-035.

### Schema-driven merge

The recipe schema annotates each field with one of:

| Annotation | Meaning |
|---|---|
| `merge: replace` | Default for scalars. Overlay value replaces base value. |
| `merge: deep` | Default for nested objects. Recursive deep-merge. |
| `merge: keyed:<field>` | Arrays of keyed objects. Match by key; deep-merge per match; append unmatched. Used by `tools[]` (keyed by `name`), `memory_blocks[]` (keyed by `name`). |
| `merge: ref` | Code-registry references. Overlay must declare a semver-compatible version. |

No inline `$patch` escape hatches. Escape hatches require schema updates — deliberate friction for governance. If a real case can't be expressed, the schema gains a new annotation rather than the overlay gaining ad-hoc syntax.

### Tenant whitelist (forward-compatible)

The base recipe declares which fields a future tenant overlay may touch via per-field `overridable: true` annotation. Engine ships the annotation; engine enforces the whitelist if a tenant overlay is presented (but the tenant overlay layer itself is stronghold-owned). Lint rule: certain field paths (`tools[].reversibility`, `tools[].compensator`, `tools[].impact_estimator`) are never `overridable`.

### Code-registry references

Fields with `merge: ref` carry a `name@version` string: `impact_estimator: "stripe.charge.dollars@v2"`. The substrate maintains a code registry alongside the recipe registry. Registry refs require explicit version; substrate refuses to load a recipe with an unversioned ref. Compatibility is semver: `v2.x` accepts `v2.y` overlays; major-version bumps require explicit recipe update.

> The code registry — storage, signing, resolution, and crucially the **microVM-isolated
> execution** of registered code — is fully specified in **ADR-069**. The `CodeRegistry` protocol
> sketched below is its load/resolve surface; ADR-069 adds `invoke()` (Hyperlight microVM,
> fail-closed) under the ADR-068 authorization envelope.

## Interface (sketch)

```python
class RecipeOverlay(BaseModel):
    target: str               # base recipe name
    overrides: dict[str, Any] # path -> value; merged per schema rules

class CodeRegistry(Protocol):
    def resolve(self, ref: str) -> Callable: ...           # "name@version" -> function
    def compatible(self, base_ref: str, overlay_ref: str) -> bool: ...

class RecipeRegistry:  # extends ADR-006
    def __init__(
        self,
        recipes_dir: Path | None = None,
        overlay: RecipeOverlay | None = None,
        code_registry: CodeRegistry | None = None,
    ) -> None: ...
    def render_effective(self, name: str) -> AgentRecipe | None: ...  # base + overlay
```

## Acceptance criteria

- [ ] Loading a recipe with no overlay returns the base unchanged (back-compat with ADR-006).
- [ ] Overlay merge follows schema-declared annotations.
- [ ] Overriding a non-`overridable: true` field fails at load with `OverlayValidationError`.
- [ ] `merge: ref` fields require `name@version`; missing version fails at load.
- [ ] Semver-incompatible overlay ref fails at load.
- [ ] `render_effective` is idempotent.
- [ ] Hypothesis property test: for any `(base, overlay)` pair satisfying the schema and whitelist, `render_effective` succeeds.
- [ ] Lint rule: `tools[].reversibility`, `tools[].compensator`, `tools[].impact_estimator` are never `overridable: true` (CI check).
- [ ] Span `recipe.render_effective` per ADR-037.

## Resolved decisions (v0)

1. **Effective-recipe cache key → `(base_name, overlay_hash, code_registry_version)`.** Invalidate on any registry or overlay change.
2. **Hot-reload of overlays → no (v0).** Restart-to-pick-up is acceptable; **deferred**.
3. **A/B testing of overlays → deferred.** A future ADR may add a `selector` field the registry consults.
4. **Overlay-of-overlays → deferred.** If a real env-specific (dev/staging/prod) case appears, model it as multiple product overlays with explicit precedence rather than nesting.
5. **Linter coverage → explicit lock-list + PR-time review.** New code-shaped fields (`impact_estimator`, `*_compensator`, `*_resolver`) are added to the lock-list deliberately at PR review, not auto-detected.

## Source references

- ADR-006 recipe registry (the flat model this extends).
- ADR-035 catalog ownership split (the two-tier shape this aligns with).
- ADR-031 versioning and registry conventions.
- Kustomize strategic-merge-patch — prior art for schema-driven merge.

## Out of scope

- Tenant overlay layer (stronghold concern per ADR-035).
- Hot-reload of overlays at runtime.
- A/B testing of overlays.
- Cross-recipe inheritance (`extends:` field) — separate ADR if needed.
