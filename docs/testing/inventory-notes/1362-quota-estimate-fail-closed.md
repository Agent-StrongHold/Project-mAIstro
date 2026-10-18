---
inventory-delta:
  packages/maistro-core/tests: +30
---
# PR 1362: refuse unknown quota estimates before dispatch

Measured with `pytest --collect-only -q packages/maistro-core/tests` at the
original PR head `ecd792f39cc05d4acb0e5d420370531a7b61b495` and this repair:
12,144 -> 12,174 node IDs. The inventory script generated the **net +30**
above. No baseline, floor, exemption, or existing ledger entry changes.

## Replacement mapping

Six private-helper cases in `test_container_capability_effects.py` are replaced
by 36 production-composition cases in `test_container_quota_admission.py`:

- `TestTheInputEstimateIsACeiling` (three cases) asserted Unicode character
  count plus guessed framing, per-message framing, and a positive empty-input
  guess. None proves a billed-token ceiling. The replacement exercises the
  actual `_wire_capability_effects` estimator and real file-backed SQLite quota
  admission for empty/default, ordinary text, Unicode, full-message fields,
  tool-call history, tool schemas, response schemas, and multimodal payloads.
  All eight must refuse both token and money policies before dispatch when the
  gateway has no proven complete-input bound: **16 cases**.
- `TestTheCostCeilingMakesMicroUsdBudgetsUsable` (three cases) tested priced
  arithmetic, rounding, and unknown pricing in a helper that no longer has a
  valid production input ceiling. The unused helper is removed rather than
  retaining arithmetic that falsely advertises safe admission. Actual
  money-budget admission with absent, zero, and negative output limits must
  refuse without charging/holding or dispatching: **3 cases**. The other
  numeric refusal cases above also cover a registry-priced model with an
  explicit positive output limit; pricing alone cannot bound its full input.
- With no quota configured or with a request-only quota, all eight payloads
  above still dispatch unchanged and replay exactly once. Request-only
  admission charges one request: **16 cases**.
- An explicitly injected trusted adapter-backed context retains its identity,
  positive numeric admission, unknown-usage holds, and exactly-once replay:
  **1 case**. This proves composition compatibility, not that the shipped
  gateway now supplies a verified complete-request bound.

Initial fail-first run on the original source: 15 refusal cases failed and 12
preservation cases passed. The final additions include empty/plain-text and
injected-context coverage. The finished quota-admission file has 36 passing
cases; including the unchanged four container-capability cases gives 40.

The governing estimate contract remains
`maistro/quota/invocation_quota.py`: trusted adapter-enforced physical bounds,
not caller or registry-price assertions. Numeric-budget usability remains
incomplete under #1196. This patch does not claim #55/#1196 complete or make
PR #1362 merge-ready on its own. Existing approval, effect-context policy,
quota lifecycle, recorder, and architectural convergence tests are unchanged.
