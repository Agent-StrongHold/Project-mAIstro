# reference-greeter

The reference MAIstro extension (M9-A3, #951): a complete, buildable,
out-of-tree package that shows an external author every artifact an extension
needs and nothing it doesn't.

- `extension.json` — the manifest: identity, contract range, family,
  capabilities (empty — least authority), effects, entrypoint.
- `src/reference_greeter/plugin.py` — the entrypoint object the manifest names.
- `tests/` — the extension's own contract tests, runnable in a bare venv.

## Build and test from a clean environment

```bash
uv build --wheel --out-dir dist
uv venv .venv-isolated
uv pip install --python .venv-isolated/bin/python dist/reference_greeter-1.0.0-py3-none-any.whl pytest
.venv-isolated/bin/python -m pytest tests -q
```

No path into the MAIstro repository is used at any step; the wheel and pytest
are the only things the venv contains. `scripts/check-reference-extension.py`
runs exactly this sequence in CI against a throwaway venv.

The normative manifest schema is the versioned extension SDK package
(`maistro-ext-sdk`, M9-A1); the field-by-field guide lives at
[`docs/extensions/manifest-reference.md`](../../docs/extensions/manifest-reference.md).
