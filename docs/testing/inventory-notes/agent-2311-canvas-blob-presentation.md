---
inventory-delta:
  packages/maistro-canvas/tests: +17
  packages/maistro-server/tests: +19
---
# agent-2311-canvas-blob-presentation

maistro-canvas **+17**:

- `test_blob_presentation.py` (**+10**): the blob-reference / presentation-URL
  seam. Pins the classification (a governed reference is a canonical UUID;
  data URLs, remote URLs, paths and non-canonical UUID spellings never are),
  the one-authorized-path mapping, the pass-through behavior the design
  serializer relies on, and that a non-reference cannot be forced into a blob
  path.
- `test_canvas_blob_store.py` (**+7**): the `PgCanvasStore` blob contract
  behind the serving route. Store/read round trip carries bytes, media type
  and the Workspace/Project scope stamp through real PostgreSQL (PG-gated,
  throwaway schema); a fresh store instance reads the committed row (the
  restart half of the durability claim); an unknown id reads as absence for
  both reads; `get_blob` and `read_blob` answer one row. The metadata
  coercion branches (jsonb as text, native dict, anything else) are
  unit-tested without a server.

maistro-server **+19**:

- `test_canvas_blob_route.py` (**+16**): the authorized bytes door
  `GET /v2/canvas/blobs/{blob_id}` and the layer serialization that maps
  stored references to it. Owner and member read the exact bytes with the
  stored media type; a foreign principal, a revoked member, a guessed id, a
  blob scoped to another Workspace and an unscoped blob all read absence
  (404); unauthenticated-with-keys is 401; a missing Workspace store, a
  missing Canvas store and a store without whole-row reads answer 503 rather
  than guessing. The serializer half asserts the URL never regresses to the
  raw reference (the negative test: restoring UUID-as-URL fails here), that
  non-reference image values pass through untouched, and that the emitted
  URL round-trips back to the bytes.
- `test_canvas_supported_path.py` (**+3**, PG-gated): the full generate →
  durable scope-stamped blob → presented URL → authenticated retrieval →
  accept-variant → fresh-store-restart path over real PostgreSQL, plus the
  second-variant byte identity and the foreign-principal/guessed-id denials
  on the wired surface.
