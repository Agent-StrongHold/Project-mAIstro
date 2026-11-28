---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +20
  packages/maistro-server/tests: +6
---

# #2247 one effective-key precedence across maistro-server and hive-conductor

Twenty new node IDs in `packages/maistro-core/tests` (fourteen in
`config/test_gateway_key.py`, new; six in
`integration/test_governed_request_end_to_end.py`, new), six new node IDs in
`packages/maistro-server/tests/test_worker_yaml_config_startup.py`
(`TestInstalledGatewayCredential` 3 → 9), and four new node IDs in
`packages/hive-conductor/backend/tests/test_effective_gateway_key.py`
(`TestOneMatrixAcrossCompositions`, new).

**Core +14** pin the canonical precedence matrix
(`maistro.config.gateway_key.effective_gateway_key`), the one function both
compositions now order their credential legs through: single-leg resolution,
the #2247 split-brain regression (conflicting `MAISTRO_LLM_API_KEY` vs
`LITELLM_API_KEY` resolves to the maistro-scoped key), strict inter-leg
ordering, empty-string-falls-through at every leg, none-everywhere →
`None` (fail-closed, never `""`), and lazy leg resolution — a leg may be a
zero-arg resolver, evaluated only if every earlier leg is unset, so a
winning leg never pays for the side-effectful resolvers beneath it and a
fully-unresolved set of resolvers still answers `None`.

**Core +6** prove ONE installed governed request joins the whole chain with
only the final transport replaced: real `create_container` bootstrap +
scoped credential registration, real spine (`RunExecutionService` →
NodeRun → Attempt, joined via `context_factory` attempt-identity stamping),
the resolved Binding, the Invocation filed under that Binding and Attempt,
and the gateway-reported usage records — with the physical call
authenticated by the pool-issued credential, not the env impostor. Four
refusal cases (foreign scope, missing Binding, disabled Binding,
no-registered-credential) refuse before dispatch and leave a FAILED Attempt
naming the refusal; an unregistrable `credential_refs` declaration refuses
at bootstrap (`ConfigError`).

**Server +6** pin the engine half of the same contract: an operator key
outranks the gateway aliases (the split-brain regression, through
`_gateway_credential` *and* `_agent_config`), engine resolution equals the
shared core contract for the same environment, the `LITELLM_PROXY_KEY`
alias outranks the bundled master key, a blanked operator key falls through
(compose emits `MAISTRO_LLM_API_KEY=${MAISTRO_LLM_API_KEY:-}`), an
unconfigured deployment resolves no credential, and the governed egress
`_build_container` builds carries the operator key. The class gained an
autouse fixture clearing all four alias variables, so the three pre-existing
tests in it are also hermetic against operator environments that state
`MAISTRO_LLM_API_KEY`.

**Hive +4** pin the Hive half: `effective_llm_gateway_key` delegates the
leg ordering to the shared core matrix (source-level pin; the hand-walked
alias chain stays gone), its answer is exactly what the shared contract
resolves for the same environment — including the blanked-alias
fall-through — and a winning leg is resolved without reading the aliases
beneath it (`test_a_winning_leg_is_resolved_without_touching_the_ones_beneath`:
the regression the #2247 round itself hit, where eager
`litellm_key=litellm_api_key(settings)` attribute/vault access broke
duck-typed settings stubs carrying only a stated alias; the wrapper now
hands its settings-backed legs over as resolvers and the matrix evaluates a
leg only if reached), so the two compositions cannot select different
credentials and neither resolves more secrets than its winner needs.

**Red-check.** With `_gateway_credential` reverted to its pre-#2247 body
(`os.getenv("LITELLM_API_KEY") or settings.litellm.master_key`), the four
new operator/alias server tests fail and the three pre-existing ones pass —
the tests name the regression, not a fixture value. With the Hive wrapper's
lazy resolvers re-collapsed to eager arguments, the new
winning-leg-resolves-without-touching-the-ones-beneath test fails
(AttributeError on the one-alias settings stub, the exact
`test_provider_pin_registration.py` CI failure) and
`test_provider_pin_registration.py` fails with it again — the repair is
named by the tests it re-enables.
