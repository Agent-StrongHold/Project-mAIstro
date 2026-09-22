# Backend Package Namespaces

The retained backend application namespaces are explicit and stable:

| Application | Import namespace | ASGI target |
|---|---|---|
| Hive Conductor / Workspace | `hive_conductor` | `hive_conductor.main:app` |
| Turing backend | `maistro_turing_backend` | `maistro_turing_backend.main:app` |

`maistro_turing` remains the reusable Turing runtime library. The
`maistro_turing_backend` namespace is its HTTP application surface, not a
second runtime or execution authority.

Application modules must remain below their approved namespace. In particular,
`main`, `routes`, `middleware`, `config`, and `state` must not be resolved as
backend-owned top-level modules. The CI fitness check in
`scripts/check-backend-package-namespaces.py` rejects flat Python modules and
unpackaged Python directories under `packages/*/backend/`.

Both services can therefore be imported in one Python process without
`sys.path` ordering or `sys.modules` aliases deciding which application's
`main` or route package wins. Deployment entry points use the same qualified
ASGI targets documented above.
