---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---

# Evolve cycle membership fencing (#1065)

Adds focused behavioral coverage for the admission-time population snapshot,
rejection of pair work beyond immutable graph capacity, serialization of
manual/background cycle admission through the shared service lock, and real
HTTP POST /seed during evaluation and battle traversal. Two racing POST /cycle
requests now execute against the real canonical Graph/Run path, with persisted
pair plans and finalization evidence checked for both Runs.

Review disposition for the unresolved #947 pair-sizing thread: pair capacity and
pair planning now both derive from the same admission-time membership snapshot;
post-admission seeds are excluded from that Run and recorded membership/provenance
makes the decision inspectable.
