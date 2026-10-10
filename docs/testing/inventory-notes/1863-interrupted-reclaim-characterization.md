---
inventory-delta:
  packages/maistro-core/tests: +4
---

# 1863-interrupted-reclaim-characterization

Adds two exact #1863 characterization tests, each on the in-memory and
file-backed SQLite recovery boundaries. The tests inject process loss only
after the real lease reclaim has committed the physical CANCELLED Attempt and
before logical reconciliation, then compare public rediscovery with an explicit
RECOVERED reconciliation positive control.
