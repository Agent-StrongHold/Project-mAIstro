---
inventory-delta:
  packages/maistro-server/tests: +2
---
# 893-stateful-api-workflows

Two node IDs arrive with the M8-A13 research prototype (#893): a generated
stateful API workflow suite over the tasks/runs/workspaces/projects surface
(`test_api_workflow_statefulness`) and its served-OpenAPI contract probe
(`test_the_served_contract_has_the_workflow_surface`).

The state machine drives the real routers on the in-memory canonical Run spine
the production lifespan wires for a no-database deployment. Bodies for task
submission are drawn from the served OpenAPI document via schemathesis
positive-mode generation; the workflow layer adds what stateless endpoint tests
cannot: transition rules over created resources, cross-request data
dependencies (task_id/run_id/parent_project_id feeding later requests),
authorization variants (a second principal interleaving its own workflow and
probing the first one's resources), and idempotency/retry relations (explicit
keys, derived keys, replay after cancellation, key-payload mismatch, distinct
keys for identical payloads). Every rule and the listing invariant assert
against a model of the scenario's own history — the ordering/interleaving
failure class single-request tests cannot reach.

Why this is not a duplicate of the endpoint tests it overlaps: the mutation
battery run for #893 shows the division of labor precisely. Of four relation
mutants, the terminal-replay re-admission (retry of a cancelled admission
re-answering "queued") and the run-cancel idempotence drop (cross-route
cancellation stranding the receipt projection) were caught by *only* this
suite — 996-998 stateless tests across `packages/maistro-server/tests` and
`packages/maistro-core/tests/tasks` survived both. The other two (fingerprint
narrowing, list owner-scoping dropped) were also caught here at the HTTP
relation level while core unit tests caught them directly. The suite encodes
the observed production asymmetry that a Run cancelled through
`POST /runs/{id}/cancel` terminalizes the Run while its receipt stays `queued`
until a worker reconciles it — a relation no stateless test in this package
asserts.

An independent re-validation round exposed two latent defects in the suite's
own oracle (model, not production): the listing invariant checked only the
first 200-row page while deep runs accumulate past one page in the shared
in-memory store (now walks `next_cursor` to exhaustion), and it kept one
owner per textual idempotency key where the admission scope is
per-(principal, workspace, action, key) — both principals can hold the same
textual key, and each owner's replay/409 verdict is computed against their
own record (now tracked per-owner). Both surfaced only at nightly depth
(fresh seeds), never on the derandomized PR profile.

Runtime cost: ~7s derandomized on PRs (25 examples × ≤12 steps, 5/5 stable
runs during development, 3/3 on re-validation post-fix); 100×20 randomized
runs green 4/4 post-fix at 36-54s. Deeper nightly runs
without touching the file: `MAISTRO_STATEFUL_API_EXAMPLES=200
MAISTRO_STATEFUL_API_STEPS=40 MAISTRO_STATEFUL_API_DERANDOMIZE=0`. The second
node ID also pins contract documentation: the served spec still declares no
OpenAPI response links, which is why native Schemathesis stateful testing
(`as_state_machine`) cannot run against this surface.

Evaluation and disposition: `docs/research/893-stateful-api-workflows.md`.
