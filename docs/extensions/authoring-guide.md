# Extension authoring guide

From nothing to a working, policy-clean extension package — using the
reference extension (`extensions/reference-greeter/`) as the worked example.

## 0. What you need

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/) (any PEP 517 builder
  works; the examples use `uv build`).
- Nothing from the MAIstro repository: no checkout paths, no `sys.path`
  editing, no product packages. If your extension needs a repository checkout
  to build or test, it is depending on product internals and will fail the
  boundary gate (`scripts/check-extension-imports.py`) and the isolation
  fixture (`scripts/check-reference-extension.py`).

## 1. The package layout

An extension is its own buildable project. Recommended layout:

```
my-extension/
├── pyproject.toml          # the project: name, version, dependencies
├── extension.json          # the manifest (see manifest-reference.md)
├── src/
│   └── my_extension/
│       └── plugin.py       # the entrypoint object the manifest names
└── tests/
    └── test_my_extension.py
```

Rules the gates enforce:

- **One project per extension**, with its own `pyproject.toml`. Extension
  packages in this repository live under `extensions/`, never under
  `packages/` — `packages/*` is the product workspace.
- **Declare every third-party dependency** in `[project].dependencies`. An
  import that is not the standard library, your own package, the public SDK
  root (`maistro_ext_sdk`), or a declared dependency fails the gate.
- **Never import first-party product modules.** `maistro`,
  `maistro_server`, `maistro_turing`, `maistro_canvas`, `maistro_bootstrap`,
  `maistro_registry`, `maistro_design`, `maistro_evolve`, and `maistro_rsi`
  are product-private. `maistro_ext_sdk` is the public SDK root.
- **Never repair `sys.path`** or import `packages.*` / `extensions.*` —
  those are repo-relative imports: they depend on a checkout, not a release.
- Underscore-prefixed modules are private **even under the public SDK root**;
  `maistro_ext_sdk._internal` is exactly as forbidden as `maistro` itself.

## 2. The manifest

`extension.json` declares identity, the contract version you code against,
your extension family, and the authority you need (capabilities, effects,
data scopes, network, filesystem, secrets). Field-by-field:
[manifest-reference.md](manifest-reference.md). The reference extension's
manifest is the smallest honest one:

```json
{
  "id": "reference.greeter",
  "publisher": "reference",
  "version": "1.0.0",
  "title": "Reference greeter tool",
  "description": "A tool extension that reads nothing, writes nothing, and greets.",
  "contract": ">=1.0.0,<2.0.0",
  "family": "tool",
  "capabilities": [],
  "effects": ["read-only"],
  "data": { "scopes": [] },
  "entrypoint": { "module": "reference_greeter.plugin", "object": "PLUGIN" }
}
```

Declaring nothing yields nothing: an extension with no capabilities receives
no authority, and the host grants only what the manifest declares.

## 3. The entrypoint

The manifest's `entrypoint` names a module and an object. Keep it plain —
validation never imports it; a host loads it only after the manifest is
accepted:

```python
PLUGIN: dict[str, object] = {
    "kind": "tool",
    "name": "reference.greeter",
    "version": "1.0.0",
    "capabilities": [],
    "handler": "greet",
}

def greet(target: str = "world") -> str:
    return f"Hello, {target}!"
```

The canonical context object and lifecycle hook signatures an entrypoint
receives are defined by the extension SDK's lifecycle contracts (M9-A2,
#950); until you adopt them, keep the entrypoint data-only so upgrading is a
type annotation, not a rewrite.

## 4. Build and test from a clean environment

This is the exact sequence the isolation fixture executes against the
reference extension; run it in your own extension to check yours:

```bash
uv build --wheel --out-dir dist
uv venv .venv-isolated
uv pip install --python .venv-isolated/bin/python dist/reference_greeter-1.0.0-py3-none-any.whl pytest
.venv-isolated/bin/python -m pytest tests -q
```

What proves what:

- `uv build --wheel` succeeds with **no repository on the path** — your
  `pyproject.toml` and your source tree are enough.
- The fresh venv contains **only your wheel and pytest** (plus the
  dependencies your wheel declares). If the tests pass there, they need no
  repo-relative import and no product-private module.
- To see the negative control yourself:
  `.venv-isolated/bin/python -c "import maistro"` must print
  `ModuleNotFoundError`.
- The manifest rides in the wheel: the fixture reads `extension.json` back
  out of the installed distribution before running your tests, so packaging
  that drops the manifest fails the fixture instead of surfacing when a host
  first tries to discover your extension.
- The fixture stages your `tests/` into its sandbox before running them, so
  a suite can only read files the installed wheel actually ships — never a
  resource that happens to sit next to the checkout's tests.

The wheel is what a host installs. Tests import your package through the
venv's `site-packages`, exactly as a user's runtime would.

## 5. Before you publish

- Run the boundary gate against your tree: from a MAIstro checkout with your
  extension under `extensions/`, `python3 scripts/check-extension-imports.py`.
- Pin your manifest's `contract` range to the major you coded against
  (`>=1.0.0,<2.0.0`); see [manifest-reference.md](manifest-reference.md) for
  the versioning and deprecation rules.
- Declare the least authority that works: every capability, effect, and data
  scope you claim is one a host must grant — and one a security reviewer will
  read. See [capabilities.md](capabilities.md).
