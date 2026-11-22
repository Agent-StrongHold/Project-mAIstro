---
inventory-delta:
  packages/maistro-core/tests: +7
  tests/: +5
---
# 980-reference-gallery-catalog-import

Follow-up round on #980 (review fixes on top of `980-reference-gallery.md`):
the published catalog gets a production parser, every gallery package ships
the SDK's discovery manifest, and the publish tool refuses unsafe output
directories.

## What moved

`packages/maistro-core/tests` (+7), new `tests/extensions/test_catalog_json.py`:
`maistro.extensions.catalog_json.parse_catalog_document` is the consumer half
of the publish contract — it turns an emitted `catalog.json` into the exact
`CatalogEntry`/`ExtensionManifest` objects `resolve_lock` and
`CatalogService.set_catalog` consume. The seven tests pin its fail-closed
refusals: a snapshot digest that does not cover the shipped entries, an
identity contradicting its own manifest bytes (package digest vs. artifact
claim), an unrecognized format tag, a signature that does not verify against
the document's own key, a key swap without re-signing, and duplicate
identities — each raising `CatalogDocumentError` rather than handing a
half-trusted catalog to resolution.

`tests/` (+5), in `test_reference_gallery.py`:

- `test_every_package_carries_an_sdk_validatable_manifest` — runs the SDK
  CLI's `validate` command (subprocess, the way a third party invokes it)
  against all four gallery packages and pins that the two manifest envelopes
  agree on publisher, version, authority, and entrypoint. This is the
  executable form of the policy change: `required_artifacts` was empty, so
  nothing proved the wheels were SDK-discoverable.
- `test_the_published_wheels_carry_the_sdk_discovery_manifest` — every built
  wheel carries `extension.json` at the package root (the policy's
  required-artifact rule, checked against the real artifacts).
- `test_published_catalog_imports_through_the_catalog_service` — the
  published `catalog.json` flows through the production parser into
  `CatalogService.set_catalog`, and the service reads back exactly what was
  published (per-entry snapshot digest, manifest/package digests, publisher,
  signature).
- `test_publish_refuses_unsafe_out_dirs` /
  `test_publish_cli_refuses_non_dedicated_directory` — the publish step
  clears `--out-dir` before installing output, so a stray `--out-dir .` must
  fail loudly instead of recursively deleting unrelated files; the CLI-level
  test proves the refusal happens before any build or clearing and leaves a
  sentinel file untouched.

Supporting production change (no test-count effect): the SDK validator
resolves entrypoints under `src/` layout as well as flat, mirroring the
harness discovery rule — without it the SDK CLI rejects exactly the
copy-from-template trees this monorepo advertises. The gallery packages'
own suites (+7/+6/+11/+6, recorded in `980-reference-gallery.md`) are
unchanged.
