# CR2347 repair: ruff 0.17.2 lint/format compliance and llm_gateway splice fix

No recorded suite moved: every edit below is count-neutral, so this note
carries no `inventory-delta` block — per `scripts/check-suite-inventory.py`,
front matter without that key records no delta, which is the documented normal
case for a change that moved no count. `formal/models` itself has no RECIPES
entry (it is the formal-conformance workflow's suite, guarded by
`scripts/check-formal-oracle-independence.py`, which passes for this branch),
so a delta block for it cannot exist.

Dependency bump PR #2347 (ruff 0.15.12 → 0.17.2) rebuilt onto develop carried a
botched re-application of lane history into
`packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`: the
`_dispatch_adapter_model_chat` docstring lost its opening delimiter (SyntaxError
at import), the function referenced an undefined `provider` name, a stale
adapter tail leaked into `_post_chat_completion` (undefined `adapter_provider`),
`import json` was removed while `json.loads` stayed, and
`_adapter_identity_suffix`/`_adapter_log_fields` were duplicated verbatim. The
base commit cannot collect any suite importing the module —
`formal/models/test_rsi_audit_trail_conformance.py`,
`packages/maistro-core/tests/a2a/test_external_agent_conformance.py`, and the
rest of the tree fail at collection.

Repairs, all count-neutral:

- `llm_gateway.py`: coherent adapter dispatcher restored (`_adapter_preflight` →
  rate-limit check → shared `_post_chat_completion` → adapter log fields →
  `_adapter_response_body`); `_post_chat_completion` now returns the raw
  response; duplicate helpers and duplicate `_seed_context_probe` removed;
  `import json` restored. No test added — the existing suites
  (`test_llm_gateway_resilience_connect.py`, `test_provider_adapters.py`,
  `test_llm_gateway_branches.py`, `test_model_chat_egress.py`,
  `test_admitted_model_calls.py`, `test_governed_llm_execution_identity.py`;
  239 cases) already pin the adapter dispatch seam and pass, at 97% line+branch
  on the file (CI diff floors are 90/80 per file).
- `formal/models/*` (12 files): ruff 0.17 compliance only — I001 import
  sorting, RUF036 `None`-last unions, RUF100 stale `noqa` removals, RUF012
  `ClassVar` annotations on Hypothesis state-machine attributes, RUF059
  underscore-prefixing of unused unpacks, C401/C408/SIM114/PLR0402 mechanical
  rewrites. Every assertion is preserved verbatim; `pytest formal/models/
  --hypothesis-seed=0` stays 670 passed against a live PostgreSQL and
  `pytest formal/` stays 666 passed / 4 skipped in the no-services quality
  configuration. Suite counts unchanged, so `inventory-delta` is +0 and the
  recorded inventory still matches (`scripts/check-suite-inventory.py` ok).
- `packages/maistro-{core,rsi}/src` (6 files): annotation-order and import-sort
  compliance only (`int | None | str` → `int | str | None` etc.); no runtime
  semantics.
- 132 Markdown files: ruff 0.17 formats Python code blocks in fenced fences;
  applied `ruff format .` (docs/specs, docs/testing/inventory-notes prose,
  .cursor/context notes, CONTRIBUTING.md). No prose outside code fences moved.

The ruff gate itself is the acceptance evidence: `uv run ruff check .` and
`uv run ruff format --check .` (CI's exact invocations) pass on the repaired
tree and failed on the base commit.
