---
inventory-delta:
  tests/: +7
---
# s1-3-openapi-types-gate

Workspace cutover S1.3 (#1048): the hive-conductor frontend's entity types are
now generated from the backend's OpenAPI document into
`packages/hive-conductor/frontend/src/api/types.gen.ts`, and CI fails when a
fresh generation differs from the committed file.

All +7 node IDs are one new file, `tests/test_dump_hive_openapi.py`, covering
`scripts/dump-hive-openapi.py`:
- two cases that the written bytes depend only on the document (key order does
  not leak through; output is newline-terminated JSON of the same document);
- two cases that the dump writes nothing when an optional router failed to load
  or the document has no paths, so the drift check cannot pass on a partial
  schema;
- three cases against the real app: every optional router loads, the schema
  carries paths and components, and a built `frontend/dist` (which registers
  `spa_fallback`) leaves the schema's paths unchanged. That last one fails
  without the `include_in_schema=False` added to `spa_fallback` in `main.py`.

No other suite moved.
