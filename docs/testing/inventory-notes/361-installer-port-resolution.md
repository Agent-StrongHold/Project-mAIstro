---
inventory-delta:
  tests/: +41
---
# 361-installer-port-resolution

`tests/test_install_port_resolution.py` (new file, 41 collected node IDs —
six of its test functions expand under `@parametrize`) guards the
issue-#361 rewiring of `install.sh`: one resolved port configuration drives
Compose, health waits, callbacks, and printed URLs. Following the established
verbatim-lift pattern (`tests/test_install_engine_floor.py`,
`tests/test_secret_env.py`), the tests sed-extract the real functions
(`setting_value`, `setting_source`, `resolve_effective_config`,
`compose_published_port`, `read_back_effective_ports`, `wait_for_engine_health`,
`wait_for_conductor_health`, plus helpers) out of `install.sh` and run them
under `set -euo pipefail` against stub `docker`/`curl` binaries.

Covered: resolution precedence matching Compose interpolation (process
environment > .env > default, including quoted and commented .env values);
fail-closed port validation naming the value's source; IPv6 bind-address
bracketing for compose mappings and URLs; read-back of the published mapping
before polling (override remap — the reverse-proxy-fronted mechanism) with
warn-and-fallback when the front-end cannot answer; probes demonstrably hitting
the mapping compose actually bound rather than the process environment; the
never-healthy terminal path; and per-install resolution isolation — each
install directory resolves its own configuration with nothing bleeding between
resolutions (resolver-contract isolation only: simultaneous Compose stacks
collide on `docker-compose.yml`'s fixed container names and host ports
regardless of disjoint `MAISTRO_PORT`/`HIVE_PORT`, so true concurrent-stack
installs are not claimed here). Four structural pins hold the wiring: `main()`
resolves after
env validation and before `start_engine`; `start_engine` reads the mapping back
between `up` and polling; no consumer hand-builds `http://${BIND_HOST}` URLs;
and the 8101 Conductor default is declared once.

The curl stub is unconditional: a real curl aimed at a port another process on
the test machine occupies (and never answers) hangs the harness — the same
occupied-port hazard the installer must fail closed on.

No existing test was moved, renamed, parametrized, or deleted, so the
root-suite collection change is exactly +41 node IDs. (Repair round: the
original note recorded +39 by counting `def test_` functions instead of
collected node IDs — the exact mistake the C1/#286 gate exists for — and the
concurrent-installs case was scoped to the resolver contract per the
collision note above. The delta was corrected to +41 via
`check-suite-inventory.py --update`; no test count moved in that round.)
