---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---

# Evolve cycle membership fencing (#1065)

Adds focused behavioral coverage for the admission-time population snapshot,
rejection of pair work beyond immutable graph capacity, serialization of
manual/background cycle admission through the shared service lock, and real
HTTP POST /seed plus racing POST /cycle requests through that admission path,
including a real canonical cycle whose persisted pair plan excludes the delayed seed.

Review disposition for the unresolved #947 pair-sizing thread: pair capacity and
pair planning now both derive from the same admission-time membership snapshot;
post-admission seeds are excluded from that Run and recorded membership/provenance
makes the decision inspectable.
