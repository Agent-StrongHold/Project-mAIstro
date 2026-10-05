---
inventory-delta:
  packages/maistro-core/tests: +107
---
# 964-tool-skill-contracts

M9-E3 (#964): the published third-party tool and Skill contracts with
canonical capability/effect classification. All 107 new node IDs live in
`packages/maistro-core/tests/` — four files over the new
`maistro.extensions.tool_skill` package in `tests/extensions/`, plus the CLI
command's exit paths in `tests/cli/test_extensions_contract.py`. No existing
test moved. (+18 on top of the first recorded delta, added in the CI-repair
round: seventeen negative controls driving every failure branch of the shared
conformance battery, and the runner-side allowlist enforcement — a tool the
Agent/Workspace allowlist excludes is refused by direct id before any Binding
is resolved or handler dispatched, so exposure hiding is not the boundary.

## What the tests pin

`test_tool_skill_contracts.py` (+33) — manifest parsing and the host-owned
classification:

- the closed vocabularies (families, capabilities, effects, data scopes) are
  validated fail-closed; every malformed-manifest class (unknown names, bad
  id/publisher shape, non-semver version, contract ranges that span more than
  one major, invalid entrypoint spellings, non-env-style secret names, out-of-
  range ports) fails with `ManifestContractError`;
- the effect floor derives from declared effects AND requested capabilities:
  an honest read-only tool classifies INTERNAL, an undeclared tool takes the
  ADR-050 safe default (irreversible), and `read-only` + `network.outbound`
  classifies external-side-effect — the manifest cannot label a higher-risk
  effect as reversible by what it declares;
- runtime effect claims below the host floor raise `EffectDowngradeRefused`;
  claims at or above the floor pass (an extension may take the stricter gate);
- the entrypoint object is data validated against the manifest: kind/name/
  version identity, and capabilities beyond the manifest refused.

`test_tool_skill_registration.py` (+17) — registration under allowlists:

- a tool registers from manifest + entrypoint data alone (no core edits);
  identical identity re-registers idempotently; redefinition under one
  identity is refused (upgrades belong to the #954 lifecycle);
- `ToolAccessPolicy` fails closed: an absent allowlist admits nothing; the
  Agent allowlist narrows the Workspace allowlist; exposures carry the host
  classification, manifest permissions, and manifest digest;
- the canonical Binding carries the host-derived effect tier in `config` —
  not a string the extension supplied;
- Skill registration projects into the product `InMemorySkillRegistry` with a
  host-owned trust tier; composition over tools outside the allowlist is
  refused with the denied names; the product registry's t0-overwrite rule
  still applies to extension skills; `load_entrypoint_handler` resolves (and
  refuses) handlers across the host's code-import boundary.

`test_tool_skill_execution.py` (+13) — one governed dispatch path through the
real `new_in_memory_effect_context` seam:

- a state-changing tool executes through Binding -> policy -> Invocation; the
  Invocation row carries run/node_run/attempt/workspace/actor attribution;
- same-arguments retries replay the recorded Invocation without redispatch
  (effect-key ledger semantics);
- the outcome's `status` is the canonical
  `capabilities.invocation.InvocationStatus` — the one work-state vocabulary
  this seam reports, exactly as the Invocation ledger recorded it. The
  refusal and interruption families stay machine-readable through
  `error_code` (policy_denied / approval_required / capability_unavailable /
  handler_error / cancelled / deadline_exceeded); no second status enum is
  introduced, so the execution-lifecycles ratchet classifies nothing new;
- denial, approval (with durable pending request id), handler exceptions
  (FAILED + `handler_error` for the caller, UNKNOWN in the ledger), deadline
  expiry (`ExtensionToolCancellation`, outcome UNKNOWN mirroring the ledger
  row), and external task cancellation (re-thrown `CancelledError` with the
  attributable outcome attached) are all canonical and attributable;
- a downgrade effect claim is refused before dispatch — no Invocation row, no
  dispatch; a higher claim runs under the stricter classification.

`test_tool_skill_conformance.py` (+29) — the shared conformance suite:

- the identical battery passes an external-style package and a built-in
  surface (exposure, canonical result, attributable error, cancellation,
  attributable refusal);
- negative controls: a policy that denies everything fails the result check
  while its refusal still conforms; a subject that reports success over an
  interrupted call fails the cancellation check; a fabricated completed
  outcome without an Invocation fails attribution;
- every failure branch of every check is driven by a scripted subject:
  nameless descriptors and non-ADR-050 reversibility fail exposure;
  non-completed, invocation-less, and uncorrelated outcomes fail the result
  check; over-reported, unattributed, and silent failures fail the error
  check; bare `CancelledError` without an outcome, silent returns, and
  untyped interruption families fail the cancellation check while the
  outcome-on-`exc.outcome` spelling passes; over-reported refusals, untyped
  refusal families, missing execution scope, missing effect classification,
  and request-id-less approval gating fail the denial check. A conformance
  suite that cannot fail is decorative — these pin that it fails for the
  right reason, by name;
- the real out-of-tree `extensions/reference-greeter` package is parsed from
  its `extension.json`, its handler loaded through the import boundary, and
  its governed call completes and records — the out-of-tree criterion, end to
  end.

`tests/cli/test_extensions_contract.py` (+14) — `maistro extensions
contract`: the valid manifest reports the host classification; a `read-only`
claim beside `network.outbound` reports the derived floor, not the claim;
unreadable / invalid-JSON / non-object / contract-violating manifests exit 1
with the field named; the real reference extension classifies internal.

## Ledger reconciliations this change mandates

Two quality-ledger shrinks were required by their gates' own rules (both are
debt *reductions* caused by this change wiring formerly-unreachable code; no
floor was raised and no new debt authorized):

- `quality/reachability-baseline.json`: `maistro.tools.reversibility` left the
  unreachable set — the tool/Skill contract derives every extension tool's
  ADR-050 classification through that module, and `maistro extensions
  contract` reads it. Its disposition row in
  `quality/reachability-dispositions.json` was pruned with the reason noted.
- `quality/vulture-baseline.json`: one identity
  (`maistro/tools/reversibility.py::unused variable 'INTERNAL'`) pruned — the
  enum member is now referenced by the floor mapping in
  `maistro/extensions/tool_skill/contracts.py`.

New framework surface whose callers live outside this tree
(`ExtensionToolCatalog.exposed_tools`/`.tool_binding`, the
`maistro extensions contract` CLI command) is referenced in
`packages/maistro-core/src/_vulture_whitelist.py` per the established
framework-surface pattern.
