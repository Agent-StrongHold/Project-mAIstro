---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# #87 M3-A5 — authenticated real-model canonical Graph execution E2E

`packages/hive-conductor/backend/tests/test_e2e_authenticated_real_model_graph.py`
(6 tests, ~5 s) closes the M3-A5 acceptance: from a clean composition, an
authenticated principal submits a canonical DAG, the canonical durable Graph
executor runs it (`Run -> NodeRun -> Attempt`), a real configured model gateway
is called over HTTP, and the result is non-stub — with the negative legs
pinning that no fake/stub/degraded response is ever accepted as success.

## What "real model" means here, stated plainly

This workstation has no provider credentials, so the *gateway* is stood up
in-process as a live OpenAI-compatible HTTP server on `127.0.0.1` — the exact
interface the shipped LiteLLM proxy presents in a deployment
(`litellm_config.yaml` / `LITELLM_API_BASE`). The system under test is
everything behind that interface: genuine network POSTs with bearer
credentials through the outbound SSRF policy (`GuardedTransport`, allowance
seeded exactly the way `main._seed_outbound_policy` does), and loud refusal
when no gateway is configured. A leg gated on live provider keys would not be
repeatable; this one is (6/6 twice consecutively, 5.0 s / 4.2 s).

## Per-criterion evidence (all executed in this worktree at c5e070d9 + this delta)

- **no fake/stub/degraded response accepted as success** —
  `test_dag_run_without_a_gateway_refuses_instead_of_fake_success`: with every
  gateway env var stripped and `ALLOW_STUB_LLM` off, the canonical Run ends
  `failed` and the error names `ALLOW_STUB_LLM` (the CHANGELOG-recorded
  fake-success fix, re-proven through the HTTP route, not just the unit seam in
  `test_graph_runner.py`). `test_stub_opt_in_payloads_are_labelled_...`: with
  the opt-in on, the run "completes" only with `"stub": true` in every node
  payload.
- **Run/NodeRun/Attempt/Invocation/event evidence captured** — the headline
  test reads the durable record back from the canonical executor's store
  (`services.dag_agents.get_run_store().get(run_id)`): `Run` completed with
  `actor_principal_id` equal to the authenticated `whoami` id and the
  authorized Workspace/Project scope, one completed `NodeRun` per DAG node, and
  completed `Attempt`s linked to those NodeRuns. Invocation evidence is on the
  governed leg below. Event projection is the shipped
  `record_run_completion`/DagRunStore path exercised by the run itself.
- **Warden/Sentinel and auth context on the path** — auth: real
  `POST /v1/auth/login` session; the Run carries the authenticated actor id;
  Workspace admission refuses unauthorized scopes (covered by
  `test_dags_routes.py::test_run_dag_missing_scope_fails_before_execution`,
  re-run green). Warden: `test_injection_turn_is_refused_by_the_warden_before_
  any_model_call` — an authenticated injection turn is refused
  (`content_filter`) before dispatch and the gateway sees zero requests.
  Sentinel side of the seam: `test_unauthorized_model_node_fails_closed_before_
  any_gateway_call` — the governed capability seam with its policy evaluator
  (in full deployments fed live by Sentinel's `CapabilityPermissionSource`,
  `container.py`) refuses an unbound `llm.summarize` node: Run failed, no
  Invocation, zero gateway traffic.
- **cost/token/model/provider telemetry present** —
  `test_canonical_llm_node_crosses_the_governed_invocation_seam`: the shipped
  `llm.summarize` node runs through `run_durable_graph` and crosses
  Binding -> governed Invocation -> approved Provider; the persisted Invocation
  carries `usage.input_units/output_units` (11/7), `model`, `provider`,
  and measured `cost_cents > 0`; the DAG leg carries the model and the
  gateway-reported usage at the boundary.
- **automated E2E repeatable** — the file passes twice consecutively
  (6 passed in 5.0 s, then 4.2 s) with no external services.

## Executed validation

- `uv run pytest packages/hive-conductor/backend/tests/test_e2e_authenticated_real_model_graph.py -q`
  → 6 passed (three consecutive rounds, incl. post-ruff-format).
- Neighbor sweep (global outbound-policy save/restore must not leak):
  `uv run pytest .../test_e2e_authenticated_real_model_graph.py
  .../test_dags_routes.py .../test_graph_runner.py
  .../test_chat_voice_gates.py .../test_outbound_gateway_policy.py -q`
  → 112 passed.
- `uv run ruff check` and `uv run ruff format --check` clean on the new file.

## Environmental caveats (workstation I/O, not product defects)

- Cold `import main` on this workstation measured **289.8 s** (matching the
  ~161 s cold-boot note in `86-clean-install-proof-round.md`; same disk). With
  warm `__pycache__` the whole E2E file runs in ~5 s. CI hardware is unaffected.
- The first run attempt (cold venv + cold imports) exceeded a 600 s shell
  budget on `uv run` re-syncing the worktree venv; once synced/warm, nothing
  hangs.

## Reconciliation notes (issue text vs. shipped reality)

- The legacy DAG adapter (`hive.legacy_node`) calls the configured gateway
  directly (`_build_llm_call`); canonical `Invocation` persistence lives on the
  governed node path (`llm.summarize` -> `ModelChatEgress`, #56). The E2E
  therefore proves both legs: the authenticated DAG leg (auth, admission,
  canonical Run/NodeRun/Attempt, real gateway HTTP, non-stub result) and the
  governed-node leg (Invocation evidence + cost/token telemetry + fail-closed
  policy). Both use the same physical execution authority
  (`run_durable_graph`); no second scheduler was introduced. Routing the legacy
  adapter's LLM call through the governed egress remains future work (#55/#717
  lineage) and is NOT claimed as done here.
- The live gateway is test environment infrastructure standing in for the
  deployment's LiteLLM proxy (same `/v1/chat/completions` contract, real
  sockets, real usage accounting). It is not a stub *of the system under test*;
  the stub-detection legs prove the SUT neither synthesizes nor accepts stubs.
