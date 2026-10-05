---
inventory-delta:
  packages/hive-conductor/backend/tests: +39
---
# Preserve explicit no-effect ordinary DAG mode (#1085, #87)

Exact-head CI exposed three failures in the unchanged authenticated graph E2E
file: its spine-only fixture lacked model authority, and the ordinary-node
cutover had removed both actionable no-gateway guidance and the existing
`ALLOW_STUB_LLM` labelled development response. All three failures were reproduced
locally before repair. No assertion was deleted or weakened to conceal them.

## Bounded compatibility contract

Real ordinary model calls still use the existing admitted model adapter and all
persisted execution, configured Binding, credential, policy and quota checks.
Missing runtime or a failed real call never triggers fallback. The raw builder,
sandbox script and model-backed tool paths remain untouched.

A separate zero-effect path is eligible only when the selected Container has
neither an endpoint nor model declarations and canonical application Settings
also has neither. Settings remains the owner of gateway alias resolution;
unavailable settings are not evidence of an unconfigured deployment. A
nonempty requested Binding or any malformed provided selector refuses even in
this mode. The static payload requires the existing explicit opt-in and a
nonblank identity matching active canonical execution. It preserves the
`"stub": true` label and produces no HTTP, model Invocation or usage evidence.
Without opt-in the node fails with the existing `ALLOW_STUB_LLM` guidance.

The server computes `ordinary_model_dry_run` in existing immutable Run
provenance at admission. User-supplied graph provenance cannot choose this mode.
Recovery requires the marker and current no-model configuration before serving
static output. Missing markers remain real/admitted. Real-to-stub and
stub-to-real recovery drift both refuse; an UNKNOWN real Invocation cannot be
hidden by removing configuration and enabling the flag later. This flag applies
only to ordinary model nodes, not sandbox or tool effects in the same graph.

## Hermetic evidence

- The original six-test authenticated E2E file retains all behavioral legs. Its
  real-model leg now boots actual SQLite Container authority, creates the
  Workspace through authenticated HTTP, reopens with an explicit operator model
  Binding and trusted fixture registry, and checks exact actor/scope/Run/NodeRun/
  leased Attempt/Binding/Invocation joins and once-only usage.
- Its only real HTTP destination is its explicitly allowlisted in-process
  `127.0.0.1` recording gateway. Inherited proxy variables are cleared for that
  fixture so traffic cannot escape through a developer/CI proxy. No external
  gateway or provider credentials are used.
- 39 new tests cover static zero-effect output and guidance, all supported
  gateway aliases, unavailable settings, configured missing/revoked/ambiguous
  grants, missing credentials/runtime, policy/quota/transport refusal, UNKNOWN
  evidence, invalid execution identities, explicit/malformed selectors,
  user-forged mode data, both recovery-mode drift directions, and flag changes
  after admission. A late opt-in cannot change the selected mode; later opt-out
  still refuses static output.
- The existing no-runtime refusal test now explicitly declares a gateway while
  enabling the flag, preserving its assertion that missing real authority fails.
- Inventory increases from 3,449 to 3,488. Existing E2E counts are unchanged.

Only named hermetic suites are executed. Full local Hive execution and external
live-gateway verification remain prohibited. Unchanged remote CI is required
again for the final published head.
