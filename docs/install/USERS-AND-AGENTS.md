# Users, tenancy, and install output

Installer answers include `users_intent` (`bootstrap_admin` | `sso_later` | `skip`). That flag is **not** executed by `maistro-install`; it drives documentation and future wiring.

## Product templates (Copier)

When `product` is set in answers, the CLI prints a `copier copy …` line per [ADR-033](../adr/ADR-033-templates-and-copier-workflow.md). Single-tenant and autonoetic templates live under `templates/`; Stronghold-shaped products stay **out of tree** (see [resolver-matrix](resolver-matrix.md)).

## maistro-server auth

The default `docker-compose.yml` stack sets `REQUIRE_AUTH=true` for `maistro-engine`. Create users and API keys through the product’s documented admin path after compose is healthy — **not** via committed YAML secrets.

## Next steps

- [SPEC-181](../specs/SPEC-181-hive-missions-maistro-core-bridge.md) for mission execution beyond Hive stubs.
