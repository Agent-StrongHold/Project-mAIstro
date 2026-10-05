# Extensions

Extension packages live in this tree, **outside `packages/`**, on purpose: an
extension is a third-party-shaped project that must build and test on its own,
against the public extension SDK — never against this repository's internal
layout (no repo-relative imports, no `packages.*` imports, no `sys.path`
repairing).

## What is in here

| Path | What it is |
|------|------------|
| [`namespace-policy.json`](namespace-policy.json) | The machine-readable public package namespace policy. Declares which first-party import roots are public SDK and which are product-private. |
| [`reference-greeter/`](reference-greeter/) | The reference extension: a minimal, buildable, out-of-tree package with its own `pyproject.toml`, manifest, entrypoint, and tests. |

## How the boundary is enforced

- **`scripts/check-extension-imports.py`** — static gate. Reads the policy
  file, walks every Python file under every extension tree, and fails on any
  import that is product-private, repo-relative, `sys.path`-repaired, or an
  undeclared third-party dependency. Underscore-prefixed modules are private
  even under a public SDK root.
- **`scripts/check-reference-extension.py`** — isolation fixture. Builds each
  extension as a wheel, installs it (plus pytest, nothing else) into a fresh
  venv, and runs its tests there. A fresh venv contains no part of this
  repository, so the run doubles as the proof that the extension needs no
  repo-relative imports and no product-private modules to build or test.

Both run in CI (`lint-and-type-check` job in `.github/workflows/ci.yml`).

## Authoring

Start at [`../docs/extensions/authoring-guide.md`](../docs/extensions/authoring-guide.md);
the manifest fields are tabled in
[`../docs/extensions/manifest-reference.md`](../docs/extensions/manifest-reference.md).
The normative, machine-validatable manifest schema is the versioned extension
SDK package itself (`maistro-ext-sdk`, M9-A1).
