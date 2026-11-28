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

## Deep-review round 2 (2026-11-28, verifier b5a0f12 re-check at f91b3104e451)

Adversarial re-examination of the round-1 findings against reachable
production behavior. No production file changed; suite inventory unchanged.

**Proven by direct execution this round** (beyond the suites above):
- Engine ≡ core contract, probed through real `maistro_server.main.
  _gateway_credential` (not the tests): conflicting aliases → operator key;
  all four legs stated → `LITELLM_API_KEY` leg; blanked operator key falls
  through; unconfigured → `""` (fail-closed); proxy-only → proxy alias.
- Hive ≡ core, probed through real `services.secrets.
  effective_llm_gateway_key`: same four scenarios agree, and a winning leg
  is resolved without touching the settings beneath it (laziness holds).
- Counterfactual: the pre-#2247 engine body answers `sk-gateway` where the
  #2247 engine answers `sk-operator` — the new tests name the regression,
  not a fixture value.
- No bypass: `_gateway_credential` is the only production credential reader
  in `maistro-server` (main.py:326-329; consumed at main.py:395,437,566).
- Full mypy (CI's seven-package command): 976 files, no issues.
- `check-closure-targets.py` with the real PR #2563 body: closes no issue.

**Round-1 finding adjudication:**
- Owner-decision artifact: CONFIRMED absent — all 8 #2247 comments and all
  79 human-authored #1824 comments are bot progress markers; no ADR names
  the matrix. Weight reduced: the matrix is verbatim the shipped operator
  contract at the develop base (`.env.example:33-38`, since #2185 merge
  a7a6dd9a29), and #2247's own body prescribes exactly this reconciliation
  target; #1824 requires an owner disposition only "if no accepted contract
  resolves them". Sub-claim "#2185's Codex review flagged the gap P1" is
  REFUTED: the captured review is a 655-char receipt with no
  gateway/credential/P1 content.
- Weak tests: `TestBothCompositionsResolveThroughOneOrdering` is indeed
  literal-only (misleading name; substance covered by the server/hive
  composition suites). Downgraded: only 1 of the 4 new hive tests is a
  `getsource` pin — the other three are behavioral.
- Pre-existing non-matrix core readers re-confirmed at conductor.py:111,
  llm_summarize.py:337, config/loader.py:74, browser/client.py:67; all are
  overridden by the pool credential at model_chat.py:598 on the governed
  path. Out of #2247 scope (engine/Hive contract readers only).
- CI: live refresh at review time — 72 SUCCESS / 3 SKIPPED / 5 IN_PROGRESS
  (test, coverage (no services), docker-build, Container scan, integration-
  scope), 0 failures. Completion remains UNVERIFIED; the governance residue
  (owner-gate provenance label) needs adjudication, not a code repair.
