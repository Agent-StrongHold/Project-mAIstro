# Canonical compatibility windows

M1 convergence may move or rename canonical contracts, but it must not silently reinterpret durable identity, persisted history, or a cross-product API. This policy extends the architecture-fitness vocabulary established by #36: a compatibility owner is an adapter around one canonical owner, never a second authority.

`quality/compatibility-contracts.json` is the machine-readable contract consumed by the blocking architecture-fitness suite. It records the current canonical identity surface and every reviewed compatibility alias.

## Rename rule

A breaking rename or move of a canonical Workspace, Project, Graph, Run, NodeRun, Attempt, Event, Invocation, or shared cross-product contract requires an explicit compatibility disposition in the same reviewed change. The disposition must state the old and replacement identity, compatibility scope, migration strategy, deprecation window, owner, retirement condition, and release-note obligation.

For import-only names, a non-authoritative import alias is sufficient while the compatibility window is open. New code uses the canonical name. The alias must remain visibly marked as compatibility-only and cannot own persistence, lifecycle, sequencing, or routing behavior.

If persisted or cross-product data can outlive the rename, an import alias is not enough. The compatibility record must use one of: dual-read, schema migration, translation adapter, or version negotiation. Pre-rename records remain interpretable through the declared window; an existing ID or historical record must never acquire a different meaning.

## Version and migration discipline

A canonical type or required identity field listed in `canonical_surface` may not disappear from the candidate tree merely because references were renamed. The fitness gate fails first. The reviewed migration then updates the canonical surface and records the compatibility disposition that makes old readers/data interpretable.

Compatibility adapters are explicitly non-authoritative. They translate or preserve old names only; they may not mint replacement canonical IDs, create a second lifecycle, or become a durable owner. Every adapter has a named retirement condition tied to convergence retirement evidence (#35 or a more specific successor).

Breaking canonical contract changes must be called out in release notes/changelog. The compatibility registry requires a release-note obligation for every compatibility entry so deletion cannot be treated as an internal refactor.

## Persisted fixture requirement

Whenever `persisted_data` is true, the owning change must include a pre-rename persisted fixture and a test that loads it through the declared compatibility strategy. The registry rejects `import-alias` as a persisted-data strategy. A future persisted rename is therefore incomplete until the durable compatibility path and fixture exist.

## Immediate breaks

An immediate break is exceptional. It requires a reviewed compatibility record whose deprecation window explicitly says `immediate-break`, names the owner and disposition/retirement plan, explains why no surviving persisted or cross-product consumer exists, and calls out the break in release notes. It still may not reinterpret an existing canonical ID or historical record.

## Removal

A compatibility entry is removed only when its stated retirement condition is proven. Removing the implementation without removing the registry entry is a stale-ledger failure; removing the registry entry while the alias still exists is an unreviewed-alias failure. This makes compatibility windows monotonic and visible while multiple convergence branches are active.
