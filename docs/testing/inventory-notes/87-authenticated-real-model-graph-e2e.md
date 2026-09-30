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

## Per-criterion evidence (executed at c5e070d9 + this delta; event assertions and claim-accuracy repair at 3f096274 + this repair)

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
  governed leg below. Event evidence is on the governed leg too: the shipped
  `GovernedInvocationExecutionService.invoke` appends the
  `capability.invocation.policy_decision` and `capability.invocation.completed`
  EventEnvelopes into the effect context's event store
  (`maistro/capabilities/governed_invocation.py`), and the test asserts them —
  decision/rule/binding/capability/effect identity, Run/NodeRun/Attempt
  linkage, and the causal chain (terminal event `causation_id` == policy event
  `event_id`). The fail-closed leg additionally asserts the refused node left
  the event stream empty. The DAG leg itself appends no capability events (its
  legacy adapter calls the gateway directly — see reconciliation notes), so
  event evidence is claimed on the governed leg only; the earlier claim that
  the `record_run_completion`/DagRunStore path is the event evidence was wrong
  and is retracted.
- **Warden/Sentinel and auth context on the path** — auth: real
  `POST /v1/auth/login` session; the Run carries the authenticated actor id;
  Workspace admission refuses unauthorized scopes (covered by
  `test_dags_routes.py::test_run_dag_missing_scope_fails_before_execution`,
  re-run green). Warden: `test_injection_turn_is_refused_by_the_warden_before_
  any_model_call` — an authenticated injection turn is refused
  (`content_filter`) before dispatch and the gateway sees zero requests.
  Sentinel is NOT on this path, stated plainly:
  `test_unauthorized_model_node_fails_closed_before_any_gateway_call` — the
  governed capability seam refuses an unbound `llm.summarize` node: Run
  failed, no Invocation, zero gateway traffic, and an empty event stream. The
  seam's policy evaluator is the shipped `binding_scope_policy` M1 baseline
  (`effect_context.py`) — the same evaluator the production Container composes
  (`container.py`), so the exercised refusal is shipped behavior. But
  `CapabilityPermissionSource` feeds Sentinel's own permission decisions
  (`container.py`), not this seam, and Binding resolution refuses the node
  before any policy evaluation. Deep-review resolution of the acceptance's
  "Sentinel" component, by ADR reconciliation (accepted ADRs govern where
  issue text conflicts): ADR-081226-6b46 puts authorization and policy
  narrowing on the **Binding** and security/policy audit on the **Invocation**
  — exactly what this seam ships and the tests assert (fail-closed Binding
  refusal, `binding_scope_policy` verdict, policy_decision/completed audit
  events on the canonical stream) — while ADR-073 scopes Sentinel to the
  model-facing **tool-call boundary**, where the Container does arm it
  fail-closed (ADR-072726-0d6b; wiring proven by
  `packages/maistro-core/tests/test_container_security_wiring.py`). Sentinel
  is therefore proven as armed-on-its-ADR-scope plus a fail-closed
  policy-refusing seam on the executed path — not as a Sentinel decision on
  the node->Binding seam, which would need its own ADR to wire. That
  Sentinel-derived seam evaluator is a genuine, here-recorded residual; it is
  neither wired nor claimed.
- **cost/token/model/provider telemetry present** —
  `test_canonical_llm_node_crosses_the_governed_invocation_seam`: the shipped
  `llm.summarize` node runs through `run_durable_graph` and crosses
  Binding -> governed Invocation -> approved Provider; the persisted Invocation
  carries `usage.input_units/output_units` (11/7), `model`, `provider`,
  and measured `cost_cents > 0`; the governed node's own output carries the
  same usage (`tokens_in`/`tokens_out` = 11/7). The DAG boundary carries the
  model only — `canonical_dag_runner._node_results` projects
  role/response/success/model/isolation, no usage — so gateway-side usage at
  the DAG boundary is NOT claimed; the usage-telemetry criterion is met by the
  governed leg's persisted Invocation.
- **automated E2E repeatable** — the file passes twice consecutively
  (6 passed in 5.0 s, then 4.2 s) with no external services.

## Executed validation

- `uv run pytest packages/hive-conductor/backend/tests/test_e2e_authenticated_real_model_graph.py -q`
  → 6 passed (three consecutive rounds pre-repair; re-run green post-repair:
  6 passed in 4.0 s with the new event assertions active).
- Neighbor sweep (global outbound-policy save/restore must not leak):
  `uv run pytest .../test_e2e_authenticated_real_model_graph.py
  .../test_dags_routes.py .../test_graph_runner.py
  .../test_chat_voice_gates.py .../test_outbound_gateway_policy.py -q`
  → 112 passed (pre-repair and again post-repair, 5.1 s).
- `uv run ruff check` and `uv run ruff format --check` clean on the new file.

## Repair round (verify finding → fix, at 3f096274 + this repair)

The verify round found three claim-drift items; all three are addressed with
evidence, not wording alone:

1. **Event evidence was claimed but never asserted** — the note attributed
   event evidence to `record_run_completion`/DagRunStore, which is not event
   evidence. The shipped event path is `GovernedInvocationExecutionService`
   appending `capability.invocation.policy_decision` and
   `capability.invocation.completed` EventEnvelopes into the effect context's
   event store. The governed-leg test now asserts both envelopes (identity,
   linkage, causal chain), and the fail-closed leg now asserts the refused
   node left the event stream empty. The wrong note claim is retracted.
2. **Sentinel was claimed on the seam** — it is not: the seam evaluator is the
   container's own `binding_scope_policy` baseline, and
   `CapabilityPermissionSource` feeds Sentinel's decisions, not this seam.
   Note and test docstring now state this plainly; no Sentinel claim remains.
3. **Usage at the DAG boundary was overstated** — `_node_results` projects
   model only. Note corrected; usage telemetry is claimed only via the
   governed leg's persisted Invocation (which the test asserts).

CI-gate checks in this round: `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1402 reviewed
identities, all banked; no ledger amendment needed — this repair touches only
tests and docs), and `check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` → ok:2949.

### Repair round 2 (deep-review resolution, ADR reconciliation)

The prior verify round asked for an acceptance re-scope or an ADR for
"Sentinel on the path". Resolved by reconciliation against the two accepted
ADRs that already answer it, recorded in the per-criterion section above:
ADR-081226-6b46 assigns seam authorization to the Binding and audit to the
Invocation; ADR-073 assigns Sentinel to the tool-call boundary. A
Sentinel-derived evaluator on the governed seam is recorded as a residual
requirement (needs its own ADR), not silently claimed. Also tightened the
Leg-1 comment that still implied gateway-reported usage at the DAG boundary —
the boundary projects model only; usage is claimed via the governed leg's
persisted Invocation.

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
