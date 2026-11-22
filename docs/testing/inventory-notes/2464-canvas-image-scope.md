---
inventory-delta:
  packages/maistro-canvas/tests: +2
  packages/maistro-server/tests: +10
---
# 2464-canvas-image-scope

Issue #2464 (M1-D1): bind the Canvas image Invocation authorization and
attribution to the owning canonical Run's scope.

## What moved

**`packages/maistro-server/tests` +10** — seven land in
`test_canvas_runtime.py`, four in the new `test_canvas_scope_postgres.py`
(collected here; it runs only with `MAISTRO_TEST_PG_DSN`):

- The governed image client now resolves its Binding through
  `BindingStore.resolve` in the executing Run's durable scope instead of a
  bare `get`, and cannot be constructed without a scope. Five unit tests pin
  the edges: a Binding registered in another scope and a Run whose bound
  scope differs from the composition's both refuse with `BindingScopeDenied`
  before any egress call (the negative criterion: no provider invocation, no
  misleading receipt), the scope-matched Run still dispatches, and an
  unscoped construction is refused.
- `start_canvas_job_runner` registers the image Binding under a
  scope-qualified id in the chat admission scope. Three runner tests pin the
  registration scope (never the caller's settings value, never a fabricated
  `default`), a settings/admission disagreement refusing the start, and the
  upgrade path: a pre-fix row under the retired bare-family id stays
  untouched and unconsulted while the new identity registers beside it.
- The PostgreSQL E2E walks the acceptance chain on the stores production
  wires — Run → NodeRun → Attempt → Binding → Invocation — against a
  database migrated by the root Alembic chain: one consistent non-default
  Workspace/Project across all five identities, restart reusing the persisted
  Binding, two tenants on one database holding distinct Bindings and their
  own scopes, and a foreign-scope Run claimed by another tenant's runner
  refused with zero provider requests and zero Invocation rows.

**`packages/maistro-canvas/tests` +2** — the executor's error sanitizer
classifies a Binding authorization refusal as governed-boundary machinery
(truthful fixed message, retryable) rather than a provider fault; and the
stage projection guard refuses a yielded Attempt (Canvas has no pause
semantics) instead of projecting an empty receipt.

## Why the counts moved the way they did

No tests were removed: the existing suite's assertions were updated in place
where the fixed Binding id and scope changed what a passing record looks
like (registration scope, restart reuse, conflicting-shape refusal), so the
old identities test the same behaviors under the corrected contract rather
than disappearing. The PG E2E suite is deliberately its own module: it needs
a per-module migrated database (the supported-path E2E's pattern) and skips
without a server, so its four node IDs collect everywhere and run where the
service exists.
