---
inventory-delta:
  packages/maistro-core/tests: +17
---
# 980-catalog-json-refusal-coverage

CI-repair round on #980 (M9-J2): the Coverage gate's diff half failed at
`packages/maistro-core/src/maistro/extensions/catalog_json.py` — 84.3% of 121
changed lines against the 90% per-file floor, 19 uncovered lines, every one a
fail-closed refusal branch the review-fix round's tests never reached.

## What moved

`packages/maistro-core/tests` (+17), all in
`packages/maistro-core/tests/extensions/test_catalog_json.py`. The existing
seven tests pinned the digest, format, signature, artifact-claim and duplicate
refusals; the new seventeen walk the rest of the parser's refusal surface,
branch by branch:

- Document level: text that is not JSON, a JSON document that is not an
  object, a document carrying no `catalog_snapshot_sha256`, and both shapes of
  an entry-less document (key absent, empty list).
- Entry level: an entry that is not an object, an entry missing required keys,
  `manifest_bytes` that is not a string, an identity whose name or version
  contradicts the manifest bytes, and manifest bytes that inspect cleanly but
  no longer digest to the identity's `manifest_sha256`.
- Identity level: a non-object identity, an identity missing fields, and
  digest fields that are not 64 lowercase hex characters (both the wrong
  characters and the wrong length).
- Dependencies: a non-array `dependencies`, a non-object dependency, and the
  parse-through — declared edges reaching `CatalogEntry` in resolution's form
  with `required` defaulting on and honoring an explicit opt-out — plus the
  blank-required-string refusal (`_string_field`'s empty case).

No production code changed: the gate's complaint was measurement of refusal
branches that existed and were unexercised, so the repair is the missing
evidence, not new behavior.
