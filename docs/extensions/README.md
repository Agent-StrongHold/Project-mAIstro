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

## Guides

| Document | What it covers |
|----------|----------------|
| [Authoring guide](authoring-guide.md) | Build an extension from zero, and build the reference package from a clean environment. |
| [Manifest reference](manifest-reference.md) | Every `extension.json` field, the closed authority vocabulary, and the contract-versioning/deprecation rules. |
| [Lifecycle](lifecycle.md) | What happens between discovery and teardown, and what an extension may do at each stage. |
| [Capabilities](capabilities.md) | Worked examples for every capability, effect, and data scope — least authority by default. |

The normative, machine-validatable manifest schema is the versioned extension
SDK package itself (`maistro-ext-sdk`, M9-A1, #949); these guides explain how
to use it, and the canonical extension lifecycle context is defined by
M9-A2 (#950).
