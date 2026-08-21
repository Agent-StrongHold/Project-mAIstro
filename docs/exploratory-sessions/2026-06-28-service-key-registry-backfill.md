---
date: 2026-06-28
tester: Claude (agent)
area: packages/maistro-core/src/maistro/auth/registry.py — ServiceKeyRegistry
charter: "Retroactive backfill: this session predates docs/EXPLORATORY-TESTING.md. Logged now, from the original change, as proof the BACKLOG escalation path works for past findings, not just future ones."
---

## Observations

While extending `formal/models/test_auth_registry.py` with adversarial fuzzing (malformed YAML,
colliding env-derived key hashes) for the Phase 0 adversarial-testing pass, fuzzing
`ServiceKeyRegistry.load_dict`/`load_yaml`/`load_env` surfaced two real issues in
`auth/registry.py`, not just gaps in test coverage:

1. **Stale key mapping.** `load_dict`/`load_env` previously did `self._key_to_name[key] = name`
   unconditionally on every (re-)registration. If a service was registered twice with two
   different keys (e.g. a key rotation replayed through `load_yaml` then `load_env`, or two
   YAML files both defining the same service name with different keys), the *old* key stayed in
   `_key_to_name` pointing at the same service name — so a rotated-out key kept authenticating
   as that service indefinitely. Fixed by adding `_register_key()`, which removes any other key
   currently mapped to the same name before inserting the new one.
2. **Unguarded YAML/shape parsing.** `load_yaml` called `yaml.safe_load` and indexed
   `data["services"]` with no exception handling around malformed YAML (`yaml.YAMLError`) and no
   type check on `data` or `data["services"]` before treating them as mappings — a malformed
   config file would raise an uncaught exception out of `load_yaml` instead of degrading
   gracefully, inconsistent with `discover_into`'s established "log and skip" philosophy
   elsewhere in the capability-discovery code. Fixed with explicit `isinstance` checks and a
   `try/except yaml.YAMLError`.

## Findings

| # | Kind | Description | Escalated to | Follow-up test |
|---|------|-------------|---------------|----------------|
| 1 | bug | Stale key-to-name mapping let a rotated-out service key keep authenticating after re-registration with a new key. | `BACKLOG.md#engine-110` | `formal/models/test_auth_registry.py` (key-rotation / re-registration cases) |
| 2 | bug | `load_yaml` raised uncaught exceptions on malformed YAML or a non-mapping `services` value instead of degrading per `discover_into`'s log-and-skip convention. | `BACKLOG.md#engine-110` | `formal/models/test_auth_registry.py` (malformed-YAML and malshaped-`services` cases) |
