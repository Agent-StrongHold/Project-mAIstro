---
inventory-delta:
  packages/maistro-core/tests: +15
---

# 1872-interrupted-reclaim-rediscovery-repair

Production repair for the gap #1863 characterized on PR #1872: the recovery
tick's replay half now re-finds a reclaimed Attempt (CANCELLED with the sweep's
own reclaim evidence) that is still the newest row under a NodeRun the canonical
Run/NodeRun still show RUNNING, and reconciles it with the RECOVERED cause, so
the stranded Run parks WAITING instead of waiting for a reconcile that would
never come.

This file adds the scope guards that keep the rediscovery narrow:
retry-owned terminals (FAILED, TIMED_OUT, requested-CANCELLED) stay with their
owners, a reclaimed Attempt a newer Attempt supersedes is not parked over, a
stranded node parks alone while a leased sibling keeps the Run RUNNING, and the
tick keeps its #1850 counting rule (a rediscovery-only tick reports zero). The
four #1863 characterization nodes themselves are unchanged and now pass on the
in-memory and SQLite boundaries.
