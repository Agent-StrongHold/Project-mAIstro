---
inventory-delta:
  packages/maistro-core/tests: +46
---
# 958-external-agent-discovery

External Agent discovery/card ingestion and canonical capability projection
lands (#958, epic M9-D #941) as `packages/maistro-core/src/maistro/a2a/external.py`,
exported through `maistro.a2a`.

**+46 `packages/maistro-core/tests/a2a/test_external_agents.py`** — one test
(or parametrized matrix) per rule, each naming the acceptance criterion it
pins (+35 from the initial implementation, +11 from repair rounds: the
6-case non-boolean capability-flag matrix, the 3 identity-mismatch
refusals, and the 2 central surface-clamp tests below):

- *descriptor inspection without invocation* (4): JSON-string and dict
  payloads parse identically; the registry takes no transport/invoker argument
  at all and `project()` inspects endpoint/version/tools/skills without
  contacting anything; slug-id derivation (explicit `id` wins); legacy
  `inputModes`/`outputModes` keys with the A2A `text` default; payload-digest
  stability; unknown agent ids fail loudly; malformed payloads fail with the
  offending field named (8-case matrix + bad JSON + non-object + non-payload).
- *unsupported/unknown capabilities fail explicitly* (5-case parametrized +
  1, plus the 6-case repair-round matrix): `pushNotifications`/
  `stateTransitionHistory` asserted, unknown capability keys, and capability
  `extensions` (named and unnamed) all raise `UnsupportedCapability` at
  ingestion; unasserted unsupported flags and `extensions: null` are
  tolerated; a supported flag whose value is not an actual boolean
  (`"false"`, `"0"`, `""`, `1`, `None`, `[True]`) raises `DescriptorInvalid`
  instead of being truthiness-coerced into a feature the card never
  declared.
- *no canonical root authority from a remote card* (3, plus the 2
  repair-round storage-clamp tests): the projected card is
  unconditionally clamped (`t9`/`P5`/`delegation_mode="none"`/no
  sub-agents/`scope="external"`) even when the policy grants capabilities;
  the default-deny policy authorizes nothing and the card projects inactive;
  a policy cannot mint capabilities the card does not declare — and the
  registry enforces that at the single record-build point, not at render:
  a verbatim-granting policy's out-of-surface grants are dropped before
  storage (`authorization.capabilities ⊆ declared`), and a policy whose
  grants all fall outside the declared surface cannot mark the specialist
  authorized or eligible. The serialized card re-attaches
  `scope="external"` (`AgentCard.to_dict()` omits it), so the clamp
  survives serialization instead of falling back to the `builtin` default.
- *projection retains remote provenance/version* (2): remote version,
  publisher, protocol version, source URL, payload digest and ingestion time
  ride the projection; `refresh_descriptor` re-snapshots provenance to the new
  payload.
- *availability truthful and distinct from authorization* (6): fresh records
  are `unknown` and never eligible; available-but-unauthorized is not
  eligible; authorized-but-unavailable is not eligible while both axes stay
  independently visible (`require_available=False`); authorized+available is
  eligible; inactive registrations are never eligible; availability reports on
  unknown agents fail.
- *refresh cannot silently broaden authority* (7, plus the 3 repair-round
  identity refusals): broadening is refused under the default policy (record
  untouched); even a granting policy refuses broadening it did not approve;
  policy-approved broadening is accepted AND re-authorized (effective =
  declared ∩ authorized); narrowing needs no approval; identical payload
  refresh is a no-op; endpoint re-pointing is `EndpointConflict` both on
  refresh and re-registration; changed bytes via `register` redirect to
  `refresh_descriptor`; and a refresh whose explicit `id` — or name-derived
  slug — differs from the registered id is refused
  (`DescriptorIdentityMismatch`) so lookups can never split from
  projections, while a refresh under the registered id still succeeds.

Registration idempotence, protocol conformance of `DefaultDenyProjectionPolicy`,
and the serialization surface are covered directly — including the repair-round
pin that `SpecialistProjection.to_dict()` re-attaches `scope="external"` on the
serialized card, because `AgentCard.to_dict()` itself omits `scope` and a
consumer falling back to its `builtin` default would silently un-clamp the
projection's security classification.

Fail-before evidence: muting the surface-subset check in
`ExternalAgentRegistry.refresh_descriptor` makes the three broadening tests
pass their refresh silently (effective tools widen without policy evaluation);
reverting the `_parse_capabilities` unknown-key raise makes the unsupported-
capability matrix pass by silent degradation. Both mutations were reverted
before commit.

Validation on this head: `pytest packages/maistro-core/tests/a2a` 169 passed
(123 pre-existing + 46); `mypy --strict packages/maistro-core/src` clean
(721 files);
`ruff check`/`format --check` clean on touched trees;
`check-reachability.py` (1284 modules / 170 unreachable — unchanged), and the
vulture per-identity scan with CI arguments produces zero identities outside
`quality/vulture-baseline.json` (the three registry lifecycle methods without
an in-tree caller yet — `refresh_descriptor`, `report_availability`,
`eligible_specialists`, wired by M9-D2 #959 — are referenced in
`_vulture_whitelist.py` with that rationale, the same contract-first posture
as the M9-B1 store seams).
