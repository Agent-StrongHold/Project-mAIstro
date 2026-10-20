# maistro-ext-sdk

The public MAIstro **extension SDK**: a versioned extension contract and a
machine-validatable manifest schema that every M9 extension family builds on
([#949](https://github.com/Agent-StrongHold/Project-mAIstro/issues/949),
epic [#938](https://github.com/Agent-StrongHold/Project-mAIstro/issues/938)).

Standalone by design: the only runtime dependency is `pydantic`, and the
package imports **no** `maistro` product module. Extension authors install
this; the product consumes the contract it publishes, never the reverse
(ADR-081226-034b). Import hygiene is enforced by the package's own test
suite (`tests/test_import_hygiene.py`), not by convention.

## Two versions

| Version | Where | Moves with |
|---|---|---|
| Package (`__version__`) | installed dist-info / lockstep fallback | the monorepo `VERSION` file (ADR-073126-c4e1) |
| **Contract** (`contract_version()`) | `maistro_ext_sdk.contract` literal | the manifest schema only — **independently of the application** |

`EXTENSION_CONTRACT_VERSION` is a literal, not a derivation: a manifest
written against contract 1.x keeps validating no matter how many
application releases ship in between.

## Writing an extension

An extension package is a directory with `extension.json` at its root and
the entrypoint module somewhere under it:

```
my-extension/
├── extension.json
└── my_extension/
    ├── __init__.py
    └── plugin.py
```

`examples/minimal-extension/` is the reference to copy. Validate it from any
Python process — **no extension code is imported during validation**:

```python
from maistro_ext_sdk import validate_extension_dir

ext = validate_extension_dir("./my-extension")
print(ext.manifest.id, ext.entrypoint_target())
# only now does a host import ext.manifest.entrypoint.module
```

or from any shell with the installed console script:

```console
$ maistro-ext-sdk validate ./my-extension   # exit 0 iff valid; names the offending token otherwise
$ maistro-ext-sdk schema                    # print the manifest JSON Schema
$ maistro-ext-sdk --contract-version        # print the contract version
```

## Scaffolding a new extension (M9-H1, #973)

```console
$ maistro-ext-sdk new my-tool --publisher acme --family tool
```

writes a complete, valid, buildable project — manifest, packaging metadata
with the SDK pin, a family-shaped entrypoint module, sample tests, and a
README — then validates what it wrote with the same public validator
(fail-closed: a scaffold that cannot validate is a generator bug). Families:
`tool`, `skill`, `mcp-gateway`, `capability-provider`, `renderer-plugin` —
structurally distinct where the contract distinguishes them (the `tool`
template carries the pinned handler protocol; the others are declarative
data-only objects whose pinned protocols arrive with their SDK slices).

The generated project builds and tests outside this repository, runs the
harness conformance suite, and certifies — the full `new → test → validate →
package → sign` flow is executed per family by
`scripts/check-extension-scaffold.py`.

Every failure — malformed JSON, unknown field, unknown capability, contract
mismatch, missing entrypoint file — raises `ExtensionManifestError` with a
message naming the offending token.

## The manifest contract (v1)

| Field | Meaning |
|---|---|
| `id`, `publisher`, `version`, `title` | identity; `id` must be `<publisher>.<name>` |
| `contract` | range of contract versions, e.g. `">=1.0.0,<2.0.0"` |
| `family` | one of `tool`, `skill`, `mcp-gateway`, `capability-provider`, `renderer-plugin` |
| `capabilities` | authority asked of the host (closed vocabulary, e.g. `network.outbound`) |
| `effects` | reversibility classes (ADR-050): `read-only`, `mutating`, `external-side-effect`, `irreversible` |
| `data` | product-data categories touched (`workspace`, `agent`, `run`, `memory`, `messages`, `artifacts`) |
| `network` | `allow` (hosts, `*.`-suffix allowed) + `allowed_ports` |
| `filesystem` | absolute `paths` + `mode` (`read`/`write`/`read-write`) |
| `secrets` | `UPPER_SNAKE_CASE` secret names for the host to inject |
| `dependencies` | other extensions, by id + version range |
| `optional_features` | host-enabled opt-ins: `streaming`, `background`, `scheduled`, `interactive` |
| `entrypoint` | `module` + `object` **as strings** — inspectable without importing |

Least authority runs both ways, and both directions fail validation
explicitly: declaring `network.outbound` without naming hosts is rejected,
and naming hosts without the capability is rejected too. There is no
"unknown" authority: every name is from the closed vocabulary above, so a
manifest cannot invent authority by misspelling one.

## Machine validation without this SDK

`public_json_schema()` emits the contract as a JSON Schema (2020-12)
document; validate manifests against it with any JSON Schema implementation.

## Reconciliation note

ADR-073126-c4e1 makes *package* versions lockstep across the monorepo. The
extension **contract** version is a separate semantic axis that ADR does not
speak to; it versions independently here as #949 requires. A host that
rejects a manifest names the contract version it enforces, so "malformed"
and "written against an older contract" are distinguishable failures.
