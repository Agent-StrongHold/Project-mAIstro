---
verified-by: maistro-verifier
head: df00785bb41b678ce34e187beccc420d37cced9a
base: df00785bb41b678ce34e187beccc420d37cced9a
---

# Issue #753 — independent verification record

Re-derived acceptance from the issue text and the 2026-09-08 audit comment; none
of the prior PR (#754/#784) claims were trusted. The canonical implementation
landed on this branch's history via `74fca7ebf` (#784 head, merged through
`c65cdc23a`) and was hardened by #1444/#1728/#1816/#1319. Executed at head
`df00785bb` (clean worktree, base == head):

- `uv run pytest packages/maistro-turing/tests packages/maistro-turing/backend
  /tests -q` with CI's env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`, ci.yml:548-556):
  **300 passed**. Suite contents checked against the issue first: the chat suite
  drives the real FastAPI app over HTTP and inspects the canonical stores.
- `scripts/check-suite-inventory.py` (full): **ok, 17/17 suites match** the
  recorded baseline+delta ledger, after `uv sync --locked --extra dev` restored
  the stale local venv (missing `maistro_ext_harness`; the pre-sync collection
  failure was environmental, not inventory drift).
- `uv run ruff check .` / `ruff format --check .`: clean (3090 files).
- Canonical AGENTS.md `mypy` command: Success, no issues in 846 files.
- `check-api-route-contracts.py` OK; `check-cross-package-imports.py` OK;
  `check-owned-store-access.py` OK. `check-execution-lifecycles.py` /
  `check-public-routes.py` refuse to run locally only because head == base
  (they need a commit under judgement); no diff exists for them to judge.

Acceptance re-derived from live execution (TestClient against `create_app()`,
probes in the job log, not fixtures):

- Success: one `POST /v1/chat` produced **exactly one** new Run (diffed
  `list_by_status(COMPLETED)` before/after), one `turing-chat-turn` NodeRun and
  one Attempt; `durable_store.get(run_id)` returns the physical record; response
  body carries `run_id` (`test_chat_with_fake_provider_has_canonical_execution_
  evidence` pins the same shape).
- Failure: with no provider wired the route returns the fixed public 503
  `Turing chat execution failed` and the canonical Run is FAILED with the
  NodeRun FAILED; the Attempt physically carries the failed NodeResult
  (`success=False, error_code='RuntimeError', error_message='no LLM client
  configured'`) — the shared spine's terminalization semantics
  (`graph/nodes/base.py` returns a failed envelope; `runs/execution.py`
  terminalizes), not a Turing-local authority.
- The audit's condemned fallback is gone: no `_unrecorded_reply` exists; on
  `TuringAdmissionUnavailable` the route raises 503 and
  `test_canonical_admission_failure_refuses_chat_without_dispatch` /
  `test_checkpoint_admission_failure_is_compensated_before_dispatch` assert the
  provider is never called (`provider_calls == 0`) and the partially admitted
  Run is compensated to CANCELLED with `ADMISSION_INCOMPLETE`.
- Domain state stays Turing-owned: conversation history lives in
  `TuringChatSession._history`, mood/facets/artifacts in `backend/state.py`;
  the canonical Run carries only the message parameter, the reply result, and
  `provenance {product: turing, session_id}`. `_SESSIONS` holds sessions only —
  no run/attempt state.
- Dormancy: no background tasks, lifespan hooks, or producer loop anywhere in
  `backend/` (grep over `create_task|lifespan|on_event|BackgroundTasks`);
  `maistro_turing.producers` is consumed only by the request-driven dashboard
  (`routes/state.py::compute_drives`).
- Truthful container claim: the only `maistro.container` mention in the package
  is `routes/chat.py` explicitly **denying** such wiring; `container.py` has
  zero Turing references (grep verified).
- Collision boundary: this lane adds only this note. The implementation lives
  under `packages/maistro-turing/backend/**` and consumes only public canonical
  APIs (`run_durable_graph`, `CanonicalDurableRunStore`, `InMemoryRunStore`,
  chat admission/retention contracts); no `maistro-core` file references Turing.

Residual observations (non-blocking):

- `docs/testing/inventory-notes/754-turing-canonical-chat.md` still narrates the
  PR-#754-era admission fallback ("executing the turn ... without a `run_id`")
  that later commits replaced with fail-closed 503. It is dated ledger history
  of a closed PR, not a live behavior claim; left untouched to avoid rewriting
  delta-ledger notes.
- The `backend/tests` inventory row predates the +8/+8 deltas of the two #753
  notes; the full gate confirms baseline+deltas == 90 collected, so no ledger
  action is needed.
