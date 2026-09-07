---
inventory-delta: {}
---

# pgvector 0.5.0 typing shim repair (#1025)

Typing-only fix, no test delta. pgvector 0.5.0 began shipping inline types
(`py.typed`) and renamed the SQLAlchemy type to `VECTOR` (keeping `Vector`
as an alias export), which broke the optional-dependency shim in
`maistro/memory/store.py` under mypy: the old `# type: ignore[import-untyped]`
became unused, and `Vector = None` in the `except ImportError` branch became an
illegal rebinding of a now-typed class alias.

The fix pre-annotates the shim name (`Vector: Any`) so the `None` fallback is
legal in both installed and missing-pgvector environments, and drops the stale
ignore. No behavior change: verified that with pgvector installed the
`embedding` column is declared, and with the import blocked it is omitted,
exactly as before. Existing suites cover this surface
(`tests/persistence/`, `tests/memory/`); nothing was added or moved.
