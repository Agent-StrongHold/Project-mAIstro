# Extensions

MAIstro extensions are external packages that add tools, skills, MCP
gateways, capability providers, and renderer plugins to a running product.
They are built against a **versioned public SDK**, never against this
repository's internal modules — the boundary is enforced, not suggested:

- **Namespace policy** — [`../../extensions/namespace-policy.json`](../../extensions/namespace-policy.json)
  (repo root `extensions/`) declares the public SDK roots and the
  product-private roots. Underscore-prefixed modules are private even under a
  public root.
- **Import gate** — `scripts/check-extension-imports.py` fails CI when any
  extension package imports a product-private module, repairs `sys.path`,
  reaches across repo-relative roots (`packages.*`, `extensions.*`), or
  imports a third-party dependency it does not declare.
- **Isolation fixture** — `scripts/check-reference-extension.py` builds each
  extension as a wheel, installs it into a fresh venv (plus pytest, nothing
  else), proves the product's own modules are unimportable there, and runs
  the extension's tests with that interpreter. This is the executed proof
  that an extension needs no repo-relative import to build or test.

The reference extension lives at `extensions/reference-greeter/` — outside
`packages/`, with its own `pyproject.toml`, because that is how every
third-party extension looks from the outside.

## Domain packs (M9-F, #966)

A **domain pack** is an extension that ships reusable *defaults* — Graph
shapes, Persona templates, Rubric dimension catalogs — as version-addressable
assets instead of (or alongside) code. Its manifest is a governed-install
subtype (`"kind": "domain-pack"`, parsed fail-closed from bytes by
`maistro.extensions.packs.inspect_pack_manifest`, the M9-B machinery's
namespace), and its contract is canonical-object-only: instantiation mints
canonical `GraphTemplate`/`Persona`/`RubricSemantic` identities bound to
caller-named Workspaces, the pack-local asset ids ride only in provenance
(full exact-source identity: publisher, pack version, asset id/version, and
the manifest digest — on `GraphTemplate` metadata, `Persona`
`extension_metadata`/`source_template_*`, and the canonical
`RubricProvenance` detail fields), dependencies resolve through the same
compatibility evaluator every extension
uses, and disabling a pack gates new use without touching anything already
created. The manifest snapshot is anchored to its bytes — payload trees are
frozen at parse time and every asset use resolves against a pristine
re-parse of `raw`, so a mutated stored snapshot cannot make new
instantiations diverge from the digest their provenance names. No pack can
declare an executor, a store, or a Goal/Persona/Rubric
authority — the schema has no such field, and instantiation persists nothing.
The in-repo product/game/book packs of `maistro_design.packs` (#793) remain
the shipped defaults; `maistro.extensions.packs` is the installable,
out-of-tree generalization (M9-F1), whose Workspace-scoped activation
lifecycle is M9-F3 (#968).

## Guides

| Document | What it covers |
|----------|----------------|
| [Authoring guide](authoring-guide.md) | Build an extension from zero, and build the reference package from a clean environment. |
| [Manifest reference](manifest-reference.md) | Every `extension.json` field, the closed authority vocabulary, and the contract-versioning/deprecation rules. |
| [Lifecycle](lifecycle.md) | What happens between discovery and teardown, and what an extension may do at each stage. |
| [Capabilities](capabilities.md) | Worked examples for every capability, effect, and data scope — least authority by default. |
| [Tool and Skill contracts](tool-skill-contracts.md) | How the host classifies `tool`/`skill` packages, who may call them, and the one governed path every call crosses (M9-E3). |
| [Upgrade preflight](upgrade-preflight.md) | Evaluating installed extensions against a target host release before upgrading — compatible, deprecated, migration-required, or blocking. |

The normative, machine-validatable manifest schema is the versioned extension
SDK package itself (`maistro-ext-sdk`, M9-A1, #949); these guides explain how
to use it, and the canonical extension lifecycle context is defined by
M9-A2 (#950).
