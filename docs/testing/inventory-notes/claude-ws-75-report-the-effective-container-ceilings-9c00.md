---
inventory-delta:
  packages/maistro-core/tests: +17
  packages/maistro-server/tests: +2
---
# claude-ws-75-report-the-effective-container-ceilings-9c00

Additions only; no test was removed, renamed or skipped.

- `packages/maistro-core/tests/security/test_container_limits.py` (+17) covers
  the new cgroup v2 reader `maistro.security.container_limits`. Each case
  writes a real cgroup tree under `tmp_path`. The cases are: bounded and
  `max` values for memory, PIDs and CPU; a fractional CPU quota; a missing
  hierarchy and a missing per-controller file, both `unknown`; an unreadable
  entry; the default mount; and ten parametrized malformed inputs that must
  read `unknown` without raising, including a quota too large to divide into
  a float and one longer than Python's int-parsing digit limit.
- `packages/maistro-server/tests/api/test_resource_policy_health.py` (+2)
  asserts that `GET /health/ready` reports `container_limits`. It runs once
  with a bounded/unbounded tree and once with no hierarchy, injected through
  `maistro_server.api.health.CGROUP_ROOT` (#75).
