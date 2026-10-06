# reference-gallery

The **out-of-tree reference extension repository** (#980, M9-J2). This
directory is built, signed, resolved, installed, and invoked exactly the way
an external publisher's repository would be — no product-private import, no
editable source path, no fork of the platform's machinery. It exists to prove
the M9 extension platform supports real third-party extension ecosystems
spanning multiple families, and to serve as the copy-from template external
developers start from.

## What is in here

| Path | What it is |
|------|------------|
| [`packages/`](packages/) | One buildable extension package per family (below). Each has its own `pyproject.toml`, manifest, entrypoint module, and test suite. |
| [`tools/publish.py`](tools/publish.py) | The shared publish workflow: build every package, bind each manifest to its built artifact, sign with the publisher key, and emit the catalog snapshot the platform's registry/resolution consumes. |
| [`keys/reference-publisher.pub`](keys/reference-publisher.pub) | The gallery publisher's Ed25519 public key (hex). It is derived from the fixed fixture seed documented in `tools/publish.py`; the publish workflow fails loudly if the key file and the seed ever disagree. **This is a fixture identity**: it signs nothing of value, and a real publisher keeps the private key out of the repository entirely. |
| [`namespace-policy.json`](namespace-policy.json) | The gallery's own namespace policy. The same reusable M9 gates that police the first-party reference extension run against this file via `--policy`. |

## Extension families

The issue asks for a repository that spans the extension families. Each
package below is a complete, installable extension in one family; the
first-party `extensions/reference-greeter` already covers the plainest
`tool` shape, so the gallery demonstrates the families a real publisher
would ship together:

| Package | Family | What it proves |
|---------|--------|----------------|
| `gallery-weather-connector` | `tool` | A connector/tool: declares `network.outbound` + `tool.invoke`, ships pure data-shaping handlers. The host owns the transport; the extension never holds a socket. |
| `gallery-unit-skill` | `skill` | A skill that *depends on* the connector (a real `dependencies` declaration), driving dependency resolution and the reproducible lock. |
| `gallery-model-adapter` | `capability-provider` | A **provider adapter** (ADR-104): declares its models, auth style, and error taxonomy as plain data plus pure normalization functions; the host validates it through `run_adapter_conformance` and registers it through `register_adapter_models`, the one registration seam. |
| `gallery-renderer-pack` | `renderer-plugin` | A UI pack: renders structured product data into display text without touching product internals. |

## The manifest workflow

Each package ships `manifest.json` — the authority declaration, in the
platform install envelope (`maistro.extensions.inspect_manifest` is the
executable contract this repository codes against; see Reconciliation
below). The author never writes an artifact digest: `tools/publish.py`
builds the wheel, computes its digest/size, and binds the `artifact` claim
at publish time. Authority names come from the closed capability vocabulary
(`network.outbound`, `tool.invoke`, `workspace.read`, …); declaring nothing
yields nothing.

## The signing workflow

`tools/publish.py` signs the canonical install payload — extension name,
semantic version, package digest, manifest digest — with the publisher's
Ed25519 key, exactly the payload `maistro.extensions.verify` checks at
install time. Signatures travel inside `catalog.json`; verification happens
against the *registered* publisher key, never a key the package brought
along. Publishing is deterministic: same packages, same bytes, same
signatures.

## The install path (no editable sources)

Nothing in this repository is installed by path. The platform consumes the
catalog snapshot:

```
publish → catalog.json (+ wheels)
        → resolve_lock(root requests, catalog)      # deterministic lock
        → materialize_lock(lock, store, fetcher)    # digest+signature-verified install records
        → ExtensionInstallService.inspect → authorize → install
        → loader imports the entrypoint             # the only code-execution seam
```

`tests/test_reference_gallery.py` (repository side) executes that entire
chain against the real `maistro.extensions` and
`maistro.capabilities.provider_adapters` code.

## Reconciliation with the docs' manifest guide

[`docs/extensions/manifest-reference.md`](../../docs/extensions/manifest-reference.md)
describes the manifest schema the future `maistro-ext-sdk` package (#949)
will enforce; that package has not landed in this tree, so its envelope has
no executable validator here. The platform's *install* envelope —
`manifest_version`, `id`, `name`, `version`, `publisher`, `api_version`,
`permissions`, `entry_points`, `artifact`, optional `dependencies` — is what
`maistro.extensions` actually validates, and it is what this repository
ships. The authority *names* are the documented closed vocabulary either
way; when the SDK package lands and unifies the envelopes, only
`manifest.json` files change, never extension code.

One platform seam needs the same reconciliation noted: dependency ranges.
The lock resolver (`maistro.extensions.resolution`) reads comparator lists
(`>=1.0.0,<2.0.0`), while the install-time compatibility preflight
(`maistro.extensions.compatibility`) accepts exact versions, `^X.Y.Z`, or
`*` and fails closed on anything else — so the two layers accept different
grammars today. This repository pins dependency ranges exactly (`1.0.0`),
the one form both layers validate; the lock carries the full immutable
identity anyway, so the pin loses nothing. Platform lanes own unifying the
grammars; when they do, only `manifest.json` changes.

## How the boundary is kept

The gallery packages import nothing first-party — not the product, not the
repo-relative roots, not even the (not-yet-published) SDK package. The
same two reusable gates run in CI against this policy:

```
python3 scripts/check-extension-imports.py --policy extensions/reference-gallery/namespace-policy.json
python3 scripts/check-reference-extension.py --policy extensions/reference-gallery/namespace-policy.json
```

The isolation fixture builds each package as a wheel and runs its tests in
a fresh venv containing no part of this repository — the executed proof
that the gallery builds and tests without cloning or importing MAIstro
core internals.
