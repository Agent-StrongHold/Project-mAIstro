---
inventory-delta:
  tests/: +1
---
# Issue 1134 — Hive Docker build context must match the Dockerfile's COPY paths

Salvage repair for the #1134 verifier finding: `packages/hive-conductor/README.md`
documented

    docker build -f packages/hive-conductor/Dockerfile packages/hive-conductor -t hive-conductor:local

but the Dockerfile's `COPY packages/maistro-core ...` (and the other
`packages/...` sources) require the *monorepo root* as the build context, so
the exact documented command failed at the first COPY. The README now documents
the root context (`.`), matching the Dockerfile header comment and
`docker-compose.yml` (`context: ../..`).

Added `tests/test_hive_docker_build_context.py` (+1 in `tests/`):

- every `COPY`/`ADD` source in the Dockerfile resolves from the repo root;
- the root-only sources do *not* resolve from the package directory (pinning
  why the package dir can never be the context);
- the README's `docker build` command uses `.` as its context;
- compose keeps `context: ../..`.
