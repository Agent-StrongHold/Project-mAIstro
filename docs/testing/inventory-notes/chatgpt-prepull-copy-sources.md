---
inventory-delta:
  tests/: +2
---
# chatgpt-prepull-copy-sources

Two focused root-suite tests cover external Docker images introduced through `COPY --from=...`, including the shipped `docker:27-cli` source that bypassed the retrying pre-pull step during a merge-group run.

No existing test was moved, renamed, parametrized, or deleted, so the root-suite collection change is exactly +2 node IDs.
