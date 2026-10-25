---
inventory-delta:
  packages/maistro-core/tests: +3
---

# 552: convergence-surface containment repair

Repair-pass note for epic #552 (canonical convergence, #50). The RSI
promotion path's containment surface is derived, not enumerated
(`scripts/check-promotion-surface.py` walks the import closure out of the
promotion roots and requires every reached module to escalate), so whatever
the convergence seam imports becomes the surface a candidate needs
adversarial review to edit. This pass settles what that seam drags in and
protects exactly that.

## What this pass changes

- `maistro_rsi/sensitive_paths.py` — the substrate the convergence seam
  genuinely reaches joins `SENSITIVE_PATH_PATTERNS`: the canonical
  execution/work-source substrate (`runs/`, `graph/` engine modules,
  `workspaces/`, `backlog/`, `projects/`, `governance/`, `agents/recipes/`,
  interop, ontology, runtime, tasks, archive, circuit breaker, personas),
  the extension SDK (`maistro/extensions/`) and the isolated-execution
  boundary (`maistro/sandbox/`) reached through the SDK's union facade. The
  graph modules are enumerated from the walk rather than a `maistro/graph/`
  blanket: the ordinary node library stays outside escalation on purpose
  (`TestSensitiveSurfaceCoverage` pins `nodes/llm_summarize.py` as not
  sensitive). A candidate that can edit what admits, executes, scopes,
  claims work for, or contains its own promotion now escalates — the
  question the gate exists to ask (#303, #305).
- `maistro/personas/__init__.py` — the scorer tier (`DeepEvalScorer`,
  `RubricScorer`, `create_judge_scorer`) loads lazily, identity-style: the
  RSI promotion path reaches this package through the Workspace persona
  store, whose static needs are the data/store tier only. Importing
  `maistro.personas` no longer drags the judge tier in.
- `maistro_server/api/extensions.py` — imports policy/service/types names
  from their defining submodules instead of the package root, where
  `WorkspaceExtensionPolicy` is the #969 effective-authority input rather
  than the #971 enablement policy this file's layer uses.

## Deliberately rejected: a lazy `maistro.extensions` facade

A lazy union facade (identity-style `_LAZY_EXPORTS`) would shrink the
promotion closure by the whole SDK, but it makes the tier modules
statically unreachable, and `check-reachability-provenance.py` treats each
as a NEW unreachable module requiring authorization from the merge base
(the two-merge rule) — grants that do not exist on develop and that an
implementation branch cannot mint for itself. The eager facade is kept, and
the containment question is answered in production code instead: what the
eager closure reaches (the SDK and `maistro/sandbox/`) escalates. That is
the stronger containment anyway — the SDK is the host's
authority/trust substrate and the sandbox is the isolated-execution
boundary (#305), so a candidate editing either is editing what contains or
authorizes it.

## Tests added (3, all in `packages/maistro-core/tests`)

`personas/test_lazy_scorer_tier.py` — a clean-interpreter import of
`maistro.personas` does not load `personas.scorer` (subprocess form: the
asserting process's own imports would leak a loaded tier into
`sys.modules` and false-pass the property); scorer names resolve from the
root on first access; an unknown root name raises `AttributeError`.

## Gate evidence (this pass, tree under note)

- `uv run python scripts/check-promotion-surface.py` — ok.
- `uv run python scripts/check-reachability-provenance.py` — ok
  (148 unreachable of 1466, unchanged from the trusted base).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — ok.
- `uv run mypy` (CI's ten-package scope), `uv run ruff check .`,
  `uv run ruff format --check .` — clean.
- Diff coverage (three producers: core, rsi, server suites under
  `coverage run --branch`) — every measured changed file ≥90% lines /
  ≥80% branch arcs.
