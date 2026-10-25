---
inventory-delta:
  tests/: +16
  extensions/reference-gallery/packages/gallery-weather-connector/tests: +7
  extensions/reference-gallery/packages/gallery-unit-skill/tests: +6
  extensions/reference-gallery/packages/gallery-model-adapter/tests: +11
  extensions/reference-gallery/packages/gallery-renderer-pack/tests: +6
---
# 980-reference-gallery

The out-of-tree reference extension repository lands (#980, epic M9-J
#948): four third-party-shaped extension packages under
`extensions/reference-gallery/packages/`, one per family (tool connector,
skill, capability-provider/model adapter, renderer/UI pack), plus a shared
publish workflow (build → artifact binding → Ed25519 signing → catalog
snapshot) and its own namespace policy that the same reusable M9 gates read
via `--policy`.

## What moved

`tests/test_reference_gallery.py` (+15) is the repository-side lifecycle
proof, all of it over the real `maistro.extensions` and
`maistro.capabilities.provider_adapters` code and the gallery's published
wheels (never its source trees):

- publish determinism (byte-identical catalog across runs), artifact-claim
  binding, signature verification against the committed publisher key, and
  the published manifests passing the platform inspector;
- `resolve_lock` over the catalog snapshot: determinism, the full
  four-family lock, and dependency resolution pulling the connector in for
  the skill;
- `materialize_lock` through the durable SQLite install store: verified
  evidence, provenance, idempotent re-materialization, and the tampered-
  artifact batch failing closed with zero records;
- governed activation per family (inspect → authorize → install → ACTIVE)
  with a wheel-unpacking loader as the only code-execution seam, no
  product module imported at any point, and a tampered payload rejected
  before any code runs;
- the provider-adapter family registering through `register_adapter_models`
  and passing `run_adapter_conformance`, with canonical router selection —
  and a lying error taxonomy refused at registration;
- CI wiring: both reusable gates present in `ci.yml` against the gallery
  policy, plus the import gate passing over the real tree as CI runs it.

Four new package suites (+7/+6/+11/+6) are the extensions' own
self-contract tests, run by the isolation fixture in a fresh venv holding
only the built wheel — the executed form of "builds and tests without
importing MAIstro core internals".

`tests/test_check_reference_extension.py` (+1) adds discovery of the
gallery packages under the gallery's own policy; the existing
policy-shape pin changes with the policy (product-side trees now enumerate
`extensions/reference-greeter` explicitly — the gallery is governed by its
own policy file, one gate pair per policy).
