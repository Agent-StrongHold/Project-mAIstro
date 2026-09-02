---
inventory-delta:
  tests/: +7
---
# M1 #899 bounded build evidence

Adds seven pytest node IDs to `tests/test_buildx_build_retry.py` for the CI
budget-coherence defect observed while closing M1.

One test uses a fake `docker buildx build` that never returns and proves the
per-attempt deadline terminates it, retries it, and ultimately fails rather
than reporting green. Five parametrized cases prove zero or malformed timeout
values are rejected before Docker is invoked. One workflow-contract test pins
the producer/aggregator budget ordering: the docker-build outer ceiling is 25
minutes, the Integration Scope evidence poll window is at least the observed
35-minute runner-scheduling lag plus that producer ceiling, and the aggregator
job ceiling is longer than its poll window.

Existing tests continue to cover immediate success, transient failure followed
by success, persistent failure, configurable retry count, and the `--` workflow
call-site contract. No production test inventory is removed or weakened.
