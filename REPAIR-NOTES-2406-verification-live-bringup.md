# #2406 verification round — live bring-up re-executed at final HEAD

This round re-verified the ADR-045 cutover branch at its final head
`d6d688406c9439f1cd2d68fa2433193521116807` (after the `228dec753f` develop
merge), because every prior live bring-up ran at `74e7ea6374` — **before**
the develop merge landed — and the merge was the one event that could have
broken the live path without any fresh-state test noticing. The prior verify
round recorded "AC5 live-bring-up not executed by this round"; this round
executed it. No production code changed.

## Executed evidence (this round, this head)

Live `docker compose` stack (postgres + litellm + maistro-engine; image
rebuilt from this head; no `maistro-canvas-worker` service — the engine
itself is the runner):

- `capability_bindings` row `canvas-image-gateway | default | default |
  image.generate` present — `start_canvas_job_runner` ran its registration
  path inside the shipped image.
- `GET/POST /v2/canvas/designs`: 401 unauthenticated, 200 with API key
  (+ `X-Canvas-Token` accepted as the alternate credential); a create
  round-tripped to the PostgreSQL row. Operable, fail-closed.
- **Runner liveness proven behaviorally, not by log line** (the image logs
  structlog at WARNING, so the INFO `canvas_runner_started` event is
  filtered): a pending `generation_jobs` row inserted directly into
  PostgreSQL was claimed, executed, retried per the backoff schedule to the
  ceiling, and terminalized (`attempts=3`, sanitized
  `Generation failed: provider error.` message, no stack traces) — the
  full claim/execute/retry loop of the in-process `CanvasJobRunner`.
- **Restart durability** (the regression the r3 round found live): two
  engine restarts against the persisted database → healthy both times,
  exactly one binding row with one `created_at`, no immutability errors.

## Gate battery (CI-exact arguments, this head)

vulture `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
(rc=0, 1222 findings all banked), reachability (82 unreachable, rc=0),
dispositions (27 groups, rc=0), radon (124 blocks, rc=0),
durable-table-inventory (124 tables, rc=0), ratchet-provenance (rc=0),
shipped-surface-truth (rc=0), suite-inventory all 21 suites (rc=0),
`maistro-registry lint . --strict` (rc=0), xenon CI-exact invocation
(0 block/0 average violations), interrogate floors (server 59.7% ≥ 59,
canvas 39.6% ≥ 36), `mypy --strict packages/maistro-core/src` (clean,
844 files), `ruff check` + `ruff format --check` (clean).

Tests: `packages/maistro-canvas/tests packages/maistro-server/tests`
**1257 passed, 85 skipped**; `test_production_registration_universe.py`
14 passed (pins `maistro_design.nodes` reachable — AC for #2311's
design-node CONNECT); parity suite 10 passed.

## Findings recorded for the integrator (no tree change warranted)

1. **Two dead grant rows** in `quality/ratchet-authorizations.json`
   (`canvas/routes.py::unused function 'delete_layer'`,
   `layers.py::unused variable 'perspective'`): the b745 batch eliminated
   both identities at source (handler renamed to `remove_layer`;
   `GroundPlane.perspective` deleted) and pruned the vulture-baseline rows,
   but left these authorizations behind. No gate reads them (provenance
   passes with them present; the CI-exact vulture scan finds neither
   identity). By the issue's own rule — "an authorization for a nonexistent
   block can never be exercised" — they are inert debt; grant-file edits
   are outside this round's authorization, so they are recorded here rather
   than pruned.
2. **`MAISTRO_CANVAS_DEFAULT_DRAFT_MODEL` is not threaded through
   `docker-compose.yml`** (only `CANVAS_API_TOKEN` is): a compose operator
   gets the documented fail-closed refusal for model-default admissions
   rather than an env knob. Behavior is per contract (the registry warns
   truthfully; admissions fail closed naming the variable); threading the
   knob is a one-line follow-up if wanted.
3. **PR-body prose is stale at this head** (test counts, the
   deletion-collateral banking claim, trailing `Closes #2311`): GitHub
   state, not tree state; flagged by the prior verify round and unchanged
   by this one.
