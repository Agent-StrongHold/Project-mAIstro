---
inventory-delta:
  packages/maistro-core/tests: +53
---

# 961-provider-adapter-sdk

Implements the third-party model/provider adapter SDK (M9-E1, #961):
`packages/maistro-core/src/maistro/capabilities/provider_adapters.py` (spec,
adapter protocol, catalog, registration, conformance, reference adapter,
bootstrap), adapter transport inside the one approved egress module
(`capabilities/providers/llm_gateway.py`), adapter-aware resolution and
capability refusals in `capabilities/model_chat.py`, the
`AgentConfig.provider_adapters` wiring surface (`types/config.py`), and
container composition. ADR-104 records the decision.

**+53 `packages/maistro-core/tests/capabilities/test_provider_adapters.py`**
(collect-only verified on this head), each cluster naming the acceptance
criterion it pins:

- **Declarative spec fail-closed (8)** — least-authority capability defaults;
  duplicate model names, per-model capabilities beyond the adapter's, auth
  styles without their parameter names, non-HTTP base URLs, secret-shaped
  fields (the "not extension plaintext config" refusal), unsupported protocol
  declarations, and relative health paths all refuse at validation.
- **Shared conformance suite (7)** — the built-in reference adapter and a
  fabricated third-party-style adapter (Acme: provider-specific response
  shape, custom usage field, own error mapping) pass the same suite; lying
  adapters are caught (wrong usage numbers, 401 mapped outside AUTH, response
  normalizer dropping choices, spec carrying a secret attribute, raising
  normalization hooks).
- **Registration seam (6)** — adapter models land in the canonical registry
  and the cost-aware router selects them (no core routing edit); duplicate
  ids, a different object under a registered id, re-sourcing an existing
  model name, and conformance failures refuse without recording anything;
  same-object re-registration re-syncs rows idempotently.
- **Governed egress end to end (12)** — adapter calls record canonical
  Invocations with usage from the adapter hook, cost from registry metadata,
  trust tier and adapter provenance on the persisted Binding snapshot; the
  adapter hook never sees the secret while the transport presents the scoped
  credential per bearer/query/header styles; the error taxonomy raises
  canonical `LlmAuthError`/`LlmHttpError` with real statuses (401/403/429/500
  and an adapter-mapped 418); unreachable endpoints raise `EffectNotApplied`;
  undeclared tools and structured output refuse as typed unavailable
  resolutions with zero HTTP; declared capabilities pass through to the
  normalized payload; a foreign provider handle is a `TypeError` (no
  alternate egress); unavailable adapter selections refuse instead of
  falling back.
- **Process-default composition (2)** — absent catalog keeps exact
  gateway-only behavior; configure/release/reset round-trips.
- **Health/capacity (4)** — a failed probe refuses canonical selection; a
  recovery probe restores it; adapters without declared probes are never
  marked; the probe follows the adapter hook across healthy/unhealthy/HTTP-
  error/transport-error/no-probe shapes.
- **Operator bootstrap (6)** — Binding loaded with adapter provenance, the
  secret provisioned through the scoped credential authority under the
  adapter's declared pool + reference and nowhere else; pin validation;
  unregistered adapter ids, pins outside the adapter's models, and foreign
  credential references refuse; a key-less entry stays fail-closed at
  acquisition; the built-in reference adapter self-registers through the
  same seam.

One pre-existing graph-node test (`test_sync_kinds.py`) asserts the wire
shape its strict `post()` double accepts; the adapter `params` kwarg now
crosses only for query-style auth, so gateway-era call sites see the
unchanged shape.

## Repair round (2026-10-06, head bccdea79 + this fix)

No suite-count delta: zero tests added or removed; `inventory-delta` above is
unchanged. This round only adds traceability and governance artifacts:

- **20 `@pytest.mark.ac("SPEC-284/AC-n")` markers** on existing tests in
  `test_provider_adapters.py` (collect count unchanged at 84), mapping the six
  issue acceptance bullets to the tests that already pin them.
- **`docs/specs/SPEC-284-provider-adapter-sdk.md`** — the spec implementing
  ADR-104 (fixes the `check-ac-state.py` failure: `adrs_without_implementing_spec`
  32 → 31, `design_coverage` raised past the 42.8609 floor), with all six
  criteria measured `reachable` on a full `--run-tests --ratchet --mandate
  56332162` run (mandates OK, improvement banked to
  `quality/ac-state-notes/auto-961.json`).
- **devskim pragma relocation in `provider_adapters.py`** — the two
  `DS137138` suppressions moved from adjacent lines onto the flagged lines
  (same-line is the syntax CI honors; adjacent-line pragmas at 898/1141 did
  not suppress findings at 899/1140), and the module docstring's bare
  ``http://`` literal reworded away (line 112).
