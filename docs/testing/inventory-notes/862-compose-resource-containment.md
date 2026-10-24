---
inventory-delta:
  tests/: +5
---

# #862 Compose resource containment

Added five root contract tests for the resource policy gate:

- supported standalone Compose profiles pass the finite memory, swap, PID, and
  CPU policy;
- each service carries all four effective service-level controls and does not
  rely on Swarm-only `deploy.resources`;
- missing limits and effectively unbounded values fail closed; and
- both Copier Compose templates render the same containment controls.

The gate covers the concrete Docker/Podman Compose files, supported overlays,
and the Phoenix add-on. Overlays repeat the ceiling intentionally so a rendered
file cannot appear safe only because a reviewer happened to know its base.
