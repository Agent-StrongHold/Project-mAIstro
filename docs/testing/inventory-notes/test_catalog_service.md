---
inventory-delta:
  packages/maistro-core/tests: +11
---
Private organizational extension catalog service tests (#979, M9-J1).

`packages/maistro-core/tests/extensions/test_catalog_service.py` replaces its
broken draft with eleven cases mapped to the issue's acceptance criteria:

- fresh-instance discovery: an organization with no published snapshot sees
  no catalog, empty listings, no version history, and no detail (empty
  results, never partial data);
- publish/round-trip: entries and their inspected manifest snapshots are
  both retrievable per identity;
- snapshot immutability: mutating the sequence a snapshot was published
  from cannot rewrite catalog history, and entries are frozen records that
  refuse in-place publisher/signature tampering;
- listing: name-then-semantic-version ordering (9.0.0 before 10.0.0 — a
  lexicographic sort would invert them), search across extension name and
  publisher case-insensitively, exact publisher filtering, and the combined
  filter;
- version history: semantic newest-first ordering per extension, with other
  extensions excluded;
- detail: the immutable-artifact digest chain (package, manifest, source
  digests) plus manifest-declared requested permissions and dependencies;
- degraded availability: a store serving no manifest bodies still yields
  digest-level entry metadata, and manifest claims are absent rather than
  invented — catalog metadata stays inspectable without the manifest bytes;
- authority separation: the service surface offers exactly the six
  read/publish methods and nothing resembling install or activation, pinning
  that the catalog cannot grant runtime extension authority.

No existing cases were removed or renamed; the suite count moves +11.
