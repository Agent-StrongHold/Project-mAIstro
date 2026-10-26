---
inventory-delta:
  packages/maistro-core/tests: +49
---
# Extension attribution through canonical telemetry (#976, M9-I1)

## What moved

`packages/maistro-core/tests` collects 49 more node IDs, all additive; no test
was removed or renamed.

- **41** from the extension attribution evidence slice: a new
  `tests/extensions/test_attribution.py` suite (the version-tagged
  `ExtensionAttribution` payload — exact identity construction from B1/B2
  install records, fail-closed decode, historical readability without a
  registry, correlation-namespace refusal, secret-freedom, delegation-hop
  round-trip) and new cases in
  `tests/capabilities/test_provider_adapters.py` (declared adapter identity
  through bootstrap → Binding snapshot → governed call → Invocation evidence,
  identity-bearing error messages and call logs, conformance of a declaring
  adapter).
- **4** from the production-emitter repairs that give the attribution surface
  real callers: terminal invocation events carry the fragment in Event
  provenance (`governed_invocation.py`), governed activation logs identity
  fields (`extensions/service.py`), and `maistro extensions show` renders the
  payload (`cli/_extensions.py`) — two events cases, one log case, one CLI
  case.
- **3** from the promotion-surface containment repair that moved the
  attribution carrier into the capabilities layer: the extension surface
  re-exports the one canonical carrier object (one type, not two
  implementations), the carrier's strict-version rule is pinned to the
  extension contract's parser over a corpus, and a static check refuses any
  ``maistro.capabilities`` module that imports ``maistro.extensions`` — the
  edge that put 300+ extension modules on the promotion path.
- **1** from the reference-extension proof: the shipped out-of-tree gallery
  adapter package (`extensions/reference-gallery/packages/gallery-model-adapter`)
  is driven through the canonical provider-adapter bootstrap, one governed
  call and the terminal audit event, with the identity bound to the artifact
  the host actually installed (the package's manifest digest and the digest of
  the wheel `uv build` produces from the shipped source) — a real extension
  proving the correlation end to end, not a fabricated stand-in.

## Evidence shape

Each new test names the #976 acceptance criterion it pins via
`@pytest.mark.ac("#976/AC-n")`. The events case asserts the canonical
correlation fields stay authoritative (`correlation_id == run_id`) while the
extension identity rides only under `provenance["extension"]`; the legacy
(non-declaring) bindings case asserts no fragment is emitted at all.
