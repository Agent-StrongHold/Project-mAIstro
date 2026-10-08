---
inventory-delta:
  packages/maistro-core/tests: +45
---
# 969-extension-effective-authority

Forty-five tests in
`packages/maistro-core/tests/extensions/test_effective_authority.py`, for the
M9-G1 canonical effective-authority calculation (#969): extension authority as
the intersection of manifest request, publisher trust, host policy, caller
delegation, and Workspace policy. No existing test moved, was removed, or was
reparametrised; the 153 pre-existing tests in
`packages/maistro-core/tests/extensions/` pass unchanged, as do the 16
`packages/maistro-server/tests/api/test_extensions_api.py` tests against the
wired install service.

## What the new module is

`maistro.extensions.effective_authority` computes, as a pure function:

```text
effective = manifest.requested
          ∩ host.ceiling ∩ host.tier_ceilings[trust.tier]
          ∩ host.family_ceilings[family]        (when the family is mapped)
          ∩ caller.delegated_permissions
          ∩ workspace.permission_ceiling
          minus package blockers                 (untrusted publisher;
                                                  extension not enabled)
```

Deny-by-default throughout: an absent ceiling is an empty ceiling, empty
grants nothing, and every layer must admit a permission for it to be
effective. A manifest omission is structurally unrecoverable — the requested
universe is exactly the manifest's declared permissions, and no layer carries
ambient/default access. Results are digest-anchored (`decision_digest`, a
SHA-256 over the canonical decision payload) so the same inputs always
re-derive the same answer, policy changes are forward-looking only, and
`with_execution_context` pins a result to Run/NodeRun/Attempt ids (the same
canonical execution identity `InvocationPolicyContext` uses) without mutating
it. `ExtensionInstallService` accepts optional `ExtensionAuthorityInputs`;
when wired, `authorize` freezes the grant to the intersection, denies
outright when the intersection is empty, and records the digest and per-
permission denial reasons in the audited transition trail.

Review follow-ups on PR #2013 (commit `b093336`) extended both the code and
this suite by seven tests:

* package-level blockers deny even when the manifest requests nothing
  (`permissions: []` no longer reaches AUTHORIZED through the
  `granted_none && requested_permissions` gap), with the degenerate path
  pinned end-to-end incl. the loader seam never running;
* the UNTRUSTED tier is an unconditional blocker even on a
  contradictorily-constructed `PublisherTrust(tier=UNTRUSTED, trusted=True)`;
* authorization binds to the trust evidence persisted on the record at
  inspection (`ExtensionInstallRecord.trust_evidence`), not a
  service-wide claim, and untrusted evidence is rejected at inspection;
* an empty intersection caused by ceilings (no blockers) records the
  per-permission denial reasons on the trail;
* a wired `WorkspaceExtensionPolicy` whose `scope` does not cover the
  record's scope is not an applicable ceiling: authorization is denied
  before any authority is computed (`record.decision_digest` stays unset);
* the decision digest fingerprints the full authority context (trust
  verdict/tier, host/tier/family ceilings, caller principal + delegation,
  Workspace scope/enablement/ceiling), so equal permission projections from
  different callers, Workspaces, tiers, or unused allowances never share an
  evidence identity;
* the full 64-hex `decision_digest` is persisted on the install record for
  both authorized and denied outcomes — the durable join key, not just a
  prefix in transition prose.

## Per-criterion mapping (issue #969 acceptance)

* **never broader than any ceiling** — `TestNeverBroaderThanAnyCeiling`:
  one cap test per layer plus a combined-subset test.
* **manifest omission cannot be recovered** — `TestManifestOmission`, with
  every policy layer deliberately configured to allow more than the
  manifest; a hypothesis property re-checks the ambient case
  (`test_effective_never_exceeds_the_intersection`).
* **delegation capped in both directions** —
  `TestDelegationCappedFromBothDirections` and the untrusted-package
  variant no caller or Workspace can rescue.
* **stable, inspectable, linked to Run evidence** — `TestStableInspectable`:
  equality and digest stability, digest sensitivity to every layer,
  manifest-byte anchoring, and the evidence link carrying run identity
  without changing the digest.
* **policy changes affect new operations only** —
  `TestPolicyChangeIsForwardLooking`: recorded evidence survives a policy
  change bit-for-bit while recomputation reflects the new policy.
* **differential/property tests, deny-by-default** — `TestProperties`
  (hypothesis: subset-of-intersection, per-layer monotonicity, empty-caller
  deny-by-default, blocker dominance) and `TestDenyByDefault` /
  `TestResolvePublisherTrust` (missing tier ceiling, untrusted publisher,
  disabled extension, malformed policy tokens fail closed).
* **service integration** — `TestServiceIntegration`: the grant freezes to
  the intersection, the loader seam receives the intersected record, an
  empty intersection denies despite operator approval, and the #953
  no-inputs contract is preserved.

## Verification run against this change

`uv run pytest packages/maistro-core/tests/extensions -q` → 198 passed;
`uv run pytest packages/maistro-server/tests/api/test_extensions_api.py -q`
→ 16 passed; `uv run ruff check .` and `uv run ruff format --check .` clean;
`uv run mypy packages/maistro-core/src` clean; the
vulture per-identity scan (CI arguments: `packages/*/src --min-confidence 60
--exclude '*/third_party/*'`) matches `quality/vulture-baseline.json` with
zero added and zero stale identities; `scripts/check-reachability.py`
reports the same 170-entry unreachable set as the baseline.

## Develop-sync re-verification (post-merge round)

The branch was synced with `origin/develop` (merges `2e772aaf9`, `4ab512f01`
resolving the `extensions/__init__.py` `__all__` union and the
`_vulture_whitelist.py` import union against develop's #956/#2002 work).
Both files were resolved as mechanical sorted unions — no behavior change, no
test change, so this note's inventory delta is unchanged. Re-run against the
merged tree: extensions suite 398 passed (the 45 tests of this note among
them), maistro-core 13505 passed, maistro-design/ext-sdk/server 1215 passed;
ruff check/format clean; mypy 743 files clean; vulture (CI-exact arguments)
1332=1332 with base read from the develop merge base; reachability 170 =
baseline; suite inventory 16/16 suites match; radon 138=138; doc-links,
backlog-consistency, route-permissions, principal-identity, wiring-reads,
agent-store-writes, workspace-retirement, release-consistency, and
credential-authority gates all exit 0.
